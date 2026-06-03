# Legion Validation Runbook — prove the Friday foundation end-to-end

**Who you are:** the Claude Code instance running **on the Legion machine** — the
one with a real Frappe bench and database (`/home/friday/friday/friday-bench`,
site `friday.localhost`). The Mac Claude writes code and opens PRs; **you** are
the only one who can run `bench migrate`, hit a real model, and exercise the
real database.

**Why this session exists.** Over the last stretch the Mac shipped the whole
Hermes-core feature block — the ReAct loop (A), error classifier (F), tool-call
dedup (D), OpenAI + Anthropic providers (B1/B2), conversation compression (C) —
plus two governance items (H3 scoped-token, H2 approval) and the tracker's
failure auto-raise (D6). **Every one of these is unit-tested but has NEVER run on
a real bench.** They've been merged on the strength of mocked tests alone. Your
job is to prove the foundation actually works end-to-end, fix whatever the real
seams expose, and report back.

> **Altitude check.** Friday is an **enterprise-grade agentic orchestration +
> governance framework** — a hard fork of Frappe that builds agent capabilities
> into the core, with Hermes as the proven reference. This session validates the
> *single-agent runtime + governance spine* before we build the multi-agent
> orchestration layer on top. Don't think of it as "testing an app" — you're
> certifying the foundation of a framework.

---

## Why we validate before building higher

A real latent bug already proved the point: the providers returned tool calls in
the nested OpenAI shape (`{id, function:{name, arguments}}`) but the dispatcher
reads the flat shape (`{id, name, arguments}`) — so **real** tool calls would
never have dispatched. Mocked tests passed; the seam was invisible until someone
read it. There are more seams like that. **You don't build the coordination
layer for a fleet until one agent can complete one real task end-to-end.** That
is this session.

---

## Ground rules (you already have these in your memory — restated for focus)

- **Tests-first, tight diffs, design-lock-first.** Fix the *code*, not the test
  (unless the test is genuinely wrong).
- **Branch off `main`.** Never commit straight to `main`.
- **Open PRs via the fork-safe API** (plain `gh pr create` 422s on this fork):
  `gh api repos/Friday-Labs-Inc/friday/pulls -f base=main -f head=<branch> -f title=... -f body=...`
- **Confirm with the user before any push/PR, and before any destructive or
  irreversible bench operation** (especially the rename migration in Phase B).
- **Never write the SSH password to a file.**
- Reference the locked designs as you go: `docs/design/51-hermes-core-port-roadmap.md`
  (the roadmap + S9/S10), `docs/design/53-project-issue-tracker-port.md` (the
  tracker), `docs/design/48-hermes-port-decisions.md` (the ReAct loop),
  `docs/design/52-hermes-to-friday-map.md` (the one-to-one map — keep it current).

---

## Phase A — VALIDATE (do this first, in order)

### A0. Preconditions
The open PRs must be merged to `main` first (the user merges them in GitHub):
**#48** (H3 scoped-token), **#49** (H2 approval), **#50** (tracker D6), and this
runbook PR. Then:

```bash
cd /home/friday/friday/friday-bench
git -C apps/frappe fetch origin
git -C apps/frappe checkout main
git -C apps/frappe pull origin main
```

### A1. Migrate — and verify it's clean
```bash
bench --site friday.localhost migrate
```
**Verify** (must all be true):
- migrate completes with **no traceback**;
- new DocTypes exist: **Compaction Summary**, **Workflow Request**;
- new fields exist: **Chat Message.compacted**, **Agent Settings.compression_model**.

Quick check in the console:
```bash
bench --site friday.localhost console
>>> import frappe
>>> frappe.db.exists("DocType", "Compaction Summary"), frappe.db.exists("DocType", "Workflow Request")
>>> frappe.get_meta("Chat Message").has_field("compacted")
>>> frappe.get_meta("Agent Settings").has_field("compression_model")
```
**On failure:** read the traceback, fix the schema (the offending `.json`), re-run.
Report exactly what you changed.

### A2. Run the bench-only test modules
These exercise the seams the Mac's mocked tests *cannot* reach (real provider
resolution, real Issue rows, the real runner → dispatcher → DB path):

```bash
bench --site friday.localhost run-tests --module frappe.friday_core.tests.test_llm_provider
bench --site friday.localhost run-tests --module frappe.friday_core.tests.test_runner_tool_call
bench --site friday.localhost run-tests --module frappe.friday_core.tests.test_prompt_builder
bench --site friday.localhost run-tests --module frappe.friday_core.tests.test_issue_doctype
bench --site friday.localhost run-tests --module frappe.friday_core.tests.test_compression
bench --site friday.localhost run-tests --module frappe.friday_core.tests.test_approval
bench --site friday.localhost run-tests --module frappe.friday_core.tests.test_task_failure_issue
```
**Verify:** all green. **On failure:** a failing test here is very likely a *real
seam bug* (the mocked version passed). Debug it, fix the code, re-run. Report each
fix with a one-line cause.

### A3. The real end-to-end smoke — the important one
This is the **first time a real model drives the governed loop**. Set up one of
each, in the console or via a small script:
- an **LLM Provider** row (use whichever key you have — Minimax, OpenAI, or
  Anthropic; pick the matching `provider_type`);
- an **Agent Profile** linked to it, permitted to use the `slice6-create-note`
  skill;
- send a message that **forces a tool call**, e.g. *"Create a note titled Hello
  with body World."*

Drive it through the real entry point (`gateway.service.handle_inbound`, or
`agent_runner.runner.run_turn` directly for a tighter loop), then **verify the
whole chain**:

1. the ReAct loop calls the model, gets a tool call, and dispatches it;
2. **the tool-call flatten fix works for real** — a live provider's nested
   `tool_calls` become `{id, name, arguments}` and actually dispatch (this is the
   first real test of the bug we fixed — watch it specifically);
3. the skill runs (Docker sandbox, or the in-process fallback if Docker isn't
   up), the result is fed back, and a final reply is returned;
4. **the governance spine recorded it:** an **Execution Log** row *and* a
   **Permission Decision Log** row were written;
5. exactly **one inbound + one outbound Chat Message** for the turn.

**On failure:** this is where real seam bugs surface — debug, fix, re-run until
the full chain is clean. This passing is the headline result of the session.

### A4. H2 approval round-trip (needs #49 merged)
```
- Set a test skill's `requires_approval = 1`.
- Trigger it via a message. VERIFY: the skill did NOT execute; a Workflow Request
  (status Pending) was created; the loop paused with the "needs approval" reply.
- In the console: from frappe.friday_core.approvals.workflow import approve
  approve("<request name>", approved_by="<your user>", reason="ok")
  VERIFY: the skill now executes; an Execution Log row is written; the request is
  Approved and its execution_log is linked.
- Try approvals.workflow.reject(...) on a fresh Pending request → VERIFY: Rejected,
  nothing runs.
```
Optionally wire the **Frappe Workflow** on `Workflow Request` (states
Pending → Approved/Rejected, transitions gated to the **Agent Supervisor** role)
so approvers get Desk buttons. The enforcement logic already works without it;
this is the human UX layer.

### A5. Compression smoke (optional, if time)
Force a session over the threshold (either build a long history, or temporarily
lower `compression.DEFAULT_CONTEXT_WINDOW_TOKENS`). **Verify:** a **Compaction
Summary** row is created, the old Chat Messages get `compacted = 1`, and the next
`prompt_builder.build()` leads with the summary (carrying the reference-only
preamble) instead of the full transcript.

### A6. Report
Write a short report (and offer to commit it as `docs/rollouts/legion-validation-<date>.md`):
for each step PASS/FAIL, every seam bug found + fixed (one line of cause each),
the migrate output, and the headline answer: **is the single-agent runtime +
governance spine trustworthy now?** If you opened fix PRs, list them.

---

## Phase B — BUILD the rest of the tracker (only after Phase A is green)

This is the migration-bound work the Mac deliberately did NOT do blind. It is
locked in `docs/design/53-project-issue-tracker-port.md`. Design is already
locked — go tests-first, confirm before push.

### B1. The rename (doc 53 §7) — the careful one
Rename the agent-namespaced DocTypes to the **generic** ones (D1):
`Agent Project → Project`, `Agent Task → Task` (and the child
`Agent Task Skill → Task Skill`).
- Use a **`frappe.rename_doc` patch** (preserves data), registered in
  `patches.txt`.
- Sweep **every** code + schema reference: `tasks/dispatcher.py`,
  `tasks/runner.py`, `tasks/workflow.py`, `warroom/publisher.py`,
  `gateway/service.py`, `hooks.py`, `issue.json` (the `related_task` / `waiting_on`
  Link `options`), and `issues/raise_issue.py` `TASK_DOCTYPE`.
- `grep -rn "Agent Task\|Agent Project"` must come back empty (outside the patch
  + migration notes) when you're done.
- **Verify:** `bench migrate` clean; existing task rows survive the rename; the
  chat + task flows still work.

### B2. Field alignment (the gotcha)
`issues/raise_issue.py` `unfinished_dependencies()` reads a **`status`** field,
but the current `Agent Task` has **`workflow_state`**, not `status`. Pick one and
align everything (doc 53 §3.2 frames the Task as having a status). This is *why*
D5 was held back — wiring it before this alignment would be half-built.

### B3. `depends_on` + D5 (Dependency-Wait auto-raise)
- Add a **`Task Depends On`** child DocType (one `task` Link field) and a
  **`depends_on`** Table field on `Task` (ported from ERPNext `Task.depends_on`).
- Wire D5 into the dispatch/assignment path: before running a task, call
  `unfinished_dependencies(task)`; if any blocker is unsettled, **park the task**
  and `raise_dependency_wait_issue(task, blocker)` (avoid duplicate Issues per
  (task, blocker)).
- Tests-first: a blocked task raises exactly one Dependency-Wait Issue and does
  not execute; once the blocker settles, it proceeds.

### B4. Workflow states (D7) + map
Add the native Frappe Workflows (Project / Task / Issue) per doc 53 D7. Then
refresh `docs/design/52-hermes-to-friday-map.md` (§8 / §12) to mark the tracker
built.

---

## What NOT to do this session
- Don't build the **learning loop** (§9 — self-creating skills). Out of v0.1 scope.
- Don't invent the H3 scoped-token **REST-boundary validation** scheme — it's a
  flagged Phase-1.5 design call; raise it with the user first.
- Don't widen scope mid-task. One phase, one PR, confirm before push.
