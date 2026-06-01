# 24 — Sandbox Architecture & Implementation

> See `00-glossary.md` for term definitions.
> Implements the isolation layer from `04-security-model.md` Layer 3.
> Phase 1 minimum bar lives in `42-phase-one-authority-contract.md` §5. Anything beyond that is Phase 1.5+.

---

## 1. Goals

- **Strong isolation** — a compromised skill cannot read other agents' data, the host, or another container.
- **Predictable resources** — every execution gets defined CPU, memory, disk, and time budgets. No noisy-neighbour effects.
- **Acceptable startup latency** — < 200ms median (warm pool); < 1.5s (cold).
- **Safe by default** — operators do not have to harden network or capabilities; Friday does it.
- **Observable** — every container start, exit, kill, OOM is logged and queryable.

Non-goals: defeating a kernel-level attacker; full multi-tenant compliance (separate documents).

---

## 2. Architecture

```
        Gateway dispatcher
              │
              ▼
       ┌──────────────────┐
       │ Sandbox          │
       │ Orchestrator     │   ← Friday Python module
       └──────────────────┘
              │
   ┌──────────┴──────────┐
   ▼                     ▼
Container Pool        Container Spawner
(warm, 5–20 idle)     (cold when pool empty)
              │
              ▼
       Docker daemon
              │
   ┌──────────┴──────────────────┐
   ▼            ▼                ▼
Container A  Container B  ...  Container N

Each container:
  - read-only rootfs (overlay)
  - tmpfs scratch (/tmp, 64MB, noexec, nosuid)
  - no host mounts; no Docker socket
  - network = friday-execution-net (egress allowlist)
  - cgroups: CPU, memory, PIDs, IO weight
  - capabilities: drop ALL
  - user: nonroot (UID 65532)
  - env: scoped API token + skill credentials
```

---

## 3. Container image

A single Friday-managed runtime image:

```dockerfile
FROM python:3.14-slim AS runtime

# Pinned dependencies for skill runtime.
RUN pip install --no-cache-dir \
    requests==2.32.3 \
    pydantic==2.7.1 \
    frappe-client==1.0.0

# Nonroot user.
RUN useradd --no-create-home --uid 65532 friday
USER friday
WORKDIR /home/friday

# Entrypoint: reads task JSON from stdin, executes, exits.
COPY --chown=friday:friday entrypoint.py /home/friday/entrypoint.py
ENTRYPOINT ["python", "/home/friday/entrypoint.py"]
```

Built reproducibly. Pinned digests recorded in `friday-images.lock`. `trivy` scans on every release; no critical or high CVEs may ship.

---

## 4. Spawn lifecycle

### 4.1 Request

```python
result = sandbox.execute(
    skill=skill,
    parameters=parameters,
    agent_profile=agent_profile,
    credentials=resolved_credentials,
    timeout_seconds=300,
    cpu_cores=2,
    memory_mb=512,
)
```

### 4.2 Pool check

The orchestrator maintains a warm pool (configurable; default min_idle=5, max_idle=20). On a hit, the container is reset (env cleared, scratch wiped) and reused. Otherwise cold-spawn.

### 4.3 Configuration applied

| Setting | Value |
|---|---|
| Image | `friday/skill-runtime:vX.Y.Z` (pinned digest) |
| Network | `friday-execution-net` (custom bridge, egress allowlist) |
| CPUs | `cpu_cores` (cgroup quota) |
| Memory | `memory_mb` (cgroup limit; swap disabled) |
| PIDs | 256 |
| Read-only rootfs | yes |
| tmpfs mount | `/tmp` (64MB, noexec, nosuid) |
| Capabilities | drop ALL; add nothing |
| User | UID 65532 (nonroot) |
| Seccomp | Docker default profile |
| AppArmor / SELinux | `docker-default` when available |
| `no-new-privileges` | yes |
| Env vars | scoped API token + credential bindings + task metadata |

### 4.4 Task payload

```json
{
  "skill_name": "send_notification",
  "skill_version": 4,
  "parameters": {"note_id": "NOTE-001"},
  "frappe_base_url": "http://frappe:8000",
  "execution_id": "uuid...",
  "trace_id": "uuid..."
}
```

### 4.5 Execution

`entrypoint.py` inside the container:

1. Reads payload from stdin.
2. Validates the JSON shape.
3. Loads the skill module by name (bundled into the image or fetched read-only from a skill repo if not bundled).
4. Calls the skill's `run(parameters, frappe_client)` with a Frappe client authenticated via the scoped API token.
5. Captures stdout and stderr.
6. Writes the result envelope:
   ```
   >>>FRIDAY_RESULT_BEGIN<<<
   {...}
   >>>FRIDAY_RESULT_END<<<
   ```
7. Exits 0 on success, non-zero on failure.

### 4.6 Result capture and exit

The orchestrator reads stdout, parses the envelope, captures surrounding logs, and stops the container. On normal exit: destroyed (cold mode) or returned to the pool reset (warm mode).

### 4.7 Timeout

Wall clock exceeds `timeout_seconds` → SIGTERM, wait 5s, then SIGKILL. Execution recorded as `timeout`.

### 4.8 OOM

Docker kills containers exceeding memory limit. Exit code 137 → recorded as `oom`.

### 4.9 Cleanup verification

A janitor scans every 5 minutes for any container labelled `friday=true` older than `MAX_EXECUTION_AGE` (default 30 min) and force-removes it. No orphans accepted.

---

## 5. Network policy

Custom Docker bridge `friday-execution-net`:

- DNS resolution beyond an allowlist is denied (via a dnsmasq sidecar or per-skill iptables egress allowlist).
- Default-deny on egress.
- Per-skill / per-agent allowlist appended at spawn time:
  - Frappe API host is always allowed (skills must call back).
  - Hosts in `agent_profile.network_allowlist` allowed.
  - Hosts in `skill.network_allowlist` allowed.

Implementation: a sidecar HTTP egress proxy. Containers reach the outside world only through it; the proxy enforces the allowlist based on container labels.

**Open question:** Docker bridge networking has known limits at scale. Single-host with < 50 concurrent containers (Phase 1 target) is well within Docker's capability. For > 1000 concurrent containers per host, Kubernetes-based isolation is the better fit — Phase 2+ evaluation.

---

## 6. Filesystem isolation

- Root filesystem read-only (`--read-only`).
- `/tmp` is the only writeable location, backed by tmpfs (no disk persistence).
- No host paths bind-mounted.
- No Docker socket exposed.
- Logs stream via container stdout/stderr to the orchestrator; not written to disk.

A skill producing a persistent artifact (e.g. a generated PDF) writes to `/tmp`, uploads via the Frappe File API with proper permissions, and returns the File DocType reference in its result JSON. Artifact creation funnels through Frappe's permission and audit system.

---

## 7. Credential injection

Per `23-secrets-credentials-management.md`:

- Credentials passed as env vars at container start.
- Container has read-only access to env from inside; cannot mutate the host's view.
- Friday's masker scans the container's stdout/stderr stream for credential values and redacts before they reach the Execution Log.
- Container `linkmode` is configured so env vars are not exposed to peer containers.

---

## 8. Pool management

```
Warm pool
├── min_idle = 5
├── max_idle = 20
├── max_age_per_container = 1 hour
└── reset_on_release: clear env vars, wipe /tmp, re-stat capabilities

Scaling rules:
- queue_depth > 0 AND idle < max_idle → keep warm
- queue idle > 60s AND idle > min_idle → drain to min_idle
- container exited with error → don't return to pool; spawn fresh
```

Pool containers spawn in a suspended state (sleeping on stdin read). Dispatch writes the task payload to stdin. Effective cold-start cost: ~50ms typical.

---

## 9. Per-agent resource quotas

Beyond per-container limits, Friday tracks per-agent budgets sourced from `agent_role_profile.default_resource_quota`:

- Max concurrent containers.
- Max executions per hour.
- Max CPU-seconds per day.
- Max memory-MB-seconds per day.

When an agent exceeds budget:

- **Soft cap:** subsequent invocations queued, not denied; operator notified.
- **Hard cap:** invocations rejected with a clear error and an Execution Log row of status `quota_exceeded`.

---

## 10. Observability

Per execution, structured logs and metrics:

| Metric | Type |
|---|---|
| `friday_container_spawn_total` | counter; label cold_or_warm |
| `friday_container_duration_seconds` | histogram; label skill_name, status |
| `friday_container_exit_code` | counter; label code |
| `friday_container_oom_total` | counter |
| `friday_container_timeout_total` | counter |
| `friday_container_pool_size` | gauge |
| `friday_container_queue_depth` | gauge |

Logs carry the `trace_id` so a full trace (gateway → orchestrator → container → result) is reconstructable.

---

## 11. Failure modes

| Mode | Detection | Recovery |
|---|---|---|
| Container crash | non-zero exit | Record `failed`; submit Execution Log; free pool slot |
| OOM | exit code 137 | Record `oom`; recommend increasing memory in skill config |
| Wall-clock timeout | orchestrator timer | Record `timeout`; SIGKILL; free pool slot |
| Docker daemon unresponsive | spawn API timeout | Circuit-break: stop dispatching for N seconds; alert operator |
| Egress denied | skill HTTP error | Record in Execution Log; surface in War Room |
| Skill module not found | entrypoint error | Record `invalid_skill`; mark Skill row degraded |
| Result envelope missing | parse failure | Record `protocol_error`; retain stdout for debugging |
| Orphan container | janitor scan | Force-remove; log warning |

Every failure produces an Execution Log row. Silent failures are not acceptable.

---

## 12. Host hardening checklist

Per host running the orchestrator:

- [ ] Docker daemon socket not exposed over network (Unix socket only).
- [ ] Host kernel patched; weekly automated update window.
- [ ] AppArmor or SELinux enforcing on the host.
- [ ] Image registry uses signed manifests (Docker Content Trust).
- [ ] Friday image rebuilt and rescanned weekly.
- [ ] No skill bundled into the base image; skills loaded from Frappe at runtime.
- [ ] Container runtime CVE feeds monitored.
- [ ] Egress allowlist regularly reviewed.
- [ ] Audit log of all `docker run` invocations retained for 1 year.

---

## 13. Multi-host and scaling

Phase 1 targets a single host. Phase 2 scales horizontally:

- Multiple sandbox-orchestrator workers per Frappe site.
- Frappe RQ load-balances dispatches across workers.
- Each worker maintains its own pool; no cross-worker pool sharing.
- Eventually: optional Kubernetes-backed mode where each skill execution is a Pod.

The transition is mechanical. The `sandbox.execute(...)` API does not change.

---

## 14. Alternatives considered

| Alternative | Why not (Phase 1) |
|---|---|
| Firecracker microVMs | Stronger isolation; more operational complexity. Phase 3 consideration. |
| gVisor | Stronger syscall isolation; performance hit. Phase 3 consideration. |
| Process-level sandbox (no container) | Too weak; rejected per `04-security-model.md` threat model |
| Per-skill Kubernetes Pod | Too heavy for sub-second dispatch latency |
| Wasm sandbox | Insufficient skill ecosystem; LLM-generated Wasm is impractical |

Docker with hardened defaults strikes the Phase 1 balance.

---

## 15. Testing

| Type | Scope |
|---|---|
| Unit | Orchestrator logic (pool management, payload serialisation) |
| Integration | Real Docker spawn/teardown; resource limits enforced |
| Security | Attempted break-outs: egress to disallowed host, Docker socket mount, host OOM, fork bomb (pid limit), DNS amplification, infinite loop vs. timeout |
| Load | 100 concurrent executions; pool drains correctly; no orphans |
| Chaos | Kill containers mid-execution; orchestrator detects and records |

The security test suite runs in CI and is a release blocker on regression.

---

## 16. Phasing

| Phase | Sandbox capability |
|---|---|
| 1 (v0.1) | Minimum bar per `42-phase-one-authority-contract.md` §5: non-root, resource limits, timeout / OOM handling, no host or Docker socket mounts, scoped credentials, structured result capture, cleanup path |
| 1.5 | Hardened single-host: warm pool, egress allowlist/proxy, read-only rootfs everywhere, full observability, automated attack suite |
| 2 | Multi-host orchestration via RQ; cross-host pool-aware dispatch |
| 3 | Optional gVisor / Firecracker backend for high-risk skills |
| 4 | Kubernetes-backed mode for cloud deployments |
