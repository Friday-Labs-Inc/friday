# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""
Tests for the interrupt mechanism (Design 83, LOCKED).

Tests-first: these pin the contract BEFORE the code exists, per the workflow
rule. Mock-based — no DB, no redis, no worker.

What they pin (the LOCKED decisions):
  Q2 — cooperative flag checked at the ReAct iteration boundary: run_turn stops
       at the NEXT boundary and makes no further provider.chat call.
  Q3 — clear-at-entry: a stale flag set before the turn does NOT stop it
       (run_turn clears the session's flag once at entry).
  flag helpers — request / is_requested / clear over frappe.cache(), with a TTL.
"""

import unittest
from unittest.mock import MagicMock, patch

from frappe.friday_core.agent_runner.dispatcher import DispatchResult

_I = "frappe.friday_core.gateway.interrupt"
_R = "frappe.friday_core.agent_runner.runner"


def _resp(content="", tool_calls=None):
	return {
		"content": content,
		"finish_reason": "tool_calls" if tool_calls else "stop",
		"usage": {"total_tokens": 7},
		"tool_calls": tool_calls,
	}


def _tc(call_id="c1", name="s", arguments="{}"):
	return {"id": call_id, "name": name, "arguments": arguments}


def _patched_run(interrupt_side_effect, provider):
	"""Run run_turn with all externals patched + the interrupt helpers controlled.

	Returns (result, provider, clear_mock).
	"""
	prompt = {"messages": [{"role": "user", "content": "hi"}], "tools": [], "model": "m"}
	dispatch_ok = DispatchResult(
		success=True, content="ok", execution_log_name="EL", tool_call_name="s", tool_call_id="c1"
	)
	with (
		patch(f"{_R}.maybe_compress_session"),
		patch(f"{_R}.load_for_profile", return_value=[]),
		patch(f"{_R}.build", return_value=prompt),
		patch(f"{_R}.get_provider_for_profile", return_value=provider),
		patch(f"{_R}.dispatch", return_value=dispatch_ok),
		patch(f"{_R}._is_permission_denial", return_value=False),
		patch(f"{_R}.is_interrupt_requested", side_effect=interrupt_side_effect),
		patch(f"{_R}.clear_interrupt") as clear_mock,
	):
		from frappe.friday_core.agent_runner.runner import run_turn

		result = run_turn("P", "S", "hi")
	return result, provider, clear_mock


class TestFlagHelpers(unittest.TestCase):
	@patch(f"{_I}.frappe")
	def test_request_sets_session_key_with_ttl(self, fr):
		from frappe.friday_core.gateway import interrupt

		interrupt.request_interrupt("S-1")
		fr.cache.return_value.set_value.assert_called_once()
		args = fr.cache.return_value.set_value.call_args.args
		kwargs = fr.cache.return_value.set_value.call_args.kwargs
		self.assertIn("S-1", args[0])  # key is scoped to the session
		self.assertEqual(kwargs.get("expires_in_sec"), interrupt._INTERRUPT_TTL_SECONDS)

	@patch(f"{_I}.frappe")
	def test_is_requested_reflects_key_presence(self, fr):
		from frappe.friday_core.gateway import interrupt

		fr.cache.return_value.get_value.return_value = "1"
		self.assertTrue(interrupt.is_interrupt_requested("S-1"))
		fr.cache.return_value.get_value.return_value = None
		self.assertFalse(interrupt.is_interrupt_requested("S-1"))

	@patch(f"{_I}.frappe")
	def test_clear_deletes_session_key(self, fr):
		from frappe.friday_core.gateway import interrupt

		interrupt.clear_interrupt("S-1")
		fr.cache.return_value.delete_value.assert_called_once()
		self.assertIn("S-1", fr.cache.return_value.delete_value.call_args.args[0])


class TestRunnerHonorsInterrupt(unittest.TestCase):
	def test_interrupt_mid_loop_stops_before_next_chat(self):
		# Provider always wants to keep going (tool-call every turn). The flag is
		# unset on the first boundary, set on the second.
		prov = MagicMock()
		prov.chat.return_value = _resp(tool_calls=[_tc()])
		result, prov, clear_mock = _patched_run([False, True], prov)

		self.assertIn("interrupt", result.lower())
		# Bailed at the 2nd boundary → only ONE LLM call happened.
		self.assertEqual(prov.chat.call_count, 1)
		# The flag was cleared on honor (and at entry).
		self.assertTrue(any(c.args == ("S",) for c in clear_mock.call_args_list))

	def test_stale_flag_cleared_at_entry_does_not_stop_turn(self):
		# Flag never reads True during the loop (entry-clear neutralised it).
		prov = MagicMock()
		prov.chat.return_value = _resp(content="hello")  # plain text → clean end
		result, prov, clear_mock = _patched_run([False], prov)

		self.assertEqual(result, "hello")
		# Q3: run_turn cleared the session flag once at entry.
		clear_mock.assert_any_call("S")


if __name__ == "__main__":
	unittest.main()
