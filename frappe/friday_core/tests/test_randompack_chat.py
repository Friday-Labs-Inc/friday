# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""The RandomPack chat-intake surface wire (surfaces/randompack_chat.py).

DB-free: the pure pieces — the <think> stream filter, SSE framing, the wire-delta step
mapping, the field vocabulary, and (the #161 lesson) the ENDPOINTS' Frappe routing
registration. The streaming orchestration + HMAC verify need the web stack / a Connector
row and are exercised on deploy.
"""

from __future__ import annotations

import unittest

from frappe.friday_core.surfaces import randompack_chat as chat


def _run_filter(chunks):
	f = chat._ThinkFilter()
	out = "".join(f.feed(c) for c in chunks)
	return out + f.flush()


class TestThinkFilter(unittest.TestCase):
	def test_plain_text_passes(self):
		self.assertEqual(_run_filter(["hello ", "world"]), "hello world")

	def test_whole_think_block_is_hidden(self):
		self.assertEqual(_run_filter(["<think>secret reasoning</think>answer"]), "answer")

	def test_open_tag_split_across_chunks(self):
		self.assertEqual(_run_filter(["<thi", "nk>secret</think>visible"]), "visible")

	def test_close_tag_split_across_chunks(self):
		self.assertEqual(_run_filter(["<think>secret</thi", "nk>visible"]), "visible")

	def test_text_around_a_think_block(self):
		self.assertEqual(_run_filter(["Hi <think>x</think> there"]), "Hi  there")

	def test_a_lone_less_than_is_eventually_emitted(self):
		# "<" that is NOT the start of a tag must not be swallowed.
		self.assertEqual(_run_filter(["a <", " b"]), "a < b")


class TestSseAndWireDeltas(unittest.TestCase):
	def test_sse_framing(self):
		self.assertEqual(chat.sse({"type": "done"}), 'data: {"type": "done"}\n\n')

	def test_wire_delta_tags_the_step(self):
		out = chat.wire_deltas([{"field": "company_name", "value": "Loop Coffee", "confidence": 0.9}])
		self.assertEqual(
			out, [{"step": "identity", "field": "company_name", "value": "Loop Coffee", "confidence": 0.9}]
		)

	def test_unknown_field_dropped(self):
		self.assertEqual(chat.wire_deltas([{"field": "ssn", "value": "x", "confidence": 1.0}]), [])

	def test_array_values_pass_through(self):
		out = chat.wire_deltas([{"field": "personality", "value": ["rugged", "heritage"], "confidence": 0.8}])
		self.assertEqual(out[0]["step"], "taste")
		self.assertEqual(out[0]["value"], ["rugged", "heritage"])


class TestFieldVocabulary(unittest.TestCase):
	def test_never_touch_fields_are_absent(self):
		names = {f["name"] for f in chat._FIELDS}
		for forbidden in ("password", "gate_commitment", "terms_accepted"):
			self.assertNotIn(forbidden, names)

	def test_selects_name_their_options(self):
		by = {f["name"]: f["description"] for f in chat._FIELDS}
		self.assertIn("Referral", by["lead_source"])  # exact option strings present
		self.assertIn("SaaS", by["category"])
		self.assertIn("Rebranding", by["stage"])
		self.assertIn("Need a name", by["naming_status"])

	def test_personality_and_references_are_arrays(self):
		by = {f["name"]: f["description"] for f in chat._FIELDS}
		self.assertIn("ARRAY", by["personality"].upper())
		self.assertIn("array", by["references"].lower())

	def test_extraction_fields_drop_the_step_key(self):
		# What the extractor sees is {name, description} only — step is wire metadata.
		self.assertTrue(all(set(f.keys()) == {"name", "description"} for f in chat._EXTRACTION_FIELDS))


class TestEndpointsAreRoutable(unittest.TestCase):
	"""The #161 lesson, applied proactively: a whitelisted HTTP endpoint must be
	registered with Frappe routing — calling the core function in a test isn't enough."""

	def test_chat_endpoints_are_whitelisted_guest_post(self):
		import frappe

		for fn in (chat.chat_send, chat.chat_finalize):
			self.assertIn(fn, frappe.whitelisted)
			self.assertIn(fn, frappe.guest_methods)
			self.assertIn("POST", frappe.allowed_http_methods_for_whitelisted_func[fn])


if __name__ == "__main__":
	unittest.main()
