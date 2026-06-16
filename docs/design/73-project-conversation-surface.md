# Design 73 — Project Conversation Surface

**Status:** Building (doc written alongside code, not lock-first). Slices 1 + 5 + project-context-memory shipped 2026-06-15; **Slice 3 (inbound routing) locked + built 2026-06-16** — see the Slice 3 section below.

## The vision

Friday is a **hosted, enterprise, multi-agent orchestration platform** — not a personal desktop tool. A CLI (the Hermes / OpenClaw model) is not a real interface for a hosted system; a dashboard-only Desk can't carry a multi-agent *conversation*. So Friday's primary human interface is **conversational, in the browser** — Style A (see memory `interface-style-a-conversational`). Raven is that surface: a web chat living natively inside the same Frappe site as the agents, tasks, projects, and governance.

The organizing idea: **each Project is a real collaborative room** where the agent team, the human director, the deliverables, and the gate decisions live together — the way an AI-native creative agency would actually work.

### Architectural spine (thin skin)

Raven is a **bidirectional human skin over Friday's structured truth** — never the system of record, never a coordination bus.

- **Truth** lives in Friday's doctypes: `Chat Message` (conversation), the deliverables, `Permission Decision Log` / `Workflow Request` (governance), the task/delegation graph (`Task`, Design 69).
- **Raven** *projects* that truth into a human-readable room and *captures* human input (commands, approvals) back into the structured record.
- If Raven dies, you lose the window, never the data.

This also resolves the reliability question: anything load-bearing behind a surface that dies on a bench restart is a design error. Keeping Raven a projection/input skin is what makes depending on it safe.

### Hermes boundary

Port Hermes's *brains* faithfully (agent loop, governance, transport). **Never** port its *interface* — Hermes is CLI because it's a personal desktop tool; Friday is hosted enterprise. (Consistent with `unified-gateway-service`.)

## The use-case catalog (the spreadsheet)

| # | Use case | What happens | Who | Truth lives in | Status |
|---|---|---|---|---|---|
| 1 | **Per-project channel** | Create project → dedicated channel auto-made | system | `Raven Channel` linked to `Project` | ✅ **Slice 1** |
| 2 | **Channel mirrors project status** | Channel archives when project closes | system | mirror of `Project.status` | ✅ **Slice 1** (archive on close) |
| 3 | **Talk to the orchestrator** | Type "Friday, make the names punchier" → it works | you → Friday | `Chat Message` → routed to agent | ⏳ Slice 3 (inbound gateway) |
| 4 | **See the agent team** | Specialists post progress + results in the channel | agents | `Task` / `Chat Message` | ⏳ Slice 4 |
| 5 | **File / deliverable sharing** | Agents post deliverables; humans share references | both | `Deliverable`/`File` on Project+Task | ⏳ Slice 5 (the deliverables gap) |
| 6 | **Director discusses between gates** | Human feedback; agents revise | human + agents | `Chat Message` + feedback | ⏳ Slice 4 |
| 7 | **Gate decision in chat** | "Approve BD-0010? ✅/❌" + reason | human | `Workflow Request` / gate milestone | ⏳ Slice 6 |
| 8 | **Ops / status feed** | "task completed / blocked" | system → all | `Dispatcher Event` (Design 72) | ✅ exists (war room) |
| 9 | **DM the orchestrator (no project)** | "Friday, start a project for Acme" | you → Friday | `Chat Message` | ⏳ Slice 3 |

## Slice plan

- **Slice 1 (SHIPPED):** per-project channel — auto-provisioned on Project creation, linked both ways, seeded with a welcome, archived on close. Best-effort (never breaks a Project save). **+ the Raven reliability fix below.**
- **Slice 2:** Private channels + explicit team membership (assigned agents + human roles), backfill patch for existing projects.
- **Slice 3:** the **inbound gateway path** — human types in a channel → routed to the orchestrator → governed turn → reply in channel. (The platform's main entrance.)
- **Slice 4:** multi-agent visibility — specialists post their work into the project channel.
- **Slice 5:** deliverables as real artifacts, posted to the channel AND attached to the Project/Task (fixes the deliverables gap).
- **Slice 6:** gate approvals in chat → captured as governed decisions.

## Slice 1 — what shipped

- `Project.conversation_channel` (Data field — the channel docname; Data not Link so `friday_core` stays installable without Raven).
- `friday_core/conversation/project_channel.py`:
  - `provision_project_channel(project)` — idempotent; creates an Open channel in the Friday workspace, named `proj-<backend_ref|docname>`, with Raven's native `linked_doctype`/`linked_document` back-link + the reverse link on the Project, adds the Friday bot, enqueues the welcome **after commit**.
  - `archive_project_channel(project)` — sets `is_archived` when the project reaches Completed/Cancelled.
  - doc_events hooks (`Project.after_insert` / `on_update`), both **savepoint-guarded** — a Raven failure (or Raven absent) never breaks a Project save.
- 8 tests (`test_project_channel.py`): provision + link + idempotency + bot membership + archive-on-close + on-hold-doesn't-archive + Raven-absent-graceful + provision-failure-doesn't-break-insert.

### Key decisions (made while building)

- **Open channel, not Private, for v0.1.** Simplest — no membership management. Private + explicit team is Slice 2.
- **Welcome posted after commit, as the Friday bot** (see reliability fix).
- **Data field, not Link, for `conversation_channel`** — keeps friday_core decoupled from Raven's schema (thin-skin).

## The Raven reliability fix (cornerstone for the whole vision)

Found while building Slice 1 — the root cause of the recurring "war room messed up" / "already a member" failures:

Raven's `track_channel_visit` (`raven/utils.py:44`) looks up channel membership by the message's **`owner`** but then *inserts* a member for **`frappe.session.user`**. When that user is already a member, `Raven Channel Member.before_insert` throws `DuplicateEntryError("You are already a member of this channel")` — aborting the whole message insert. This is why War Room posts were intermittently lost and the channel UI errored on open.

**Fix:** post **as the Friday bot**, not as the session user. `raven_message.on_update` gates `track_channel_visit` on `not is_bot_message`, so bot messages skip the buggy path entirely. This is also *correct* — Friday's messages should come from Friday, not impersonate "Administrator". Applied to:
- the Slice 1 welcome (`project_channel._seed_welcome`)
- the War Room publisher (`warroom/publisher._post_to_raven`)

Both fall back to the plain API only if the bot isn't provisioned.

## What does NOT ship in Slice 1

- Private channels / explicit team membership (Slice 2)
- Backfill of channels for pre-existing projects (FLI-001 was provisioned manually for the demo; a patch comes in Slice 2)
- The inbound human→agent path (Slice 3) — the big one
- Deliverables-as-artifacts (Slice 5)
- Gate-approval-in-chat (Slice 6)

## Slice 3 — inbound routing: the project's own orchestrator (LOCKED 2026-06-16)

### The surprise: the path was already there

We opened Slice 3 expecting to *build* the inbound path. We found it already wired end-to-end (it came in with the unified gateway + the CLI surface):

```
Raven Message.after_insert → raven_adapter.handle_raven_message   (human msg → inbound Chat Message row)
Chat Message.after_insert  → gateway.service.handle_inbound        (governed run_turn → outbound Chat Message row)
outbound Chat Message      → raven_adapter.handle_outbound_to_raven (post the reply back as the Friday bot)
```

The governed turn already fires the full stack: the permission matrix, the H2 approval gate, the execution log, and the Design 69a depth/concurrency gates (a human-started turn is a *top-level* chat session, so depth = 0 / concurrency = 0 — it passes cleanly). Even project-scoped **memory** is already injected (it shipped with `design-73-project-context-memory`).

So Slice 3 is **not** "build the path." It is "make the existing path **project-aware**," because today it's project-blind in two ways.

### The two blindnesses (what we fix)

1. **Routing ignores the room.** `routing/resolve.py:resolve_profile` returns the single `Chat Platform.default_agent_profile` for every Raven message — it never asks "whose project channel is this?" So a message in `proj-fli-001` is answered by the platform default, not by FLI-001's own commander (`Project.project_lead_profile`). The `chat_id` parameter was reserved for exactly this and sat unused.
2. **The turn has no project *status*.** `prompt_builder.build` already injects a *name-only* PROJECT CONTEXT line ("you're in project X, scope to it"). But the orchestrator gets no live state: what's open, what's done, what's been delivered.

### Locked decisions (Q-by-Q, 2026-06-16)

- **Scope:** project-aware routing + a live status snapshot, then verify live. (Not a rebuild.)
- **Trigger — UNCHANGED.** A human still `@Friday`-mentions in a channel (DMs still answer in-membership). We touch **zero** trigger logic: project rooms are Open channels, and keeping the mention requirement holds human-to-human chatter out of the agent. *(Chosen over "answer every message in a project room".)*
- **Context — INJECT A SNAPSHOT each turn:** status + open tasks + deliverables, upgrading the name-only block. *(Chosen over a pull-on-demand tool — the orchestrator should never have to ask where its own project stands.)*

### Change 1 — project-aware routing (`routing/resolve.py`)

`resolve_profile(platform, sender_id, chat_id, content)` gains **one** branch, checked before the platform default:

> if `chat_id` maps to a Project (via `memory.project_for_session`) **and** that Project's `project_lead_profile` is an **Active** Agent Profile → route to it. Otherwise fall through to the existing `Chat Platform.default_agent_profile`.

`raven_adapter._resolve_profile()` now passes `chat_id=doc.channel_id`. **Fallbacks (all → platform default):** non-project channel, DM, project with no lead, or a Suspended/Retired lead. No regression — when `chat_id` is `None` or resolves to nothing, the result is byte-for-byte the old default lookup.

We deliberately **don't** hard-require the lead be role=Orchestrator — a project may legitimately be led by a specialist, and the existing `delegate-task` role gate already handles a non-orchestrator that tries to delegate. We only require the lead be **Active** (never route to a dead agent).

### Change 2 — the status snapshot (`llm/project_context.py`, new)

`project_snapshot_block(project)` returns one system message (or `None`): the scoping instruction (kept from the old block) + a **CURRENT STATE** section —

- **Status + progress** (`Project.status` / `percent_complete` / `completed_tasks` / `total_tasks`)
- **Open tasks** — title + `workflow_state` for non-terminal tasks (Pending/Assigned/Executing/Review/Blocked), capped at 20
- **Deliverables** — `deliverable-*` files attached to the Project (the package) + per-task artifacts (Slice 5), capped at 8, or "none yet"

`prompt_builder.build` swaps its inline name-only block for this call. It still fires **only** when `project_for_session(session_id)` resolves — so DMs and non-project sessions are unchanged, and the UUID-session prompt-builder tests stay green.

**No schema change** — both changes read existing fields. The migrate gate is a no-op delta, but is still run.

### Hermes comparison

Hermes resolves "who answers" trivially — it's a single-user CLI, so the agent is always the one you launched. Friday is hosted and multi-project, so "who answers" is a real routing decision: the *room* selects the agent. This is the unified-gateway divergence (memory `feedback-unified-gateway-service`) doing exactly what it was built for — the function body grew; no adapter changed.

### Verify plan

1. `tests/test_resolve.py` (mock-based, hermetic) — routing branches: active-lead / no-lead / inactive-lead / no-project / no-chat_id / unknown-platform. → *verify: green, zero DB writes.*
2. `tests/test_project_context.py` (commit-free, rolled back) — snapshot lists open tasks, excludes terminal, "none yet" deliverables, `None` for a missing project; `build()` injects the block for a `task::` session and not for a UUID session. → *verify: green.*
3. Existing `test_prompt_builder` + `test_raven_adapter` + `test_chat_flow` + `test_memory_project_scope` → *verify: still green (no regression; the memory-scope build test asserts "PROJECT CONTEXT" + the project name, which the snapshot preserves).*
4. `bench --site friday.localhost migrate` → *verify: clean (no schema delta).*
5. **LIVE:** set `FLI-001.project_lead_profile`, `@Friday` in `proj-fli-001`, ask "where are we?" → *verify: the outbound Chat Message's `agent_profile` == the project lead, and the reply cites a real open task / real status from the snapshot.*
