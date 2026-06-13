# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""
Unit tests for surrogate sanitization (agent_runner/message_hygiene.py).

Verbatim port of Hermes' surrogate sanitizers: lone surrogates (U+D800–U+DFFF)
are invalid UTF-8 and crash json.dumps in the model SDK; they're replaced with
U+FFFD so the turn survives.

Surrogates are built with chr() (a .py file can't hold literal lone surrogates).
"""

import unittest

from frappe.friday_core.agent_runner.message_hygiene import (
	sanitize_messages_surrogates,
	sanitize_surrogates,
)

SUR = chr(0xD800)  # a lone surrogate (invalid on its own)
SUR2 = chr(0xDFFF)  # another lone surrogate
FFFD = chr(0xFFFD)  # the Unicode replacement character


class TestSanitizeSurrogates(unittest.TestCase):
	def test_clean_text_unchanged(self):
		self.assertEqual(sanitize_surrogates("hello world"), "hello world")

	def test_lone_surrogate_replaced(self):
		self.assertEqual(sanitize_surrogates("a" + SUR + "b"), "a" + FFFD + "b")

	def test_multiple_surrogates_replaced(self):
		self.assertEqual(sanitize_surrogates(SUR + SUR2), FFFD + FFFD)

	def test_empty(self):
		self.assertEqual(sanitize_surrogates(""), "")


class TestSanitizeMessagesSurrogates(unittest.TestCase):
	def test_content_sanitized_and_returns_true(self):
		msgs = [{"role": "user", "content": "hi" + SUR}]
		self.assertTrue(sanitize_messages_surrogates(msgs))
		self.assertEqual(msgs[0]["content"], "hi" + FFFD)

	def test_clean_messages_returns_false(self):
		self.assertFalse(sanitize_messages_surrogates([{"role": "user", "content": "clean"}]))

	def test_content_list_parts_sanitized(self):
		msgs = [{"role": "user", "content": [{"type": "text", "text": "a" + SUR}]}]
		self.assertTrue(sanitize_messages_surrogates(msgs))
		self.assertEqual(msgs[0]["content"][0]["text"], "a" + FFFD)

	def test_tool_call_function_args_sanitized(self):
		msgs = [
			{
				"role": "assistant",
				"tool_calls": [{"id": "c1", "function": {"name": "f", "arguments": '{"x":"' + SUR + '"}'}}],
			}
		]
		self.assertTrue(sanitize_messages_surrogates(msgs))
		self.assertEqual(msgs[0]["tool_calls"][0]["function"]["arguments"], '{"x":"' + FFFD + '"}')

	def test_other_nested_field_sanitized(self):
		# reasoning_content etc. — byte-level reasoning models leak surrogates here.
		msgs = [{"role": "assistant", "content": "ok", "reasoning_content": "r" + SUR}]
		self.assertTrue(sanitize_messages_surrogates(msgs))
		self.assertEqual(msgs[0]["reasoning_content"], "r" + FFFD)

	def test_non_dict_message_skipped(self):
		self.assertFalse(sanitize_messages_surrogates(["notadict", {"role": "user", "content": "ok"}]))


if __name__ == "__main__":
	unittest.main()
