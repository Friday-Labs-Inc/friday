# Doc 49 — Foundations Deviation Audit

**Status:** Findings, not yet actioned
**Audited against:** `main` @ `0f2cdd9` (includes PR #35 "make main green" and PR #36 doc 48)
**Date:** 2026-05-30
**Why this exists:** We halted Roo Code because the foundation felt like it had
drifted from the design docs. This is the complete, evidence-backed list of where
the code and the design docs disagree — ranked worst-first — so we can decide the
fix order together. **Nothing here is fixed yet.** This is the map, not the repair.

Sibling precedent: [doc 46 — security-claims-audit](46-security-claims-audit.md)
did the same evidence-first treatment for the security claims. This doc does it for
the whole agent-execution foundation.

---

## 0. How to read this

Every finding has four parts:

- **In plain English** — what's wrong, no jargon. A new developer should understand it.
- **Evidence** — exact `file:line` so you can see it yourself.
- **Design doc it breaks** — which committed spec this contradicts.
- **The Frappe-correct fix** — what "right" looks like, in Frappe's own terms.

Severity ladder:

| Tag | Meaning |
|-----|---------|
| **CRITICAL** | A headline v0.1 capability does not work at all, or a security boundary is absent. |
| **HIGH** | A core capability or guarantee is missing/unenforced; the system "looks done" but isn't. |
| **MEDIUM** | Real bug or spec-drift that is currently masked, latent, or cosmetic-but-misleading. |
| **LOW** | Dead wiring, doc gaps, or correctness bugs that are dormant behind a bigger finding. |

---

## 1. TL;DR — the ranked list

| # | Sev | One-line | Breaks |
|---|-----|----------|--------|
| **C1** | CRITICAL | The async Agent Task execution route is **dead** — tasks get claimed but never run. | doc 42 §7 (task route) |
| **C2** | HIGH (borderline CRITICAL) | The Docker sandbox is **advisory, not mandatory** — any Docker hiccup silently runs skills in-process. | doc 04 Layer 3, doc 42 §5 |
| **H1** | HIGH | There is **no ReAct loop** — the agent takes exactly one action then stops. | doc 47 / Hermes parity |
| **H2** | HIGH | The **approval subsystem is half-wired** — the `requires_approval` flag exists but nothing enforces it. | doc 04 Layer 2 §7 + Layer 6, doc 42 §3 |
| **H3** | HIGH | The **scoped-credential token is a stub** nobody validates, and there are **two different token generators**. | doc 04 Layer 4, doc 23/24 |
| **M1** | MEDIUM | **Docs 04 + 05 are stale** — they mandate things that don't (and shouldn't) exist. This is the *root cause* of the drift. | n/a (the docs are the bug) |
| **M2** | MEDIUM | **Resource quotas can't be set** — the code reads a field that doesn't exist, so limits always fall back to defaults. | doc 04 quotas |
| **M3** | MEDIUM | The production handler is registered under a **test name** (`slice6-create-note`), and there are **two divergent handler registries**. | doc 10 Slice 6 |
| **M4** | MEDIUM | The two skill-execution call paths **disagree on the function signature** — the task path passes `api_key=` to a function that has no such parameter (latent `TypeError`, masked by C1). | n/a (internal consistency) |
| **M5** | MEDIUM | The task dispatcher reads `profile.agent_role_profile`, a **field that does not exist** → latent `AttributeError`. | n/a (latent crash) |
| **L1** | LOW | **Missing rollout docs** for Slices 6–9 + War Room (our two-layer docs rule). | internal rule |
| **L2** | LOW | **Dead wiring:** `hooks.py` still registers a now-no-op handler on every migrate. | n/a |
| **L3** | LOW | The sandbox egress allowlist is **logically inverted** and uses a **host-filesystem bind-mount** (a doc 42 §5 checklist violation). Dormant behind C2. | doc 42 §5 |
| **L4** | LOW | **Execution Log field drift** — `duration_ms` is stuffed into the result JSON instead of its column; the permission link is only set on rejection. | doc 04 audit schema |

---

## 2. What is SOLID — do not "fix" these

The audit is not all bad news. The **chat path is sound and faithful** and must not be
disturbed while we repair the rest:

- **The chokepoint pattern works.** `gateway.service.handle_inbound` is the single
  entry for inbound messages, exactly as locked in [doc 47](47-gateway-design-decisions.md).
- **Permission enforcement is real and deny-by-default.** `permissions.matrix.check()`
  is called on every dispatch (`agent_runner/dispatcher.py:220`), writes an **immutable**
  Permission Decision Log via `decisions.record()` (insert + submit), and denies anything
  not explicitly allowed.
- **The audit trail is immutable.** Execution Log rows are submitted (`status in ("success","rejected")`)
  so they cannot be edited after the fact (`agent_runner/dispatcher.py:487`).
- **Defense in depth is correctly layered.** `skills.loader` filters the tool menu at
  menu-build time using `evaluate` (pure, no logging), and the dispatcher re-checks at
  call time using `check` (logs). A stale menu cache cannot grant a forbidden skill.
- **The LLM provider resolution is clean.** `llm/provider.py` resolves provider strictly
  from the LLM Provider DocType with a 3-level fallback. (Only Minimax is implemented; that
  is a known scope line, not a deviation.)

When we fix the task path (C1), it should be wired to *reuse* this same dispatcher so the
async route inherits all of the above for free.

---

## 3. What is NOT a deviation — do not over-correct

Two things look missing if you read the *stale* docs (04/05), but are correctly absent
per the **authoritative** [doc 42](42-phase-one-authority-contract.md). Calling these
"deviations" would push us to build complexity the locked scope explicitly avoids:

- **Agent Role Profile** — doc 42 §3 makes this **conditional**: build it only *"if Frappe's
  native Role Profile is insufficient."* The code correctly relies on Frappe's native
  `Has Role` / roles. Its absence is **correct**. (The one stray reference to
  `profile.agent_role_profile` in `tasks/dispatcher.py` is a leftover bug — see M5 — not
  evidence we need the DocType.)
- **Agent Session** — not in doc 42 at all. `Chat Message.session_id` being a plain `Data`
  string (`chat_message.json`) is fine for single-tenant v0.1. We are
  [single-tenant, not SaaS](../../README.md); a session-registry DocType is not required.

---

## 4. Findings

### C1 — CRITICAL — The async Agent Task route is dead

**In plain English.** Friday has two ways to do work: (1) you chat with it and it acts
immediately, and (2) it runs queued background "Agent Tasks." Route (1) works. **Route (2)
is completely dead.** A task gets claimed and marked assigned, an event is announced — and
then nothing runs it. The task sits forever.

**Why it's dead.** The code tries to "subscribe" to a server-side event using
`frappe.realtime.on(...)`. That function **does not exist on the server.** In Frappe,
`frappe.publish_realtime` is a *one-way push to browser clients over socket.io* — it is not
a server-side message queue you can subscribe to. PR #35 already discovered this (it was
crashing `bench migrate`) and stopped the crash by turning the subscriber into a no-op:

- `tasks/runner.py:75` — `register_task_runner()` is now literally `pass`. Its own docstring
  (`tasks/runner.py:55-74`) explains the problem correctly but only applied the band-aid.
- `tasks/dispatcher.py:107` — the cron dispatcher claims a task and calls
  `frappe.publish_realtime("agent_task.assigned", ...)`.
- `tasks/workflow.py:135` — the workflow hook **also** emits the same event (a second dead emit).
- `tasks/runner.py:78` `on_agent_task_assigned` → `:141` `_run_task` is the only code that
  would actually execute a task, and **nothing reaches it.**

**Evidence.** The emits go to browsers; the one consumer is a no-op. Net effect: claimed
tasks never execute.

**Design doc it breaks.** [doc 42 §7](42-phase-one-authority-contract.md) completion gate
lists the Agent Task route as required v0.1 functionality.

**The Frappe-correct fix.** Replace the publish/subscribe fiction with a real background job.
At the point we currently emit (dispatcher and/or workflow hook), call:

```python
frappe.enqueue(
    "frappe.friday_core.tasks.runner.on_agent_task_assigned",
    queue="long",
    message={"task_name": ..., "assigned_to_profile": ...},
)
```

Then delete the no-op `register_task_runner` and its `hooks.py` entry (L2). Keep exactly
one emit site (collapse the dispatcher/workflow duplication). `_run_task` should dispatch
through the **same** `agent_runner.dispatcher.dispatch` the chat path uses, so it inherits
permission checks + immutable logs.

---

### C2 — HIGH (borderline CRITICAL) — The sandbox is advisory, not mandatory

**In plain English.** Skills are supposed to run locked inside a Docker container so a
buggy or malicious skill can't touch the host. But if Docker is unavailable for *any*
reason (image not built, daemon down, an exception), the dispatcher quietly runs the skill
**in-process instead** — inside the Frappe worker, with full privileges. The isolation
boundary the security model promises just… isn't there in that failure mode.

**What PR #35 already changed.** This used to be *silent*. PR #35 restored a `WARNING` log
(`agent_runner/dispatcher.py:384-385`) so ops can at least see it happen. That's an
improvement — but a log line is not a wall. There is still **no "strict mode"** that makes
the sandbox mandatory.

**Evidence.**
- `agent_runner/dispatcher.py:371-383` — `_execute_sandboxed` wraps `sandbox.execute(...)`
  in a `try`; on *any* exception it `return handler(skill_name=..., parameters=...)`
  in-process.
- `sandbox/runner.py:82-97` — when Docker is missing, `_get_client` returns a dummy
  `_NoDocker` whose `.images()` raises, guaranteeing the fallback path triggers.

**Why "borderline CRITICAL."** For a single-tenant site the sandbox exists to protect the
site from a misbehaving *skill*. If skill code is ever untrusted, in-process fallback means
a bad skill runs with the worker's full database and filesystem access. **Promote to CRITICAL
if the threat model includes untrusted skill code; keep at HIGH if all skills are first-party
and trusted in v0.1.** This is a judgment call for us to make together.

**Design doc it breaks.** [doc 04](04-security-model.md) Layer 3 (isolation) and
[doc 42 §5](42-phase-one-authority-contract.md) "sandbox minimum bar."

**The Frappe-correct fix.** Add a site-config flag, e.g. `friday_require_sandbox` (default
**True** in production). When set, `_execute_sandboxed` should **raise** (and write an
`error` Execution Log) instead of falling back. Allow fallback only when the flag is
explicitly off (developer machines). The fallback then becomes opt-in, not the default.

---

### H1 — HIGH — There is no ReAct loop

**In plain English.** A real agent thinks, acts, *looks at the result, and decides what to
do next* — repeating until the job is done (this is the "ReAct" loop: reason → act →
observe). Friday does **one** action and stops. It dispatches the first tool call the LLM
returns and hands back the raw result, with no second turn.

**Evidence.**
- `agent_runner/runner.py:85-89` — checks for tool calls.
- `agent_runner/runner.py:92` — comment claims *"multi-step loop is Slice 8"* — but Slice 8
  shipped as the **tasks module** (a different thing); the agent loop was never built.
- `agent_runner/runner.py:100` — dispatches `tool_calls[0]` only (the first call).
- `agent_runner/runner.py:121-129` — calls `dispatch(...)` once and returns `result.content`
  (raw output), never feeding the observation back to the model.

**Design doc it breaks.** Parity with **Hermes**, whose agent core is a think-act-observe
loop. [doc 47](47-gateway-design-decisions.md) Q11.9 deferred *tool invocation* to Slice 6;
the multi-step loop itself was never specced as "done."

**The Frappe-correct fix.** Already **design-locked** in [doc 48](48-hermes-port-decisions.md)
(Feature A). The loop belongs in `agent_runner.runner.run_turn`: after `dispatch`, append the
tool result to the message list and re-call the LLM, bounded by a max-iterations guard, until
the model returns a final text answer. (This is the next sprint item; flagged here for
completeness because it is a foundation gap, not a nice-to-have.)

---

### H2 — HIGH — The approval subsystem is half-wired (more dangerous than missing)

**In plain English.** Skills can be marked "this needs a human to approve before it runs."
The flag exists, the UI field exists, the loader reads it and even shows it to the LLM — but
**nothing ever stops and waits for approval.** A skill marked `requires_approval=True`
executes immediately. It *looks* implemented, which is worse than an obvious gap because it
gives false confidence.

**Evidence.**
- `skills/loader.py:155,167,177,193,211` — `requires_approval` is loaded into `SkillDefinition`
  and serialized into the tool definition handed to the LLM.
- `agent_profile.json` — a profile-level `requires_approval_above_risk` (Select) field also
  exists.
- **But:** `permissions/matrix.py` contains **zero** approval logic, the dispatcher never
  reads `requires_approval`, and **`Workflow Request` appears 0 times in the entire codebase**
  (the DocType doc 42 §3 calls for does not exist).

**Design doc it breaks.** [doc 04](04-security-model.md) Layer 2 step 7 ("if
`skill.requires_approval` → create Workflow Request") and Layer 6 (approval workflows);
[doc 42 §3](42-phase-one-authority-contract.md) lists the Workflow Request schema as required.

**The Frappe-correct fix.** Decide scope first (this is a real v0.1-vs-later question): either
(a) build the minimal **Workflow Request** DocType + a gate in `dispatch` that, when a skill
requires approval, writes a pending Workflow Request and returns "awaiting approval" instead
of executing; or (b) if approvals are out of scope for v0.1, **remove the half-wiring** and
mark doc 04 §7/Layer 6 as deferred so the data model stops advertising a guarantee it doesn't
keep. Do **not** leave it half-wired.

---

### H3 — HIGH — Scoped-credential token is an unvalidated stub, and there are two of them

**In plain English.** When a skill runs in the sandbox it's supposed to get a short-lived,
scoped API token so it can call back into Frappe with *limited* rights that expire when the
container dies. Today the token is a throwaway random string that **Frappe never checks** —
so the "Layer 4" trust boundary in the security model isn't actually enforced. Worse, there
are **two different functions** that mint these tokens, in two modules, and they don't agree.

**Evidence.**
- `sandbox/runner.py:208-216` — `_generate_scoped_token` returns `str(uuid.uuid4())` with a
  literal `TODO Phase 1.5` note; used at `sandbox/runner.py:303`.
- `sandbox/credentials.py:33-46` — a *different* `generate_scoped_token` returns
  `frappe.generate_hash(length=32)`; used by the task path at `tasks/runner.py:217`.
- Nothing server-side validates either token's scope or expiry.

**Design doc it breaks.** [doc 04](04-security-model.md) Layer 4 (agent-scoped API key trust
boundary); doc 23/24 (secrets/credential management).

**The Frappe-correct fix.** Pick **one** generator (delete the other). For real enforcement,
mint a genuine Frappe API Key/Secret scoped to the agent profile with an expiry equal to the
container timeout, pass it as the container's bearer token, and let Frappe validate it
server-side. **Note:** this is an *explicitly documented* Phase 1.5 deferral — the deviation
is that doc 04 presents Layer 4 as a current guarantee when it is not yet enforced. Lower
urgency than C1/C2, but it is a security-boundary claim that today is decorative.

---

### M1 — MEDIUM — Docs 04 + 05 are stale (this is the root cause of the drift)

**In plain English.** The reason the code drifted is that two design docs describe a
*different, heavier* system than the one we locked. Whoever coded against 04/05 built toward
ghosts. These docs are the actual bug.

**Evidence (things 04/05 mandate that don't — and shouldn't — exist):**
- **Agent Session** — referenced in doc 04; never built (and not required, see §3).
- **Workflow Request** — doc 04 Layer 2/6; 0 occurrences in code (see H2).
- **`resource_quota` as a Table** and **`network_allowlist` as a Table** — doc 04; actual
  `agent_profile.json` has **no** `resource_quota` field and `network_allowlist` is a
  `Small Text` (see M2).
- **doc 05** mandates Agent Session / Agent Role Profile / Workflow Request *unconditionally*,
  prescribes a module layout (`agents/`, `messaging/`, `approvals/`) that does not match the
  real `friday_core/` tree, and names the wrong inbound hook target
  (`friday.gateway.session_manager.on_new_message`; the real one is
  `gateway.service.handle_inbound`).

**Design doc it breaks.** The docs *are* the deviation. [doc 42](42-phase-one-authority-contract.md)
is the authority; 04/05 were never reconciled down to the locked single-tenant scope.

**The Frappe-correct fix.** Reconcile 04 and 05 to doc 42: mark superseded sections, correct
the DocType/field types to match the actual schema, fix the hook target and module layout,
and add a banner pointing to doc 42 as the source of truth. This is *documentation work*
(safe for me to do) and it stops the bleeding for whoever codes next.

---

### M2 — MEDIUM — Resource quotas are not settable

**In plain English.** You're supposed to be able to cap a profile's CPU/memory/timeout. The
code tries to read those caps from a profile field that **doesn't exist**, so it silently
falls back to hard-coded defaults (1 CPU, 256 MB, 300 s) every time. The knobs are fake.

**Evidence.**
- `sandbox/runner.py:184-201` — `_resolve_limits` does `profile.get("resource_quota") or {}`.
- `agent_profile.json` — has **no** `resource_quota` field, so the `.get` is always empty.

**Design doc it breaks.** [doc 04](04-security-model.md) resource-quota controls.

**The Frappe-correct fix.** Either add the `resource_quota` fields to Agent Profile (and read
them properly), or, if per-profile quotas are out of v0.1 scope, drop the dead `_resolve_limits`
lookup and document the fixed defaults as intentional.

---

### M3 — MEDIUM — Production handler registered under a test name; two registries

**In plain English.** The one real skill (`create_note`) is registered in the chat path under
the throwaway name **`slice6-create-note`**, but every doc and the Skill DocType talk about
**`create_note`**. Separately, the sandbox has its **own** handler registry that *does* use
`create_note`. So there are two registries with two names for the same skill — a setup that
will silently fail to find a handler when the names don't line up.

**Evidence.**
- `agent_runner/dispatcher.py:449` — `register_skill_handler("slice6-create-note", _handle_create_note)`.
  (Its own docstrings at lines 116/121 use `create_note`.)
- `sandbox/handlers.py:55` — `@register("create_note")` into a separate `_HANDLERS` dict
  (`sandbox/handlers.py:29`).

**Design doc it breaks.** [doc 10](10-agent-execution-guide.md) Slice 6 (the skill is `create_note`).

**The Frappe-correct fix.** Rename the registration to `create_note` and converge on **one**
registry. When C2's sandbox path becomes the real execution route, the chat path's in-process
`_SKILL_HANDLERS` should either be deleted or become the explicit dev-fallback registry — not
a parallel source of truth with a different name.

---

### M4 — MEDIUM — The two execution paths disagree on the function signature

**In plain English.** The chat path and the task path both call the sandbox, but they call it
*differently*. The task path passes an `api_key=` argument that the sandbox's `execute()`
function **doesn't accept** — so the moment that path runs, it would crash with a `TypeError`.
It hasn't crashed yet only because C1 means that path never runs.

**Evidence.**
- `tasks/runner.py:219-223` — `sandbox_runner.execute(..., api_key=token, ...)`.
- `sandbox/runner.py:251-261` — `execute()`'s signature has no `api_key` parameter.

**Design doc it breaks.** Internal consistency (no single doc, but it's a real latent bug).

**The Frappe-correct fix.** Pick one calling convention. When C1 is fixed to route through
the shared dispatcher, the task path stops calling `execute()` directly and this disappears.
Until then, the mismatch is a tripwire.

---

### M5 — MEDIUM — Task dispatcher reads a non-existent field

**In plain English.** When a task has no explicit skills, the dispatcher tries to read
`profile.agent_role_profile` to find skills another way. That field doesn't exist on Agent
Profile, so this line throws `AttributeError` the moment it's hit.

**Evidence.**
- `tasks/dispatcher.py:175,178` — `if not skills and profile.agent_role_profile:` then
  `frappe.get_doc("Agent Role Profile", profile.agent_role_profile)`.
- `agent_profile.json` — no `agent_role_profile` field (and no Agent Role Profile DocType; see §3).

**Design doc it breaks.** Latent crash; also a leftover from the stale 04/05 assumption that
Agent Role Profile is mandatory.

**The Frappe-correct fix.** Delete the `agent_role_profile` branch (we use native Frappe roles
per §3). If "infer skills from roles" is desired, implement it against `Has Role` instead.

---

### L1 — LOW — Missing rollout docs for Slices 6–9 + War Room

**In plain English.** Our rule is two layers of docs: in-code docstrings **and** a committed
`docs/rollouts/slice-N-*.md` narrative shipped with each slice. Slices 6–9 and the War Room
bridge shipped without their rollout docs.

**The fix.** Backfill `docs/rollouts/` for each. This is safe documentation work.

---

### L2 — LOW — Dead `after_migrate` wiring

**In plain English.** `hooks.py:344` still registers `register_task_runner` to run on every
migrate, but that function is now a no-op (see C1). It does nothing; it's just noise.

**The fix.** Remove the `hooks.py` entry when C1's real `frappe.enqueue` wiring lands.

---

### L3 — LOW — Sandbox egress allowlist is inverted and uses a host-fs mount

**In plain English.** The sandbox tries to control which hosts a skill can reach by writing an
`/etc/hosts` file and bind-mounting it. Two problems: (1) the logic is **backwards** — it maps
*allowed* hosts (and the Frappe host itself) to `127.0.0.1`, which would *break* the very hosts
it means to permit, including the container's callback to Frappe; and (2) bind-mounting a
host-filesystem file **violates doc 42 §5's "no host filesystem mounts."** This is dormant
today only because C2 means the sandbox rarely runs.

**Evidence.**
- `sandbox/runner.py:165-177` — `_build_etc_hosts` maps `frappe_host` and every allowlisted
  host to `127.0.0.1`.
- `sandbox/runner.py:348-354` — writes a host tempfile and bind-mounts it via
  `volumes={hosts_path: {"bind": "/etc/hosts", "mode": "ro"}}`.

**Design doc it breaks.** [doc 42 §5](42-phase-one-authority-contract.md) "no host filesystem mounts."

**The fix.** Replace `/etc/hosts` host-mounting with a proper egress mechanism (a locked-down
Docker network with an allowlist, or DNS/proxy egress control) and correct the inverted logic.
Tackle alongside C2.

---

### L4 — LOW — Execution Log field drift

**In plain English.** Small audit-record sloppiness: the skill's run-time (`duration_ms`) is
shoved inside the free-form result JSON instead of its own column, and the link to the
permission decision is only filled in when a skill is *rejected*, not on success/error. Makes
the audit table harder to query.

**Evidence.**
- `agent_runner/dispatcher.py:326` — `result={**outcome, "duration_ms": duration_ms}` (into JSON).
- `agent_runner/dispatcher.py:479-480` — `permission_decision` set only on the rejection path.

**The fix.** Write `duration_ms` to its column; link the permission decision on every path.

---

## 5. Root-cause through-line

Two forces produced every CRITICAL/HIGH finding above:

1. **Stale specs (M1).** Docs 04 and 05 were never trimmed down to the locked single-tenant
   scope in doc 42. Code written against them reached for Agent Session, Workflow Request,
   Agent Role Profile, and Table-typed quota/allowlist fields — none of which match reality.
   The half-wired approval system (H2) and the dead-field crash (M5) are direct fallout.

2. **One Frappe-architecture misunderstanding (C1).** `frappe.publish_realtime` was treated
   as a server-side job queue. It is not — it's a browser push. Because the tests asserted the
   *event fires* rather than that a *task executes*, the dead route passed CI and shipped.

C2, H1, H3 are honest "Phase 1.5 / next-slice" deferrals that the docs over-promise as done.
The repair is therefore as much **reconciling the docs to reality** as it is changing code.

---

## 6. Proposed fix order (for discussion — not yet decided)

This is a *starting proposal*; we prioritize together.

1. **C1** — wire `frappe.enqueue` so the task route actually runs (route it through the shared
   dispatcher so it inherits permissions + immutable logs). Highest impact: turns a dead
   headline feature on.
2. **M1** — reconcile docs 04/05 to doc 42. Cheap, safe, and stops the next round of drift.
   Doing this *before* more code lands prevents new deviations.
3. **C2** — add `friday_require_sandbox` strict mode. Decide HIGH-vs-CRITICAL based on the
   skill threat model.
4. **H2** — decide approvals in-or-out for v0.1, then either build the minimal Workflow Request
   gate or remove the half-wiring.
5. **M3 / M4 / M5** — converge handler names/registries and delete dead-field/signature
   mismatches (largely falls out of fixing C1).
6. **H1** — ReAct loop (already design-locked in doc 48; proceeds on its own track).
7. **H3, L1–L4** — credential token hardening, rollout-doc backfill, egress fix, log-field
   tidy.

**Open question for you:** is C2 HIGH or CRITICAL? That depends on whether v0.1 skills are all
first-party/trusted. Your call decides whether strict-mode jumps ahead of doc reconciliation.
