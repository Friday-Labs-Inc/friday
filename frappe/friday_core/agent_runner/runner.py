# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt

"""
The agent runner — the ReAct loop that produces a reply for one chat turn.

PLAIN ENGLISH
=============

Given an Agent Profile, a session ID, and the user's message, this function
returns the agent's reply text. It runs a **ReAct loop**: call the model, and
while the model keeps asking for tools, dispatch them, feed the results back,
and let the model observe and decide its next step — up to
MAX_REACT_ITERATIONS (15) cycles. The turn ends when:

  - the model returns a plain-text answer (no tool calls), or
  - a tool call is **denied** by the permission engine (a governance signal —
    we surface it, we don't let the model route around it), or
  - the iteration budget is exhausted.

The prompt the loop starts from is:
  - the agent's system prompt + conversation history (built by prompt_builder),
  - the list of permitted tools (loaded by the skill loader).

WHAT THIS MODULE DOES NOT DO
============================

- Does not write Chat Message rows. The gateway does that — **one inbound +
  one outbound row per turn**, regardless of how many loop iterations run.
- Does not check permissions itself. The dispatcher calls
  `permissions.matrix.check` before executing any skill; a *denial* breaks
  this loop (doc 48 §1 A.4).
- Does not run skills in a sandbox. That's the dispatcher's sandbox wrapper.
- Does not stream tokens. Deferred until a real-time surface needs it.

REFERENCED DESIGN
=================
- `docs/design/48-hermes-port-decisions.md` §1 — Feature A, the locked ReAct
  loop contract (decisions A.1–A.6).
"""

from __future__ import annotations

import hashlib
import json

import frappe

from frappe.friday_core.agent_runner.dispatcher import DispatchResult, dispatch
from frappe.friday_core.llm import get_provider_for_profile
from frappe.friday_core.llm.compression import maybe_compress_session
from frappe.friday_core.llm.prompt_builder import build
from frappe.friday_core.skills.loader import load_for_profile

# A.1 — the loop is capped at 15 think/act cycles per turn. A module constant
# (not a per-profile field for v0.1, to avoid premature config surface) so
# tests can patch it.
MAX_REACT_ITERATIONS = 15

# A.2 — what the user sees when the loop runs out of budget.
_BUDGET_EXHAUSTED_SUFFIX = "\n\n[loop budget exhausted after {n} iterations]"
_EMPTY_REPLY_FALLBACK = "I'm unable to complete this in the time allotted."


def run_turn(profile_name: str, session_id: str, inbound_content: str) -> str:
	"""Produce one agent reply for one user message via the ReAct loop.

	Arguments:
	  - `profile_name`: the Agent Profile name (Frappe primary key).
	  - `session_id`: the conversation's session UUID.
	  - `inbound_content`: the user's message text.

	Returns the reply text the gateway writes to the single outbound Chat
	Message row for this turn.

	The loop (doc 48 §1):
	  1. Call the LLM with the running conversation.
	  2. No tool calls → that's the final answer; return it.
	  3. Tool calls → dispatch each in order; feed every result back as a
	     `{role:"tool", ...}` message; then re-prompt so the model observes
	     the results and decides the next step.
	  4. A permission *denial* breaks the loop and is surfaced to the user.
	  5. After MAX_REACT_ITERATIONS without a plain-text reply, return the last
	     assistant text with a budget-exhausted suffix.

	Tool problems never raise here — a tool *error* is fed back to the model so
	it can adapt (A.3). LLM transport errors propagate to the gateway, which is
	the last error catcher.
	"""
	skill_definitions = load_for_profile(profile_name)

	# Feature C: fold old turns into a summary if this session has grown large,
	# BEFORE assembling the prompt — build() then sees the summary + the
	# shortened (uncompacted) tail. Best-effort: a compression failure must
	# never break the turn, so we log and continue with the full prompt.
	try:
		maybe_compress_session(profile_name, session_id)
	except Exception as exc:  # noqa: BLE001 — compression must never break a turn
		frappe.logger("friday.compression").warning(
			f"Compression pass errored for session {session_id!r}: "
			f"{type(exc).__name__}; continuing with the full prompt."
		)

	prompt = build(
		profile_name=profile_name,
		session_id=session_id,
		inbound_content=inbound_content,
		tools=skill_definitions,
	)
	provider = get_provider_for_profile(profile_name)

	# A working copy of the conversation that the loop appends to.
	messages: list[dict] = list(prompt["messages"])
	tools = prompt["tools"]
	model = prompt["model"]

	last_assistant_content = ""

	for _iteration in range(MAX_REACT_ITERATIONS):
		response = provider.chat(messages=messages, tools=tools, model=model)
		content = response.get("content") or ""
		tool_calls = response.get("tool_calls")
		tokens_used = (response.get("usage") or {}).get("total_tokens", 0)

		if not tool_calls:
			# Plain-text reply — the agent is done.
			return content

		# D (doc 51 §4.D) — drop duplicate (name, arguments) calls in this
		# response, then give every call a stable id (deterministic when the
		# provider omitted one) so the wire's assistant<->tool links hold and
		# identical calls don't churn ids across re-serialisation.
		tool_calls = _deduplicate_tool_calls(tool_calls)
		for _index, _call in enumerate(tool_calls):
			if not _call.get("id"):
				_call["id"] = _deterministic_call_id(
					_call.get("name", ""), _call.get("arguments", ""), _index
				)

		last_assistant_content = content
		# Put the assistant's turn (with its tool calls) back into the
		# conversation so the next call shows the model what it asked for.
		messages.append(_assistant_message(content, tool_calls))

		for tool_call in tool_calls:  # sequential, in order (A.6)
			result = dispatch(
				tool_call=tool_call,
				agent_profile=profile_name,
				session_id=session_id,
				tokens_used=tokens_used,
			)
			if _is_permission_denial(result):
				# A.4 — the operator said NO. Break the loop and surface it;
				# letting the model silently route around it is a governance hole.
				return result.content

			# A.3 — feed the tool result (success or error) back verbatim so
			# the model can observe it and adapt. The loop then continues.
			messages.append(
				{
					"role": "tool",
					"tool_call_id": result.tool_call_id or tool_call.get("id", ""),
					"content": result.content,
				}
			)
		# Loop continues: re-prompt so the model observes the tool results.

	# A.2 — hit the iteration cap without a clean plain-text reply.
	final = last_assistant_content or _EMPTY_REPLY_FALLBACK
	return final + _BUDGET_EXHAUSTED_SUFFIX.format(n=MAX_REACT_ITERATIONS)


def _assistant_message(content: str, tool_calls: list[dict]) -> dict:
	"""Rebuild the assistant turn in OpenAI wire shape for re-sending.

	The provider hands tool calls to the runner in Friday's flat canonical form
	(`{id, name, arguments}`, which the dispatcher consumes). To put that turn
	*back* into the conversation for the next API call, expand it to the OpenAI
	`{id, type:"function", function:{name, arguments}}` shape. `arguments` must
	be a JSON string on the wire.
	"""
	wire_calls = []
	for tc in tool_calls:
		args = tc.get("arguments", "{}")
		if not isinstance(args, str):
			args = json.dumps(args)
		wire_calls.append(
			{
				"id": tc.get("id", ""),
				"type": "function",
				"function": {"name": tc.get("name", ""), "arguments": args},
			}
		)
	return {"role": "assistant", "content": content or "", "tool_calls": wire_calls}


def _is_permission_denial(result: DispatchResult) -> bool:
	"""True only when a dispatch failed *because the operator denied it* (A.4).

	A denial is `success == False` AND the linked Execution Log row is
	`status == "rejected"`. A plain tool *error* (status "error") is NOT a
	denial — it gets fed back to the model instead of breaking the loop.
	Keeping this distinction in one helper keeps the loop readable.
	"""
	if result.success or not result.execution_log_name:
		return False
	status = frappe.db.get_value("Execution Log", result.execution_log_name, "status")
	return status == "rejected"


def _deduplicate_tool_calls(tool_calls: list[dict]) -> list[dict]:
	"""D.1 — drop tool calls whose (name, arguments) match an earlier call in the
	SAME response; keep the first. Ported from Hermes `_deduplicate_tool_calls`.
	Logs each drop so a model that repeats itself is visible. Within-response
	only (D.3) — cross-turn idempotency is explicitly deferred.
	"""
	seen: set[tuple[str, str]] = set()
	deduped: list[dict] = []
	for tc in tool_calls:
		key = (tc.get("name", ""), _arguments_key(tc.get("arguments", "")))
		if key in seen:
			frappe.logger("friday.agent_runner.runner").info(
				f"dropped duplicate tool call {tc.get('name', '')!r} "
				f"(identical name+arguments repeated in one response)"
			)
			continue
		seen.add(key)
		deduped.append(tc)
	return deduped


def _deterministic_call_id(name: str, arguments, index: int) -> str:
	"""D.2 — a stable id for a tool call the provider left id-less, derived from
	(name, arguments, index). Ported from Hermes `_deterministic_call_id`.
	Identical content yields an identical id (so re-serialising the same
	conversation doesn't churn ids and bust prompt caching); the index keeps two
	*different* calls in one response distinct.
	"""
	digest = hashlib.sha1(
		f"{name}:{_arguments_key(arguments)}:{index}".encode("utf-8")
	).hexdigest()[:12]
	return f"call_{digest}"


def _arguments_key(arguments) -> str:
	"""Normalise a tool call's arguments to a stable string for comparison and
	hashing. Arguments arrive as a JSON string (OpenAI-shaped providers) or a
	dict; either way the same content yields the same key (sorted keys), so
	dedup and the deterministic id are independent of key order.
	"""
	if isinstance(arguments, str):
		try:
			arguments = json.loads(arguments)
		except (json.JSONDecodeError, TypeError):
			return arguments  # not JSON — compare/hash verbatim
	try:
		return json.dumps(arguments, sort_keys=True, separators=(",", ":"))
	except (TypeError, ValueError):
		return str(arguments)
