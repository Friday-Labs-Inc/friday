# Friday Roadmap

## Phase 1: Fundamentals

Build the governed framework loop first:

- Friday framework shell
- Agent Profile
- Skill
- Project / Task / Issue tracker (generic work objects; agents are stakeholder Users — see [doc 53](design/53-project-issue-tracker-port.md))
- configurable workflow and Kanban view
- permission engine
- sandboxed execution path
- Execution Log
- Permission Decision Log
- Control Room

Then run the first business-automation flagship dogfood:

- A domain-specific Agent Profile
- Read-only support / alerting where it reduces risk
- Coordinator Agent basic oversight
- Operations Policy DocType (approval thresholds)
- human approval for high-risk or financially binding actions

## Phase 1.5: Hardening

- stronger sandbox defaults
- egress allowlist/proxy
- warm container pool
- Control Room product polish
- Raven War Room bridge if not already included
- security claims audit
