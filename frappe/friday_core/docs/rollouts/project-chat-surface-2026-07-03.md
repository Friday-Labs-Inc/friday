# Project chat surface + the shared streaming spine

**Date:** 2026-07-03 · **Files:** `surfaces/chat_spine.py` (new), `surfaces/randompack_project_chat.py` (new), `surfaces/randompack_chat.py` (refactored onto the spine)

## What this adds, in plain English

RandomPack's customer portal is getting an AI chat next to each project's timeline. A
customer who already paid can ask Friday about their project — "what should I look for
when choosing a direction?", "should I approve Gate 2?" — and when they clearly express
a gate decision in chat ("lock direction B"), Friday **proposes** it. RandomPack shows a
one-tap confirmation card, and only the customer's tap executes the real decision.

## The trust boundary (the important part)

**Friday proposes. The human confirms. RandomPack executes.**

Friday never fires `decide_gate` or any irreversible business action from chat. On top
of that, every proposed action is validated hard before it leaves Friday:

- No gate open → no action, ever. Discussion only.
- The action's gate must equal the **currently open** gate (a "Gate 2" proposal while
  Gate 1 is open is dropped — the hallucination case).
- Gate 1 → only "Direction Selected", and the direction must be one of the labels
  actually offered. Gate 2 → only "Approved" / "Refinement Requested", never a direction.
- Confidence is clamped; RandomPack only shows the card at ≥ 0.5.

The advisor's prompt also states its authority plainly: it has none. It may never claim
it approved or submitted anything. And because RandomPack only holds the direction
*labels* (A/B/C) server-side, the advisor is forbidden from inventing what a direction
looks like — the visuals live in the customer's delivered PDF.

## The shared spine (why the refactor)

This is Friday's **second** streamed chat surface, so the plumbing both surfaces share
moved into one place — `surfaces/chat_spine.py`: the HMAC signature check, SSE framing,
the `<think>`-hiding stream filter, the worker-thread streaming model, transcript +
LLM-usage audit with the **explicit commit** (the #166→#168 lesson: an SSE generator
runs after the request's auto-commit, so without it every write silently vanishes),
Chat Platform registration (#168's root cause), and the never-a-blank-reply guard.

Each surface now keeps only its meaning:

| | Intake (`randompack_chat`) | Project chat (`randompack_project_chat`) |
|---|---|---|
| Who | Guest lead, pre-sale | Authenticated customer, post-sale |
| Profile | Customer Intake | Project Advisor |
| Platform | `randompack-intake` | `randompack-project` |
| Context | missing brief fields | live project state + open gate |
| Structured events | wizard `delta`s | gate `action` proposals |

A fix to the hard parts now lands once and applies to every chat surface — the audit
bug that had to be fixed twice in intake can't be re-introduced by a copy.

## Config (operator)

`provision_advisor_profile()` creates the `Project Advisor` profile (inert — the
operator picks its `model_provider`) and the `randompack-project` Chat Platform row
(also created by `after_migrate`). Same HMAC secret as the rest of the RandomPack seam.
