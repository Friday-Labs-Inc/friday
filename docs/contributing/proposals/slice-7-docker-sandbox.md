# slice-7-docker-sandbox.md

> **Status:** DRAFT  
> **Author:** fridaylabs / sponsor `@Fridaylabsinc`  
> **Stakeholders:** @Fridaylabsinc, AI contributor agent  
> **Audit required before merge:** Security review of sandbox configuration, resource limits, and network isolation.

---

## 1. Problem & Context

Slice 6 shipped in-process skill execution — the `create_note` skill runs directly inside the Frappe process. This is fine for a demo, but it is not safe for production:

- A buggy or malicious skill can crash the Frappe worker process (shared process = shared blast radius)
- A skill with network access can reach any host the Frappe server can reach
- No CPU/memory isolation between concurrent skill executions
- Skills runs as the same OS user as the web server

Slice 7 introduces the **Docker sandbox**: every skill invocation runs inside an isolated Docker container with scoped credentials, resource limits, network restrictions, and structured result capture. The Frappe REST API is the only permitted channel back to the framework.

**Reference architecture:** [`docs/design/24-sandbox-architecture-implementation.md`](docs/design/24-sandbox-architecture-implementation.md) — this proposal implements the Phase 1 minimum bar from [`docs/design/42-phase-one-authority-contract.md`](docs/design/42-phase-one-authority-contract.md) §5.

---

## 2. Proposed Changes & Architecture

### 2.1 Docker Image (`friday/sandbox/Dockerfile`)

A single runtime image. Pinned base, pinned deps, no host mounts.

```dockerfile
FROM python:3.14-slim AS runtime

RUN pip install --no-cache-dir \
    requests==2.32.3 \
    pydantic==2.7.1 \
    frappe-client==1.0.0

# Nonroot user UID 65532 — matches the container user
RUN useradd --no-create-home --uid 65532 friday
USER friday
WORKDIR /home/friday

COPY entrypoint.py /home/friday/entrypoint.py
ENTRYPOINT ["python", "/home/friday/entrypoint.py"]
```

Image is built and tagged as `friday/skill-runtime:latest`. Digest pinned in `friday-images.lock`. `trivy` scan runs on every build; **no critical or high CVEs** may ship.

### 2.2 Entrypoint (`friday/sandbox/entrypoint.py`)

Lives inside the container. Reads task JSON from stdin:

```json
{
  "skill_name": "create_note",
  "parameters": {"title": "Meeting", "content": "board mtg notes"},
  "frappe_base_url": "http://frappe:8000",
  "api_token": "<scoped-token>",
  "execution_id": "uuid..."
}
```

1. Validate JSON shape
2. Call the skill's `run(parameters)` function — skills are bundled in the image or loaded via Frappe API at runtime (Phase 1: bundled is acceptable; the image ships with all Phase 1 skill handlers)
3. Write structured result to stdout with markers:

```
>>>FRIDAY_RESULT_BEGIN<<<
{"status": "success", "result": {...}}
>>>FRIDAY_RESULT_END<<<
```

4. Exit 0 on success, non-zero on failure (captured by orchestrator)

### 2.3 Sandbox Orchestrator (`friday/sandbox/runner.py`)

The single entry point for all skill execution. Replaces the direct handler call from Slice 6's dispatcher.

```python
@dataclass
class SandboxResult:
    status: str           # "success" | "failed" | "timeout" | "oom"
    result: dict | None
    logs: str             # stdout + stderr captured
    duration_ms: int
    container_id: str | None

def execute(
    skill_name: str,
    parameters: dict,
    agent_profile: str,
    credentials: dict,          # resolved from Skill Credential DocType
    timeout_seconds: int = 300,
    cpu_cores: int = 1,
    memory_mb: int = 256,
) -> SandboxResult:
    ...
```

**Spawn lifecycle:**

1. Pull/check image (on cold start; warm pool has it cached)
2. Create container with:
   - `friday/skill-runtime:latest`
   - `Network=friday-execution-net` (custom bridge, created once)
   - `--read-only` rootfs, tmpfs at `/tmp` (64MB, noexec, nosuid)
   - `--cpus=X`, `--memory=XM` (cgroup limits)
   - `--pids-limit=256`
   - `--user=65532` (nonroot)
   - `--cap-drop=ALL --cap-add=NONE`
   - `--security-opt=no-new-privileges`
   - Environment: `api_token`, `frappe_base_url`, `execution_id`
3. Start container suspended (cold-spawn in Phase 1; warm pool in Phase 1.5)
4. Write task payload JSON to container's stdin
5. Unpause container, wait for `>>>FRIDAY_RESULT_BEGIN<<<` on stdout (or timeout)
6. Parse result, destroy container (cold mode; Phase 1)
7. Return `SandboxResult`

**Failure mappings:**

| Failure | Docker exit code | Result.status |
|---|---|---|
| Normal exit | 0 | `success` |
| Skill raised exception | non-zero | `failed` |
| OOM | 137 | `oom` |
| Wall-clock timeout | signal 9 | `timeout` |

**Janitor:** A separate function (`janitor_cleanup()`) called from the scheduler every 5 minutes scans for any `friday=true`-labelled container older than `MAX_EXECUTION_AGE=30min` and force-removes it. No orphans accepted.

### 2.4 Network Isolation

Custom Docker bridge `friday-execution-net`:

- Created once at setup: `docker network create friday-execution-net --driver bridge`
- All skill containers attach to this network
- Egress: allowlist-only. Frappe API host is always allowed. Any other host requires `agent_profile.network_allowlist` entry or `skill.network_allowlist` entry
- Implementation: an HTTP egress proxy sidecar (`friday-egress-proxy`) running inside the container network; containers route through it via `http_proxy` env var

For Phase 1, the minimum allowlist is:
```
egress allow: <frappe_base_url>
egress deny: all other hosts
```

The `network_allowlist` field on `Agent Profile` and `Skill` activates in Phase 1.5; Phase 1 accepts the field exists but defaults to Frappe-only allowlist.

### 2.5 Scoped Credentials

When the dispatcher receives a skill call, it calls `resolve_credentials(agent_profile, skill_name)` before spawning the sandbox. This reads any `Skill Credential` rows linked to the skill and profile, and produces a `credentials` dict injected as env vars into the container.

The scoped API token is a Frappe API key generated per execution with:
- Expiry: when the container exits (short-lived)
- Scope: the specific `Agent Profile` only — cannot be used cross-profile
- Stored as env var `FRIDAY_API_TOKEN` inside the container

### 2.6 Integration with Dispatcher (`friday/agent_runner/dispatcher.py`)

The dispatcher in Slice 6 calls the handler directly:

```python
# SLICE 6 (current) — in-process
result = handler(skill_name, parameters)
```

Slice 7 replaces this with:

```python
# SLICE 7 — sandboxed
from friday.friday_core.sandbox.runner import execute as execute_sandbox
result = execute_sandbox(
    skill_name=skill_name,
    parameters=parameters,
    agent_profile=agent_profile,
    credentials={},  # resolved in dispatch before this point
    timeout_seconds=300,
)
```

The dispatcher continues to write the `Execution Log` row (submitted). The log's `status` field maps from `SandboxResult.status`.

### 2.7 Module Structure

```
friday/friday_core/sandbox/
├── __init__.py
├── runner.py          # execute(), SandboxResult dataclass, container lifecycle
├── entrypoint.py      # container entrypoint — skill runner inside container
├── pool.py            # warm pool manager (Phase 1.5; Phase 1 is cold-spawn stub)
├── proxy.py           # egress proxy helper (Phase 1.5; Phase 1 is a comments-only note)
├── credentials.py     # scoped token generation + resolution (stubbed in Phase 1)
└── Dockerfile         # the runtime image definition
```

---

## 3. Files to Create or Modify

### New files

| File | Purpose |
|---|---|
| `friday/friday_core/sandbox/__init__.py` | Package marker |
| `friday/friday_core/sandbox/runner.py` | `execute()` — orchestrator, cold-spawn |
| `friday/friday_core/sandbox/entrypoint.py` | Container entrypoint |
| `friday/friday_core/sandbox/pool.py` | Warm pool stub (cold-spawn returns None; Phase 1.5 wire it) |
| `friday/friday_core/sandbox/credentials.py` | Scoped API key generation stub |
| `friday/friday_core/sandbox/Dockerfile` | Runtime image definition |
| `friday/friday_core/tests/test_sandbox_runner.py` | Unit + integration tests |

### Modified files

| File | Change |
|---|---|
| `friday/friday_core/agent_runner/dispatcher.py` | Replace direct handler call with `execute_sandbox()` call |
| `friday/friday_core/doctype/execution_log/execution_log.json` | `status` options: `oom` and `timeout` added (alongside existing ones) |
| `frappe/hooks.py` | Add `agent_task.assigned` pub/sub handler (for Slice 8 wiring); Wire the janitor scheduler event |
| `docs/contributing/proposals/slice-7-docker-sandbox.md` | This file |

---

## 4. Testing Plan

### Test Cases

| # | Scenario | Expected |
|---|---|---|
| T1 | `execute()` spawns a container and returns `SandboxResult` with `status=success` | Container created, result has stdout JSON, `container_id` set |
| T2 | Skill raises an exception → `status=failed` | Execution Log has `status=failed` |
| T3 | Container OOM (memory limit exceeded) → `status=oom` | Exit code 137, result.status=`oom` |
| T4 | Wall-clock timeout (skill runs > `timeout_seconds`) → `status=timeout` | SIGKILL sent, result.status=`timeout` |
| T5 | Skill attempts egress to non-allowlisted host: connection refused | Container cannot reach external host |
| T6 | 10 consecutive executions → no orphaned containers | `docker ps -a` shows no stale Friday containers |
| T7 | Slice 6's `create_note` flow end-to-end → Note row created | `create_note` skill runs inside Docker container; `Note` row exists |
| T8 | Container with bad skill name → `status=failed` with `invalid_skill` sub-reason | Graceful failure recorded in Execution Log |
| T9 | Null/empty `skill_name` → raises ValueError | Dispatcher catches and returns error DispatchResult |
| T10 | Two concurrent `execute()` calls → both complete independently | No shared state, no race condition |

### Coverage Targets

- `sandbox/runner.py`: ≥ 80% line coverage
- `sandbox/entrypoint.py`: ≥ 80% line coverage
- Integration tests: real Docker spawn + teardown (not mocked)

### Slice 6 Regression

All Slice 6 `test_dispatcher.py` and `test_runner_tool_call.py` tests must pass. The only behavioral change is: skill execution is now inside Docker. From the caller's perspective (`dispatch()`), the interface is unchanged — `SandboxResult` looks like what the handler returned in Slice 6.

---

## 5. Risks & Mitigations

| Risk | Severity | Mitigation |
|---|---|---|
| Docker not installed on developer machines | 🔴 High | Document Docker as a prerequisite; add a `DockerUnavailable` error with clear message; tests skip gracefully if daemon is unreachable |
| Cold-spawn latency too high (> 3s) | 🟠 High | Warm pool is Phase 1.5; add profiling to catch it early; fallback to in-process execution path if this becomes blocking |
| Egress proxy complexity for Phase 1 | 🟠 High | Phase 1: simple iptables-based block on `fraturday-execution-net` default-deny; egress proxy sidecar is Phase 1.5 per DOC 24 §5 |
| Container breakout (skill escapes isolation) | 🔴 Blocker | Drop ALL capabilities, read-only rootfs, nonroot UID, no Docker socket, tmpfs only; runs in CI with attempted break-out test suite |
| Conflicting Docker network name on host | 🟡 Low | Network name `fridays-execution-net-${SITE_NAME}` scoped to site |
| Image pull from public registry fails in restricted env | 🟡 Low | Image build is local; operator can `docker build` from the included Dockerfile |

---

## 6. Exit Gate

### Slice 6 Regression

```
$ bench --site friday.localhost run-tests --module friday.friday_core.tests.test_dispatcher
$ bench --site friday.localhost run-tests --module friday.friday_core.tests.test_runner_tool_call
```
→ **17/17 + 6/6 all green** (unchanged from Slice 6)

### Sandbox Tests

```
$ bench --site friday.localhost run-tests --module friday.friday_core.tests.test_sandbox_runner
```
→ **≥ 10/10 green**

### Manual Smoke Test

1. `docker network create fridays-execution-net --driver bridge` (setup)
2. Run: `bench --friday.localhost friday chat --profile "note_taker"`
3. Type: "make a note titled Docker Test about sandbox isolation"
4. Observe: Note row created in DB; reply confirms it was sandboxed

### Validation Checklist (from `docs/design/11-agent-validation-checklist.md`)

- [ ] Friday-worker Docker image builds cleanly
- [ ] Image has Python 3.14, pinned deps, no host mounts
- [ ] `execute()` returns structured `SandboxResult`
- [ ] Container destroyed after execution (no orphans)
- [ ] Slice 6 `create_note` flow still works end-to-end inside Docker
- [ ] OOM → exit code 137 → `status=oom` recorded
- [ ] Timeout → `status=timeout` recorded
- [ ] Network isolation: non-allowlisted host → connection refused

---

*Last updated: 2026-05-28*
