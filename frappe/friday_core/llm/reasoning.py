# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt

"""
Strip model reasoning/"thinking" blocks from assistant text.

Ported from Hermes `agent/think_scrubber.py` — specifically the complete-string
`_strip_think_blocks` semantics it references, NOT the streaming
`StreamingThinkScrubber` state machine. Friday's ReAct loop is non-streaming
(the provider returns the whole message at once), so the per-token streaming
machine isn't needed yet; the complete-string scrub is the right port.

PLAIN ENGLISH
=============
Reasoning models (MiniMax-M2, DeepSeek-R1, etc.) often wrap their internal
chain-of-thought in tags like `<think>...</think>`. That reasoning must NOT:
  - reach the user as the answer, or
  - be fed back into the conversation as if it were the assistant's reply
    (it pollutes context and wastes tokens on every later turn).

This removes it from a complete response string before the runner returns it or
appends it to history. Three cases, matching Hermes exactly:

  1. **Closed pair** `<think>X</think>` — removed anywhere. A closed pair is an
     intentional, bounded block, so it's stripped even mid-line.
  2. **Unterminated open at a line boundary** `<think>... (to end)` — removed.
     Boundary-gated (start-of-string or after a newline) so ordinary prose that
     *mentions* `<think>` isn't over-stripped.
  3. **Orphan close tag** `</think>` — removed with trailing whitespace.

Recognised tag variants (case-insensitive): think, thinking, reasoning,
thought, REASONING_SCRATCHPAD.
"""

from __future__ import annotations

import re

_TAG_NAMES = ("think", "thinking", "reasoning", "thought", "REASONING_SCRATCHPAD")
_NAMES = "|".join(_TAG_NAMES)

# 1. Closed <tag>...</tag> pair — non-greedy, across newlines, any variant.
_CLOSED_PAIR = re.compile(rf"<(?:{_NAMES})>.*?</(?:{_NAMES})>", re.IGNORECASE | re.DOTALL)

# 2. Unterminated open tag at start-of-string or after a newline (+ optional
#    leading whitespace) → strip to the end. Boundary-gated.
_OPEN_TO_END = re.compile(rf"(?:\A|\n)[ \t]*<(?:{_NAMES})>.*\Z", re.IGNORECASE | re.DOTALL)

# 3. Orphan close tag + any trailing whitespace.
_ORPHAN_CLOSE = re.compile(rf"</(?:{_NAMES})>[ \t\n\r]*", re.IGNORECASE)


def strip_reasoning(text: str | None) -> str:
    """Remove reasoning/thinking blocks from a complete assistant string.

    Returns the visible answer with reasoning removed and surrounding whitespace
    trimmed. Idempotent; safe on empty/None input.
    """
    if not text:
        return ""
    text = _CLOSED_PAIR.sub("", text)
    text = _OPEN_TO_END.sub("", text)
    text = _ORPHAN_CLOSE.sub("", text)
    return text.strip()
