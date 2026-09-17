# Learning loop — Slice 1: post-turn memory review

_Shipped 2026-06-23. Design 79/80, the #1 ledger gap. Friday agents now learn
from conversations. Default-off-safe (interval 0 disables it)._

## In one sentence

After every few conversational turns, the agent quietly re-reads the
conversation and saves anything durable worth remembering — so the next
conversation starts knowing more, without anyone telling it to.

## What it actually does (plain terms)

Until now a turn ended and that was it — unless the agent explicitly chose to
call `remember`, anything the user revealed was forgotten. Now, after every Nth
conversational turn (N = `Agent Settings → Memory Review Interval`, default 3;
0 = off), Friday runs a short background "reflection":

- It re-reads the same conversation, but with its toolset **restricted to the
  `remember` skill only** (it can save memories and do nothing else).
- It decides whether the user revealed a preference, a fact about themselves, a
  durable decision, or a standing instruction — and saves it.
- If nothing stands out, it stays silent. If it saved something, a
  "💾 Learned: …" note appears in the channel.

It runs as a **background job** — the user's reply was already sent, so the
reflection never adds latency. And it can run on a **cheaper model** if you set
one (`Agent Settings → Review Model Provider`).

## What scenarios it now covers

| Scenario | Before | After |
|---|---|---|
| User mentions a preference in passing | Forgotten unless explicitly saved | Captured by the review, available next time |
| A durable decision is made | Same | Saved |
| Nothing notable in the turn | n/a | Review runs, saves nothing, stays silent |
| Pipeline / task turns | n/a | Never trigger a review (conversational turns only) |
| Review interval = 0 | n/a | Feature off, zero behaviour change |
| Review errors / model down | n/a | Best-effort: logged, never affects the conversation |

## What it means for friday-core

This is the capability the whole "agent that learns" story rests on. It reuses
machinery already shipped today: the `run_turn` toolset restriction
(`allowed_skills`) and compression skip, the governed `remember` skill (so every
saved memory is permission-checked + Execution-Log-audited), and the scored +
semantic recall that will surface those memories next time. The review turn
writes **no** Chat Message rows, so it never pollutes the conversation or
disturbs the turn-count cadence.

## How it gets along with the Frappe ecosystem

| Friday concept | Frappe reality |
|---|---|
| "Reflect every N turns" | count of processed inbound `Chat Message` rows for the session; no new counter state |
| The background reflection | a best-effort `frappe.enqueue` job on the `friday` queue (faithful adaptation of Hermes' daemon thread) |
| Cadence + model knobs | two `Agent Settings` fields: `memory_review_interval`, `review_model` |
| Saved fact | the existing `remember` skill → governed `Agent Memory` row + its Execution Log (the audit) |
| Channel note | an outbound `Chat Message` ("💾 Learned: …"), surfaced to Raven/CLI |

## Faithfulness + the one disclosed divergence

The memory-review prompt is a faithful port of Hermes' `_MEMORY_REVIEW_PROMPT`
(`background_review.py`), adapted to the `remember` skill and Friday's
do-not-save norms. The Hermes daemon-thread → Frappe RQ-job swap is the only
structural divergence (Frappe has no long-lived process). **Skill review is NOT
in this slice** — Hermes self-edits its own skills; in Friday that becomes a
*governed proposal* (propose → human approves, never self-edit), which is
Slice 2.

## Risks and limits a product head should hold

- **Cost.** Each review is an extra (short) model turn every N conversational
  turns. Mitigations shipped: it's cadence-gated (default every 3), runs on the
  optional cheaper `review_model`, and the toolset is tiny.
- **No skill learning yet** (Slice 2 — governed proposal).
- **No dedup of repeated learnings yet** — the review may re-save a fact it
  already saved; the recall side de-prioritises duplicates but a write-side
  dedup is a polish item.
- **Quality depends on the model.** A weak review model will under- or
  over-save; tunable via the prompt, the cadence, and `review_model`.

## What this unlocks

- Slice 2 — the governed skill-proposal half of Design 79.
- Compounds with the memory program: more facts captured → better recall.

## Numbers for the record

- Files: `agent_runner/self_review.py` (new), `agent_runner/runner.py`
  (`provider_override` param), `gateway/service.py` (cadence trigger on
  successful turns), `doctype/agent_settings/agent_settings.json` (+2 fields),
  `tests/test_self_review.py` (new, 11).
- Tests: test_self_review 11/11; regressions green (react_loop 20/20,
  gateway 11/11, compression 25/25). Migrate clean (2 new fields).
- Default `memory_review_interval = 3`; `0` disables the whole feature.
