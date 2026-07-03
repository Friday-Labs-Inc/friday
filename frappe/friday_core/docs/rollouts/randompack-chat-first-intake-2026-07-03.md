# RandomPack chat-first intake (CONTRACT §4.8)

**Date:** 2026-07-03 · **Surface:** `surfaces/randompack_chat.py`

## What changed, in plain English

RandomPack turned their hero chat into the **whole** intake. There are no separate
wizard steps any more — the customer just talks to Friday, and only reviews at the very
end. So Friday's job changed from "quietly extract fields while chatting" to "actively
interview until the brief is complete."

## How it works now

Every turn, RandomPack sends a third thing in the `chat_send` request — a `context`:

```json
{
  "session_id": "...",
  "message": "...",
  "context": {
    "missing_required": ["email", "what_you_do", ...],
    "missing_questionnaire": ["brand_animal", "logo_style", ...]
  }
}
```

Those two lists are RandomPack's **ground truth** for what the brief still lacks. They
recompute them from the draft brief every turn, so they shrink as Friday's deltas apply
(and grow again if the customer changes an earlier answer). Friday uses them to steer:

- Ask **one** question per turn — never a wall of questions.
- Cover **`missing_required` first** (these gate checkout), then `missing_questionnaire`
  in the order given.
- **Never re-ask** a field that's in neither list (already answered).
- If the customer's message already answers upcoming questions, emit those deltas and
  skip the questions.
- When **both lists are empty**, stop asking, give a one-line summary, and tell the
  customer to tap **"Review & pay"** (the exact CTA label in RandomPack's UI).

Raw field names (like `brand_story`) are turned into natural questions via a small hint
map — the model is told to ask them naturally, not read them out.

## New fields the chat now captures

`brand_story`, `brand_surfaces`, `color_preferences`, `brand_animal`, `brand_symbol`,
and `logo_style` (a select: *Wordmark (text only)* / *Icon / symbol* / *Combination* /
*Not sure*). `personality` still snaps to the live Brand Attribute vocabulary (§4.5); the
three never-extract fields (`password`, `gate_commitment`, `terms_accepted`) remain absent.

## The "no reply" fix

A live test ("*I want to start an adult pleasure toy brand*") got **no assistant reply** —
a lawful category the model shouldn't refuse. Two guards:

1. The system prompt now says, in every variant: RandomPack serves every lawful business,
   **never refuse, judge, or moralise** — always reply.
2. If a completion still comes back empty (a refusal-as-silence, or an all-reasoning reply
   that gets stripped to nothing), Friday sends a gentle nudge instead of a blank turn.

If it recurs, the remaining cause would be a provider-level content filter (Minimax), which
is a provider setting, not a prompt fix.

## Not changed

`chat_finalize` is untouched on the wire — but because the 6 new fields are in the shared
vocabulary, its full-transcript re-extraction picks them up for free.
