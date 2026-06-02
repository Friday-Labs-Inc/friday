# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""
Unit tests for the ReAct loop in agent_runner/runner.py (Feature A, doc 48 §1).

Mock-based — no DB. Every external the loop touches (skill loader, prompt
builder, provider, dispatcher, the denial check) is patched, so these run
anywhere `import frappe` works and pin the loop's contract:

  - a plain-text reply ends the turn
  - tool calls are dispatched **sequentially**, results fed back as
    `{role:"tool", ...}` messages, and the loop re-prompts (A.3, A.6)
  - the re-sent assistant turn uses OpenAI wire shape
  - a **permission denial breaks the loop** (A.4)
  - a tool **error is fed back and the loop continues** (A.3)
  - the loop is capped at MAX_REACT_ITERATIONS with a budget suffix (A.2)

The DB-backed integration (real Skill/Profile/Note) lives in
test_runner_tool_call.py and runs on a bench.
"""

import unittest
from unittest.mock import MagicMock, patch

from frappe.friday_core.agent_runner.dispatcher import DispatchResult

_R = "frappe.friday_core.agent_runner.runner"


def _resp(content="", tool_calls=None):
	return {
		"content": content,
		"finish_reason": "tool_calls" if tool_calls else "stop",
		"usage": {"total_tokens": 7},
		"tool_calls": tool_calls,
	}


def _tc(call_id, name="slice6-create-note", arguments='{"title": "x"}'):
	return {"id": call_id, "name": name, "arguments": arguments}


def _ok(content="Done.", call_id="c1"):
	return DispatchResult(success=True, content=content, execution_log_name="EL-1",
	                      tool_call_name="s", tool_call_id=call_id)


def _err(content="boom", call_id="c1"):
	# success=False WITH a log row, but NOT a permission denial.
	return DispatchResult(success=False, content=content, execution_log_name="EL-err",
	                      tool_call_name="s", tool_call_id=call_id)


def _provider(*responses):
	p = MagicMock()
	if len(responses) == 1:
		p.chat.return_value = responses[0]
	else:
		p.chat.side_effect = list(responses)
	return p


def _run(provider, dispatch_results=None, denial=False, messages=None):
	"""Run run_turn with all externals patched. Returns (result, dispatch_mock, provider)."""
	from frappe.friday_core.agent_runner.runner import run_turn

	prompt = {
		"messages": messages if messages is not None else [{"role": "user", "content": "hi"}],
		"tools": [],
		"model": "m",
	}
	with patch(f"{_R}.load_for_profile", return_value=[]), \
	     patch(f"{_R}.build", return_value=prompt), \
	     patch(f"{_R}.get_provider_for_profile", return_value=provider), \
	     patch(f"{_R}.dispatch", side_effect=dispatch_results) as md, \
	     patch(f"{_R}._is_permission_denial", return_value=denial):
		result = run_turn("P", "S", "hi")
	return result, md, provider


class TestPlainText(unittest.TestCase):
	def test_plain_text_first_response_ends_turn(self):
		prov = _provider(_resp(content="Hello!"))
		result, md, _ = _run(prov, dispatch_results=[])
		self.assertEqual(result, "Hello!")
		md.assert_not_called()
		self.assertEqual(prov.chat.call_count, 1)


class TestSingleToolCall(unittest.TestCase):
	def test_tool_call_then_plain_text_returns_final_reply(self):
		prov = _provider(_resp(tool_calls=[_tc("c1")]), _resp(content="All done."))
		result, md, _ = _run(prov, dispatch_results=[_ok(call_id="c1")])
		self.assertEqual(result, "All done.")
		self.assertEqual(md.call_count, 1)
		self.assertEqual(prov.chat.call_count, 2)

	def test_tool_result_and_assistant_are_appended_in_openai_shape(self):
		prov = _provider(_resp(content="thinking", tool_calls=[_tc("c1")]), _resp(content="done"))
		_run(prov, dispatch_results=[_ok(content="Note created", call_id="c1")])

		# The conversation list is mutated in place, so the last chat call's
		# messages hold the full appended state.
		msgs = prov.chat.call_args.kwargs["messages"]
		roles = [m["role"] for m in msgs]
		self.assertEqual(roles, ["user", "assistant", "tool"])

		assistant = msgs[1]
		self.assertEqual(assistant["tool_calls"][0]["type"], "function")
		self.assertEqual(assistant["tool_calls"][0]["id"], "c1")
		self.assertEqual(assistant["tool_calls"][0]["function"]["name"], "slice6-create-note")
		self.assertIsInstance(assistant["tool_calls"][0]["function"]["arguments"], str)

		tool_msg = msgs[2]
		self.assertEqual(tool_msg["tool_call_id"], "c1")
		self.assertEqual(tool_msg["content"], "Note created")


class TestSequentialDispatch(unittest.TestCase):
	def test_multiple_tool_calls_dispatched_in_order(self):
		# Distinct arguments so Feature D's dedup keeps all three (three
		# *identical* (name, arguments) would correctly collapse to one — that
		# behaviour is covered in test_react_dedup).
		prov = _provider(
			_resp(tool_calls=[
				_tc("c1", arguments='{"title": "a"}'),
				_tc("c2", arguments='{"title": "b"}'),
				_tc("c3", arguments='{"title": "c"}'),
			]),
			_resp(content="finished"),
		)
		result, md, _ = _run(prov, dispatch_results=[_ok(call_id="c1"), _ok(call_id="c2"), _ok(call_id="c3")])
		self.assertEqual(result, "finished")
		self.assertEqual(md.call_count, 3)
		dispatched_ids = [c.kwargs["tool_call"]["id"] for c in md.call_args_list]
		self.assertEqual(dispatched_ids, ["c1", "c2", "c3"])


class TestPermissionDenialBreaks(unittest.TestCase):
	def test_denial_breaks_loop_and_returns_denial_text(self):
		prov = _provider(_resp(tool_calls=[_tc("c1")]))  # would loop forever if not broken
		denied = DispatchResult(success=False, content="I don't have permission to do that: nope",
		                        execution_log_name="EL-rej", tool_call_id="c1")
		result, md, _ = _run(prov, dispatch_results=[denied], denial=True)
		self.assertIn("permission", result.lower())
		self.assertEqual(md.call_count, 1)
		self.assertEqual(prov.chat.call_count, 1)  # never re-prompted after denial


class TestToolErrorContinues(unittest.TestCase):
	def test_tool_error_is_fed_back_and_loop_continues(self):
		prov = _provider(_resp(tool_calls=[_tc("c1")]), _resp(content="recovered"))
		result, md, _ = _run(prov, dispatch_results=[_err(content="skill blew up", call_id="c1")], denial=False)
		self.assertEqual(result, "recovered")
		self.assertEqual(prov.chat.call_count, 2)  # error fed back, loop continued
		# The error content is fed back verbatim so the model can adapt.
		tool_msg = prov.chat.call_args.kwargs["messages"][-1]
		self.assertEqual(tool_msg["role"], "tool")
		self.assertEqual(tool_msg["content"], "skill blew up")


class TestMaxIterations(unittest.TestCase):
	def test_budget_exhausted_suffix_after_cap(self):
		prov = _provider(_resp(content="still working", tool_calls=[_tc("c1")]))  # always tool_calls
		with patch(f"{_R}.MAX_REACT_ITERATIONS", 3):
			result, md, _ = _run(prov, dispatch_results=[_ok(call_id="c1")] * 3)
		self.assertIn("loop budget exhausted after 3 iterations", result)
		self.assertTrue(result.startswith("still working"))
		self.assertEqual(md.call_count, 3)
		self.assertEqual(prov.chat.call_count, 3)

	def test_budget_exhausted_empty_content_uses_fallback(self):
		prov = _provider(_resp(content="", tool_calls=[_tc("c1")]))
		with patch(f"{_R}.MAX_REACT_ITERATIONS", 2):
			result, _, _ = _run(prov, dispatch_results=[_ok(call_id="c1")] * 2)
		self.assertIn("unable to complete", result.lower())
		self.assertIn("loop budget exhausted after 2 iterations", result)


class TestIsPermissionDenial(unittest.TestCase):
	"""The denial detector: success=False + a 'rejected' Execution Log row."""

	@patch(f"{_R}.frappe")
	def test_rejected_log_is_denial(self, mock_frappe):
		from frappe.friday_core.agent_runner.runner import _is_permission_denial
		mock_frappe.db.get_value.return_value = "rejected"
		self.assertTrue(_is_permission_denial(_err()))

	@patch(f"{_R}.frappe")
	def test_error_log_is_not_denial(self, mock_frappe):
		from frappe.friday_core.agent_runner.runner import _is_permission_denial
		mock_frappe.db.get_value.return_value = "error"
		self.assertFalse(_is_permission_denial(_err()))

	@patch(f"{_R}.frappe")
	def test_success_is_not_denial_and_skips_db(self, mock_frappe):
		from frappe.friday_core.agent_runner.runner import _is_permission_denial
		self.assertFalse(_is_permission_denial(_ok()))
		mock_frappe.db.get_value.assert_not_called()

	@patch(f"{_R}.frappe")
	def test_no_log_name_is_not_denial(self, mock_frappe):
		from frappe.friday_core.agent_runner.runner import _is_permission_denial
		self.assertFalse(_is_permission_denial(DispatchResult(success=False, content="x", execution_log_name=None)))
		mock_frappe.db.get_value.assert_not_called()


if __name__ == "__main__":
	unittest.main()
