# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""
Unit tests for within-turn tool-call de-duplication + deterministic IDs
(Feature D, doc 51 §4.D). Mock-based — no DB.

Pins:
  - D.1 — identical (name, arguments) calls in one response collapse to one;
    different name or arguments are both kept.
  - D.2 — a tool call with no id gets a deterministic id derived from
    (name, arguments, index); the same content yields the same id.
  - Loop wiring — duplicates are dropped *before* dispatch, and an id-less
    call reaches the dispatcher with a stable id.
"""

import unittest

from frappe.friday_core.agent_runner.runner import (
	_deduplicate_tool_calls,
	_deterministic_call_id,
)
from frappe.friday_core.tests.test_react_loop import _ok, _provider, _resp, _run


class TestDeduplicateToolCalls(unittest.TestCase):
	def test_identical_calls_collapse_to_one(self):
		calls = [
			{"id": "a", "name": "create_note", "arguments": '{"title": "x"}'},
			{"id": "b", "name": "create_note", "arguments": '{"title": "x"}'},
		]
		out = _deduplicate_tool_calls(calls)
		self.assertEqual(len(out), 1)
		self.assertEqual(out[0]["id"], "a")  # the first is kept

	def test_different_arguments_both_kept(self):
		calls = [
			{"id": "a", "name": "create_note", "arguments": '{"title": "x"}'},
			{"id": "b", "name": "create_note", "arguments": '{"title": "y"}'},
		]
		self.assertEqual(len(_deduplicate_tool_calls(calls)), 2)

	def test_different_name_both_kept(self):
		calls = [
			{"id": "a", "name": "create_note", "arguments": '{"title": "x"}'},
			{"id": "b", "name": "update_note", "arguments": '{"title": "x"}'},
		]
		self.assertEqual(len(_deduplicate_tool_calls(calls)), 2)

	def test_same_content_different_key_order_collapses(self):
		# Comparison is normalised, so re-ordered-but-identical args are a dup.
		calls = [
			{"id": "a", "name": "n", "arguments": '{"a": 1, "b": 2}'},
			{"id": "b", "name": "n", "arguments": '{"b": 2, "a": 1}'},
		]
		self.assertEqual(len(_deduplicate_tool_calls(calls)), 1)

	def test_empty_list_returns_empty(self):
		self.assertEqual(_deduplicate_tool_calls([]), [])


class TestDeterministicCallId(unittest.TestCase):
	def test_same_inputs_same_id(self):
		self.assertEqual(
			_deterministic_call_id("create_note", '{"title": "x"}', 0),
			_deterministic_call_id("create_note", '{"title": "x"}', 0),
		)

	def test_same_content_across_reserialisation(self):
		# A dict and the equivalent JSON string (any key order) -> same id.
		self.assertEqual(
			_deterministic_call_id("n", {"a": 1, "b": 2}, 0),
			_deterministic_call_id("n", '{"b": 2, "a": 1}', 0),
		)

	def test_index_distinguishes_calls(self):
		self.assertNotEqual(
			_deterministic_call_id("n", "{}", 0),
			_deterministic_call_id("n", "{}", 1),
		)

	def test_arguments_distinguish_calls(self):
		self.assertNotEqual(
			_deterministic_call_id("n", '{"title": "x"}', 0),
			_deterministic_call_id("n", '{"title": "y"}', 0),
		)

	def test_id_has_call_prefix(self):
		self.assertTrue(_deterministic_call_id("n", "{}", 0).startswith("call_"))


class TestLoopWiring(unittest.TestCase):
	def test_duplicate_calls_dispatched_once(self):
		dup_a = {"id": "a", "name": "create_note", "arguments": '{"title": "x"}'}
		dup_b = {"id": "b", "name": "create_note", "arguments": '{"title": "x"}'}
		prov = _provider(_resp(tool_calls=[dup_a, dup_b]), _resp(content="done"))
		result, md, _ = _run(prov, dispatch_results=[_ok(call_id="a")])
		self.assertEqual(md.call_count, 1, "the duplicate must be dropped before dispatch")
		self.assertEqual(result, "done")

	def test_idless_call_gets_deterministic_id_before_dispatch(self):
		idless = {"id": "", "name": "create_note", "arguments": '{"title": "x"}'}
		prov = _provider(_resp(tool_calls=[idless]), _resp(content="done"))
		_result, md, _ = _run(prov, dispatch_results=[_ok(call_id="x")])
		dispatched = md.call_args_list[0].kwargs["tool_call"]
		self.assertTrue(dispatched["id"], "an id-less call must be given an id")
		self.assertTrue(dispatched["id"].startswith("call_"))


if __name__ == "__main__":
	unittest.main()
