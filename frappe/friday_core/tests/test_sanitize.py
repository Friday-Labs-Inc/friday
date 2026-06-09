# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""
Unit tests for tool-call argument repair (agent_runner/sanitize.py).

Ported from Hermes `_repair_tool_call_arguments`: a malformed-JSON tool call
should be repaired into a valid action, not killed. The function always returns
parseable JSON.
"""

import json
import unittest

from frappe.friday_core.agent_runner.sanitize import repair_tool_arguments


class TestRepairToolArguments(unittest.TestCase):
	def _loads(self, raw):
		# Every return value must be valid JSON — parse it to prove it.
		return json.loads(repair_tool_arguments(raw))

	def test_valid_json_passes_through(self):
		self.assertEqual(self._loads('{"title": "Hello"}'), {"title": "Hello"})

	def test_empty_and_whitespace_become_empty_object(self):
		self.assertEqual(repair_tool_arguments(""), "{}")
		self.assertEqual(repair_tool_arguments("   "), "{}")

	def test_python_none_becomes_empty_object(self):
		self.assertEqual(repair_tool_arguments("None"), "{}")

	def test_trailing_comma_repaired(self):
		self.assertEqual(self._loads('{"a": 1, "b": 2,}'), {"a": 1, "b": 2})

	def test_unclosed_brace_repaired(self):
		self.assertEqual(self._loads('{"title": "x"'), {"title": "x"})

	def test_unclosed_nested_repaired(self):
		self.assertEqual(self._loads('{"a": [1, 2'), {"a": [1, 2]})

	def test_literal_control_chars_in_string_repaired(self):
		# A real newline inside the JSON string value (strict=False handles it).
		self.assertEqual(self._loads('{"msg": "line1\nline2"}'), {"msg": "line1\nline2"})

	def test_unrepairable_becomes_empty_object(self):
		self.assertEqual(repair_tool_arguments("not json at all {{"), "{}")

	def test_always_returns_parseable_json(self):
		for raw in ('{"a":1}', '{bad', 'None', '', '{"x": [}', '<garbage>'):
			json.loads(repair_tool_arguments(raw))  # must not raise


if __name__ == "__main__":
	unittest.main()
