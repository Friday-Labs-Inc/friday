# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""The streaming customer-intake turn (conversation/intake.py).

DB-free: a fake provider streams tokens for the conversational reply and returns JSON
for the extraction pass; history/persist are injected. Pins that one turn streams its
reply AND produces validated wizard deltas from a SEPARATE extraction pass.
"""

from __future__ import annotations

import unittest

from frappe.friday_core.conversation import intake

_FIELDS = [
	{"name": "business_name", "description": "the company name"},
	{"name": "industry", "description": "what the business does"},
]


class _FakeProvider:
	"""Streams `reply` token-by-token on the conversational call; returns `extraction`
	JSON on the extraction call (detected by the extraction system prompt)."""

	def __init__(self, reply, extraction):
		self.reply = reply
		self.extraction = extraction

	def chat(self, messages, tools=None, model=None, on_token=None):
		is_extraction = any("extract structured intake fields" in (m.get("content") or "") for m in messages)
		if is_extraction:
			return {"content": self.extraction}
		if on_token:
			for word in self.reply.split(" "):
				on_token(word + " ")
		return {"content": self.reply}


class TestParseDeltas(unittest.TestCase):
	def test_valid_deltas_pass(self):
		out = intake.parse_deltas(
			'{"deltas": [{"field": "business_name", "value": "Loop Coffee", "confidence": 0.9}]}', _FIELDS
		)
		self.assertEqual(out, [{"field": "business_name", "value": "Loop Coffee", "confidence": 0.9}])

	def test_unknown_field_is_dropped(self):
		out = intake.parse_deltas('{"deltas": [{"field": "ssn", "value": "x", "confidence": 1.0}]}', _FIELDS)
		self.assertEqual(out, [])

	def test_confidence_clamped_and_bad_json_is_empty(self):
		out = intake.parse_deltas(
			'{"deltas": [{"field": "industry", "value": "coffee", "confidence": 5}]}', _FIELDS
		)
		self.assertEqual(out[0]["confidence"], 1.0)
		self.assertEqual(intake.parse_deltas("not json at all", _FIELDS), [])

	def test_extraction_messages_carry_fields_and_transcript(self):
		msgs = intake.build_extraction_messages("user: hi", _FIELDS)
		user = msgs[-1]["content"]
		self.assertIn("business_name", user)
		self.assertIn("user: hi", user)


class TestExtractDeltas(unittest.TestCase):
	def test_provider_failure_yields_no_deltas(self):
		class _Boom:
			def chat(self, *a, **k):
				raise RuntimeError("model down")

		self.assertEqual(intake.extract_deltas("user: hi", _FIELDS, _Boom()), [])

	def test_no_fields_skips_the_pass(self):
		called = {"n": 0}

		class _Counting:
			def chat(self, *a, **k):
				called["n"] += 1
				return {"content": "{}"}

		self.assertEqual(intake.extract_deltas("t", [], _Counting()), [])
		self.assertEqual(called["n"], 0)  # no LLM call when there are no fields

	def test_on_usage_receives_the_extraction_calls_usage(self):
		# The extraction pass is a real model call and must be cost-auditable: when an
		# on_usage callback is given it gets the call's token usage (the gap that left the
		# streaming chat path with no LLM Usage Log rows).
		class _Provider:
			def chat(self, *a, **k):
				return {"content": '{"deltas": []}', "usage": {"total_tokens": 7}}

		seen = {}
		intake.extract_deltas("user: hi", _FIELDS, _Provider(), on_usage=seen.update)
		self.assertEqual(seen, {"total_tokens": 7})

	def test_on_usage_callback_failure_never_breaks_extraction(self):
		class _Provider:
			def chat(self, *a, **k):
				return {
					"content": '{"deltas": [{"field": "business_name", "value": "X", "confidence": 0.9}]}',
					"usage": {},
				}

		def boom(_u):
			raise RuntimeError("usage sink down")

		out = intake.extract_deltas("t", _FIELDS, _Provider(), on_usage=boom)
		self.assertEqual(out[0]["field"], "business_name")  # extraction still succeeded


class TestStreamIntakeTurn(unittest.TestCase):
	def test_turn_streams_reply_and_extracts_deltas(self):
		provider = _FakeProvider(
			reply="Nice to meet you Loop Coffee!",
			extraction='{"deltas": [{"field": "business_name", "value": "Loop Coffee", "confidence": 0.92}]}',
		)
		tokens = []
		out = intake.stream_intake_turn(
			"sess-1",
			"We're Loop Coffee, a roastery",
			system_prompt="You are an intake assistant.",
			fields=_FIELDS,
			provider=provider,
			history_fn=lambda: [],
			persist_fn=lambda *a: None,
			on_token=tokens.append,
		)
		# The reply streamed token-by-token...
		self.assertEqual("".join(tokens).strip(), "Nice to meet you Loop Coffee!")
		# ...the full reply came back...
		self.assertEqual(out["reply"], "Nice to meet you Loop Coffee!")
		# ...and the wizard delta was extracted by the separate pass.
		self.assertEqual(
			out["deltas"], [{"field": "business_name", "value": "Loop Coffee", "confidence": 0.92}]
		)

	def test_history_is_threaded_into_the_prompt(self):
		seen = {}

		class _Capture:
			def chat(self, messages, tools=None, model=None, on_token=None):
				if "extract structured intake fields" in (messages[0]["content"] or ""):
					return {"content": '{"deltas": []}'}
				seen["messages"] = messages
				return {"content": "ok"}

		intake.stream_intake_turn(
			"sess-2",
			"and we sell online",
			system_prompt="sys",
			fields=_FIELDS,
			provider=_Capture(),
			history_fn=lambda: [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}],
			persist_fn=lambda *a: None,
		)
		roles = [m["role"] for m in seen["messages"]]
		# system + 2 history + the new user message.
		self.assertEqual(roles, ["system", "user", "assistant", "user"])
		self.assertEqual(seen["messages"][-1]["content"], "and we sell online")

	def test_persist_failure_does_not_lose_the_reply(self):
		def boom(*a):
			raise RuntimeError("db hiccup")

		out = intake.stream_intake_turn(
			"sess-3",
			"hi",
			system_prompt="sys",
			fields=[],
			provider=_FakeProvider(reply="hello", extraction="{}"),
			history_fn=lambda: [],
			persist_fn=boom,
		)
		self.assertEqual(out["reply"], "hello")


if __name__ == "__main__":
	unittest.main()
