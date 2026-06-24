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
from frappe.friday_core.llm.memory import project_for_session, recall_block
from frappe.friday_core.llm.project_context import project_snapshot_block
from frappe.friday_core.llm.references import expand_references
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

	# 1a. Project status snapshot (design 73, Slice 3) — when this turn happens
	# in a project room (a Raven channel linked to a Project, or a task:: session),
	# inject a fresh snapshot: which project it is (with the anti-bleed scoping
	# instruction), its status, the open tasks, and the deliverables. Resolved
	# from session_id, so no extra plumbing through the gateway is needed. Without
	# this the agent is blind to the room it's standing in — it asks "which
	# project?" and pulls in other clients' details.
	project = project_for_session(session_id)
	if project:
		snapshot = project_snapshot_block(project)
		if snapshot:
			messages.append({"role": "system", "content": snapshot})

	# 1b. Memory recall (design 59, Q2) — the profile's Active memories in a
	# fenced reference-only block, right after the system prompt. Same
	# placement pattern as the compaction summary: durable context the model
	# must know but never treat as instructions. Design 73 — scoped to the
	# project when in a project room (this project's memories + global ones,
	# never another project's).
	memories = recall_block(profile_name, project=project, query=inbound_content)
	if memories:
		messages.append({"role": "system", "content": memories})

	# 2. Conversation history (prior turns).
	history = _load_history(session_id, max_history_turns)
	messages.extend(history)

	# 3. Current user message — with any @-referenced records expanded and
	# appended (design 59, Q4/Q5; Hermes appends expansions to the user turn
	# so the context travels with the message).
	references = expand_references(inbound_content, profile_name)
	if references:
		inbound_content = f"{inbound_content}\n\n{references}"
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
	"""Assemble the system prompt from the operator's text and a minimal frame.

	The GOVERNANCE paragraph (design 66, Q3) is non-negotiable: it ends the
	"agent fabricates records when it has no read tool" failure mode the
	Legion validation transcript documented (L5142).

	After governance comes the ROLE PREAMBLE (design 68, Q3) — three to five
	lines that frame how the agent should approach work based on its role
	(Orchestrator / Specialist / Worker). The operator's system_prompt rides
	after the role preamble, verbatim, so per-profile voice composes with the
	role contract instead of conflicting.
	"""
	# Design 80 — date line (date-only, like Hermes system_prompt.py: the model
	# must know the current date) + tool-use guidance (Hermes SKILLS_GUIDANCE,
	# the "call each tool once, then stop" discipline applied to conversational
	# turns too, not only the task path).
	frame = (
		"You are a Friday AI Agent. "
		f"Today's date is {frappe.utils.today()}. "
		"Respond conversationally or use a tool when appropriate. "
		"Think step by step. "
		"When you use a tool, output only the tool call — do not describe it. "
		"Call each tool at most once unless its result tells you otherwise; once "
		"you have what you need, stop calling tools and write your final reply.\n\n"
		"GOVERNANCE: If you do not have a tool that can fetch the "
		"information someone is asking about, say so plainly. Never invent "
		"records, files, or data you did not retrieve through a tool call. "
		"Hallucination is a governance failure, not a creativity feature.\n\n"
	)
	role_preamble = _role_preamble(getattr(profile, "agent_role", None))
	operator_prompt = profile.system_prompt or ""
	return frame + role_preamble + operator_prompt


# Design 68 — role preambles. Short and operational: tells the agent how to
# frame its work, not what to think. Unknown/blank role falls back to
# Specialist (the gentlest frame, matches existing behaviour for pre-migration
# profiles).
_ROLE_PREAMBLES = {
	"Orchestrator": (
		"ORCHESTRATOR ROLE: Your job is to plan and coordinate. Break complex "
		"work into small tasks; use the delegate-task tool to assign each to "
		"the right Specialist or Worker profile by name. Run delegations in "
		"parallel when they do not depend on each other. Synthesise results "
		"once children report back. Prefer asking the human one clarifying "
		"question over guessing on scope.\n\n"
	),
	"Specialist": (
		"SPECIALIST ROLE: You are a domain expert. Go deep in your area; ask "
		"for help when a question falls outside it. Cite the records and files "
		"you used.\n\n"
	),
	"Worker": (
		"WORKER ROLE: Execute one task precisely. Do not expand scope. If the "
		"request is ambiguous, ask one clarifying question; otherwise complete "
		"and report.\n\n"
	),
}


def _role_preamble(role: str | None) -> str:
	return _ROLE_PREAMBLES.get(role or "Specialist", _ROLE_PREAMBLES["Specialist"])


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
