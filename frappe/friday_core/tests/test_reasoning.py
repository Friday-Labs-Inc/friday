# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""
Unit tests for reasoning-block scrubbing (llm/reasoning.py).

Ported behaviour from Hermes `agent/think_scrubber.py` (complete-string form):
closed pairs removed anywhere, unterminated opens removed only at a line
boundary (so prose mentions survive), orphan close tags removed.
"""

import unittest

from frappe.friday_core.llm.reasoning import strip_reasoning


class TestStripReasoning(unittest.TestCase):
	def test_closed_pair_removed(self):
		self.assertEqual(strip_reasoning("<think>let me check</think>Hello"), "Hello")

	def test_all_tag_variants(self):
		for tag in ("think", "thinking", "reasoning", "thought", "REASONING_SCRATCHPAD"):
			self.assertEqual(strip_reasoning(f"<{tag}>x</{tag}>Answer"), "Answer")

	def test_case_insensitive(self):
		self.assertEqual(strip_reasoning("<THINK>x</Think>Hi"), "Hi")

	def test_multiline_block(self):
		self.assertEqual(strip_reasoning("<think>\nstep 1\nstep 2\n</think>\nDone"), "Done")

	def test_multiple_blocks(self):
		self.assertEqual(strip_reasoning("<think>a</think>X<think>b</think>Y"), "XY")

	def test_unterminated_open_at_boundary_stripped_to_end(self):
		# A model that opens a block and never closes it — strip from the tag on.
		self.assertEqual(strip_reasoning("Answer.\n<think>leaking to the end..."), "Answer.")

	def test_open_at_start_with_only_reasoning_becomes_empty(self):
		self.assertEqual(strip_reasoning("<think>all reasoning, no answer"), "")

	def test_prose_mention_is_NOT_stripped(self):
		# Mid-line mention, not a real block opener → preserved (boundary gate).
		self.assertEqual(strip_reasoning("use <think> tags carefully"), "use <think> tags carefully")

	def test_orphan_close_removed(self):
		self.assertEqual(strip_reasoning("Answer</think>"), "Answer")

	def test_plain_text_unchanged(self):
		self.assertEqual(strip_reasoning("Just a normal reply."), "Just a normal reply.")

	def test_empty_and_none(self):
		self.assertEqual(strip_reasoning(""), "")
		self.assertEqual(strip_reasoning(None), "")

	def test_idempotent(self):
		once = strip_reasoning("<think>x</think>Reply")
		self.assertEqual(strip_reasoning(once), once)


if __name__ == "__main__":
	unittest.main()
