# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""
Tests for the steer mechanism (Design 84, LOCKED).

Tests-first: pin the contract BEFORE the code exists. Mock-based — no DB,
no redis, no worker.

What they pin (the LOCKED decisions):
  Q2 — a pending steer is appended to the LAST tool result as
       "User guidance: {text}" before the next provider.chat (Hermes-faithful);
       at the no-tool-yet edge it injects as a user message.
  Q3 — push coalesces (newline-join); drain reads then clears.
  Q4 — run_turn clears the steer slot at entry (a stale steer does not inject).
"""

import copy
import unittest
from unittest.mock import MagicMock, patch

from friday.friday_core.agent_runner.dispatcher import DispatchResult

_S = "friday.friday_core.gateway.steer"
_R = "friday.friday_core.agent_runner.runner"


def _resp(content="", tool_calls=None):
	return {
		"content": content,
		"finish_reason": "tool_calls" if tool_calls else "stop",
		"usage": {"total_tokens": 7},
		"tool_calls": tool_calls,
	}


def _tc(call_id="c1", name="s", arguments="{}"):
	return {"id": call_id, "name": name, "arguments": arguments}


def _run_with_steer(drain_side_effect, responses):
	"""run_turn with externals patched; records the messages each chat() saw.

	Returns (result, seen) where seen[i] is a deep copy of the messages list
	passed to the i-th provider.chat call.
	"""
	prov = MagicMock()
	resp_iter = iter(responses)
	seen = []

	def chat_se(**kwargs):
		seen.append(copy.deepcopy(kwargs["messages"]))
		return next(resp_iter)

	prov.chat.side_effect = chat_se

	prompt = {"messages": [{"role": "user", "content": "do it"}], "tools": [], "model": "m"}
	dispatch_ok = DispatchResult(
		success=True, content="tool-out", execution_log_name="EL", tool_call_name="s", tool_call_id="c1"
	)
	with (
		patch(f"{_R}.maybe_compress_session"),
		patch(f"{_R}.load_for_profile", return_value=[]),
		patch(f"{_R}.build", return_value=prompt),
		patch(f"{_R}.get_provider_for_profile", return_value=prov),
		patch(f"{_R}.dispatch", return_value=dispatch_ok),
		patch(f"{_R}._is_permission_denial", return_value=False),
		patch(f"{_R}.is_interrupt_requested", return_value=False),
		patch(f"{_R}.clear_interrupt"),
		patch(f"{_R}.drain_steer", side_effect=drain_side_effect),
		patch(f"{_R}.clear_steer") as clear_steer_mock,
	):
		from friday.friday_core.agent_runner.runner import run_turn

		result = run_turn("P", "S", "do it")
	return result, seen, clear_steer_mock


class TestSteerHelpers(unittest.TestCase):
	@patch(f"{_S}.frappe")
	def test_push_first_sets_text(self, fr):
		from friday.friday_core.gateway import steer

		fr.cache.return_value.get_value.return_value = None
		self.assertTrue(steer.push_steer("S-1", "use staging"))
		self.assertEqual(fr.cache.return_value.set_value.call_args.args[1], "use staging")

	@patch(f"{_S}.frappe")
	def test_push_coalesces_with_newline(self, fr):
		from friday.friday_core.gateway import steer

		fr.cache.return_value.get_value.return_value = "first"
		steer.push_steer("S-1", "second")
		self.assertEqual(fr.cache.return_value.set_value.call_args.args[1], "first\nsecond")

	@patch(f"{_S}.frappe")
	def test_push_empty_is_rejected(self, fr):
		from friday.friday_core.gateway import steer

		self.assertFalse(steer.push_steer("S-1", "   "))
		fr.cache.return_value.set_value.assert_not_called()

	@patch(f"{_S}.frappe")
	def test_drain_returns_then_clears(self, fr):
		from friday.friday_core.gateway import steer

		fr.cache.return_value.get_value.return_value = "go faster"
		self.assertEqual(steer.drain_steer("S-1"), "go faster")
		fr.cache.return_value.delete_value.assert_called_once()

	@patch(f"{_S}.frappe")
	def test_drain_empty_returns_none(self, fr):
		from friday.friday_core.gateway import steer

		fr.cache.return_value.get_value.return_value = None
		self.assertIsNone(steer.drain_steer("S-1"))


class TestRunnerAppliesSteer(unittest.TestCase):
	def test_steer_appended_to_last_tool_result(self):
		# iter0: no steer → tool call; iter1: steer present → appended to the
		# tool result from iter0, then a plain-text reply ends the turn.
		result, seen, _ = _run_with_steer(
			drain_side_effect=[None, "use staging DB"],
			responses=[_resp(tool_calls=[_tc()]), _resp(content="done")],
		)
		self.assertEqual(result, "done")
		# The iter1 chat saw the steer riding on the tool result (Q2).
		iter1_msgs = seen[1]
		tool_msgs = [m for m in iter1_msgs if m.get("role") == "tool"]
		self.assertTrue(tool_msgs)
		self.assertIn("User guidance: use staging DB", tool_msgs[-1]["content"])

	def test_steer_at_iteration_zero_injects_user_message(self):
		# Steer present on the very first boundary — no tool result yet, so it
		# injects as a user message (Q2 fallback).
		result, seen, _ = _run_with_steer(
			drain_side_effect=["keep it short"],
			responses=[_resp(content="ok")],
		)
		self.assertEqual(result, "ok")
		iter0_msgs = seen[0]
		self.assertTrue(
			any(
				m.get("role") == "user" and "User guidance: keep it short" in (m.get("content") or "")
				for m in iter0_msgs
			)
		)

	def test_steer_slot_cleared_at_entry(self):
		# Q4: run_turn clears the steer slot once at entry.
		_, _, clear_steer_mock = _run_with_steer(
			drain_side_effect=[None],
			responses=[_resp(content="ok")],
		)
		clear_steer_mock.assert_any_call("S")


if __name__ == "__main__":
	unittest.main()
