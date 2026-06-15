# Design 73 — Project Conversation Surface

**Status:** Building (doc written alongside code, not lock-first). Slice 1 shipped 2026-06-15.

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
