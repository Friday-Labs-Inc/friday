# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""
Unit tests for reasoning-block scrubbing (llm/reasoning.py).

Verbatim port of Hermes `strip_think_blocks` — per-variant closed pairs, inline
tool-call XML stripping, boundary-gated unterminated opens, orphan tags.
"""

import unittest

from friday.friday_core.llm.reasoning import strip_reasoning


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
		self.assertEqual(strip_reasoning("Answer.\n<think>leaking to the end..."), "Answer.")

	def test_open_at_start_with_only_reasoning_becomes_empty(self):
		self.assertEqual(strip_reasoning("<think>all reasoning, no answer"), "")

	def test_orphan_open_tag_is_stripped_but_prose_survives(self):
		# Hermes' orphan pass removes a bare <think> tag (it's not at a boundary,
		# so case 2 leaves the rest of the line) — the prose around it survives.
		self.assertEqual(strip_reasoning("use <think> tags carefully"), "use tags carefully")

	def test_orphan_close_removed(self):
		self.assertEqual(strip_reasoning("Answer</think>"), "Answer")

	def test_mismatched_tags_keep_inner_content(self):
		# Per-variant (not combined): <think>...</thinking> is NOT a pair, so the
		# inner text is kept and only the orphan tags are stripped. (A combined
		# alternation would treat it as a pair and delete "keep".)
		self.assertEqual(strip_reasoning("answer <think>keep</thinking>."), "answer keep.")

	def test_inline_tool_call_xml_stripped(self):
		self.assertEqual(strip_reasoning('before<tool_call>{"n":1}</tool_call>after'), "beforeafter")

	def test_function_call_xml_at_boundary_stripped(self):
		self.assertEqual(strip_reasoning('\n<function name="f">args</function>\nReply'), "Reply")

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
