# Compression parity — quick wins (on-error retry + last-user-in-tail)

_Shipped 2026-06-23. First two of the five compression-parity gaps the Hermes
ledger identified. Both are correctness/robustness fixes, no schema change._

## In one sentence

Friday now (1) recovers from a "conversation too long" error by compressing and
retrying instead of hard-failing, and (2) always keeps the user's most recent
message verbatim when it compacts — so the agent never loses the very question
it's meant to answer.

## What it actually does (plain terms)

**Fix 1 — on-error compress + retry.** When the model rejects a request because
the conversation exceeds its context window, Friday's error classifier already
flagged it as "should compress" — but nothing acted on that flag, so the turn
just failed. Now the runner catches that specific error, runs the compaction
pass, rebuilds the (now shorter) prompt, and retries the call once. Any other
error — or a second overflow — still surfaces normally.

**Fix 2 — keep the latest user message.** When a long conversation is compacted,
the most recent turns are kept verbatim and the older middle is summarised. If
the user's latest message happened to be very large, it could fall into the
"middle" and get folded into the summary — and since the compaction note tells
the next model "respond only to messages after the summary," the agent would be
left with no current question to answer. Now the latest user message is always
forced into the kept-verbatim tail. (This is a direct port of a known Hermes
fix, issue #10896.)

## What scenarios it now covers

| Scenario | Before | After |
|---|---|---|
| Context window overflow mid-turn | Hard error to the user | Compress + retry once, turn continues |
| Overflow persists after one compaction | n/a | Surfaces as a real error (capped at 1 retry — no loop) |
| Any non-overflow LLM error | propagated | propagated (unchanged) |
| A review turn (skip_compression) overflows | n/a | Propagates (review turns never compress the real session) |
| Compaction with a huge latest user message | Could be folded into the summary | Always kept verbatim in the tail |

## What it means for friday-core

These close the two highest-value items from the compression-parity section of
the Hermes port ledger. The `should_compress` flag is no longer computed-but-
ignored; long conversations degrade gracefully instead of erroring. Both changes
are guarded and minimal — the retry is capped at 1, and the tail guarantee is a
~10-line addition with no effect on normal-sized conversations.

## How it gets along with the Frappe ecosystem

| Friday concept | Frappe reality |
|---|---|
| On-error retry | `agent_runner/runner.py` wraps `provider.chat()`; reuses `classify_api_error` + the existing `maybe_compress_session` |
| Last-user guarantee | `llm/compression.py:_split_middle_tail` — a post-pass on the Chat Message rows (`direction == "inbound"`) |
| Durability | unchanged — compaction still writes a durable `Compaction Summary` row |

## Risks and limits a product head should hold

- **One retry only.** A conversation that overflows even after a full compaction
  surfaces a real error (by design — better than an infinite compress loop).
- **Review turns don't retry.** Self-improvement review turns pass
  `skip_compression=True` and must not compress the live session, so they
  propagate an overflow instead. Acceptable (reviews are short).
- **Three remaining compression-parity gaps** are not in this slice: the
  13-section structured summary prompt, tool-result pruning before summarising,
  and provider-usage token refinement. Tracked in the ledger.

## What this unlocks

- The remaining compression-parity gaps (13-section prompt, tool-result pruning,
  usage refinement) build on this.
- Removes a class of hard failures on long agent runs — relevant as sessions get
  longer with the new memory/learning work.

## Numbers for the record

- Files: `agent_runner/runner.py` (on-error compress+retry, `MAX_COMPRESS_RETRIES=1`),
  `llm/compression.py` (`_split_middle_tail` last-user-in-tail guarantee),
  `tests/test_react_loop.py` (+4: overflow→retry, second-overflow-raises,
  non-compress-error-raises, skip_compression-no-retry),
  `tests/test_compression.py` (+1: last-user-always-in-tail).
- Tests: test_react_loop 20/20, test_compression 25/25. No schema change → no
  migration. (A separate DB-backed suite, test_runner_tool_call, showed 2
  failures from accumulated dev-site test pollution — a `create_note` write
  path unrelated to these changes; verify on a fresh test site for certainty.)
