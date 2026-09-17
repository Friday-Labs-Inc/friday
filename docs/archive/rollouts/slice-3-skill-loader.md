# Slice 3 Rollout — The Skill Loader

> **Slice:** 3 of 9 — see `docs/design/10-agent-execution-guide.md`
> **PR:** [#27](https://github.com/Friday-Labs-Inc/friday/pull/27)
> **Author:** `fridaylabs` / sponsor `@Fridaylabsinc`
> **Audience:** Anyone — engineer, product owner, or a high schooler curious about what Friday now does.

---

## In one sentence

**Friday's AI agents can now see the list of tools available to them — and that list is automatically filtered by who they are, what they're allowed to do, and what's currently safe to ship.**

---

## What it actually does (in plain terms)

Imagine an AI agent as an employee on their first day. Before they can do useful work, two things have to be true:

1. They need a job description that says "you're allowed to use the credit-card printer, the customer database, and the email tool."
2. They need a *menu* that translates that job description into "here are the specific buttons you can press right now."

Slice 2 was the job-description checker — it answers yes/no when an agent tries to press a button. **Slice 3 is the menu** — it shows the agent which buttons it can even see in the first place.

Why have both? Two reasons:

- **The menu is fast.** Looking up "what can this agent do?" once and caching it for 5 minutes is much cheaper than asking the gatekeeper 50 times per conversation.
- **The menu hides what shouldn't be offered.** An agent that can't see a tool can't ask to use it. Combined with the gatekeeper still checking every call (defense in depth), this is two layers of "no" instead of one.

---

## What scenarios it now covers

| Scenario | Outcome |
|---|---|
| Agent has the role, skill is published as Active, operator allow-listed it | **In the menu.** |
| Skill is still in Draft / Experimental | **Hidden.** Engineering isn't ready to ship it. |
| Skill was Retired or Archived | **Hidden.** It used to exist; it no longer does for this agent. |
| Operator didn't put the skill on this agent's allow-list | **Hidden.** Permission *could* be there, but the operator chose not to grant it. |
| Agent's roles don't cover one of the (DocType, operation) the skill needs | **Hidden.** No silent audit-log spam — failed skills don't fill the log just because the agent looked at the menu. |
| Same agent asks for its menu again 2 minutes later | **<1ms return** from cache. |
| Admin promotes a skill from Draft → Active | **Affected agents see it on the next request** (cache invalidates automatically). |
| Admin removes a skill from an agent's allow-list | **Same.** Surgical invalidation, no global flush needed. |
| Admin edits a Role itself | **All agents' menus rebuild on next request.** Broad but rare. |

All of these are proven by tests (`frappe/friday_core/tests/test_skill_loader.py`). 8/8 green.

---

## What it means for friday-core

**Before Slice 3:** friday-core had a gatekeeper (Slice 2). An agent could be told "do X" and the gatekeeper would either allow or deny. But the agent had no way of *knowing* what tools to even ask about.

**After Slice 3:** friday-core has the two-sided permission story:

- **Front door (Slice 3):** the menu the agent reads before acting.
- **Back door (Slice 2):** the gatekeeper that re-checks before the action runs.

Both pull from the same permission matrix. Both invalidate from the same hooks. There's no place in the system where permissions can drift between "what was offered" and "what was allowed" — they're physically the same data.

This is the moment Friday's permission story becomes *complete enough to demo*. Today you can write code like:

```python
tools = load_for_profile("Research Agent")
# → list of OpenAI-format tool definitions, filtered, fresh
```

…and hand it directly to a real LLM API. Which is exactly what Slice 4 will do.

---

## How friday-core gets along with the Frappe ecosystem

Same story as Slice 2, extended:

| Friday concept | Frappe reality |
|---|---|
| Agent's allow-list | A child table (`Agent Profile Skill`) on Agent Profile. Edited in Desk like any other child table. |
| "What can this agent do" | Reuses Slice 2's matrix, which reuses Frappe's Role + DocPerm. |
| Tool menu cache | Frappe's Redis. |
| Invalidation triggers | Frappe's `doc_events` system, with a list of handlers per event — standard Frappe pattern. |
| Tool definition format | OpenAI / Anthropic function-calling schema (vendor-neutral). |

An admin clicking around in Frappe Desk *never has to know* Friday exists. They edit a Role, the matrix updates, the menu rebuilds. Friday is plumbing under Frappe's existing UI.

---

## What the company can say truthfully today

Three new claims, each tied to a verifiable fact:

1. **"Agents only see tools they're permitted to see."** Verified by `test_skill_excluded_when_matrix_denies`.
2. **"Looking at the menu doesn't trigger audit-log noise."** Same test — the Permission Decision Log count doesn't move when an agent merely *lists* tools.
3. **"Permission changes propagate in under 5 minutes, usually in under a second."** Cache TTL bounds the worst case; surgical invalidation hooks handle the common case.

---

## Risks and limits a product head should hold

- **No call yet.** The menu exists. The thing that takes a menu, hands it to an LLM, gets a tool call back, runs it — that's Slice 4 + Slice 5 + Slice 6. Today, the menu is built but unused.
- **Allow-list quality is operator-driven.** If an operator dumps every skill into every agent's allow-list, the menu filtering on `permitted_skills` becomes meaningless — only the role-based matrix filter saves them. Operator UX for managing allow-lists is a future concern.
- **No "this skill needs human approval" handling yet.** The flag exists on Skill (`requires_approval`) and carries through into the `SkillDefinition`, but nothing acts on it. The Workflow Request flow is later.
- **5-minute cache TTL** is a deliberate trade. If a skill is yanked at 12:00:00, an agent could conceivably see it in their menu until 12:05:00 — but the gatekeeper (Slice 2) would still deny the call. Net effect: a brief window where the agent *sees* but can't *use*. Acceptable for v0.1; revisit if a customer balks.

---

## What this unlocks

- **Slice 4 (Gateway / CLI adapter)** can write `gateway.handle(message)` and call `load_for_profile()` as part of that flow.
- **Slice 5 (LLM provider integration)** can hand `to_tool_definition` output directly to the OpenAI / Anthropic SDKs and start round-tripping real LLM calls.
- **First demo-able loop** becomes possible after Slice 5: user types a request → LLM picks a tool from the menu → gatekeeper approves → action runs (mocked). That's the moment friday-core stops being plumbing and starts being a product.

---

## Numbers for the record

- 4 files changed (1 new package `frappe/friday_core/skills/`, 1 new module `loader.py`, 1 new test file, 1 hooks edit)
- +733 lines (≈60% docstrings, 40% code + tests)
- **8/8 tests green**
- Regression: Slice 1 → 2/2, Slice 2 → 10/10
- Deliverable verified:
  ```
  $ bench --site friday.localhost execute \
      frappe.friday_core.skills.loader.load_for_profile \
      --args "['FRIDAY-SLICE3-PROFILE-FULL']"
  [{"name": "slice3-skill-active", "description": "...", "parameters_schema": {...}, ...}]
  ```
