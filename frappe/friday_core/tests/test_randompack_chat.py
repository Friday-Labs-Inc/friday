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


class TestProvisionEnsuresPlatform(unittest.TestCase):
	"""The #168 lesson at the surface level: provisioning must ensure the platform row even
	when the profile already exists (the exact box state that broke persistence). The
	platform/persistence mechanics themselves are pinned in test_chat_spine.py."""

	@patch("frappe.friday_core.surfaces.chat_spine.frappe")
	@patch(f"{chat.__name__}.frappe")
	def test_provision_ensures_platform_even_when_profile_already_exists(self, fr, spine_fr):
		fr.db.exists.return_value = True  # the Agent Profile exists...
		spine_fr.db.exists.return_value = False  # ...but the Chat Platform row is missing
		out = chat.provision_intake_profile()
		created = [c.args[0]["doctype"] for c in spine_fr.get_doc.call_args_list]
		self.assertIn("Chat Platform", created)
		self.assertTrue(out["platform_created"])
		self.assertFalse(out["created"])  # the profile was NOT re-created


class TestBrandAttributesFetch(unittest.TestCase):
	"""personality must use live Brand Attribute names (CONTRACT §4.5) — fetched from RP +
	cached (RP rate-limits get_brand_attributes to 60/hr). Best-effort: [] on any failure."""

	@patch("frappe.friday_core.connectors.client.send")
	@patch(f"{chat.__name__}.frappe")
	def test_fetches_parses_and_caches_for_full_ttl(self, fr, send):
		fr.cache.return_value.get_value.return_value = None  # cache miss
		send.return_value = {"message": ["Bold", "Heritage", "Playful"]}
		out = chat._brand_attributes()
		self.assertEqual(out, ["Bold", "Heritage", "Playful"])
		send.assert_called_once_with(chat.CONNECTOR_NAME, chat._BRAND_ATTR_PATH, {})
		self.assertEqual(fr.cache.return_value.set_value.call_args.kwargs["expires_in_sec"], chat._BRAND_ATTR_TTL)

	@patch("frappe.friday_core.connectors.client.send")
	@patch(f"{chat.__name__}.frappe")
	def test_cache_hit_skips_the_fetch(self, fr, send):
		fr.cache.return_value.get_value.return_value = '["Bold", "Calm"]'
		self.assertEqual(chat._brand_attributes(), ["Bold", "Calm"])
		send.assert_not_called()

	@patch("frappe.friday_core.connectors.client.send")
	@patch(f"{chat.__name__}.frappe")
	def test_failure_returns_empty_and_caches_briefly(self, fr, send):
		fr.cache.return_value.get_value.return_value = None
		send.return_value = None  # connector disabled / RP down — send never raises
		self.assertEqual(chat._brand_attributes(), [])
		self.assertEqual(fr.cache.return_value.set_value.call_args.kwargs["expires_in_sec"], 60)


class TestExtractionFieldsConstrainPersonality(unittest.TestCase):
	@patch(f"{chat.__name__}._brand_attributes")
	def test_personality_constrained_to_live_attributes(self, attrs):
		attrs.return_value = ["Bold", "Heritage", "Playful"]
		fields = chat._extraction_fields()
		personality = next(f for f in fields if f["name"] == "personality")
		for a in ("Bold", "Heritage", "Playful"):
			self.assertIn(a, personality["description"])
		self.assertIn("ONLY these", personality["description"])
		self.assertEqual(len(fields), len(chat._EXTRACTION_FIELDS))  # nothing dropped

	@patch(f"{chat.__name__}._brand_attributes")
	def test_falls_back_to_static_vocab_when_no_attributes(self, attrs):
		attrs.return_value = []
		self.assertIs(chat._extraction_fields(), chat._EXTRACTION_FIELDS)


class TestSystemPromptCoversRequiredFields(unittest.TestCase):
	"""#169's guarantee, restructured for §4.8: when RP sends no per-turn context, the
	general-essentials fallback still steers through the key fields before inviting review."""

	def test_general_fallback_still_covers_the_essentials(self):
		p = chat._build_system_prompt(None).lower()
		for essential in ("name", "email", "brand name", "different", "naming", "feel"):
			self.assertIn(essential, p)
		self.assertIn("review", p)


class TestChatFirstIntake(unittest.TestCase):
	"""CONTRACT §4.8 — the chat is the WHOLE intake. RP sends per-turn missing-field lists;
	Friday steers the interview toward them (required first), closes with 'Review & pay' when
	both are empty, adds the 6 new fields, and never refuses a lawful category."""

	def test_new_fields_are_in_the_vocabulary(self):
		names = {f["name"] for f in chat._FIELDS}
		for f in ("brand_story", "brand_surfaces", "color_preferences", "brand_animal", "brand_symbol", "logo_style"):
			self.assertIn(f, names)

	def test_logo_style_names_its_exact_options(self):
		desc = {f["name"]: f["description"] for f in chat._FIELDS}["logo_style"]
		for opt in ("Wordmark (text only)", "Icon / symbol", "Combination", "Not sure"):
			self.assertIn(opt, desc)

	def test_new_field_delta_survives_wire_tagging(self):
		# A new field MUST be in _FIELD_STEP or wire_deltas silently drops its delta.
		out = chat.wire_deltas([{"field": "brand_animal", "value": "owl", "confidence": 0.8}])
		self.assertEqual(len(out), 1)
		self.assertEqual(out[0]["step"], "taste")

	def test_never_touch_fields_still_absent(self):
		names = {f["name"] for f in chat._FIELDS}
		for forbidden in ("password", "gate_commitment", "terms_accepted"):
			self.assertNotIn(forbidden, names)

	def test_prompt_steers_to_missing_required_first(self):
		p = chat._build_system_prompt(
			{"missing_required": ["email", "what_you_do"], "missing_questionnaire": ["brand_animal"]}
		)
		self.assertIn("PRIORITY ORDER", p)
		self.assertIn("MUST cover", p)
		# required hints render in order, before the questionnaire section
		self.assertLess(p.index("email"), p.index("what the brand does"))
		self.assertIn("Then, in this order", p)
		self.assertIn("animal", p)  # the questionnaire field's hint
		self.assertIn("never re-ask", p.lower())

	def test_prompt_closes_when_both_lists_empty(self):
		p = chat._build_system_prompt({"missing_required": [], "missing_questionnaire": []})
		self.assertIn("Review & pay", p)
		self.assertIn("not ask", p.lower())

	def test_prompt_without_context_uses_general_essentials(self):
		p = chat._build_system_prompt(None)
		self.assertIn("name and email", p)  # from _GENERAL_ESSENTIALS
		self.assertNotIn("PRIORITY ORDER", p)

	def test_every_prompt_variant_forbids_refusal(self):
		# The refusal bug: a lawful-but-sensitive brand category got no reply. Every variant of
		# the system prompt must tell the model never to refuse.
		for ctx in (
			None,
			{"missing_required": ["email"], "missing_questionnaire": []},
			{"missing_required": [], "missing_questionnaire": []},
		):
			self.assertIn("NEVER refuse", chat._build_system_prompt(ctx))


if __name__ == "__main__":
	unittest.main()
