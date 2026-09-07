# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""
Unit tests for the durable turn journal (Design 93, slice 1).

Mock-based — no DB. Two layers:

1. `rebuild()` — the PURE replay function. Given a list of journal events,
   it must reconstruct the ReAct loop's in-memory state exactly: the
   `messages` buffer, iterations already consumed, tool calls still owed a
   result, and (when the crash happened after the model's final answer) the
   finished reply itself.

2. `run_turn` with a journal — patched like test_react_loop.py (loader,
   builder, provider, dispatch all stubbed) plus a fake in-memory
   TurnJournal, pinning the resume contract:

   - a journaled `turn.completed` short-circuits: NO LLM call, NO dispatch
   - a partial journal resumes: only the missing tool call is dispatched,
     already-journaled LLM calls are never re-paid
   - a fresh turn journals started → llm.response → completed
   - `turn_id=None` (self-review, evals) journals nothing — zero change

The DB-backed pieces (Turn Event doctype writes, gateway delivered
short-circuit) are integration-tested on a bench.
"""

import unittest
from unittest.mock import MagicMock, patch

from friday.friday_core.agent_runner.dispatcher import DispatchResult
from friday.friday_core.agent_runner.journal import (
	EVENT_LLM_RESPONSE,
	EVENT_REPLY_DELIVERED,
	EVENT_STEER_INJECTED,
	EVENT_TOOL_RESULT,
	EVENT_TURN_COMPLETED,
	EVENT_TURN_STARTED,
	rebuild,
)

_R = "friday.friday_core.agent_runner.runner"

_PROFILE = "test-profile"
_BASE_MESSAGES = [{"role": "user", "content": "hi"}]


def _ev(event_type, **payload):
	return {"event_type": event_type, "payload": payload}


def _started(messages=None, model="m", profile=_PROFILE):
	return _ev(
		EVENT_TURN_STARTED,
		messages=messages if messages is not None else list(_BASE_MESSAGES),
		model=model,
		agent_profile=profile,
	)


def _llm(content="", tool_calls=None, total_tokens=7):
	return _ev(EVENT_LLM_RESPONSE, content=content, tool_calls=tool_calls, total_tokens=total_tokens)


def _tool(call_id, content="Done."):
	return _ev(EVENT_TOOL_RESULT, tool_call_id=call_id, content=content)


def _tc(call_id, name="slice6-create-note", arguments='{"title": "x"}'):
	return {"id": call_id, "name": name, "arguments": arguments}


def _inject_steer_stub(messages, text):
	messages.append({"role": "user", "content": f"User guidance: {text}"})


class TestRebuild(unittest.TestCase):
	"""The pure replay function."""

	def test_no_events_returns_none(self):
		self.assertIsNone(rebuild([], _PROFILE, _inject_steer_stub))

	def test_no_started_event_returns_none(self):
		events = [_llm(content="orphan")]
		self.assertIsNone(rebuild(events, _PROFILE, _inject_steer_stub))

	def test_profile_mismatch_returns_none(self):
		events = [_started(profile="someone-else")]
		self.assertIsNone(rebuild(events, _PROFILE, _inject_steer_stub))

	def test_base_prompt_restored(self):
		state = rebuild([_started()], _PROFILE, _inject_steer_stub)
		self.assertEqual(state.messages, _BASE_MESSAGES)
		self.assertEqual(state.model, "m")
		self.assertEqual(state.iterations_used, 0)
		self.assertEqual(state.pending_tool_calls, [])
		self.assertIsNone(state.final_reply)

	def test_llm_response_with_tools_and_partial_results(self):
		"""Crash after tool 1 of 2 — replay owes exactly the second call."""
		calls = [_tc("c1"), _tc("c2", arguments='{"title": "y"}')]
		events = [_started(), _llm(content="working", tool_calls=calls), _tool("c1")]
		state = rebuild(events, _PROFILE, _inject_steer_stub)

		self.assertEqual(state.iterations_used, 1)
		self.assertEqual([c["id"] for c in state.pending_tool_calls], ["c2"])
		# messages = base + assistant(tool_calls) + one tool result
		self.assertEqual(len(state.messages), 3)
		self.assertEqual(state.messages[1]["role"], "assistant")
		self.assertEqual(len(state.messages[1]["tool_calls"]), 2)
		self.assertEqual(state.messages[2]["role"], "tool")
		self.assertEqual(state.messages[2]["tool_call_id"], "c1")
		self.assertEqual(state.tokens_used, 7)

	def test_all_tool_results_present_means_no_pending(self):
		calls = [_tc("c1")]
		events = [_started(), _llm(tool_calls=calls), _tool("c1")]
		state = rebuild(events, _PROFILE, _inject_steer_stub)
		self.assertEqual(state.pending_tool_calls, [])
		self.assertEqual(state.iterations_used, 1)

	def test_empty_llm_response_consumes_iteration_only(self):
		events = [_started(), _llm(content="", tool_calls=None)]
		state = rebuild(events, _PROFILE, _inject_steer_stub)
		self.assertEqual(state.iterations_used, 1)
		self.assertEqual(state.messages, _BASE_MESSAGES)
		self.assertIsNone(state.final_reply)

	def test_plain_content_response_is_the_final_reply(self):
		"""Crash between the model's final answer and turn.completed."""
		events = [_started(), _llm(content="the answer", tool_calls=None)]
		state = rebuild(events, _PROFILE, _inject_steer_stub)
		self.assertEqual(state.final_reply, "the answer")

	def test_steer_event_is_replayed(self):
		events = [_started(), _ev(EVENT_STEER_INJECTED, text="go left")]
		state = rebuild(events, _PROFILE, _inject_steer_stub)
		self.assertEqual(state.messages[-1]["content"], "User guidance: go left")

	def test_compress_restart_uses_last_started_as_base(self):
		"""A mid-turn compression writes a second turn.started — replay must
		base on the LAST one and ignore everything before it."""
		fresh = [{"role": "user", "content": "compressed"}]
		events = [
			_started(),
			_llm(tool_calls=[_tc("c1")]),
			_tool("c1"),
			_started(messages=fresh),
		]
		state = rebuild(events, _PROFILE, _inject_steer_stub)
		self.assertEqual(state.messages, fresh)
		self.assertEqual(state.iterations_used, 0)
		self.assertEqual(state.pending_tool_calls, [])


class _FakeJournal:
	"""In-memory TurnJournal stand-in. Class-level store so the patched
	classmethod `open` can hand the test a pre-seeded instance."""

	preloaded: list = []
	instances: list = []

	def __init__(self, turn_id, session_id, agent_profile):
		self.turn_id = turn_id
		self.session_id = session_id
		self.agent_profile = agent_profile
		self.events = list(self.__class__.preloaded)
		self.recorded = []
		self.__class__.instances.append(self)

	@classmethod
	def open(cls, turn_id, session_id, agent_profile):
		return cls(turn_id, session_id, agent_profile)

	def record(self, event_type, payload):
		self.recorded.append((event_type, payload))
		self.events.append({"event_type": event_type, "payload": payload})

	def completed_reply(self):
		for ev in self.events:
			if ev["event_type"] == EVENT_TURN_COMPLETED:
				return ev["payload"].get("reply")
		return None

	def is_delivered(self):
		return any(ev["event_type"] == EVENT_REPLY_DELIVERED for ev in self.events)

	def rebuild(self, profile_name, inject_steer):
		return rebuild(self.events, profile_name, inject_steer)


def _resp(content="", tool_calls=None):
	return {
		"content": content,
		"finish_reason": "tool_calls" if tool_calls else "stop",
		"usage": {"total_tokens": 7},
		"tool_calls": tool_calls,
	}


def _ok(content="Done.", call_id="c1"):
	return DispatchResult(
		success=True, content=content, execution_log_name="EL-1", tool_call_name="s", tool_call_id=call_id
	)


def _provider(*responses):
	p = MagicMock()
	if len(responses) == 1:
		p.chat.return_value = responses[0]
	else:
		p.chat.side_effect = list(responses)
	return p


def _run(provider, dispatch_results=None, preloaded=None, turn_id="CM-0001"):
	"""run_turn with all externals patched + the fake journal installed."""
	from friday.friday_core.agent_runner.runner import run_turn

	_FakeJournal.preloaded = list(preloaded or [])
	_FakeJournal.instances = []
	prompt = {"messages": list(_BASE_MESSAGES), "tools": [], "model": "m"}
	with (
		patch(f"{_R}.maybe_compress_session"),
		patch(f"{_R}.load_for_profile", return_value=[]),
		patch(f"{_R}.build", return_value=prompt),
		patch(f"{_R}.get_provider_for_profile", return_value=provider),
		patch(f"{_R}.dispatch", side_effect=list(dispatch_results or [])) as md,
		patch(f"{_R}._is_permission_denial", return_value=False),
		patch(f"{_R}.record_usage"),
		patch(f"{_R}.clear_interrupt"),
		patch(f"{_R}.clear_steer"),
		patch(f"{_R}.is_interrupt_requested", return_value=False),
		patch(f"{_R}.drain_steer", return_value=None),
		patch(f"{_R}.TurnJournal", _FakeJournal),
	):
		result = run_turn(_PROFILE, "sess-1", "hi", turn_id=turn_id)
	journal = _FakeJournal.instances[0] if _FakeJournal.instances else None
	return result, md, provider, journal


class TestRunTurnResume(unittest.TestCase):
	"""run_turn's journal integration."""

	def test_completed_turn_short_circuits(self):
		"""A journaled turn.completed returns the reply with NO model call and
		NO dispatch — the whole point of the journal."""
		provider = _provider(_resp(content="should not be called"))
		preloaded = [_started(), _ev(EVENT_TURN_COMPLETED, reply="already done")]
		result, md, provider, _ = _run(provider, preloaded=preloaded)

		self.assertEqual(result, "already done")
		provider.chat.assert_not_called()
		md.assert_not_called()

	def test_resume_dispatches_only_the_missing_tool_call(self):
		"""Crash after tool c1 of [c1, c2]: resume must dispatch ONLY c2, then
		let the model conclude. The journaled LLM call is never re-paid."""
		calls = [_tc("c1"), _tc("c2", arguments='{"title": "y"}')]
		preloaded = [_started(), _llm(content="working", tool_calls=calls), _tool("c1")]
		provider = _provider(_resp(content="final answer"))
		result, md, provider, journal = _run(
			provider, dispatch_results=[_ok(call_id="c2")], preloaded=preloaded
		)

		self.assertEqual(result, "final answer")
		# exactly ONE dispatch, and it is c2
		self.assertEqual(md.call_count, 1)
		self.assertEqual(md.call_args.kwargs["tool_call"]["id"], "c2")
		# exactly ONE model call (the continuation) — iteration 1 was replayed
		self.assertEqual(provider.chat.call_count, 1)
		# the continuation call saw the replayed conversation
		sent = provider.chat.call_args.kwargs["messages"]
		roles = [m["role"] for m in sent]
		self.assertIn("assistant", roles)
		self.assertEqual(roles.count("tool"), 2)  # c1 replayed + c2 fresh
		# the finish was journaled
		self.assertIn(EVENT_TURN_COMPLETED, [e for e, _ in journal.recorded])

	def test_resume_with_journaled_final_reply_skips_the_model(self):
		"""Crash between the model's final text and turn.completed: replay
		finds the reply in the last llm.response and finishes without a call."""
		preloaded = [_started(), _llm(content="the answer", tool_calls=None)]
		provider = _provider(_resp(content="should not be called"))
		result, md, provider, journal = _run(provider, preloaded=preloaded)

		self.assertEqual(result, "the answer")
		provider.chat.assert_not_called()
		md.assert_not_called()
		self.assertIn(EVENT_TURN_COMPLETED, [e for e, _ in journal.recorded])

	def test_fresh_turn_journals_started_response_and_completed(self):
		provider = _provider(_resp(content="hello"))
		result, _, provider, journal = _run(provider)

		self.assertEqual(result, "hello")
		types = [e for e, _ in journal.recorded]
		self.assertEqual(types[0], EVENT_TURN_STARTED)
		self.assertIn(EVENT_LLM_RESPONSE, types)
		self.assertEqual(types[-1], EVENT_TURN_COMPLETED)
		self.assertEqual(journal.recorded[-1][1]["reply"], "hello")

	def test_tool_results_are_journaled_in_a_fresh_turn(self):
		provider = _provider(
			_resp(content="calling", tool_calls=[_tc("c1")]),
			_resp(content="done"),
		)
		result, _, _, journal = _run(provider, dispatch_results=[_ok(call_id="c1")])

		self.assertEqual(result, "done")
		types = [e for e, _ in journal.recorded]
		self.assertIn(EVENT_TOOL_RESULT, types)

	def test_no_turn_id_means_no_journal(self):
		provider = _provider(_resp(content="hello"))
		result, _, _, journal = _run(provider, turn_id=None)
		self.assertEqual(result, "hello")
		self.assertIsNone(journal)  # TurnJournal.open never constructed

	def test_iteration_budget_counts_replayed_iterations(self):
		"""14 journaled LLM calls leave exactly ONE more before the cap."""
		calls = [_tc("c1")]
		preloaded = [_started()]
		for _ in range(14):
			preloaded.append(_llm(tool_calls=calls))
			preloaded.append(_tool("c1"))
		# the one remaining live call also asks for a tool → budget exhausts
		provider = _provider(_resp(content="more", tool_calls=[_tc("c9")]))
		result, _, provider, _ = _run(provider, dispatch_results=[_ok(call_id="c9")], preloaded=preloaded)

		self.assertEqual(provider.chat.call_count, 1)
		self.assertIn("loop budget exhausted", result)


if __name__ == "__main__":
	unittest.main()
