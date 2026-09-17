# Design 82 — Gateway command surface (slash dispatch) (Q-by-Q lock)

**Status:** LOCKED 2026-06-24 — D1 + Q1–Q5 all answered as the recommended path
(A throughout). Tests-first, then code. Triggered by the gateway deep audit
(`docs/ports/hermes-port-ledger.md` § Gateway deep audit, 2026-06-24), which
found that **no slash-command parsing exists on any inbound path** — and that
this absence blocks the entire session-manager port (interrupt / steer) plus
chat-driven approvals.

## The gap, in plain English

In Hermes you can type `/stop`, `/status`, `/approve`, `/steer` into any chat
and the gateway acts on it instead of feeding it to the agent. In Friday, every
inbound message — including one that starts with `/` — is written as a
`Chat Message` row and handed to `run_turn` as conversation. There is no command
layer. Confirmed by grep across `friday_core`: zero handlers for `/approve`,
`/deny`, `/stop`, `/status`, or any slash string. `cli/chat.py` and
`raven_adapter.py` pass text verbatim.

Two things are stuck behind this:

1. **The human-approval gate can't be driven from chat.** The gate already
   exists — a skill flagged `requires_approval` creates a Pending `Workflow
   Request` and pauses the turn (`agent_runner/dispatcher.py:271`,
   `approvals/workflow.py:83` `approve()` / `:121` `reject()`). But today the
   only way to approve is Desk or an API call. From Raven — where the operator
   actually lives (`project_interface-style-a-conversational`) — there is no
   `/approve`. The governance feature is built but unreachable from the primary
   surface.
2. **Interrupt and steer have no trigger.** The ledger's headline gateway gaps
   (cancel a running turn; nudge a running turn) are commands. Without a command
   layer there is nothing to wire them to.

So slash dispatch is the **prerequisite port** — small on its own, unblocks the
high-value work.

## Decision already locked (D1) — parse at the surface adapter

Locked with the user 2026-06-24: **slash commands are detected and peeled at the
surface-adapter edge, before a `Chat Message` row is written.** A command never
becomes a conversational row fed to `run_turn`. This matches Hermes (commands
handled at the adapter edge, `gateway/run.py:7026–7792`) and keeps the
conversational transcript clean of control traffic.

Consequence: `raven_adapter.handle_raven_message` (`:46`) and `cli/chat.py`
(`:86`) each gain a "is this a command?" check up front. The open questions below
are about **what happens after** that check fires.

## Why a Q-by-Q lock instead of just coding it

"Parse at the adapter" still leaves five decisions that change the schema and the
blast radius. Pick them wrong and either every new surface re-implements command
logic, or commands silently bypass governance, or `/approve` approves the wrong
request. Five questions.

---

## Q1 — Where does the dispatch *logic* live?

D1 says adapters *detect* `/cmd`. But the logic that runs a command (resolve
name → check perms → act → reply) should not be duplicated per adapter, or the
Raven and CLI paths drift.

**Option A — Shared Core dispatcher, thin adapters (recommended).** A new
`gateway/commands.py` exposes `dispatch_command(platform, channel_id, user, raw)
-> CommandResult`. Each adapter does only: detect leading `/`, tokenize, call the
dispatcher, deliver the `CommandResult` back through its own send path. One
command table, every surface inherits it. Adapters stay thin (the surface
contract per `feedback_unified-gateway-service`).

**Option B — Per-adapter handling.** Each adapter has its own `if cmd == ...`.
Closest to Hermes's literal structure (its dispatch is inside `run.py`), but
Friday has N adapters where Hermes has one process — this guarantees drift.

**Recommendation: A.** It is the unified-gateway principle applied to the command
layer: surfaces are thin, logic is central.

---

## Q2 — What commands ship in v1?

The command set we build first. Note `/stop` and `/steer` have nothing to act on
until the interrupt/steer ports (future), so shipping them now would be dead
buttons.

**Option A — Approvals + status only (recommended).**
`/approve [id]`, `/deny [id] [reason]`, `/status`, `/help`. Every one of these
acts on something that exists today: the approval gate and live session state.
`/approve` is the single highest-value command — it makes the built-but-
unreachable governance gate usable from Raven.

**Option B — Full Hermes set now.** Also ship `/stop`, `/steer`, `/new`. Bigger
surface, but `/stop`/`/steer` are no-ops until their ports land, and `/new`
(session reset) is a `simplified`/deliberately-absent concept in Friday
(sessions don't rotate — ledger bucket 1). Ships dead or semantically-foreign
commands.

**Recommendation: A.** Ship the four that do real work. Add `/stop` and `/steer`
*in the same PR as their ports*, so a command never ships before its action.

---

## Q3 — Are commands recorded, and how does the reply reach the user?

D1 means a command is **not** a conversational `Chat Message`. But governance and
debugging want an audit trail, and the reply (`"✅ Approved BB-0034."`) still has
to get back to the user.

**Option A — Audit row + direct surface reply (recommended).** Write one
`Chat Message` row with `direction=inbound`, `processed=1`, and a new
`is_command` check field (so it is auditable but the gateway hook skips it — it
was already handled). The reply is posted **directly through the adapter's send
path** (Raven: `Raven Bot.send_message`; CLI: stdout), not via the
`run_turn`/outbound-row machinery. Clean separation: control traffic is logged
but never re-enters the conversational pipeline.

**Option B — No row, reply only.** Commands leave no trace; just reply. Simplest,
but loses the audit trail for governance actions (`/approve` is a governance act
— it *should* be auditable). Rejected for approval commands specifically.

**Option C — Full row through the normal pipeline.** Treat the command like a
message with `processed=0`. Violates D1 (command becomes conversational), risks
the gateway hook re-processing it. Rejected.

**Recommendation: A.** A governance command must be auditable; a `Chat Message`
row with `is_command=1` gives that without polluting the transcript or the
pipeline. New field: `Chat Message.is_command` (Check, default 0).

---

## Q4 — What gates *who* may run a command?

Hermes `slash_access.py` is two-axis: may-talk (already enforced: Raven
membership / @mention, `raven_adapter.py:46`) vs **may-run-commands**. Friday has
no command tier. `/approve` must not be runnable by anyone who can type in the
channel.

**Option A — Frappe role per command tier (recommended).** Two tiers:
*open* (`/status`, `/help` — any user who may talk) and *operator* (`/approve`,
`/deny` — requires a Frappe role, e.g. `Friday Operator`). The dispatcher checks
`frappe.get_roles(user)` against the command's required role. Reuses Frappe's
permission substrate (the right call per the existing governance posture); no new
perm model invented.

**Option B — Reuse the agent role contract.** Gate on `Agent Profile.agent_role`
(Orchestrator/Specialist/Worker, design 68). Wrong axis — that classifies
*agents*, not the *humans* issuing commands. Rejected.

**Option C — No gating in v1.** Single-tenant, trusted operator
(`feedback_single-tenant-not-saas`). Defer. Risky: `/approve` from any channel
member defeats the human gate's purpose. Rejected for operator-tier commands.

**Recommendation: A.** Map command → required Frappe role; `/status` `/help`
open, `/approve` `/deny` require `Friday Operator`. Open commands need no role.

---

## Q5 — How does `/approve` choose *which* Workflow Request?

`approve()` takes a `request_name` (`approvals/workflow.py:83`). A channel may
have more than one Pending request. The command must resolve a target.

**Option A — Channel's current Pending, explicit id optional (recommended).**
Bare `/approve` resolves the **oldest Pending `Workflow Request` for this
session/channel** (one query: filter by the channel's session + status=Pending,
order by creation). `/approve BB-0034-req3` targets explicitly when there are
several. Matches how an operator thinks ("approve the thing you just asked me
about") while keeping an unambiguous override. Requires the `Workflow Request`
to carry the originating session/channel — verify the field exists; add if not.

**Option B — Explicit id always required.** `/approve` alone errors with the
list of Pending ids. Unambiguous but clumsy — the operator must copy an id for
the common single-pending case.

**Option C — Approve all Pending in channel.** Bare `/approve` approves every
Pending request for the channel. Dangerous — bulk-approving governance gates is
exactly what the gate exists to prevent. Rejected.

**Recommendation: A.** Default to the channel's oldest Pending; allow an explicit
id. Sub-task: confirm/add a session-or-channel link on `Workflow Request` so the
"for this channel" filter is possible (if absent, this becomes the first build
step).

---

## Summary of what lands once Q1–Q5 are answered (recommended path)

- New `gateway/commands.py` — `dispatch_command()` + a command table (Q1-A).
- v1 commands: `/approve`, `/deny`, `/status`, `/help` (Q2-A).
- Adapters (`raven_adapter`, `cli/chat`) gain a detect-and-peel step that calls
  the dispatcher and delivers the reply directly (D1 + Q3-A).
- New field `Chat Message.is_command` (Check) for the audit row (Q3-A).
- Command→role map, checked via `frappe.get_roles` (Q4-A); `Friday Operator`
  role seeded.
- `/approve` resolves the channel's oldest Pending `Workflow Request`, explicit
  id optional (Q5-A). **Confirmed:** `Workflow Request.session_id` already
  exists — no schema change needed for the channel filter.

**Tests-first** (per the workflow rule), before any handler code:
1. `/status` in a channel → returns session state, writes no conversational row.
2. `/approve` with one Pending request → request flips to Approved, paused turn
   re-dispatches, audit row written `is_command=1`.
3. `/approve` from a user lacking `Friday Operator` → refused, request stays
   Pending.
4. A normal message starting with text (not `/`) → still reaches `run_turn`
   unchanged (no regression to the conversational path).
5. `/approve` with two Pending requests and no id → targets the oldest;
   explicit id targets the named one.

Nothing is built until Q1–Q5 are confirmed.
