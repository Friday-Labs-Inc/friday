# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt

"""
Surrogate-character sanitization for messages before they hit a model API.

**Verbatim port** of Hermes `agent/message_sanitization.py`:
`_sanitize_surrogates`, `_sanitize_structure_surrogates`, and
`_sanitize_messages_surrogates`. Logic copied 1:1; the only divergences are the
public names (Hermes' are `_`-prefixed module-privates) and living in their own
module instead of the big `message_sanitization.py`.

PLAIN ENGLISH
=============
A "lone surrogate" is an invalid Unicode character (range U+D800–U+DFFF). They
sneak in from rich-text clipboard pastes (Google Docs, Word) and from byte-level
reasoning models — and they **crash `json.dumps()` inside the model SDK**, which
kills the whole turn. This replaces each one with the standard replacement
character (U+FFFD) so the turn survives. Fast no-op when there are none.
"""

from __future__ import annotations

import re
from typing import Any

_SURROGATE_RE = re.compile(r"[\ud800-\udfff]")


def sanitize_surrogates(text: str) -> str:
    """Replace lone surrogate code points with U+FFFD. No-op if there are none."""
    if _SURROGATE_RE.search(text):
        return _SURROGATE_RE.sub("�", text)
    return text


def _sanitize_structure_surrogates(payload: Any) -> bool:
    """Replace surrogates in nested dict/list payloads in-place. Returns True if any."""
    found = False

    def _walk(node):
        nonlocal found
        if isinstance(node, dict):
            for key, value in node.items():
                if isinstance(value, str):
                    if _SURROGATE_RE.search(value):
                        node[key] = _SURROGATE_RE.sub("�", value)
                        found = True
                elif isinstance(value, (dict, list)):
                    _walk(value)
        elif isinstance(node, list):
            for idx, value in enumerate(node):
                if isinstance(value, str):
                    if _SURROGATE_RE.search(value):
                        node[idx] = _SURROGATE_RE.sub("�", value)
                        found = True
                elif isinstance(value, (dict, list)):
                    _walk(value)

    _walk(payload)
    return found


def sanitize_messages_surrogates(messages: list) -> bool:
    """Sanitize surrogates from all string content in a messages list, in-place.

    Covers content/text, name, tool-call id + function name/arguments, and any
    other string/nested fields (so a retry doesn't fail on a non-content field).
    Returns True if any surrogates were replaced.
    """
    found = False
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        content = msg.get("content")
        if isinstance(content, str) and _SURROGATE_RE.search(content):
            msg["content"] = _SURROGATE_RE.sub("�", content)
            found = True
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict):
                    text = part.get("text")
                    if isinstance(text, str) and _SURROGATE_RE.search(text):
                        part["text"] = _SURROGATE_RE.sub("�", text)
                        found = True
        name = msg.get("name")
        if isinstance(name, str) and _SURROGATE_RE.search(name):
            msg["name"] = _SURROGATE_RE.sub("�", name)
            found = True
        tool_calls = msg.get("tool_calls")
        if isinstance(tool_calls, list):
            for tc in tool_calls:
                if not isinstance(tc, dict):
                    continue
                tc_id = tc.get("id")
                if isinstance(tc_id, str) and _SURROGATE_RE.search(tc_id):
                    tc["id"] = _SURROGATE_RE.sub("�", tc_id)
                    found = True
                fn = tc.get("function")
                if isinstance(fn, dict):
                    fn_name = fn.get("name")
                    if isinstance(fn_name, str) and _SURROGATE_RE.search(fn_name):
                        fn["name"] = _SURROGATE_RE.sub("�", fn_name)
                        found = True
                    fn_args = fn.get("arguments")
                    if isinstance(fn_args, str) and _SURROGATE_RE.search(fn_args):
                        fn["arguments"] = _SURROGATE_RE.sub("�", fn_args)
                        found = True
        # Any additional string / nested fields (reasoning, reasoning_content,
        # reasoning_details, …) — surrogates from byte-level reasoning models
        # can lurk there and aren't covered by the per-field checks above.
        for key, value in msg.items():
            if key in {"content", "name", "tool_calls", "role"}:
                continue
            if isinstance(value, str):
                if _SURROGATE_RE.search(value):
                    msg[key] = _SURROGATE_RE.sub("�", value)
                    found = True
            elif isinstance(value, (dict, list)):
                if _sanitize_structure_surrogates(value):
                    found = True
    return found
