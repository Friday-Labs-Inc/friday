# GitHub Labels — Friday Project

Single source of truth for the label taxonomy used on Friday issues and PRs.

When setting up the repo for the first time, create each label below in GitHub Settings → Labels. Use the suggested colours so that scanning the issue list at a glance gives useful information.

---

## 1. Type — what kind of issue is this

| Label | Colour | Use for |
|---|---|---|
| `type:bug` | `#d73a4a` red | Something is broken |
| `type:feature` | `#a2eeef` light blue | New capability |
| `type:proposal` | `#7057ff` purple | Spec-before-code proposal (per AI_CONTRIBUTORS.md Pillar 1) |
| `type:blocker` | `#b60205` dark red | Contributor is stuck, decision needed |
| `type:ai-registration` | `#5319e7` deep purple | AI contributor sponsor registration |
| `type:docs` | `#0075ca` blue | Documentation work |
| `type:security` | `#000000` black | Security concern (handle privately if vulnerability) |
| `type:chore` | `#cfd3d7` grey | Maintenance, refactor, dependency bumps |

## 2. Slice — which Phase 1 vertical slice does this belong to

One per slice in `CODEX.md` §5.

| Label | Colour | Slice |
|---|---|---|
| `slice:1-foundations` | `#fbca04` yellow | DocType skeletons |
| `slice:2-permissions` | `#fbca04` yellow | Permission engine |
| `slice:3-skills` | `#fbca04` yellow | Skill loader |
| `slice:4-gateway` | `#fbca04` yellow | CLI adapter + Chat Message |
| `slice:5-llm` | `#fbca04` yellow | LLM integration |
| `slice:6-first-skill` | `#fbca04` yellow | `create_note` end-to-end |
| `slice:7-sandbox` | `#fbca04` yellow | Docker sandboxing |
| `slice:8-dispatcher` | `#fbca04` yellow | Tasks + dispatcher + Kanban |
| `slice:9-polish` | `#fbca04` yellow | Polish + hardening |

## 3. Phase — what phase of the project

| Label | Colour | Phase |
|---|---|---|
| `phase:v0.1` | `#0e8a16` green | Phase 1 — governed framework loop |
| `phase:1-business-flagship` | `#216e39` darker green | Phase 1 — first business-automation dogfood |
| `phase:1.5-hardening` | `#bfdadc` light teal | Phase 1.5 — production-grade hardening |
| `phase:2-public-launch` | `#c5def5` pale blue | Phase 2 — open source launch and Raven |
| `phase:future` | `#e4e669` pale yellow | Beyond Phase 2 |

## 4. Area — which part of the system

| Label | Colour | Area |
|---|---|---|
| `area:agent-kernel` | `#bfd4f2` blue-grey | Profile, Skill, Execution Log, dispatcher |
| `area:workflow` | `#bfd4f2` blue-grey | Agent Task workflow, Kanban |
| `area:sandbox` | `#bfd4f2` blue-grey | Docker isolation, resource caps |
| `area:control-room` | `#bfd4f2` blue-grey | Operator-facing UI |
| `area:cli` | `#bfd4f2` blue-grey | bench friday command group |
| `area:llm` | `#bfd4f2` blue-grey | Provider interface, prompt builder |
| `area:permissions` | `#bfd4f2` blue-grey | Permission matrix and cache |
| `area:ci` | `#bfd4f2` blue-grey | GitHub Actions, test runners |
| `area:framework-core` | `#bfd4f2` blue-grey | Frappe v16 fork core divergences |

## 5. Status — where the work is in the lifecycle

| Label | Colour | Status |
|---|---|---|
| `status:needs-triage` | `#e99695` pink | New, not yet reviewed by a maintainer |
| `status:needs-decision` | `#fbca04` yellow | Decision required before work continues |
| `status:in-progress` | `#0e8a16` green | Actively being worked on |
| `status:blocked` | `#b60205` dark red | Cannot progress — see linked blocker |
| `status:review` | `#5319e7` deep purple | Awaiting human review |
| `status:done` | `#0e8a16` green | Merged or resolved |

## 6. Difficulty — for new contributor onboarding

| Label | Colour | Difficulty |
|---|---|---|
| `good-first-task` | `#7057ff` purple | New contributors can grab this, well-scoped |
| `difficulty:medium` | `#fbca04` yellow | Requires Frappe and project context |
| `difficulty:hard` | `#b60205` dark red | Architectural — needs maintainer pairing |

## 7. Contributor — who can pick this up

| Label | Colour | Who |
|---|---|---|
| `for:humans` | `#0e8a16` green | Open to human contributors |
| `for:ai-agents` | `#5319e7` deep purple | Open to registered AI contributors |
| `for:human-ai-pair` | `#7057ff` purple | Best done as a pair |
| `maintainer-only` | `#b60205` dark red | Reserved for maintainers |

---

## Bulk Label Creation

To create all these labels at once (assumes `gh` CLI is authenticated with write access to the repo), save the script below as `scripts/setup-labels.sh` and run it:

```bash
#!/usr/bin/env bash
set -euo pipefail

REPO="Friday-Labs-Inc/friday"

create() {
  local name="$1" colour="$2" desc="$3"
  gh label create "$name" --repo "$REPO" --color "$colour" --description "$desc" --force
}

# Type
create "type:bug"              "d73a4a" "Something is broken"
create "type:feature"          "a2eeef" "New capability"
create "type:proposal"         "7057ff" "Spec-before-code proposal"
create "type:blocker"          "b60205" "Contributor is stuck, decision needed"
create "type:ai-registration"  "5319e7" "AI contributor sponsor registration"
create "type:docs"             "0075ca" "Documentation work"
create "type:security"         "000000" "Security concern"
create "type:chore"            "cfd3d7" "Maintenance, refactor, dependency bumps"

# Slice
for n in 1-foundations 2-permissions 3-skills 4-gateway 5-llm 6-first-skill 7-sandbox 8-dispatcher 9-polish; do
  create "slice:$n" "fbca04" "Phase 1 vertical slice"
done

# Phase
create "phase:v0.1"             "0e8a16" "Phase 1 — governed framework loop"
create "phase:1-business-flagship" "216e39" "Phase 1 — first business-automation dogfood"
create "phase:1.5-hardening"    "bfdadc" "Phase 1.5 — production-grade hardening"
create "phase:2-public-launch"  "c5def5" "Phase 2 — open source launch"
create "phase:future"           "e4e669" "Beyond Phase 2"

# Area
for area in agent-kernel workflow sandbox control-room cli llm permissions ci framework-core; do
  create "area:$area" "bfd4f2" "Subsystem area"
done

# Status
create "status:needs-triage"   "e99695" "New, not yet reviewed"
create "status:needs-decision" "fbca04" "Decision required"
create "status:in-progress"    "0e8a16" "Actively being worked on"
create "status:blocked"        "b60205" "Cannot progress"
create "status:review"         "5319e7" "Awaiting human review"
create "status:done"           "0e8a16" "Merged or resolved"

# Difficulty
create "good-first-task"       "7057ff" "Well-scoped for new contributors"
create "difficulty:medium"     "fbca04" "Requires project context"
create "difficulty:hard"       "b60205" "Architectural — needs maintainer pairing"

# Contributor
create "for:humans"            "0e8a16" "Open to human contributors"
create "for:ai-agents"         "5319e7" "Open to registered AI contributors"
create "for:human-ai-pair"     "7057ff" "Best done as a pair"
create "maintainer-only"       "b60205" "Reserved for maintainers"

echo "All labels created."
```

Then `chmod +x scripts/setup-labels.sh && ./scripts/setup-labels.sh`.
