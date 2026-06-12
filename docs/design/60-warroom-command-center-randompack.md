# Design 60 — The War Room Command Center + the RandomPack integration

**Status: LOCKED 2026-06-12 — all seven decisions (Q1–Q7) accepted as recommended ("lock all"). Implementation: 60a then 60b.**

## What this is, in plain English

Friday's main feature, in one loop:

> RandomPack (the ops backend) emits **`project.created`** → Friday plans the
> productized 10-day pipeline into **Tasks with dependencies** → agent
> profiles execute them **as real governed turns** as dependencies clear →
> the **War Room narrates** every step and humans steer from chat → outputs
> flow back to RandomPack (**progress, deliverables, notes, gate-ready
> signals**) — audited, cost-accounted, and human-gated end to end.

Two halves, one feature: (A) the **command center** (project planning,
agentic task execution, dependencies, the chat command loop) and (B) the
**RandomPack surface** (webhook receiver + write-back client). The external
contract below is already agreed by both sides; the Qs are Friday's open
internal decisions.

**Floor-not-ceiling note:** Hermes has todo lists and delegation. A durable,
team-visible, human-gated, revenue-attached project command center is
**beyond Hermes** — this is Friday's signature feature, designed as such.

## The locked external contract (agreed with the randompack side)

- **Events in** (HMAC-signed, retried w/ backoff, replayable by UUID):
  `brief.submitted, payment.received, project.created, gate.opened,
  gate.decided, refinement.requested, phase.changed, comment.added,
  files.delivered, project.completed` **plus (new)** `project.cancelled,
  payment.refunded, gate.reminder`. Envelope `{id, type, version,
  occurred_at, data}`; `data` carries the frozen `brief_snapshot` after
  payment. No `brief.updated` (briefs immutable after submit). No
  rounds-remaining counter — rounds are unlimited (+2 delivery days each);
  `refinement.requested` carries `round`.
- **Signature:** Stripe-style per-attempt —
  `X-RP-Signature: t=<unix-of-attempt>,v1=HMAC-SHA256(secret, "{t}.{raw_body}")`.
  Friday verifies `v1` (constant-time, raw body), then enforces a **300s
  tolerance** on `t`. Backend replays re-sign with fresh `t`.
- **Write-back (outbound):** `update_task_progress` (now with optional
  `progress` 0–100 that never touches status unless passed — heartbeat-safe),
  `attach_deliverable` (two modes live today: multipart to Frappe-native
  `upload_file` with our API key → pass returned `file_url`), and
  `post_project_note`. **New:** `request_gate_open` (signal-only; humans own
  gates) and **read endpoints** (project state incl. tasks/decisions/brief;
  comments) under a "Friday Integration" role — rehydration without replay.
- **Needs-human ≠ failed:** signalled as status **`Pending Review`** + a
  `post_project_note` carrying Friday's Issue reference.
- **No echo:** `comment.added` filters comments authored by Friday's API
  user — Friday will never receive its own notes back. Per contract, Friday
  builds **no self-echo dedupe** (stated assumption, noted in code).
- Files become private Project attachments; **backend stays single writer to
  Drive**.

## Decisions to lock (Q-by-Q — Friday-internal)

**Q1 — The receiver: one durable `RandomPack Event` row per envelope.**
*Recommendation:* `POST /api/method/...surfaces.randompack.receive_event`:
verify signature → insert event row (**UUID-unique** — duplicate POST = 200
no-op) → ack 200 → enqueue processing on the dedicated `friday` queue. A
per-type handler registry processes rows; status `Received → Processed /
Failed(+reason)`. Replays re-enqueue failed events, skip succeeded ones.
(Same pattern as the gateway: ack fast, work async, everything durable.)

**Q2 — Lane 1 gets a brain: `execution_mode` on Task.**
*Recommendation:* Task gains `execution_mode` = `mechanical` (existing:
skill sequence, no model) | **`agentic`** (new: the matched profile runs a
real governed `run_turn` with the task's framing — same isolation contract
as delegation: `task::<name>` session, summary onto `Task.result`). The
existing scheduler tick + capability matcher dispatch both modes; agentic
runs land on the `friday` worker. This finishes the deferral disclosed in
design 57 Q2.

**Q3 — Dependencies: simple AND-gating.**
*Recommendation:* `depends_on` child table on Task (links to other Tasks).
A task is dispatchable only when state ∈ {Pending} **and every dependency is
Completed**. Failure upstream → dependents stay parked; the Blocked task
files its Issue (existing D6) and the chain waits for a human. No OR-deps,
no fan-in counts in v0.1 — disclosed.

**Q4 — Project planning: TEMPLATE-FIRST, not freeform.**
*Recommendation:* RandomPack is a productized, fixed-price pipeline — so the
plan is a **deterministic template** (strategy → naming → 3 directions →
gate 1 prep → build-out → refinement rounds → gate 2 prep → guidelines →
delivery), instantiated by `plan-project` with LLM-written task
*descriptions* customised from the `brief_snapshot`. Predictable structure,
intelligent content. Freeform LLM project decomposition is the disclosed
follow-up for non-productized work.

**Q5 — Write-back mapping (the state bridge).**
*Recommendation:* one module owns the mapping: Executing → `in_progress` (+
`progress` heartbeats at phase boundaries), Completed → `completed` (+
`attach_deliverable` for artifacts: PDF via Frappe print formats, structured
docs as files), Blocked/needs-human → **`Pending Review`** + note with the
Issue reference, Cancelled → terminal note. Gate-lane completion fires
`request_gate_open`. All outbound calls: savepoint-guarded, queued with
retries, API key in an encrypted field — an outbound outage never breaks a
turn (the War Room/publisher pattern).

**Q6 — Round scope-guard: advisory, not blocking.**
*Recommendation:* on `refinement.requested` with `round` N: execute
normally; when N ≥ 3, also post an internal War Room flag + a memory note
("client X on round N, +2 days each") so humans see scope creep early.
No cap enforced — business says rounds are unlimited; Friday's job is
visibility, not policing.

**Q7 — The command loop stays in ONE War Room (v0.1).**
*Recommendation:* keep the single FRIDAY_WAR_ROOM channel: the ticker
already narrates `[TASK-x]` transitions; commands work via @Friday (live
today) once the project/task skills exist (`project-status`,
`plan-project`, `update-task`, `pause-project`). Messages are
project-tagged (`[PRJ-x]`). Per-project Raven channels are the disclosed
follow-up once volume demands it. `gate.reminder` and cancellations post
here too — `project.cancelled`/`payment.refunded` **cancel all open Friday
tasks for that project immediately** (the kill switch).

## What lands on disk — TWO implementation PRs (this is deliberately split)

**60a — the integration surface:**
`surfaces/randompack.py` (receiver: signature verify w/ 300s tolerance,
event rows, UUID dedupe, queue handoff) · `RandomPack Event` + `RandomPack
Settings` DocTypes (secrets in encrypted fields) · `integrations/
randompack_client.py` (the 5 outbound calls + `upload_file` flow) · handler
registry with the event→action map · tests (signature good/bad/stale,
dedupe, replay semantics, handler routing, client retry/savepoint) · live
proof: signed test event → event row → handler fires → note posted back.

**60b — the command center:**
Task `execution_mode` + `depends_on` + dispatcher gating · agentic task
runner (delegation-style framing/isolation) · the pipeline template +
`plan-project` / `project-status` / `update-task` skills + bootstrap ·
write-back mapping module · round scope-guard · tests (dep gating, agentic
run isolation, template instantiation, state mapping, kill switch) · live
proof: `project.created` event → planned pipeline → agentic tasks execute in
dependency order → War Room narrates → progress/deliverable/`Pending
Review`/`request_gate_open` calls observed on a stub backend.

## Out of scope (deliberately, disclosed)

- Freeform LLM project decomposition (template-first per Q4).
- OR-dependencies / parallel fan-in counting.
- Per-project Raven channels.
- Direct Drive writes (backend is single writer — permanent posture).
- Round caps (business decision: unlimited).
- Generated artwork files (designer-ready specs only, v0.1 stance).
