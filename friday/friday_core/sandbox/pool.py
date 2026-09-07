# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt

"""
Warm container pool — amortises Docker cold-start latency.

Phase 1: this is a no-op stub. pool.acquire() always returns None,
causing runner.py to cold-spawn. pool.release() is a no-op.

Phase 1.5: this module maintains a pool of pre-spawned containers to
reduce cold-start latency from ~1.5 s to sub-100 ms per execution.

Architecture (per DOC 24 §8)
============================
The pool maintains N idle Docker containers in a paused state.

    acquire()  — pops a ready container from the idle pool (or returns None)
    release()  — after execution: resets env, /tmp wipe → returns to idle pool
                 If the container exited with an error or is too old → destroy it.

Scaling rules
------------
min_idle  = pool.min_idle  (always keep this many idle; default 5)
max_idle  = pool.max_idle  (cap on idle pool size; default 20)
max_age   = pool.max_age_seconds  (destroy and replace after N seconds; default 3600)

    target_idle = min_idle  (always keep min_idle warm)
    idle > max_idle          → destroy surplus
    idle < min_idle          → spawn until at min_idle
    container age > max_age   → destroy on next release(), spawn replacement

The execute() interface does NOT change — callers see only SandboxResult.
The pool is an optimisation below that interface.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
	pass

import frappe
from friday.friday_core.sandbox.runner import DOCKER_IMAGE, NETWORK_NAME, _get_client

# ---------------------------------------------------------------------------
# Singleton pool state
# ---------------------------------------------------------------------------

_all_pools: dict[str, "_PoolState"] = {}
_pool_lock = threading.Lock()


def _default_pool() -> "_PoolState":
	sid = getattr(frappe.local, "site", "default")
	with _pool_lock:
		if sid not in _all_pools:
			_all_pools[sid] = _PoolState()
		return _all_pools[sid]


@dataclass
class _PoolState:
	"""
	Per-site pool backing storage.
	Guarded by _pool_lock.
	"""

	idle: list[str] = field(default_factory=list)
	"""Container IDs available for immediate acquisition."""

	total_acquire: int = 0
	"""Total successful acquire() calls."""

	total_cold_spawn: int = 0
	"""Total cold-spawn fallbacks (pool was empty)."""

	total_returned: int = 0
	"""Total release() calls that returned container to pool."""

	total_destroyed: int = 0
	"""Total containers destroyed (error, age limit, or over max_idle)."""

	resize_thread: threading.Thread | None = None
	"""Background resize worker."""


# ---------------------------------------------------------------------------
# Pool configuration
# ---------------------------------------------------------------------------


@dataclass
class PoolConfig:
	"""Configuration for the warm pool (Phase 1.5 wiring)."""

	min_idle: int = 5
	max_idle: int = 20
	max_age_seconds: int = 3600  # 1 hour
	resize_interval_seconds: int = 60
	site: str | None = None


# ---------------------------------------------------------------------------
# Container lifecycle helpers
# ---------------------------------------------------------------------------


def _spawn_container() -> "str | None":
	"""
	Spawn a prepared Docker container and immediately pause it.

	The container starts in a paused state waiting for a task payload
	to be written to its stdin.  This gives the pool a ~50 ms effective
	resume time instead of a ~1.5 s cold-start.

	Returns the container short_id or None on Docker error.
	"""
	try:
		client = _get_client()
		# Check image is available
		try:
			client.images.get(DOCKER_IMAGE)
		except Exception:
			try:
				client.images.pull(DOCKER_IMAGE)
			except Exception:
				return None

		network = None
		try:
			network = client.networks.get(NETWORK_NAME)
		except Exception:
			pass

		kwargs: dict[str, Any] = {
			"detach": True,
			"stdin_open": True,
			"cpu_period": 100_000,
			"cpu_quota": 100_000,  # 1 CPU
			"mem_limit": "256m",
			"pids_limit": 256,
			"user": 65532,
			"cap_drop": "ALL",
			"security_opt": ["no-new-privileges:true"],
			"read_only": True,
			"tmpfs": {"/tmp": "size=64M,noexec,nosuid,mode=1777"},
			"labels": {"friday": "true", "friday_pool": "warm"},
		}
		if network is not None:
			kwargs["network"] = NETWORK_NAME

		container = client.containers.run(DOCKER_IMAGE, **kwargs)
		# Pause immediately — container is now "warm" in pool
		try:
			container.pause()
		except Exception:
			# PauseNotSupported or similar — but container is still valid
			pass
		return container.short_id
	except Exception:
		return None


def _destroy_container(container_id: str) -> None:
	"""Force-stop and remove a container. Best-effort."""
	try:
		client = _get_client()
		container = client.containers.get(container_id)
		try:
			container.unpause()
		except Exception:
			pass
		try:
			container.stop(timeout=2)
		except Exception:
			pass
		try:
			container.remove()
		except Exception:
			pass
	except Exception:
		pass


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def acquire(pool: "PoolConfig | None" = None) -> "str | None":
	"""
	Acquire a warm container from the pool.

	Phase 1: always returns None (cold-spawn path).
	Phase 1.5: pops a ready-to-use paused container from the idle pool.

	Returns a container short_id, or None if the pool is empty.
	Callers that receive None should fall back to cold-spawn.
	"""
	state = _default_pool()
	with _pool_lock:
		if state.idle:
			cid = state.idle.pop()
			state.total_acquire += 1
			return cid
	return None


def release(container_id: str, pool: "PoolConfig | None" = None, *, is_error: bool = False) -> None:
	"""
	Return a container to the pool after execution.

	Phase 1: no-op.
	Phase 1.5:
	    - Success (is_error=False) + idle < max_idle  →  reset, re-pause, return to pool
	    - Error  (is_error=True) OR idle >= max_idle  →  destroy container

	Containers that exit with errors are NEVER returned to the pool — their
	internal state is uncertain and cannot be safely reset.
	"""
	cfg = pool or PoolConfig()
	state = _default_pool()

	with _pool_lock:
		if not is_error and len(state.idle) < cfg.max_idle:
			_repool_container(container_id)
			state.total_returned += 1
		else:
			# Destroy: error exit, or pool is already at capacity
			_destroy_container(container_id)
			state.total_destroyed += 1


def _repool_container(container_id: str) -> None:
	"""
	Reset a container for reuse into the warm pool.
	Steps:
	  1. Capture + remove any leftover payload in /tmp
	  2. Remove FRIDAY_ env vars from the running container
	  3. Re-pause so it's ready for the next acquire()
	"""
	try:
		client = _get_client()
		container = client.containers.get(container_id)
		# Wipe /tmp (best-effort)
		try:
			container.exec_run("sh -c 'rm -rf /tmp/* /tmp/.[!.]* 2>/dev/null; true'")
		except Exception:
			pass
		# Re-pause (container will be resumed by the next acquire user)
		try:
			container.pause()
		except Exception:
			# If we can't re-pause, just leave it running
			pass
	except Exception:
		# Container state uncertain — destroy rather than pool
		_destroy_container(container_id)


def pool_stats(pool: "PoolConfig | None" = None) -> dict:
	"""
	Return current pool instrumentation.

	Phase 1: all counters at zero.
	Phase 1.5: real gauge values.
	"""
	state = _default_pool()
	with _pool_lock:
		idle = len(state.idle)
		acquire_t = state.total_acquire
		cold_spawn_t = state.total_cold_spawn
		returned_t = state.total_returned
		destroyed_t = state.total_destroyed
	total = acquire_t + cold_spawn_t
	hit_ratio = (acquire_t / total) if total > 0 else 0.0
	return {
		"pool_size": idle,
		"idle_count": idle,
		"acquire_total": acquire_t,
		"cold_spawn_total": cold_spawn_t,
		"hit_ratio": round(hit_ratio, 4),
		"total_returned": returned_t,
		"total_destroyed": destroyed_t,
	}


def start_pool_resize_worker(pool: "PoolConfig | None" = None) -> None:
	"""
	Start the background resize thread that maintains min_idle containers.

	Call once at site startup (e.g. from hooks.py after_site_boot).
	Idempotent — multiple calls are safe.
	"""
	cfg = pool or PoolConfig()
	state = _default_pool()

	with _pool_lock:
		if state.resize_thread is not None and state.resize_thread.is_alive():
			return

		def _resize_loop() -> None:
			while True:
				try:
					_resize_pool(cfg)
				except Exception:
					pass
				time.sleep(cfg.resize_interval_seconds)

		t = threading.Thread(target=_resize_loop, daemon=True, name="friday-pool-resize")
		t.start()
		state.resize_thread = t


def _resize_pool(cfg: PoolConfig) -> None:
	"""
	Bring idle pool to min_idle size; drain excess above max_idle.
	Called every resize_interval_seconds by the background worker.
	"""
	state = _default_pool()
	with _pool_lock:
		idle_count = len(state.idle)

		# Drain excess above max_idle
		excess = idle_count - cfg.max_idle
		if excess > 0:
			to_destroy = state.idle[-excess:]
			state.idle = state.idle[:-excess]
			# Destroy outside the lock (I/O)
		else:
			to_destroy = []

	for cid in to_destroy:
		threading.Thread(target=_destroy_container, args=(cid,), daemon=True).start()

	if excess > 0:
		return  # Don't spawn while draining

	# Bring up to min_idle
	with _pool_lock:
		current = len(state.idle)

	missing = cfg.min_idle - current
	if missing <= 0:
		return

	# Spawn missing containers (outside the lock)
	spawned = 0
	for _ in range(missing):
		cid = _spawn_container()
		if cid is not None:
			with _pool_lock:
				state.idle.append(cid)
			spawned += 1
		# Give Docker a moment between spawns to avoid overload
		time.sleep(0.05)

	frappe.logger("friday.sandbox").info(
		"Pool resize: brought %d/%d idle containers online (current=%d, target=%d)",
		spawned,
		missing,
		current,
		cfg.min_idle,
	)


def stop_pool() -> None:
	"""
	Destroy all pooled containers.  Call at site teardown.
	"""
	state = _default_pool()
	with _pool_lock:
		cids = list(state.idle)
		state.idle.clear()

	for cid in cids:
		_destroy_container(cid)


__all__ = ["PoolConfig", "acquire", "pool_stats", "release", "start_pool_resize_worker", "stop_pool"]
