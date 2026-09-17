# Learning loop — Slice 2: governed skill-proposal

_Shipped 2026-06-23. Completes Design 79 (the learning loop). Default-off-safe
(skill_review_interval 0 disables it). Track: `core`._

## In one sentence

When the agent notices a reusable how-to lesson, it now **proposes** a skill
change for a human to approve — recorded as a Pending `Skill Proposal` — and
never edits a skill itself.

## What it actually does (plain terms)

Hermes' self-improvement review has two halves: save memories (Slice 1, shipped)
and edit its own skill files. Friday must NOT let an agent rewrite its own
governed skills — so the skill half becomes a **governed proposal**:

- A new `Skill Proposal` doctype is the human-review surface: agent, title,
  rationale, proposed content, and `status` (Pending → a human Approves/Rejects).
- A new `propose_skill_change` skill records ONE Pending proposal. It changes
  nothing else.
- A second review cadence — `Agent Settings → Skill Review Interval` (default 0
  = off) — runs a background review every N conversational turns with the
  toolset restricted to `propose_skill_change`. It surfaces a "📝 Skill
  proposal: …" note when it proposes something.

Applying an approved proposal (creating/editing the real Skill) is a deliberate
human act in v0.1 — the proposal carries the content; a human applies it.

## What scenarios it now covers

| Scenario | Result |
|---|---|
| User corrects the agent's workflow/format | review proposes a skill update (Pending) |
| A reusable technique/fix emerged | proposed for human review |
| Environment error / one-off task / "tool is broken" | NOT proposed (guarded against poisoning skills) |
| `skill_review_interval = 0` (default) | feature off, zero behaviour change |
| Agent tries to edit a skill directly | impossible — there is no self-edit path; only proposals |

## What it means for friday-core

This closes the learning loop while keeping the governance line intact: the
agent learns *what to remember* (Slice 1) and *how it could work better*
(Slice 2) — but the skill library, its permission surface, is only ever changed
by a human approving a proposal. Two independent cadences (memory + skill) mirror
Hermes' two review counters; both are best-effort background RQ jobs that never
block or affect the live turn.

## How it gets along with the Frappe ecosystem

| Friday concept | Frappe reality |
|---|---|
| Human-review surface | `Skill Proposal` DocType (Pending/Approved/Rejected), visible in Desk |
| The proposal action | `propose_skill_change` skill (governed: permission-checked + Execution-Log-audited like any skill) + its `Skill Proposer` role |
| Skill cadence | `Agent Settings.skill_review_interval`; the review is an RQ job on the `friday` queue |
| Restriction | the review turn runs `run_turn(allowed_skills={"propose_skill_change"})` — it can do nothing else |

## Faithfulness + the disclosed divergence

This IS the disclosed divergence from Hermes: Hermes self-edits SKILL.md; Friday
**proposes → human approves, never auto-applies** (governance). The review prompt
is original wording that ports Hermes' skill-review intent and its do-NOT-capture
guidance (don't propose for env failures, transient errors, one-off tasks).

## Risks and limits a product head should hold

- **Applying a proposal is manual** in v0.1 (no auto-apply on approve). A future
  step could let an approved proposal create/patch the Skill.
- **Cost** — an extra review turn every N turns when enabled (off by default;
  runs on the optional cheap `review_model`).
- **No dedup** — could propose a near-duplicate; a human filters in Desk.

## What this unlocks

- The learning loop is complete (Slices 1 + 2). Next: an optional "apply on
  approve" action, and dedup.

## Numbers for the record

- Files: `doctype/skill_proposal/` (new doctype), `skills/handlers_propose_skill.py`
  + `skills/bootstrap_propose_skill.py` (new skill), `agent_runner/dispatcher.py`
  (register handler), `agent_runner/self_review.py` (skill review job + dual
  cadence + reusable surface), `doctype/agent_settings/agent_settings.json`
  (+`skill_review_interval`), `tests/test_self_review.py` (+ skill cadence/job),
  `tests/test_propose_skill.py` (new, 6).
- Tests: test_self_review 14/14, test_propose_skill 6/6, gateway 11/11. Migrate
  clean (new doctype + field); bootstrap verified live (role+skill+perms).
- Default `skill_review_interval = 0` → feature off until enabled.
