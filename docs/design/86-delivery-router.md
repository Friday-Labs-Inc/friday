# Design 86 — Delivery target DSL + router (Q-by-Q lock)

**Status:** LOCKED 2026-06-24 — Q1–Q5 all answered as the recommended path
(faithful DSL + Frappe-native sinks). Tests-first, then code. Gateway gap #5 from
the ports ledger (`delivery.py`). The user chose the **full faithful port**
including free `platform:chat` targeting, with eyes open to the governance note
below.

## Plain English

A delivery router answers "I have some output — where does it go?". Today Friday
only ever delivers to **origin** (a turn writes an outbound `Chat Message` to its
own `session_id`; the surface adapter posts it). Hermes' `gateway/delivery.py`
generalises this: a small **target DSL** (`origin`, `local`, `platform:chat_id`,
`platform`) + a router that fans one piece of content out to many targets, with
oversized-output truncation and a file sink for output that has no channel
(cron). This ports that.

## Governance note (acknowledged)

Hermes' headline feature — an agent delivering to an arbitrary `platform:chat` —
is something Friday's *skills* deliberately avoid (`share-deliverables` posts
only into the conversation's own channel, "never a free parameter"). The
resolution: **the router is a low-level primitive; governance lives at the skill
/ permission layer, not in the router.** A skill that exposes free targeting is
gated by the permission matrix; the router itself can address anywhere. The user
accepted this divergence — recorded here and in the ports ledger.

This ships slightly ahead of its consumers (cron — gap #7 — is the first real
caller). That's the accepted trade: land the primitive now, wire callers later.

## What the source says (grounded)

`gateway/delivery.py` (`reference/hermes-agent/`):
- `DeliveryTarget.parse(target, origin)` (`delivery.py:84`): `"origin"` →
  resolve from the origin source; `"local"` → file sink; `"platform:chat:thread"`
  → explicit; bare `"platform"` → home channel; **unknown platform → fall back to
  LOCAL** (never raises).
- `DeliveryRouter.deliver(content, targets, …)` (`delivery.py:167`): per-target
  `try/except`, returns `{target_string: {success, result|error}}` — one target
  failing never aborts the others.
- `_deliver_local` (`:209`): writes a timestamped Markdown doc (job name, job id,
  metadata header + content).
- `MAX_PLATFORM_OUTPUT = 4000` (`:21`): oversize → save full output to disk
  (`_save_full_output`, `:255`), deliver `content[:TRUNCATED_VISIBLE] + "…
  [truncated, full output saved to {path}]"`.
- The Telegram private-topic logic (`:285+`) is platform-specific — **not
  ported** (Friday's surface is Raven; no thread topics).

## Why a Q-by-Q lock

The DSL is portable verbatim; the *sinks* are where Frappe forces choices —
platform delivery is a `Chat Message` row, not an adapter `.send()`; the "local"
sink is a Frappe File, not a disk path. Five questions.

---

## Q1 — How does a `platform:chat_id` target actually deliver?

**Option A — insert an outbound `Chat Message` row (recommended).** Friday's
unified gateway already delivers through rows: a turn writes
`{direction: outbound, platform, session_id}` and the surface adapter
(`raven_adapter.handle_outbound_to_raven`) posts it. So "deliver to
`raven:CH-123`" = insert an outbound row with `session_id=CH-123, platform=raven`.
The router reuses the existing delivery path; nothing new posts to Raven. This is
the faithful Frappe adaptation of Hermes' `adapter.send()`.

**Option B — call a platform adapter `.send()` directly.** Bypasses the row
audit trail and re-implements posting. Rejected — violates the unified-gateway
"every message is a row" rule (`feedback_unified-gateway-service`).

**Recommendation: A.** Platform delivery = one outbound `Chat Message` row.

---

## Q2 — What is "platform", with no `Platform` enum?

Hermes has a `Platform` enum; Friday has `Chat Platform` doctype rows.

**Option A — platform is a string; `local`/`origin` reserved; unknown → local
(recommended).** `parse()` treats the first token as a Chat Platform name
(case-insensitive). It does NOT pre-validate against the DB at parse time (parse
stays pure/testable); an unknown or unconfigured platform falls back to the
`local` sink at *deliver* time — faithful to Hermes' "unknown platform → LOCAL".

**Option B — validate against `Chat Platform` rows in `parse()`.** Couples
parsing to the DB, breaks pure unit-testing of the DSL. Rejected.

**Recommendation: A.** String platform; local fallback on unknown at delivery.

---

## Q3 — What is the "local" sink in Frappe?

Hermes writes `~/.hermes/cron/output/{job_id}/{ts}.md` on disk.

**Option A — a private Frappe File (recommended).** Write the Markdown document
as a `File` doctype row (`is_private=1`), named by job id + timestamp. It gets a
URL, shows in Desk, survives restarts, and is the natural Frappe durable sink.
Disclosed frappe-adaptation of Hermes' disk path.

**Option B — a path under the site's private files dir.** Closer to Hermes
literally, but a bare path isn't first-class in Frappe (no URL, not in Desk).
Rejected.

**Recommendation: A.** `local` → a private `File`. Return its file URL in the
result.

---

## Q4 — Oversized-output truncation

**Option A — port it faithfully (recommended).** `MAX_PLATFORM_OUTPUT = 4000`.
When a platform delivery's content exceeds it: save the full content to a private
File (the Q3 sink), deliver `content[:TRUNCATED_VISIBLE]` + `"\n\n… [truncated,
full output saved to {file_url}]"`. Keeps Raven posts within sane size while never
losing the full output. `local` deliveries are never truncated (the file holds
everything).

**Recommendation: A.** Faithful 4k truncation with full-output File.

---

## Q5 — `thread_id` and the consumer

**thread_id:** Friday `Chat Message` has no thread concept. `parse()` still reads
a third `:thread` token (so the DSL round-trips), but Raven delivery **ignores
it** in v1. Disclosed simplification; revisit if a threaded surface lands.

**Consumer:** ship the module + tests now; do **not** add a new skill or refactor
the existing `_write_outbound`/`share-deliverables` paths (no churn to working
code). The first real caller is the cron port (gap #7). The module is importable
and fully tested so cron can wire it cleanly.

**Recommendation:** as above.

---

## Summary of what lands once Q1–Q5 are answered (recommended path)

- **`gateway/delivery.py`** (new):
  - `DeliveryTarget` (frozen dataclass) + `parse(target, origin)` — the DSL,
    pure/DB-free, unknown-platform→local, faithful to Hermes (Q2).
  - `DeliveryOrigin` — a tiny `(platform, session_id)` holder for `origin`
    resolution (Friday's stand-in for Hermes `SessionSource`).
  - `DeliveryRouter.deliver(content, targets, job_id=None, job_name=None,
    metadata=None) -> dict` — per-target try/except, results dict (Q1).
  - `_deliver_to_session` → outbound `Chat Message` row, with 4k truncation +
    full-output File (Q1+Q4).
  - `_deliver_local` → private Markdown `File` (Q3).
- **No** new skill, **no** refactor of existing outbound paths (Q5).

**Tests-first:**
1. `parse`: `origin` (with/without an origin), `local`, `raven:CH-1`,
   `raven:CH-1:T9` (thread parsed), bare `raven`, and unknown `wat:x` → local.
2. `deliver` to `raven:CH-1` inserts ONE outbound `Chat Message`
   (`direction=outbound, platform=raven, session_id=CH-1`).
3. `deliver` with two targets where one raises → results dict marks one success,
   one error; the other still delivered (per-target isolation).
4. Oversized content to a platform target → truncated visible body + a full-output
   File created + "[truncated …]" marker.
5. `local` target → a private `File` written with the job/metadata header; never
   truncated.
6. `origin` with no origin supplied → falls back to `local`.

Nothing is built until Q1–Q5 are confirmed.
