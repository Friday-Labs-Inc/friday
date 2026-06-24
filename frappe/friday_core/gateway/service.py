# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt

"""
The gateway chokepoint — one function, every message flows through it.

PLAIN ENGLISH
=============

This is the function that runs every time ANY surface (CLI, Telegram,
Slack, Raven, A2A — today and future) writes an inbound Chat Message
row. It's wired in `frappe/hooks.py` as the `Chat Message.after_insert`
handler.

What it does, in order:

  1. Skip if the row is outbound (the gateway only handles inbound;
     outbound rows are written BY the gateway itself, and we'd infinite-
     loop if we processed them).
  2. Skip if `agent_profile` is empty (adapter contract violation —
     write a clean validation error rather than crash).
  3. Look up the `Chat Platform` row to read `dispatch_mode`.
     - "sync"  → run the pipeline in-line, this process (explicit
       operator/test override — deterministic, no worker needed).
     - "async" (the default) → Gateway v2 (design 55): enqueue to the
       DEDICATED `friday` queue, processed by `bench worker --queue
       friday`. If no friday worker is alive, fall back to inline
       execution with a logged warning (Q1) so nothing ever hangs.
  4. The pipeline itself (`_run_pipeline`):
     a. dedup check (stub today — `is_duplicate` always returns False)
     b. acquire per-session Redis lock with 30s wait timeout
     c. flush_batch (stub today — returns [content] unchanged)
     d. permissions.matrix.check (Slice 2) — gates the action
     e. skills.loader.load_for_profile (Slice 3) — loaded per-profile
     f. agent_runner.run_turn — the full ReAct engine (loop → permission-
        checked dispatch → audited skills; see agent_runner/runner.py)
     g. write outbound Chat Message row
     h. publish_realtime("chat.outbound", ...) for future subscribers
     i. mark inbound.processed = 1
     j. release session lock

If any step fails, the gateway writes a system-error outbound row so
the user gets feedback and the audit trail records the failure. In
sync mode, Frappe's transaction semantics ALSO mean the inbound row
rolls back if we raise here — but we prefer the explicit error
outbound for visibility.

THE ONE RULE (REPEATED)
=======================

No surface imports `agent_runner` directly. If you're tempted to, stop
and re-read `docs/design/47-gateway-design-decisions.md` §9.
"""

from __future__ import annotations

import frappe
from frappe.friday_core.agent_runner.runner import run_turn
from frappe.friday_core.gateway.batching import flush_batch
from frappe.friday_core.permissions.matrix import check as permission_check

# Redis lock key prefix for per-session serialization. TTL prevents stuck
# locks if a worker dies between acquire and release.
_SESSION_LOCK_PREFIX = "friday:session_lock:"
_SESSION_LOCK_TTL_SECONDS = 300  # 5 minutes
_SESSION_LOCK_WAIT_SECONDS = 30  # max time a second inbound waits for the lock

# The realtime event name. Future subscribers — Telegram adapter, Slack
# adapter, Raven, etc. — subscribe to this. CLI does not subscribe; it
# polls for the outbound row (see cli/chat.py _wait_for_outbound).
_OUTBOUND_REALTIME_EVENT = "chat.outbound"

# Gateway v2 (design 55, LOCKED): the dedicated queue + its job timeout.
# The timeout covers the engine's worst case — LLM retry budget (~97s),
# sandbox runs, approval writes (Q2). The queue is defined bench-side in
# common_site_config.json `workers.friday`; the worker is
# `bench worker --queue friday` (one Procfile line in dev, N under
# supervisor in production).
FRIDAY_QUEUE = "friday"
FRIDAY_JOB_TIMEOUT_SECONDS = 600


def _friday_worker_alive() -> bool:
	"""True when at least one worker is consuming the friday queue (Q1).

	Any failure here (queue not configured on this bench, redis hiccup)
	counts as "no worker" — the router then falls back to inline
	execution, which always works. The fallback is what keeps
	`friday chat` usable in a bare dev shell and tests deterministic in CI.
	"""
	try:
		from frappe.utils.background_jobs import get_queue, get_workers

		return len(get_workers(get_queue(FRIDAY_QUEUE))) > 0
	except Exception:
		return False


def _enqueue_pipeline(row_name: str, lock_retry: int) -> None:
	"""Enqueue one pipeline run on the dedicated queue and stamp the row.

	- `job_id` is deterministic (`friday-gw::<row>::lock<n>`) and written
	  onto the Chat Message row, so any turn can be traced to the exact
	  queue job that ran it (Q6).
	- `enqueue_after_commit=True` closes the race where a worker grabs
	  the job before the inserting transaction has committed the row.
	"""
	job_id = f"friday-gw::{row_name}::lock{lock_retry}"
	frappe.enqueue(
		"frappe.friday_core.gateway.service.run_pipeline_for_row",
		row_name=row_name,
		lock_retry=lock_retry,
		queue=FRIDAY_QUEUE,
		timeout=FRIDAY_JOB_TIMEOUT_SECONDS,
		job_id=job_id,
		enqueue_after_commit=True,
	)
	frappe.db.set_value("Chat Message", row_name, "job_id", job_id, update_modified=False)


# ---------------------------------------------------------------------------
# The hook target
# ---------------------------------------------------------------------------


def handle_inbound(doc, method=None) -> None:
	"""Frappe `doc_events` hook for Chat Message.after_insert.

	Routes the inbound row to the gateway pipeline based on the
	platform's dispatch_mode. Sync mode runs the pipeline inline;
	async mode enqueues an RQ job and returns.
	"""
	# Outbound rows are written BY the gateway. Processing them would
	# infinite-loop: outbound row inserted → after_insert fires → gateway
	# runs → writes another outbound row → ...
	if doc.direction != "inbound":
		return

	# Design 82 — command traffic (a slash command + its reply) is audited as
	# Chat Message rows with is_command=1, but it was already handled at the
	# surface edge and must NOT run a conversational turn. Skip it here.
	if doc.get("is_command"):
		return

	# Already-processed rows (e.g. recovery retries that succeeded before
	# the current call) should not be re-run. Defensive guard.
	if doc.processed:
		return

	if not doc.agent_profile:
		# Adapter contract violation: every inbound row must name a
		# target agent. Write a clean system-error outbound rather than
		# crashing the insert transaction.
		_write_system_error(doc, "Inbound message missing agent_profile (adapter contract violation).")
		return

	platform = doc.platform
	if not platform:
		_write_system_error(doc, "Inbound message missing platform.")
		return

	dispatch_mode = _get_dispatch_mode(platform)

	# Explicit override: "sync" forces inline execution in this process.
	# Used by tests (deterministic, no worker needed) and as an operator
	# emergency hatch. Everything else takes the worker path.
	if dispatch_mode == "sync":
		_run_pipeline(doc)
		return

	# Gateway v2 (design 55, Q1): the default path for EVERY surface is
	# the dedicated friday worker. The webhook/CLI caller returns
	# immediately; the worker runs the turn. Inline fallback when no
	# friday worker is alive, so nothing ever hangs waiting on a queue
	# nobody is consuming.
	if _friday_worker_alive():
		_enqueue_pipeline(doc.name, lock_retry=0)
		return

	frappe.logger("friday.gateway").warning(
		"No friday worker alive — running the pipeline inline as fallback. "
		"Start the dedicated worker with: bench worker --queue friday"
	)
	_run_pipeline(doc)


def run_pipeline_for_row(row_name: str, lock_retry: int = 0) -> None:
	"""RQ job entrypoint — what the dedicated friday worker executes.

	Loads the Chat Message row by name and runs the same pipeline the
	inline path runs. Used by the router's worker dispatch, the recovery
	sweeper's orphan retries, and the Q3 busy-requeue.

	`lock_retry` counts session-lock attempts (0 = first try; 1 = the one
	requeue design 55 Q3 allows before the busy message).
	"""
	doc = frappe.get_doc("Chat Message", row_name)
	if doc.processed:
		# Already handled by an earlier successful run. Idempotent skip.
		return
	_run_pipeline(doc, in_worker=True, lock_retry=lock_retry)


# ---------------------------------------------------------------------------
# The pipeline
# ---------------------------------------------------------------------------


def _run_pipeline(inbound, in_worker: bool = False, lock_retry: int = 0) -> None:
	"""The same code for worker and inline dispatch.

	Executes steps 1–10 from the module docstring. Acquires the session
	lock for the duration. Always writes either an outbound reply or a
	system-error outbound — never leaves the user hanging.

	`in_worker`/`lock_retry` drive the Q3 busy behaviour: in a worker, a
	first lock failure requeues once (a fresh job waits a fresh lock
	window) before giving the busy message; inline runs keep the
	immediate busy message (there's no queue to wait on).
	"""
	session_id = inbound.session_id
	profile_name = inbound.agent_profile

	# Stub today: real dedup helper lands with the first webhook adapter.
	# Skipped without ceremony.
	# if dedup.is_duplicate(inbound.platform, inbound.sender_id, inbound.content): return

	lock_key = f"{_SESSION_LOCK_PREFIX}{session_id}"
	# `frappe.cache()` returns a RedisWrapper that inherits from
	# `redis.Redis`, so we get redis-py's built-in distributed Lock
	# with TTL and blocking-timeout semantics for free.
	#   - `timeout` = TTL on the lock key (auto-release on crash).
	#   - `blocking_timeout` = how long acquire() waits before failing.
	lock = frappe.cache().lock(
		lock_key,
		timeout=_SESSION_LOCK_TTL_SECONDS,
		blocking_timeout=_SESSION_LOCK_WAIT_SECONDS,
	)
	acquired = lock.acquire(blocking=True)
	if not acquired:
		# Design 80 queue phase — another turn for this session holds the lock.
		# QUEUE, don't drop: leave the row processed=0 and return. The turn that
		# holds the lock re-dispatches the oldest queued row the instant it
		# releases (see `_drain_next_in_session` in the finally below); the
		# orphan sweeper (gateway/recovery.py, every minute) is the backstop.
		# Queue-by-default — no message is lost and the running turn is never
		# interrupted.
		return

	# Re-check after acquiring the lock: while we waited, the turn that held it
	# — or a drain / orphan re-enqueue — may already have processed this exact
	# row. Skip to avoid a duplicate reply (double-dispatch guard, important now
	# that drain + sweeper + a concurrent worker pool can all enqueue a row).
	if frappe.db.get_value("Chat Message", inbound.name, "processed"):
		try:
			lock.release()
		except Exception:
			pass
		return

	try:
		# Stub today: real batching lands with the first bursty surface.
		# flush_batch() returns [inbound.content] — list of one.
		batch = flush_batch(session_id, inbound.content or "")
		# Slice 4's run_turn signature is still `content: str` (not
		# `messages: list`). When batching activates, this join becomes
		# the signature change. Documented in §4 Q4-C.
		joined_content = "\n".join(batch)

		# Slice 2 gate: refuse if the agent profile lacks permission on
		# any skill the agent might call. (In v0.1 the stub agent calls
		# nothing; this check exists so any future code that adds skill
		# invocations is already gated.) For Slice 4, we just resolve
		# the matrix — a real `check` happens at skill-invocation time
		# in later slices.
		# (Intentional pass-through here; permission machinery is invoked
		#  per-skill inside the agent loop in later slices.)
		_ = profile_name  # placeholder for future per-skill checks

		# Agent runs and produces a reply.
		reply = run_turn(
			profile_name=profile_name,
			session_id=session_id,
			inbound_content=joined_content,
		)

		# Write the outbound row.
		_write_outbound(
			inbound,
			content=reply,
			processed=True,
			sender_label=profile_name,
		)

		# Fire the realtime event so future Telegram/Slack/Raven
		# subscribers get pushed. CLI doesn't subscribe; it reads the
		# outbound row directly.
		frappe.publish_realtime(
			_OUTBOUND_REALTIME_EVENT,
			{
				"session_id": session_id,
				"content": reply,
				"platform": inbound.platform,
			},
			after_commit=True,
		)

		# Mark inbound as processed AFTER outbound is written. If we
		# crash between these two, recovery sweeper picks it up.
		_mark_processed(inbound, retry_count=inbound.retry_count or 0)

		# Design 79/80 — after a successful conversational turn, maybe queue a
		# self-improvement memory review (cadence-gated; best-effort). Only the
		# gateway path triggers it, so pipeline-task turns never do.
		from frappe.friday_core.agent_runner.self_review import enqueue_if_due

		enqueue_if_due(session_id, profile_name)

	except Exception as exc:
		# Log full traceback to Frappe Error Log AND write a system-error
		# outbound row so the user gets feedback. Don't re-raise: in sync
		# mode that would roll back the inbound row, hiding the audit.
		frappe.log_error(title="friday.gateway.handle_inbound failure")
		_write_outbound(
			inbound,
			content=f"(agent error: {type(exc).__name__})",
			processed=True,
			sender_label="system",
		)
		_mark_processed(
			inbound,
			retry_count=(inbound.retry_count or 0) + 1,
			failure_reason=f"{type(exc).__name__}: {exc}",
		)

	finally:
		# Always release the lock, even on error. redis-py's Lock raises
		# LockError if the lock has already expired (TTL elapsed) — that's
		# benign here, so we swallow it.
		try:
			lock.release()
		except Exception:
			pass
		# Design 80 queue phase — the lock is now free; pull the next message
		# that queued up for this session (oldest first) so a burst drains in
		# FIFO order without waiting on the orphan sweeper.
		_drain_next_in_session(session_id)


def _drain_next_in_session(session_id: str) -> None:
	"""Re-dispatch the oldest still-unprocessed inbound for a session.

	Called after a turn releases the session lock. A message that arrived while
	the session was busy was left ``processed=0`` (not dropped); now the lock is
	free we enqueue the oldest such row so queued messages drain in order.

	Best-effort: any failure is swallowed — the orphan sweeper
	(``gateway/recovery.py``) is the backstop. No-op when no friday worker is
	alive (sync/CLI has no queue; the sweeper covers async platforms).
	"""
	try:
		nxt = frappe.get_all(
			"Chat Message",
			filters={"session_id": session_id, "direction": "inbound", "processed": 0},
			fields=["name"],
			order_by="creation asc",
			limit=1,
		)
		if nxt and _friday_worker_alive():
			_enqueue_pipeline(nxt[0]["name"], lock_retry=0)
	except Exception:
		frappe.logger("friday.gateway").warning(
			f"queue drain failed for session {session_id!r}", exc_info=True
		)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_dispatch_mode(platform: str) -> str:
	"""Read the platform's dispatch_mode. Defaults to 'sync' if absent."""
	mode = frappe.db.get_value("Chat Platform", platform, "dispatch_mode")
	return mode or "sync"


def _write_outbound(inbound, content: str, processed: bool, sender_label: str) -> str:
	"""Insert one outbound Chat Message row. Returns the new docname.

	`ignore_permissions=True` because the gateway is system machinery
	recording its own action — there's no user role for "may create
	outbound Chat Message".
	"""
	doc = frappe.get_doc(
		{
			"doctype": "Chat Message",
			"session_id": inbound.session_id,
			"platform": inbound.platform,
			"direction": "outbound",
			"sender_id": sender_label,
			"agent_profile": inbound.agent_profile,
			"content": content,
			"timestamp": frappe.utils.now_datetime(),
			"processed": 1 if processed else 0,
		}
	)
	doc.insert(ignore_permissions=True)
	return doc.name


def _write_system_error(inbound, message: str) -> None:
	"""Shortcut: write a system-error outbound + mark inbound processed.

	Used for adapter-contract violations (missing platform or
	agent_profile) where running the pipeline doesn't make sense.
	"""
	_write_outbound(inbound, content=f"(system error: {message})", processed=True, sender_label="system")
	_mark_processed(inbound, retry_count=0, failure_reason=message)


def _mark_processed(inbound, retry_count: int, failure_reason: str | None = None) -> None:
	"""Set processed=1 and update retry_count / failure_reason atomically.

	Direct DB update (no `inbound.save()`) to avoid re-firing doc_events
	and to skip Frappe's validation that doesn't apply to system writes.
	"""
	update = {"processed": 1, "retry_count": retry_count}
	if failure_reason is not None:
		update["failure_reason"] = failure_reason
	frappe.db.set_value("Chat Message", inbound.name, update, update_modified=False)
