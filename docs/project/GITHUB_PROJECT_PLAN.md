# GitHub Project Plan

> **Purpose:** Source of truth for the GitHub Project board used to track Friday's evolution.
>
> **Setup steps:** see `docs/project/GITHUB_SETUP_CHECKLIST.md` — the one-time clicks needed on the GitHub website to create the board, milestones, and discussion categories.
>
> **Labels:** see `docs/project/LABELS.md` for the full taxonomy and `scripts/setup-labels.sh` to create them in bulk.

---

## Board Name

`Friday Phase 1 — Fundamentals`

## Visibility

Public.

## Views

- **Roadmap** — group by Milestone, view all slices in order
- **Current Sprint** — filter to `status:in-progress` or `status:review`
- **By Slice** — group by `Slice` field
- **By Contributor Type** — group by `for:*` labels (humans / AI / pair)
- **Design Decisions** — filter to label `type:proposal`
- **Security and Governance** — filter to label `type:security` or `area:permissions`
- **Business Flagship** — filter to milestone `Phase 1 Business Flagship` (created when v0.1 ships)

## Columns

| Column | Meaning |
|---|---|
| Backlog | Issue exists, no work started |
| Ready | Proposal approved, ready for a contributor to pick up |
| In Progress | Someone is actively working — assignee set |
| Review | PR open, awaiting human review |
| Done | Merged or resolved |

## Custom Fields

| Field | Values | Source |
|---|---|---|
| Slice | `Slice 1` … `Slice 9` | `CODEX.md` §5 |
| Area | Framework Core, Agent Kernel, Workflow, Sandbox, Control Room, CLI, LLM, Permissions, CI | `LABELS.md` §4 |
| Phase | v0.1, Phase 1 Business Flagship, Phase 1.5, Phase 2, Future | `LABELS.md` §3 |
| Risk | Low, Medium, High, Critical | Used for security-sensitive issues |
| Contributor type | Human, AI agent, Human-AI pair | `AI_CONTRIBUTORS.md` Pillar 5 |

## Automation Workflows

- **Issue opened with a `slice:*` label** → add to Backlog
- **PR opened that references an issue** → move linked issue to Review
- **PR merged** → move linked issue to Done
- **Issue closed without merge** → move to Done with reason annotated
- **`status:blocked` label applied** → move to Backlog with a flag

---

## Phase Status (as of 2026-05-17)

### Already Done — Pre-Implementation Decisions

These were the original seed issues. All resolved, captured in design docs and `docs/decisions/spike-results.md`. Do not re-open.

- ✅ Define technical feasibility spike → `docs/design/44-technical-feasibility-spike.md`
- ✅ Decide Frappe v15 vs v16 substrate → **v16** (`spike-results.md` D1)
- ✅ Decide PostgreSQL setup path → **PostgreSQL + pgvector from day one** (D2)
- ✅ Decide Friday CLI / bench command strategy → **Extend bench with `friday` group** (D5)
- ✅ Decide Raven v0.1 vs v0.2 → **v0.2** (D3)
- ✅ First business-automation flagship scope → defined in `42-phase-one-authority-contract.md` §6
- ✅ Audit public security claims → `46-security-claims-audit.md`
- ✅ Define fork policy → `45-fork-policy.md`
- ✅ Prepare open-source launch checklist → in progress (this document + `GITHUB_SETUP_CHECKLIST.md`)

### Phase 1 Vertical Slices — In Build

Each slice is one milestone on the GitHub board. Open child issues for the sub-tasks within each slice using the templates in `.github/ISSUE_TEMPLATE/`.

| Slice | Milestone | Status |
|---|---|---|
| 1 | Foundations & DocType Skeletons | Not started |
| 2 | Permission Engine | Not started |
| 3 | Skill Loader | Not started |
| 4 | Gateway + CLI | Not started |
| 5 | LLM Integration | Not started |
| 6 | First Skill: `create_note` | Not started |
| 7 | Docker Sandboxing | Not started |
| 8 | Tasks, Dispatcher, Kanban | Not started |
| 9 | Polish & Hardening | Not started |

### After Phase 1

- **Phase 1 Business Flagship** — domain agents on top of v0.1
- **Phase 1.5 Hardening** — warm pool, egress proxy, security attack suite, multi-host
- **Phase 2 Public Launch** — Raven War Rooms, additional platform adapters, semantic memory

---

## How To Use The Board

### When opening an issue
1. Use one of the issue templates in `.github/ISSUE_TEMPLATE/`.
2. The template auto-applies the right `type:*` and `status:needs-triage` labels.
3. Maintainer triages — adds `slice:*`, `phase:*`, `area:*`, assigns to milestone, sets fields.
4. Automation moves it to Backlog on the board.

### When picking up work
1. Find an issue in Backlog or Ready.
2. Comment "I'm picking this up" (or assign yourself if you have permissions).
3. Maintainer applies `status:in-progress`, board auto-moves.
4. For AI contributors: confirm sponsor is registered before claiming.

### When opening a PR
1. Use the PR template — link the proposal issue, fill validation checklist.
2. Automation moves the linked issue to Review.
3. Human reviewer (you, or a Level 3+ contributor) signs off.
4. Merge → issue moves to Done → milestone progress updates.

---

## Why A Public Board Matters

A public project board is how Friday proves the contribution model is real. Anyone visiting the repo can see:

- What is being built right now
- Who is doing it (humans, AI, paired)
- What's stuck and why
- What's already shipped

This is the same governance principle Friday applies internally — visibility creates accountability. The board makes it visible, not just to maintainers but to the entire world.
