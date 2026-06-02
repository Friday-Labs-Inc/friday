# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt

"""
The prompt builder — assembling the full LLM prompt from Frappe state.

PLAIN ENGLISH
=============

Before the LLM can answer, it needs a properly formatted prompt. This
module builds that prompt from three ingredients:

  1. **System prompt** — static instructions from `Agent Profile.system_prompt`.
     Set by the operator in Desk; the LLM treats it as foundational context.
  2. **Conversation history** — prior turns in this session (Chat Message
     rows, oldest first). The LLM uses this for continuity.
  3. **Tool definitions** — what tools the agent is permitted to use, from
     the Slice 3 skill loader. Passed as the `tools` parameter so the LLM
     can decide to call a tool or respond in text.

The output of `build()` is a dict ready to hand to `provider.chat()`:

    {
        "messages": [...],   # list of {role, content}
        "tools": [...],       # OpenAI-format tool defs or None
        "model": "MiniMax-Standard",
    }

IMPORTANT: `build()` is a pure function. It reads from the database
(history) but produces the same output for the same inputs. This makes
it easy to test: given fixed database state, the output is deterministic.

CONVERSATION HISTORY
====================

We load the last `max_history_turns` Chat Message rows for the session:

  - Inbound (user → agent): role="user"
  - Outbound (agent → user): role="assistant"

We stop after `max_history_turns` even if more history exists.
This is a conservative truncation — the LLM still has full context for
recent conversation.

When a session has grown large, the compression pass (Feature C,
`llm/compression.py`) folds the OLD middle turns into a `Compaction Summary`
and flags those Chat Messages `compacted = 1`. This builder then loads only
the **uncompacted** tail and leads it with the latest summary (carrying the
reference-only preamble), so the model gets the background without the full
transcript.

SYSTEM PROMPT ASSEMBLY
=====================

`Agent Profile.system_prompt` is stored as operator-authored text.
We wrap it with minimal framing:

    You are a Friday AI Agent. ...
    <operator's system_prompt>
    (no extra framing beyond this)

The operator controls the content; we don't inject Friday-internal
details into it. This keeps the system prompt human-readable and
editable without understanding the framework internals.

WHAT THIS MODULE DOES NOT DO
=============================

- Does not call the LLM. The caller does that.
- Does not write Chat Message rows. The caller does that.
- Does not decide which skills are permitted. That comes already-filtered
  from `load_for_profile()` in the runner.

SEE ALSO
========
- `docs/contributing/proposals/slice-5-llm-integration.md` §2.2
- `frappe/friday_core/skills/loader.py` — `load_for_profile()`
"""

from __future__ import annotations

from typing import Any

import frappe

from frappe.friday_core.llm.compression import SUMMARY_PREFIX, latest_summary
from frappe.friday_core.skills.loader import (
    SkillDefinition,
    to_tool_definition,
)


def build(
    profile_name: str,
    session_id: str,
    inbound_content: str,
    tools: list[SkillDefinition] | None = None,
    max_history_turns: int = 10,
) -> dict:
    """Build the full LLM prompt for one conversation turn.

    Arguments:
      - `profile_name` — the Agent Profile name (primary key in Frappe).
      - `session_id` — the conversation session UUID.
      - `inbound_content` — the current user message text.
      - `tools` — already-loaded and filtered SkillDefinitions from the
        runner. Pass `None` if the agent has no permitted skills.
      - `max_history_turns` — maximum number of prior turns to include.
        Defaults to 10. Set to 0 to disable history.

    Returns a dict with three keys:
      - `messages`: `list[dict]` — the full prompt in OpenAI format.
      - `tools`: `list[dict] | None` — OpenAI-format tool definitions.
      - `model`: `str` — the model to use (from Agent Profile or settings).

    Raises `frappe.DoesNotExistError` if the profile does not exist.
    """
    profile = frappe.get_doc("Agent Profile", profile_name)
    messages: list[dict[str, str]] = []

    # 1. System message — operator-authored prompt with minimal framing.
    system_text = _build_system_prompt(profile)
    messages.append({"role": "system", "content": system_text})

    # 2. Conversation history (prior turns).
    history = _load_history(session_id, max_history_turns)
    messages.extend(history)

    # 3. Current user message.
    messages.append({"role": "user", "content": inbound_content})

    # 4. Tool definitions — from the already-loaded skill list.
    tool_defs = [to_tool_definition(t) for t in tools] if tools else None

    # 5. Model — profile override, or fall back to provider default.
    model = profile.model_name or None  # None means "use provider default"

    return {
        "messages": messages,
        "tools": tool_defs,
        "model": model,
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_system_prompt(profile) -> str:
    """Assemble the system prompt from the operator's text and a minimal frame."""
    # Minimal frame. The operator's system_prompt comes after this, verbatim.
    frame = (
        "You are a Friday AI Agent. "
        "Respond conversationally or use a tool when appropriate. "
        "Think step by step. "
        "When you use a tool, output only the tool call — do not describe it.\n\n"
    )
    operator_prompt = profile.system_prompt or ""
    return frame + operator_prompt


def _load_history(session_id: str, max_history_turns: int) -> list[dict[str, str]]:
    """Load conversation context for a session: [summary?] + uncompacted tail.

    Returns a flat list of messages in chronological order, ready to append
    after the system prompt. If earlier turns were compacted (Feature C), the
    list leads with a reference-only `system` message carrying the latest
    summary; the summary covers everything before the uncompacted tail, so the
    ordering [summary] → [recent turns] stays chronological.

    Single DB round-trip via `fields=` on get_all (no per-row get_doc).
    """
    if max_history_turns <= 0:
        return []

    messages: list[dict[str, str]] = []

    # Lead with the latest compaction summary, if any (Feature C). It stands in
    # for the compacted middle turns the query below deliberately skips.
    summary = latest_summary(session_id)
    if summary:
        messages.append({"role": "system", "content": f"{SUMMARY_PREFIX}\n{summary}"})

    # Only the UNCOMPACTED tail is loaded verbatim — compacted rows are
    # represented by the summary above.
    rows = frappe.get_all(
        "Chat Message",
        filters={
            "session_id": session_id,
            "direction": ("in", ["inbound", "outbound"]),
            "compacted": 0,
        },
        fields=["direction", "content"],
        order_by="creation asc",
        limit=max_history_turns * 2,  # ×2 because each turn has 2 rows
    )

    for row in rows:
        direction = row.get("direction")
        if direction == "inbound":
            role = "user"
        elif direction == "outbound":
            role = "assistant"
        else:
            continue
        content = row.get("content") or ""
        if content:
            messages.append({"role": role, "content": content})

    return messages
