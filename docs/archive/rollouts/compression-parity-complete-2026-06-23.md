# Compression parity — complete (13-section summary + workstream closure)

_Shipped 2026-06-23. Closes the five-gap compression-parity workstream from the
Hermes ledger. This doc covers Gap 2 (structured summary) and records the
dispositions of all five._

## In one sentence

When a long conversation is compacted, the summary is now a **structured handoff
with named sections** (Active Task, Blocked, Pending User Asks, Remaining Work,
…) instead of free-form prose — so blockers and open requests survive compaction
instead of being lost.

## What it actually does (plain terms)

Compaction folds the old middle of a conversation into a summary. Before, that
summary was free-form text ending with one "Active Task" line — so a blocker or
an unanswered user request could quietly vanish, and the next model, told to
"respond only after the summary," would forget it.

Now the summariser is asked to fill **13 named sections**: Active Task, Goal,
Constraints & Preferences, Completed Actions, Active State, In Progress, Blocked,
Key Decisions, Resolved Questions, Pending User Asks, Relevant Files, Remaining
Work, Critical Context (each "None" if N/A). It must preserve identifiers and
exact error text verbatim and redact secrets. Re-compaction still feeds the
previous summary back in, so sections accumulate rather than reset.

## The five compression-parity gaps — final status

| Gap | Status |
|-----|--------|
| 1. On-error compress + retry | ✅ shipped (compression-quick-wins) |
| 4. Last-user-message-in-tail guarantee | ✅ shipped (compression-quick-wins) |
| 2. 13-section structured summary prompt | ✅ shipped (this) |
| 3. Tool-result pruning before summarising | **N/A — disclosed.** Friday's compaction transcript is built from `Chat Message` rows (user/assistant turns only). Tool calls/results are NOT persisted as Chat Messages — they live in `run_turn`'s in-memory list and never reach the summariser. So there are no tool-result messages to prune. Hermes prunes because its transcript contains tool-role messages; Friday's does not. Revisit only if tool results ever get persisted as Chat Messages. |
| 5. Provider-usage token refinement | **Deferred — disclosed.** Friday uses the char/4 estimate for the compression trigger. Switching to the provider's real `usage.prompt_tokens` is a low-urgency refinement (char/4 is close enough for text; the gap only matters for image-heavy or unusual-tokeniser providers, which Friday doesn't use yet). The real token count is already recorded in `LLM Usage Log`; wiring it into the trigger is a clean later step. |

## What it means for friday-core

Compression parity with Hermes is now functionally complete: long conversations
compress + retry on overflow, keep the latest user turn, and produce a
structured summary that preserves blockers/pending-asks/state. The two non-ports
(3, 5) are deliberate and disclosed, not oversights — 3 doesn't apply to
Friday's architecture, 5 is a measured deferral.

## How it gets along with the Frappe ecosystem

| Friday concept | Frappe reality |
|---|---|
| Structured summary | the `_SUMMARISER_SYSTEM` prompt; the summary is still stored as a durable `Compaction Summary` row |
| Iterative update | `_format_transcript` feeds the prior `Compaction Summary` back in (already in place) |

## Risks and limits a product head should hold

- A weaker auxiliary model may fill sections thinly; the structure helps but
  doesn't guarantee completeness. Tunable via `Agent Settings.compression_model`.
- Gap 5 deferral means the trigger can fire slightly late on token-dense content
  (acceptable for current text providers).

## Numbers for the record

- Files: `llm/compression.py` (`_SUMMARISER_SYSTEM` → 13 structured sections),
  `tests/test_compression.py` (+1: structured-sections assertion).
- Tests: test_compression 26/26. No schema change → no migration.
- Workstream: compression parity CLOSED (3 ports shipped, 1 N/A, 1 deferred).
