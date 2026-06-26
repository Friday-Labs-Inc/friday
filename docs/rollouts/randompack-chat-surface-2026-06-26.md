# RandomPack chat-intake surface — the wire (2026-06-26)

> The surface layer on top of the streaming foundation (#160): RandomPack's hero chat
> box, proxied to Friday over the existing HMAC seam, becomes a live streaming
> conversation that pre-fills the `/start` wizard. Built against `CONTRACT.md v1.1 §4`
> (the wire is locked; the finalize→account handoff is provisional, owned by RP's
> in-flight signup redesign).

## Endpoints (`surfaces/randompack_chat.py`)

Both whitelisted + guest; the `X-RP-Signature` HMAC (the `randompack-system` Connector's
secret, the same seam as connector events) IS the auth.

- **`chat_send`** — `POST {session_id, message}` → an **SSE stream**:
  - `{type:"token", text}` — the live reply, with `<think>…</think>` blocks hidden;
  - `{type:"delta", step, field, value, confidence}` — wizard pre-fill, one per field;
  - `{type:"done"}` / `{type:"error", error}`.
- **`chat_finalize`** — `POST {session_id}` → a final full-transcript extraction pass,
  returns `{session_id, deltas:[…]}` as JSON. (RP writes the draft brief + owns the
  account step — provisional, not built here.)

Path: `/api/method/frappe.friday_core.surfaces.randompack_chat.chat_send` (and
`…chat_finalize`). `surfaces/randompack.py` already exists as a module, so this is a
sibling file, not a `randompack/` package.

## How it works

- **Streaming.** `provider.chat()` is Frappe-free, so the streamed completion runs in a
  worker thread feeding a queue; the SSE generator (the request thread) owns all Frappe
  work — the per-session lock (`friday:session_lock:{id}`), the transcript load, and
  persistence — and relays tokens through a `_ThinkFilter`.
- **`_ThinkFilter`** suppresses `<think>…</think>` from the live token stream, **safe
  against a tag split across two chunks** (`"<thi"`+`"nk>"`), holding back any trailing
  run that could be a partial tag. The final reply is also `strip_reasoning`-scrubbed for
  persistence/extraction.
- **Extraction vocabulary** = RandomPack's 20 `Onboarding Brief` field names exactly,
  injected into the deterministic extraction pass. Select fields name their exact options
  (so the model emits a verbatim string or nothing); `personality` is a batched array
  (≤3); `references` is `[{type:"URL",url}]`. Each delta is tagged with its advisory
  wizard `step`.
- **The 3 never-touch fields** (`password`, `gate_commitment`, `terms_accepted`) are
  **not in the vocabulary at all** — they can never be emitted as deltas. (Defence in
  depth: RP also rejects them server-side.)
- **Session continuity** is the `Chat Message` rows keyed by `session_id` (== RP's
  session_id) — survives a browser refresh with no Redis-only state. RP's
  `Onboarding Conversation` is the system of record.

## Proven live (the showcase)

`bench execute …surfaces.randompack_chat.run_demo` on the real provider. From one message
("I'm Mara Lindqvist, mara@northwind.co, we're Northwind Tools — premium hand tools for
woodworkers, rugged heritage feel, found you via a YouTube review") the reply **streamed
clean (no `<think>` leaked)** and the extraction filled **8 fields across 4 steps** in
RandomPack's exact vocabulary — including `lead_source='YouTube'` (a verbatim select
option) and `personality=['rugged','heritage']` (the batched array).

## Tests

15 DB-free unit tests: the `_ThinkFilter` (whole / split-open / split-close tags, text
around a block, lone `<`), SSE framing, wire-delta step-tagging + unknown-field drop +
array pass-through, the field vocabulary (never-touch absent, selects name options,
arrays described), and — the **#161 lesson applied proactively** — a routability test
asserting both endpoints are registered with Frappe (`frappe.whitelisted` + guest +
POST), which fails if a decorator is ever dropped. ruff clean.

## NOT built (deferred / out of scope)

- The live HTTP/SSE round-trip from RP (needs the web stack) — a deploy check.
- `chat_finalize`'s account/Customer creation — provisional, owned by RP's signup
  redesign.
- A `Customer Intake` Agent Profile must be configured with a real `model_provider` on
  each site (`provision_intake_profile()` creates the profile; the operator sets the
  provider). No schema change in this slice.
