# Design 59 — Memory + @-references: Friday remembers, and you can point

**Status: LOCKED 2026-06-12 — all six decisions (Q1–Q6) accepted as recommended ("lock all").**

## What this is, in plain English

Two abilities that turn Friday from "starts cold every morning" into "knows
your clients":

1. **Memory** — durable facts that survive sessions. You (or Friday itself)
   say *"remember: Loop Coffee hates serif fonts"* — and every future turn,
   on every surface, knows it.
2. **@-references** — point Friday at a record naturally: *"draft taglines
   for @BB-0001's shortlisted direction"* — the brief's content is pulled
   into context automatically, permission-checked.

## Hermes faithfulness (sources read)

| Hermes | What it does | Friday port |
|---|---|---|
| `agent/memory_manager.py` | one manager, three seams: memory → system prompt, pre-turn recall, post-turn write; **context fencing** (`build_memory_context_block` / `sanitize_context`) so recalled memory reads as *reference, not instructions* | same three seams in `prompt_builder` + a `remember` skill; the fencing text ported faithfully — it's load-bearing |
| `agent/memory_provider.py` | provider plugin ABC (one external backend max) | ⬛ skipped v0.1 — one built-in store, no plugin layer until a second backend exists |
| `agent/context_references.py` | typed refs `@file:` `@url:` `@git:` `@diff` expanded pre-turn; sensitive-path blocklist (`.ssh`, `.netrc`…); trailing-punctuation trimming | record refs (`@BB-0001`) expanded pre-turn; the blocklist becomes the **permission matrix** (disclosed upgrade); punctuation trimming ported |

## Decisions to lock (Q-by-Q)

**Q1 — Storage: an `Agent Memory` DocType (rows, not files).**
*Recommendation:* fields — `memory` (the fact, required), `agent_profile`
(Link; whose memory it is), `subject` (optional Data tag, e.g. "BB-0001" or
"Loop Coffee", for grouping/filtering in Desk), `source_session` (audit:
where it was learned), `status` (Active/Archived). Hermes keeps MEMORY.md
files; Friday's whole pattern is durable, auditable rows — the established
adaptation. The team can read/edit/archive memories in Desk like any record.

**Q2 — Recall: inject every Active memory, every turn, inside a fence.**
*Recommendation:* `prompt_builder.build()` appends a fenced block after the
system prompt: newest-first, capped at a token budget (default 2,000 tokens
≈ dozens of memories; oldest beyond the cap are dropped from the prompt, not
deleted). The fence text is ported from Hermes' memory context block:
reference-only, never instructions. **Semantic/vector retrieval is
deliberately deferred** — single-tenant scale means hundreds of memories at
most; inject-all-capped is simpler and honest. Disclosed.

**Q3 — Writing: a `remember` skill; the agent decides when.**
*Recommendation:* `remember(memory, subject?)` — low-risk skill, one audit
row per write, `when_to_use` guidance ported from Hermes' memory norms (save
durable facts/preferences/decisions; never conversation minutiae; check it
isn't already known). Users can also just type "remember that …" and the
agent calls it. Hermes' periodic *nudge counters* and post-turn `sync_all`
auto-write are deferred (disclosed) — explicit-write-only keeps v0.1 memory
high-signal. Forgetting = archive in Desk (a `forget` skill is a disclosed
follow-up).

**Q4 — @-references: a prefix registry, starting with your records.**
*Recommendation:* scan the inbound message for `@<ID>` where the ID prefix
maps through a registry: `BB-` → Brand Brief, `BD-` → Brand Direction
(extensible dict — one line per future doctype). Each hit expands into a
fenced context block (whitelisted content fields only) appended to the turn.
Trailing-punctuation trimming ported from Hermes ("…for @BB-0001."). An
unknown or unreadable ref is **reported to the model** ("@BB-9999 not found")
rather than silently dropped — so the agent can tell the user instead of
hallucinating.

**Q5 — The permission gate (Hermes' blocklist, upgraded).**
*Recommendation:* a reference only expands when the agent profile's roles
hold READ on that doctype — the same Custom DocPerm source the permission
matrix already reads. Hermes blocklists sensitive *paths*; Friday inherits
the whole governance model instead. Memory recall is inherently scoped: a
profile sees only its own Active memories.

**Q6 — Governance class.**
*Recommendation:* `remember` = `risk_level=low`, `requires_approval=0`
(internal note-taking; still permission-gated via create-on-Agent-Memory and
fully audited). Reference expansion is a read path inside prompt assembly —
no new skill, no approval; the gate is Q5.

## What lands on disk (when locked)

- `doctype/agent_memory/` — the store (track_changes on).
- `llm/memory.py` — `recall_block(profile)` (fenced, token-capped) +
  the fence text ported from Hermes' `build_memory_context_block`.
- `llm/references.py` — registry, parse (`@ID` + punctuation trim), gated
  expansion, not-found reporting.
- `prompt_builder.py` — two seams: recall block after system; expanded
  references appended to the inbound turn.
- `skills/handlers_memory.py` + `bootstrap_memory.provision` — the
  `remember` skill, "Memory Agent" role (create on Agent Memory), wiring.
- Tests FIRST: fence content, token cap + newest-first ordering, registry
  parse + punctuation, permission-denied → reported not expanded,
  not-found reporting, remember-handler validation/persistence, profile
  scoping (no cross-profile leakage).
- Live proof: tell Friday to remember a client fact → new session recalls
  it; *"@BB-0001"* in chat pulls the brief without calling get-brand-brief.

## Out of scope (deliberately, all disclosed)

- Vector/semantic retrieval (inject-all-capped is right at this scale).
- Memory nudges + post-turn auto-sync (Hermes `sync_all`) — explicit only.
- A `forget` skill (archive via Desk meanwhile).
- The provider plugin layer (`memory_provider.py`) — one store, no plugins.
- `@url:` / `@file:` expansion — records first; web/file refs need their own
  security design (SSRF, sandbox) and arrive with the MCP/web-search slice.
