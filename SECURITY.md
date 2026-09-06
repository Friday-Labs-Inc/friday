# Security Policy

Friday is designed around governed agents, so security issues are treated as product-critical.

## Reporting

Until a public security email is configured, report vulnerabilities privately to the repository maintainers through GitHub private vulnerability reporting if enabled.

Please do not open public issues for exploitable vulnerabilities.

## Scope

Security-sensitive areas include:

- permission checks;
- Agent Profile and Skill activation;
- sandbox execution;
- credential handling;
- Execution Log and Permission Decision Log integrity;
- Raven message actions;
- ERPNext integration and agent users;
- workflow approvals;
- any path that lets an agent execute code or mutate business records.

## Baseline Expectations

- No hard-coded credentials.
- No secret values in logs, prompts, War Room messages, or issue comments.
- Every skill execution must have a Permission Decision Log.
- Every execution attempt must have an Execution Log.
- Agents must not silently activate profiles, skills, or workflows.

## Implemented Security Claims

This section documents what security properties Friday actually guarantees today, with references to the code that enforces them. Claims marked **Phase 2** are not yet implemented.

---

### Layer 1 — Frappe Role-Based Permissions

**Claim:** Agent capabilities are derived from Frappe roles assigned to the Agent Profile. Agents inherit exactly the permissions those roles grant via `DocPerm` and `Custom DocPerm` rows.

**Evidence:**
- [`friday/friday_core/permissions/matrix.py:365-401`](apps/frappe/friday/friday_core/permissions/matrix.py:365) — `_resolve_permitted_ops()` reads both `DocPerm` and `Custom DocPerm` for all assigned roles, matching Frappe's runtime layering.
- [`friday/friday_core/permissions/matrix.py:347-362`](apps/frappe/friday/friday_core/permissions/matrix.py:347) — `_build_matrix_uncached()` collects roles from the Agent Profile's `assigned_roles` child table.
- [`friday/friday_core/permissions/matrix.py:289-305`](apps/frappe/friday/friday_core/permissions/matrix.py:289) — `evaluate()` rejects if the Agent Profile status is not `"Active"`.
- [`friday/friday_core/permissions/matrix.py:292-294`](apps/frappe/friday/friday_core/permissions/matrix.py:292) — Skill must have `status == "Active"`; Draft, Experimental, Retired, and Archived skills cannot be invoked.

**Cache invalidation:** When an Agent Profile or Role is updated, the permission matrix cache is flushed within seconds via `doc_events` wired in [`frappe/hooks.py`](apps/frappe/frappe/hooks.py:1). Evidence: `doc_events` hooks in [`friday/friday_core/permissions/cache.py:158-179`](apps/frappe/friday/friday_core/permissions/cache.py:158) and [`friday/friday_core/skills/loader.py:280-324`](apps/friday/friday_core/skills/loader.py:280).

---

### Layer 2 — Gateway Pre-Check

**Claim:** The permission engine is the single chokepoint before any skill runs. Every invocation — allowed or denied — is logged immutably.

**Evidence:**
- [`friday/friday_core/permissions/matrix.py:308-339`](apps/friday/friday_core/permissions/matrix.py:308) — `check()` is the only gateway entry point; it builds the matrix, evaluates, and calls `decisions.record()` before returning.
- [`friday/friday_core/permissions/decisions.py:80-125`](apps/friday/friday_core/permissions/decisions.py:80) — `record()` inserts and **submits** a Permission Decision Log row, making it immutable. The `matrix_snapshot` field stores a JSON dump of the PermissionMatrix so the decision can be reproduced after roles or skills change.
- [`friday/friday_core/permissions/decisions.py:122`](apps/friday/friday_core/permissions/decisions.py:122) — Uses `ignore_permissions=True` because the system is recording its own audit trail; bypassing Frappe's permission check on the log DocType prevents silent failures that would hide audit rows.

---

### Layer 3 — Docker Sandbox

**Claim:** Skill execution runs inside an isolated Docker container with no network, limited CPU/memory/PIDs, and a read-only filesystem.

**Evidence (sandbox configuration):**

| Property | Value | Evidence |
|---|---|---|
| User | UID 65532 (nonroot) | [`runner.py:339`](apps/frappe/friday/friday_core/sandbox/runner.py:339), [`pool.py:145`](apps/frappe/friday/friday_core/sandbox/pool.py:145) |
| Capabilities | `CAP_DROP ALL` | [`runner.py:341`](apps/frappe/friday/friday_core/sandbox/runner.py:341), [`pool.py:146`](apps/frappe/friday/friday_core/sandbox/pool.py:146) |
| Security option | `no-new-privileges:true` | [`runner.py:342`](apps/frappe/friday/friday_core/sandbox/runner.py:342), [`pool.py:147`](apps/frappe/friday/friday_core/sandbox/pool.py:147) |
| Filesystem | `read_only=True` | [`runner.py:340`](apps/frappe/friday/friday_core/sandbox/runner.py:340), [`pool.py:148`](apps/frappe/friday/friday_core/sandbox/pool.py:148) |
| `/tmp` | `tmpfs` (64 MB, noexec, nosuid) | [`pool.py:149`](apps/frappe/friday/friday_core/sandbox/pool.py:149) |
| CPU limit | 1 cgroup quota by default | [`runner.py:336`](apps/frappe/friday/friday_core/sandbox/runner.py:336) |
| Memory limit | 256 MB by default | [`runner.py:337`](apps/frappe/friday/friday_core/sandbox/runner.py:337) |
| PIDs limit | 256 | [`runner.py:338`](apps/frappe/friday/friday_core/sandbox/runner.py:338) |
| Network | Isolated `friday-network` (no external egress) | [`runner.py:306`](apps/frappe/friday/friday_core/sandbox/runner.py:306), [`runner.py:108-121`](apps/frappe/friday/friday_core/sandbox/runner.py:108) |

**Egress allowlist (Phase 1.5):** Extra hosts in `Agent Profile.network_allowlist` are injected into the container's `/etc/hosts` as `127.0.0.1` mappings, redirecting allowlisted domains to localhost where a proxy can intercept them. Evidence: [`runner.py:138-177`](apps/frappe/friday/friday_core/sandbox/runner.py:138) (`_get_egress_config()` + `_build_etc_hosts()`), [`runner.py:327`](apps/frappe/friday/friday_core/sandbox/runner.py:327) (volume mount of hosts file as read-only).

**Warm pool security:** Pooled containers are created with identical restrictive settings and remain **paused** between executions. Evidence: [`pool.py:156-161`](apps/frappe/friday/friday_core/sandbox/pool.py:156) (immediate pause after spawn), [`pool.py:236-262`](apps/friday/friday_core/sandbox/pool.py:236) (`_repool_container()` wipes `/tmp` and re-pauses).

---

### Layer 4 — Frappe REST API as Trust Boundary

**Claim:** Containers authenticate to Frappe using a scoped bearer token (Phase 1.5). Frappe validates the token before processing any skill request.

**Evidence:**
- [`friday/friday_core/sandbox/credentials.py:33-46`](apps/frappe/friday/friday_core/sandbox/credentials.py:33) — `generate_scoped_token()` uses `frappe.generate_hash()` for cryptographically random tokens.
- [`friday/friday_core/sandbox/runner.py:303`](apps/frappe/friday/friday_core/sandbox/runner.py:303) — Token generated per execution, passed as `FRIDAY_API_TOKEN` and `FRIDAY_API_KEY` env vars.
- [`friday/friday_core/sandbox/runner.py:324`](apps/frappe/friday/friday_core/sandbox/runner.py:324) — Bearer token set as `FRIDAY_API_KEY` for the Frappe API client inside the container.

Note: Phase 1.5 token **generation** is implemented. Token **verification** in Frappe's API layer (server-side expiry, scope enforcement) is Phase 1.5 server-side validation — documented in [`credentials.py:9-18`](apps/frappe/friday/friday_core/sandbox/credentials.py:9) as a Phase 1.5 item.

---

### Layer 5 — Inter-Agent Communication

**Claim:** Agents communicate via Frappe Chat Message rows. A dedicated `agent_id` field prevents spoofing.

**Evidence:**
- [`frappe/friday/friday_core/doctype/chat_message/chat_message.json`](apps/frappe/friday/friday_core/doctype/chat_message/chat_message.json) — `sender` and `recipient` fields identify agents explicitly.
- [`frappe/friday/friday_core/gateway/service.py`](apps/frappe/friday/friday_core/gateway/service.py:1) — Gateway uses `doc_events` hooks to process inbound messages; sender identity is captured at insert time.

---

### Layer 6 — Approval Workflows

**Claim:** Agent Task uses a Frappe Workflow with explicit Approved/Rejected states. Agents cannot activate workflows on their own.

**Evidence:**
- [`frappe/friday/friday_core/doctype/agent_task/agent_task.json`](apps/frappe/friday/friday_core/doctype/agent_task/agent_task.json:1) — Agent Task DocType has `workflow_state` field.
- [`frappe/friday/friday_core/tasks/workflow.py:1`](apps/frappe/friday/friday_core/tasks/workflow.py:1) — Workflow hook registered as `doc_events["Agent Task"]["on_update"]`; transitions are driven by Frappe Workflow engine, not by agent code.
- [`frappe/friday/friday_core/doctype/agent_task/agent_task.json`](apps/frappe/friday/friday_core/doctype/agent_task/agent_task.json:1) — No field allows an agent to submit or approve its own task directly.

---

### Layer 7 — Shell-Command Policy Engine

**Status: Phase 2 (not yet implemented)**

This layer is documented in the design but has not been built. It would enforce a policy over shell commands spawned inside skill handlers.

---

### Layer 8 — Audit Trail

**Claim:** Every permission decision and every execution is recorded in an immutable DocType.

**Evidence:**
- Permission decisions: [`friday/friday_core/permissions/decisions.py:80-125`](apps/friday/friday_core/permissions/decisions.py:80) — rows are **submitted** (immutable).
- Execution logs: [`friday/friday_core/agent_runner/dispatcher.py:453-490`](apps/frappe/friday/friday_core/agent_runner/dispatcher.py:453) — `_write_execution_log()` records every dispatch attempt.
- Execution Log DocType: [`frappe/friday/friday_core/doctype/execution_log/execution_log.json`](apps/frappe/friday/friday_core/doctype/execution_log/execution_log.json:1) — `status` field captures `success`, `failed`, `timeout`, `oom`, `error`.
- Credential redaction: [`friday/friday_core/sandbox/credentials.py:108-124`](apps/frappe/friday/friday_core/sandbox/credentials.py:108) — `redact_credentials_from_logs()` replaces known credential values with `[REDACTED:name]` before logs are stored.

---

## Credential Handling

Credentials are resolved per (Agent Profile, Skill) pair from the Skill Credential DocType and injected exclusively as environment variables into the sandbox container. They are never written to disk.

**Evidence:**
- [`friday/friday_core/sandbox/credentials.py:49-105`](apps/frappe/friday/friday_core/sandbox/credentials.py:49) — `resolve_credentials()` reads Skill Credential rows and returns a dict of `FRIDAY_CREDS_<name>` env vars.
- [`friday/friday_core/sandbox/runner.py:319-325`](apps/frappe/friday/friday_core/sandbox/runner.py:319) — credentials dict merged into container `env` list at execution time.
- No credential values in logs: [`friday/friday_core/sandbox/credentials.py:108-124`](apps/friday/friday_core/sandbox/credentials.py:108) — `redact_credentials_from_logs()` is called before any log storage.

---

## Resource Quotas

Agents are bound to per-profile resource limits enforced in the sandbox.

**Evidence:**
- [`friday/friday_core/sandbox/runner.py:184-201`](apps/frappe/friday/friday_core/sandbox/runner.py:184) — `_resolve_limits()` reads `cpu_cores`, `memory_mb`, and `timeout_seconds` from the Agent Profile's quota fields, with defaults of 1 core / 256 MB / 300 s.
- Docker cgroup limits applied directly: [`runner.py:335-338`](apps/frappe/friday/friday_core/sandbox/runner.py:335) — `cpu_period`, `cpu_quota`, `mem_limit`, `pids_limit` passed to `client.containers.run()`.

---

## What's Not Yet Implemented

- **Shell-command policy engine (Layer 7)** — Phase 2.
- **Scoped token server-side verification in Frappe API** — Phase 1.5 (token generation exists; verification endpoint is pending).
- **Skill Credential DocType schema and UI** — partial (the table and SQL query exist in `credentials.py`; the DocType JSON may need to be created).
