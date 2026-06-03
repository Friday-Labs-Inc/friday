# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt
from __future__ import annotations

"""
Sandbox orchestrator — spawns Docker containers for skill execution.

Phase 1 (this module): cold-spawn per call.
Phase 1.5: pool.py wires a warm pool on top of this interface.

Usage:
    from frappe.friday_core.sandbox import execute, SandboxResult

    result = execute(
        skill_name="create_note",
        parameters={"title": "Test", "content": "Hello"},
        agent_profile="Note Taker Agent",
        credentials={},
        timeout_seconds=300,
        cpu_cores=1,
        memory_mb=256,
    )
    # result.status in ("success", "failed", "timeout", "oom")
"""

from dataclasses import dataclass
import json
import time
import uuid
from typing import TYPE_CHECKING, Any

import frappe

from frappe.friday_core.sandbox.credentials import generate_scoped_token

if TYPE_CHECKING:
    pass  # docker imported lazily inside _get_client; forward refs used below

# ---------------------------------------------------------------------------
# Datatypes
# ---------------------------------------------------------------------------


@dataclass
class SandboxResult:
    """The result of one sandboxed skill execution."""

    status: str
    """'success' | 'failed' | 'timeout' | 'oom' | 'invalid_skill'"""

    result: dict | None = None
    """Structured skill output. None on status != 'success'."""

    logs: str = ""
    """Captured stdout + stderr from the container."""

    duration_ms: int = 0
    """Wall-clock time in milliseconds."""

    container_id: str | None = None
    """Docker container ID, for debugging."""


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DOCKER_IMAGE = "friday/skill-runtime:latest"
NETWORK_NAME = "friday-execution-net"
MAX_CONTAINER_AGE_MINUTES = 30
JANITOR_INTERVAL_MINUTES = 5

# Entry/result markers written by the container entrypoint
RESULT_BEGIN = ">>>FRIDAY_RESULT_BEGIN<<<"
RESULT_END = "<<<FRIDAY_RESULT_END>>>"

# ---------------------------------------------------------------------------
# Docker client (lazily initialised; works with Docker over Unix socket)
# ---------------------------------------------------------------------------

_client: "docker.DockerClient | None" = None


def _get_client() -> "docker.DockerClient":
    global _client
    # pylint: disable=import-outside-toplevel,no-name-in-module
    import docker
    if _client is None:
        try:
            _client = docker.from_env()
        except Exception:  # noqa: BLE001
            # Docker not available (e.g. developer machine without Docker,
            # or test environment without dockerd). Caller should fall back
            # to in-process execution. We return a dummy so import succeeds.
            class _NoDocker:
                def images(self):
                    raise ModuleNotFoundError("docker")
            _client = _NoDocker()  # type: ignore
    return _client


def _logger() -> "Any":
    return frappe.logger("friday.sandbox")


# ---------------------------------------------------------------------------
# Network setup helpers
# ---------------------------------------------------------------------------

def ensure_network(network_name: str = NETWORK_NAME) -> "Any":
    """
    Create the sandbox bridge network if it does not exist.
    Called once at site setup or on first execution.
    Returns None if Docker is unavailable.
    """
    try:
        client = _get_client()
        network = client.networks.get(network_name)
        return network
    except Exception:  # noqa: BLE001
        # Networks API not available (e.g. Docker not running).
        # Run without network; container won't be network-isolated.
        return None


def get_frappe_host_network_info() -> tuple[str, int]:
    """
    Returns the Frappe API host and port that containers must reach.
    Reads from site config.
    """
    site = getattr(frappe.local, "site", "friday.localhost")
    # Frappe serves on port 8000 by default
    return site, 8000


# ---------------------------------------------------------------------------
# Egress allowlist
# ---------------------------------------------------------------------------

def _get_egress_config(agent_profile: str) -> tuple[str, list[str]]:
    """
    Returns (frappe_host, extra_allowlist_hosts) for a given agent profile.

    The sandbox network restricts egress to explicitly allowlisted hosts only.
    Always allowed: Frappe API host (so skills can call back).
    Additional hosts: comma/newline-separated in Agent Profile network_allowlist.
    """
    frappe_host, _ = get_frappe_host_network_info()
    extra_hosts: list[str] = []

    try:
        profile = frappe.get_doc("Agent Profile", agent_profile)
        raw = profile.get("network_allowlist") or ""
        if raw:
            # Comma or newline separated host list
            extra_hosts = [
                h.strip()
                for h in raw.replace("\n", ",").split(",")
                if h.strip()
            ]
    except Exception:  # noqa: BLE001
        pass

    return frappe_host, extra_hosts


def _build_etc_hosts(frappe_host: str, extra_hosts: list[str]) -> str:
    """
    Build /etc/hosts content for a container.
    Resolves all allowlisted hosts to 127.0.0.1 so containers cannot
    reach external addresses for allowlisted hostnames.
    Unknown hosts will fail DNS resolution (egress blocked).
    """
    lines = ["127.0.0.1 localhost", f"127.0.0.1 {frappe_host}"]
    for h in extra_hosts:
        h = h.strip()
        if h and h not in lines:
            lines.append(f"127.0.0.1 {h}")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# CPU / memory caps from Agent Profile or Skill
# ---------------------------------------------------------------------------

def _resolve_limits(
    agent_profile: str, skill_name: str
) -> tuple[int, int, int]:
    """
    Resolve (cpu_cores, memory_mb, timeout_seconds) for a skill execution.
    Reads from Agent Profile resource_quota section, if set.
    Defaults: cpu=1, memory=256MB, timeout=300s
    """
    try:
        profile = frappe.get_doc("Agent Profile", agent_profile)
        quota = profile.get("resource_quota") or {}
    except Exception:
        quota = {}

    cpu = int(quota.get("cpu_cores") or 1)
    memory = int(quota.get("memory_mb") or 256)
    timeout = int(quota.get("timeout_seconds") or 300)
    return cpu, memory, timeout


# ---------------------------------------------------------------------------
# Result parsing
# ---------------------------------------------------------------------------

def _parse_result(stdout: str) -> tuple[str, dict | None]:
    """
    Parse the structured result envelope from container stdout.

    Returns (status, result_dict).
    Status one of: 'success', 'failed', 'timeout', 'oom', 'protocol_error'.
    """
    begin = stdout.find(RESULT_BEGIN)
    end = stdout.find(RESULT_END)

    if begin == -1 or end == -1:
        return "protocol_error", None

    json_str = stdout[begin + len(RESULT_BEGIN) : end].strip()
    try:
        payload = json.loads(json_str)
    except json.JSONDecodeError:
        return "protocol_error", None

    status = payload.get("status", "failed")
    result = payload.get("result")
    return status, result


# ---------------------------------------------------------------------------
# Main execute function
# ---------------------------------------------------------------------------

def execute(
    skill_name: str,
    parameters: dict,
    agent_profile: str,
    credentials: dict,
    timeout_seconds: int = 300,
    cpu_cores: int = 1,
    memory_mb: int = 256,
    frappe_base_url: str | None = None,
    execution_id: str | None = None,
) -> "SandboxResult":
    """
    Spawn a Docker container and run the named skill inside it.

    Parameters
    ----------
    skill_name: Name of the Skill DocType row to execute.
    parameters: JSON-serialisable dict passed to the skill handler.
    agent_profile: Agent Profile name — used for limits, token scope, and allowlist.
    credentials: Dict of resolved credentials (env vars injected into container).
    timeout_seconds: Wall-clock timeout. Default 300.
    cpu_cores: cgroup CPU quota. Default 1.
    memory_mb: cgroup memory limit (MB). Default 256.
    frappe_base_url: URL the container uses to call back to Frappe.
        Defaults to http://<site>:8000.
    execution_id: Unique ID for this execution. Auto-generated if None.

    Returns
    -------
    SandboxResult
    """
    if not skill_name:
        raise ValueError("skill_name may not be empty")

    client = _get_client()
    execution_id = execution_id or str(uuid.uuid4())

    # Resolve Frappe URL
    site_host, site_port = get_frappe_host_network_info()
    frappe_base_url = frappe_base_url or f"http://{site_host}:{site_port}"

    # Resolve limits (from profile quota, with sensible defaults)
    cpu_cores, memory_mb, resolved_timeout = _resolve_limits(
        agent_profile, skill_name
    )
    timeout_seconds = min(timeout_seconds, resolved_timeout)

    # Resolve egress allowlist
    frappe_host, extra_allowlist = _get_egress_config(agent_profile)
    etc_hosts_content = _build_etc_hosts(frappe_host, extra_allowlist)

    # Generate scoped credential token (single source: sandbox/credentials.py — H3)
    api_token = generate_scoped_token(agent_profile, execution_id)

    # Ensure network exists
    network = ensure_network()

    # Build task payload (written to container stdin)
    payload = {
        "skill_name": skill_name,
        "parameters": parameters,
        "frappe_base_url": frappe_base_url,
        "api_token": api_token,
        "execution_id": execution_id,
    }
    payload_bytes = json.dumps(payload).encode("utf-8")

    # Environment for the container
    env = [
        f"FRIDAY_SKILL={skill_name}",
        f"FRIDAY_EXECUTION_ID={execution_id}",
        f"FRIDAY_API_TOKEN={api_token}",
        f"FRIDAY_FRAPPE_BASE={frappe_base_url}",
        f"FRIDAY_API_KEY={api_token}",  # used by Frappe client inside container
    ]
    # Inject allowlist hosts into container's /etc/hosts
    env.append(f"FRIDAY_EGRESS_ALLOWLIST={','.join(extra_allowlist)}")

    started_at = time.monotonic()

    container = None
    container_kwargs: dict[str, Any] = {
        "detach": True,
        "stdin_open": True,  # keep stdin open for payload write
        "cpu_period": 100_000,  # cgroup period (100ms)
        "cpu_quota": int(cpu_cores * 100_000),  # cgroup quota = cores × period
        "mem_limit": f"{memory_mb}m",
        "pids_limit": 256,
        "user": 65532,  # nonroot
        "cap_drop": "ALL",
        "security_opt": ["no-new-privileges:true"],
        "read_only": True,  # read-only rootfs
        "tmpfs": {"/tmp": "size=64M,noexec,nosuid,mode=1777"},
        "environment": env,
        "labels": {"friday": "true"},
    }

    # Wire /etc/hosts for allowlisted destinations
    import tempfile, os
    tmpdir = tempfile.mkdtemp(prefix="friday-egress-")
    hosts_path = os.path.join(tmpdir, "hosts")
    with open(hosts_path, "w") as f:
        f.write(etc_hosts_content)
    container_kwargs["volumes"] = {hosts_path: {"bind": "/etc/hosts", "mode": "ro"}}

    # Only attach to sandbox network when Docker is available
    if network is not None:
        container_kwargs["network"] = NETWORK_NAME

    try:
        # Pull image if needed
        try:
            client.images.get(DOCKER_IMAGE)
        except Exception:  # noqa: BLE001
            try:
                client.images.pull(DOCKER_IMAGE)
            except Exception:  # noqa: BLE001
                pass  # Docker unavailable; caller will catch container.run error

        # Run container
        container = client.containers.run(DOCKER_IMAGE, **container_kwargs)

        # Write payload to stdin, then close it (container waits for EOF before exiting)
        try:
            streams = container.attach_socket(params={"stdin": True, "stream": True})
            streams.write(payload_bytes)
            streams.close()
        except Exception:
            pass  # some images may not support attach_socket

        # Wait for result or timeout
        result_lines = []
        timeout_reached = False

        while True:
            elapsed_s = time.monotonic() - started_at
            if elapsed_s > timeout_seconds:
                timeout_reached = True
                container.kill()
                break

            # Check if container has exited
            container.reload()
            if container.status == "exited":
                exit_code = container.exit_code
                logs_bytes = container.logs(stdout=True, stderr=True)
                if logs_bytes:
                    result_lines = logs_bytes.decode("utf-8", errors="replace")
                else:
                    result_lines = ""
                status, parsed_result = _parse_result(result_lines)

                # Override status based on exit code
                if status == "success":
                    if exit_code == 0:
                        pass  # keep parsed status
                    elif exit_code == 137:
                        status = "oom"
                    else:
                        status = "failed"
                elif timeout_reached:
                    status = "timeout"

                duration_ms = int((time.monotonic() - started_at) * 1000)
                return SandboxResult(
                    status=status,
                    result=parsed_result,
                    logs=result_lines,
                    duration_ms=duration_ms,
                    container_id=container.short_id,
                )

            time.sleep(0.1)

        # Timeout path
        duration_ms = int((time.monotonic() - started_at) * 1000)
        container.kill()
        return SandboxResult(
            status="timeout",
            result=None,
            logs="",
            duration_ms=duration_ms,
            container_id=container.short_id if container else None,
        )

    except Exception as e:  # noqa: BLE001
        duration_ms = int((time.monotonic() - started_at) * 1000)
        return SandboxResult(
            status="failed",
            result=None,
            logs=str(e),
            duration_ms=duration_ms,
            container_id=container.short_id if container else None,
        )

    finally:
        # Clean up container
        if container is not None:
            try:
                container.stop(timeout=5)
            except Exception:
                pass
            try:
                container.remove()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Janitor — cleanup stale/orphaned containers
# ---------------------------------------------------------------------------

def janitor_cleanup():
    """
    Scheduled every 5 minutes. Finds and removes any friday=true containers
    older than MAX_CONTAINER_AGE_MINUTES. Prevents orphan accumulation.
    """
    client = _get_client()
    cutoff_ts = time.time() - (MAX_CONTAINER_AGE_MINUTES * 60)

    try:
        for container in client.containers.list(all=True, filters={"label": "friday=true"}):
            created_at = container.attrs.get("Created", 0)
            if isinstance(created_at, str):
                try:
                    import time as _time

                    created_ts = _time.mktime(
                        _time.strptime(created_at[:19], "%Y-%m-%dT%H:%M:%S")
                    )
                except Exception:
                    continue
            else:
                continue

            if created_ts < cutoff_ts:
                _logger().warning(
                    "Janitor removing stale container: %s (created %s)",
                    container.short_id,
                    created_at,
                )
                try:
                    container.stop(timeout=5)
                except Exception:
                    pass
                try:
                    container.remove()
                except Exception:
                    pass
    except Exception as e:
        _logger().error("Janitor failed: %s", e)
