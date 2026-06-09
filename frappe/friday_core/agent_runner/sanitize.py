# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt

"""
Repair malformed tool-call argument JSON before the dispatcher parses it.

Ported from Hermes `agent/message_sanitization.py` `_repair_tool_call_arguments`.

PLAIN ENGLISH
=============
Models don't always emit clean JSON for a tool call's arguments — you get
trailing commas, unclosed braces, literal control characters, a Python `None`,
or truncation. Without repair, the dispatcher rejects the whole call and the
*action fails* (the agent wanted to create a note, but a stray comma killed it).

This applies the same cheap, ordered repairs Hermes uses and returns **valid
JSON every time** (worst case `"{}"`, so the skill's own validation — e.g.
"title is required" — handles it, instead of a raw parse error). Repairs are
visible in the Execution Log because the dispatcher records the parameters it
actually ran with.

Pure function — no Frappe, no I/O — so it unit-tests anywhere.
"""

from __future__ import annotations

import json
import re

_TRAILING_COMMA = re.compile(r",\s*([}\]])")


def _close_structures(text: str) -> str:
    """Append closers for any unclosed `{`/`[`, in correct reverse order.

    String-aware: braces/brackets inside JSON string values are ignored, so
    `{"a": "b{c"` isn't miscounted. Improves on Hermes' flat count (which
    mis-orders nested unclosed structures).
    """
    stack: list[str] = []
    in_string = False
    escaped = False
    for ch in text:
        if escaped:
            escaped = False
            continue
        if in_string:
            if ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch in "{[":
            stack.append(ch)
        elif ch == "}" and stack and stack[-1] == "{":
            stack.pop()
        elif ch == "]" and stack and stack[-1] == "[":
            stack.pop()
    return text + "".join("}" if c == "{" else "]" for c in reversed(stack))


def repair_tool_arguments(raw_args: str, tool_name: str = "?") -> str:
    """Return wire-valid JSON for a tool call's arguments, repairing if needed.

    Always returns parseable JSON. Falls back to `"{}"` only when nothing else
    works (better than crashing the turn).
    """
    raw = raw_args.strip() if isinstance(raw_args, str) else ""

    # Empty / Python-None → empty object.
    if not raw or raw == "None":
        return "{}"

    # Pass 1 — lenient parse (accepts literal control chars) then re-serialise.
    # This is the most common local-model malformation and needs no surgery.
    try:
        return json.dumps(json.loads(raw, strict=False), separators=(",", ":"))
    except (json.JSONDecodeError, TypeError, ValueError):
        pass

    # Pass 2 — structural repairs: strip trailing commas, close unclosed
    # braces/brackets in the correct (reverse) order, then trim any excess
    # closers (bounded).
    fixed = _close_structures(_TRAILING_COMMA.sub(r"\1", raw))
    for _ in range(50):
        try:
            json.loads(fixed)
            return fixed
        except json.JSONDecodeError:
            if fixed.endswith("}") and fixed.count("}") > fixed.count("{"):
                fixed = fixed[:-1]
            elif fixed.endswith("]") and fixed.count("]") > fixed.count("["):
                fixed = fixed[:-1]
            else:
                break

    # Last resort — empty object so the turn survives.
    return "{}"
