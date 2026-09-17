# Archive

Historical design material. **Not a description of the system.**

Archived 2026-09-17 by [ADR-0009](../adr/0009-archive-the-design-dossier.md).

These documents record reasoning that was real at the time. Their status
lines — `LOCKED`, `BUILT`, `SHIPPED` — record *decisions taken*, never
*behaviour observed*; the governed loop they describe had never run end to end
when they were written. Read them for **why**, never for **what is true now**.

For what is true now: [`CONTEXT.md`](../../CONTEXT.md) and
[`docs/adr/`](../adr/).

| What | Why it's here |
|---|---|
| `design/` — 97 documents | ~30 LOCKED, 12 BUILT, none verified running. 16 name a product, inside a kernel whose own test forbids the word |
| `rollouts/` — 69 dated records | Post-implementation notes; 21 name a product |
| `testing/` | Superseded by the test ratchet, [ADR-0010](../adr/0010-blocking-test-ratchet.md) |
| `CODEX.md` | Phase-1 implementation brief. §3 lists the hard fork under "Stack Decisions (All Final — Do Not Re-Open)", which PR #209 then re-opened |
| `START_HERE.md` | Says "Slice 1 is built… no permission engine, no skill execution yet" against 341 shipped files |
| `context-conversation.md` | 802 lines of raw conversation context |

Still current, deliberately **not** archived: `docs/ports/` (promoted to the
working definition by [ADR-0008](../adr/0008-track-hermes-narrow-waist.md)),
`docs/decisions/spike-results.md`, `docs/agents/`, `docs/contributing/`.

Contradicting something in here is not automatically wrong — but surface it
rather than overriding it silently, per `docs/agents/domain.md`.
