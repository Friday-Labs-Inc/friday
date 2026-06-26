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
from unittest.mock import MagicMock, patch

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


class TestRecordTurnPersistsAndAudits(unittest.TestCase):
	"""The governance gap caught on the live loopback: a clean SSE stream left 0 Chat
	Message rows AND 0 LLM Usage Log rows. The SSE generator runs PAST the request's
	auto-commit, and the path bypassed run_turn (so no usage logging). `_record_turn`
	closes both: it writes the transcript, records usage for BOTH model calls, and — the
	load-bearing bit — COMMITS, or the writes are silently discarded."""

	@patch(f"{chat.__name__}.record_usage")
	@patch(f"{chat.__name__}.frappe")
	def test_persists_transcript_records_both_usages_and_commits(self, fr, rec):
		provider = MagicMock()
		provider.get_default_model.return_value = "minimax-m3"

		chat._record_turn("S1", "hi", "hello", provider, {"total_tokens": 50}, {"total_tokens": 10})

		# Transcript: one inbound + one outbound Chat Message row.
		chat_rows = [c.args[0] for c in fr.get_doc.call_args_list if c.args[0]["doctype"] == "Chat Message"]
		self.assertEqual([r["direction"] for r in chat_rows], ["inbound", "outbound"])
		# Usage audited for BOTH the streamed reply AND the extraction pass.
		self.assertEqual(rec.call_count, 2)
		self.assertEqual(rec.call_args_list[0].kwargs["usage"], {"total_tokens": 50})
		self.assertEqual(rec.call_args_list[1].kwargs["usage"], {"total_tokens": 10})
		# The load-bearing commit (without it the post-auto-commit writes vanish).
		fr.db.commit.assert_called_once()

	@patch(f"{chat.__name__}.record_usage")
	@patch(f"{chat.__name__}.frappe")
	def test_no_extraction_usage_skips_the_second_log(self, fr, rec):
		provider = MagicMock()
		chat._record_turn("S1", "hi", "hello", provider, {"total_tokens": 50}, {})
		self.assertEqual(rec.call_count, 1)  # only the conversational call
		fr.db.commit.assert_called_once()

	@patch(f"{chat.__name__}.record_usage")
	@patch(f"{chat.__name__}.frappe")
	def test_persistence_failure_rolls_back_and_lands_in_error_log(self, fr, rec):
		# A persistence failure must not corrupt the reply already streamed — and unlike the
		# old logger.warning (which went to a 0-byte void on the box, staying silent), it now
		# rolls back the poisoned tx and writes a durable, operator-visible Error Log row.
		fr.get_doc.side_effect = RuntimeError("LinkValidationError")
		chat._record_turn("S1", "hi", "hello", MagicMock(), {}, {})  # must not raise
		fr.db.rollback.assert_called_with(save_point="friday_intake_persist")
		fr.log_error.assert_called()
		fr.db.commit.assert_called_once()  # the error-log row is still committed


class TestEnsureIntakePlatform(unittest.TestCase):
	"""The fix's PRIMARY cause: `Chat Message.platform` Links to `Chat Platform`, and the
	`randompack-intake` row was never registered → every transcript insert hit
	LinkValidationError, so chat turns left no transcript AND no usage audit."""

	@patch(f"{chat.__name__}.frappe")
	def test_creates_the_platform_row_when_absent(self, fr):
		fr.db.exists.return_value = False
		out = chat.ensure_intake_platform()
		row = fr.get_doc.call_args.args[0]
		self.assertEqual(row["doctype"], "Chat Platform")
		self.assertEqual(row["platform_name"], chat.PLATFORM)
		self.assertEqual(row["adapter_module"], chat._ADAPTER_MODULE)
		self.assertEqual(row["enabled"], 0)  # registered for the Link, not gateway dispatch
		self.assertTrue(out["platform_created"])

	@patch(f"{chat.__name__}.frappe")
	def test_idempotent_when_present(self, fr):
		fr.db.exists.return_value = True
		out = chat.ensure_intake_platform()
		fr.get_doc.assert_not_called()
		self.assertFalse(out["platform_created"])

	@patch(f"{chat.__name__}.frappe")
	def test_provision_ensures_platform_even_when_profile_already_exists(self, fr):
		# The exact box state that broke us: profile present, platform missing. Provision
		# must still create the platform (no early-return skip).
		fr.db.exists.side_effect = lambda dt, name: dt == "Agent Profile"
		out = chat.provision_intake_profile()
		created = [c.args[0]["doctype"] for c in fr.get_doc.call_args_list]
		self.assertIn("Chat Platform", created)
		self.assertTrue(out["platform_created"])
		self.assertFalse(out["created"])  # the profile was NOT re-created


if __name__ == "__main__":
	unittest.main()
