# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt

"""
Strip model reasoning/"thinking" blocks (and inline tool-call XML) from text.

**Verbatim port** of Hermes `agent/agent_runtime_helpers.py::strip_think_blocks`
(the impl behind `run_agent._strip_think_blocks`). The regexes below are copied
1:1 from Hermes — same variants, same order, same boundary gating.

DIVERGENCES FROM HERMES (all disclosed, none silent):
  - Standalone function `strip_reasoning(text)` instead of the
    `strip_think_blocks(agent, content)` *method* — the `agent` arg is unused in
    Hermes' body, so dropping it is a clean adaptation. Friday's loop is
    non-streaming, so the separate `StreamingThinkScrubber` state machine is
    correctly NOT ported (it only matters when emitting tokens live).
  - A final `.strip()`: Hermes returns unstripped and strips at the *call site*
    (`self._strip_think_blocks(content).strip()`). Friday's runner uses the
    output directly as the reply, so that call-site strip is folded in here.

PLAIN ENGLISH
=============
Reasoning models (MiniMax-M2, etc.) wrap chain-of-thought in `<think>...</think>`
and friends; some open models also dump tool calls as inline XML
(`<tool_call>...`, `<function name="...">...`) instead of via the structured
field. None of that should reach the user or be fed back into context. Cases:

  1. Closed pairs `<tag>...</tag>` — per variant (NOT a combined alternation, so
     a *mismatched* `<think>...</thinking>` is left to the orphan pass, which
     keeps the inner text).
  1b. Inline tool-call XML blocks.
  1c. `<function name="...">...</function>` — boundary-gated.
  2. Unterminated open tag at a line boundary → stripped to end of string.
  3. Orphan open/close tags (`<think>` or `</think>`) + trailing whitespace.
  3b. Stray tool-call closers.
"""

from __future__ import annotations

import re

_DOTALL_I = re.DOTALL | re.IGNORECASE


def strip_reasoning(text: str | None) -> str:
    """Remove reasoning blocks + inline tool-call XML from a complete string."""
    if not text:
        return ""
    content = text

    # 1. Closed tag pairs — per variant, case-insensitive.
    content = re.sub(r"<think>.*?</think>", "", content, flags=_DOTALL_I)
    content = re.sub(r"<thinking>.*?</thinking>", "", content, flags=_DOTALL_I)
    content = re.sub(r"<reasoning>.*?</reasoning>", "", content, flags=_DOTALL_I)
    content = re.sub(r"<REASONING_SCRATCHPAD>.*?</REASONING_SCRATCHPAD>", "", content, flags=_DOTALL_I)
    content = re.sub(r"<thought>.*?</thought>", "", content, flags=_DOTALL_I)

    # 1b. Inline tool-call XML blocks (generic names, no boundary gating).
    for _tc in ("tool_call", "tool_calls", "tool_result", "function_call", "function_calls"):
        content = re.sub(rf"<{_tc}\b[^>]*>.*?</{_tc}>", "", content, flags=_DOTALL_I)

    # 1c. <function name="...">...</function> — boundary-gated (start, newline,
    #     or sentence-ending punctuation) AND carrying a name="..." attribute.
    content = re.sub(
        r"(?:(?<=^)|(?<=[\n\r.!?:]))[ \t]*"
        r"<function\b[^>]*\bname\s*=[^>]*>"
        r"(?:(?:(?!</function>).)*)</function>",
        "",
        content,
        flags=_DOTALL_I,
    )

    # 2. Unterminated reasoning block — open tag at a block boundary, no close.
    content = re.sub(
        r"(?:^|\n)[ \t]*<(?:think|thinking|reasoning|thought|REASONING_SCRATCHPAD)\b[^>]*>.*$",
        "",
        content,
        flags=_DOTALL_I,
    )

    # 3. Stray orphan open/close tags.
    content = re.sub(
        r"</?(?:think|thinking|reasoning|thought|REASONING_SCRATCHPAD)>\s*",
        "",
        content,
        flags=re.IGNORECASE,
    )

    # 3b. Stray tool-call closers (we do NOT strip bare/unterminated <function>,
    #     matching Hermes' intentional asymmetry).
    content = re.sub(
        r"</(?:tool_call|tool_calls|tool_result|function_call|function_calls|function)>\s*",
        "",
        content,
        flags=re.IGNORECASE,
    )

    return content.strip()
