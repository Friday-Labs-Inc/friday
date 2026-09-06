# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""The shared streaming-chat spine (surfaces/chat_spine.py).

DB-free. Pins the plumbing every chat surface inherits — the tag-split-safe <think>
filter, SSE framing, and the two hard-won lessons baked into the spine:

  #166→#168 — the SSE generator runs PAST the request's auto-commit, so `record_turn`
  must persist + audit + EXPLICITLY COMMIT (or every write is silently discarded), and a
  failure must roll back to a savepoint and land a durable Error Log row (not a void
  logger.warning).

  #168 root cause — `Chat Message.platform` is a Link, so every surface must register
  its Chat Platform row (`ensure_platform`) or every transcript insert fails.
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from frappe.friday_core.surfaces import chat_spine as spine

_S = spine.__name__


def _run_filter(chunks):
	f = spine.ThinkFilter()
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

	def test_a_lone_less_than_is_eventually_emitted(self):
		self.assertEqual(_run_filter(["a <", " b"]), "a < b")


class TestSse(unittest.TestCase):
	def test_framing(self):
		self.assertEqual(spine.sse({"type": "done"}), 'data: {"type": "done"}\n\n')


class TestRecordTurnPersistsAndAudits(unittest.TestCase):
	"""The #166→#168 governance fix, now owned by the spine for EVERY surface."""

	@patch(f"{_S}.record_usage")
	@patch(f"{_S}.frappe")
	def test_persists_transcript_records_all_usages_and_commits(self, fr, rec):
		provider = MagicMock()
		provider.get_default_model.return_value = "minimax-m3"

		spine.record_turn(
			"S1",
			"hi",
			"hello",
			provider,
			profile="Customer Intake",
			platform="demo-intake",
			usages=[{"total_tokens": 50}, {"total_tokens": 10}],
		)

		# Transcript: one inbound + one outbound Chat Message row, on the surface's platform.
		chat_rows = [c.args[0] for c in fr.get_doc.call_args_list if c.args[0]["doctype"] == "Chat Message"]
		self.assertEqual([r["direction"] for r in chat_rows], ["inbound", "outbound"])
		self.assertEqual({r["platform"] for r in chat_rows}, {"demo-intake"})
		# Usage audited for EVERY model call of the turn.
		self.assertEqual(rec.call_count, 2)
		self.assertEqual(rec.call_args_list[0].kwargs["usage"], {"total_tokens": 50})
		self.assertEqual(rec.call_args_list[1].kwargs["usage"], {"total_tokens": 10})
		self.assertEqual(rec.call_args_list[0].kwargs["profile_name"], "Customer Intake")
		# The load-bearing commit (without it the post-auto-commit writes vanish).
		fr.db.commit.assert_called_once()

	@patch(f"{_S}.record_usage")
	@patch(f"{_S}.frappe")
	def test_empty_usages_are_skipped(self, fr, rec):
		spine.record_turn(
			"S1", "hi", "hello", MagicMock(), profile="P", platform="x", usages=[{"total_tokens": 5}, {}]
		)
		self.assertEqual(rec.call_count, 1)  # the empty second usage logs nothing
		fr.db.commit.assert_called_once()

	@patch(f"{_S}.record_usage")
	@patch(f"{_S}.frappe")
	def test_persistence_failure_rolls_back_and_lands_in_error_log(self, fr, rec):
		# A persistence failure must not corrupt the reply already streamed — it rolls back
		# the poisoned tx and writes a durable, operator-visible Error Log row (never the
		# 0-byte-void logger.warning that hid the original gap).
		fr.get_doc.side_effect = RuntimeError("LinkValidationError")
		spine.record_turn("S1", "hi", "hello", MagicMock(), profile="P", platform="x", usages=[{}])
		fr.db.rollback.assert_called_with(save_point="friday_chat_persist")
		fr.log_error.assert_called()
		fr.db.commit.assert_called_once()  # the error-log row is still committed


class TestEnsurePlatform(unittest.TestCase):
	"""#168's root cause, generalized: every chat surface registers its Chat Platform row."""

	@patch(f"{_S}.frappe")
	def test_creates_the_platform_row_when_absent(self, fr):
		fr.db.exists.return_value = False
		out = spine.ensure_platform("demo-intake", "my_app.surfaces.intake_chat")
		row = fr.get_doc.call_args.args[0]
		self.assertEqual(row["doctype"], "Chat Platform")
		self.assertEqual(row["platform_name"], "demo-intake")
		self.assertEqual(row["enabled"], 0)  # registered for the Link, not gateway dispatch
		self.assertTrue(out["platform_created"])

	@patch(f"{_S}.frappe")
	def test_idempotent_when_present(self, fr):
		fr.db.exists.return_value = True
		out = spine.ensure_platform("demo-intake", "whatever")
		fr.get_doc.assert_not_called()
		self.assertFalse(out["platform_created"])


class TestStreamTurnStructuredPass(unittest.TestCase):
	"""stream_turn relays tokens, runs the surface's structured pass AFTER the reply, audits
	both calls, and never lets a pass failure break the stream."""

	def _run(self, provider, structured_pass, monkey):
		events = list(
			spine.stream_turn(
				"S1",
				"hi",
				profile="P",
				platform="x",
				system_prompt="sys",
				structured_pass=structured_pass,
			)
		)
		return events

	@patch(f"{_S}.record_turn")
	@patch(f"{_S}.history", return_value=[])
	@patch(f"{_S}.frappe")
	def test_tokens_then_events_then_done(self, fr, hist, rec):
		provider = MagicMock()
		provider.chat.side_effect = lambda messages, on_token=None: (
			[on_token(t) for t in ("hel", "lo")],
			{"content": "hello", "usage": {"total_tokens": 7}},
		)[1]
		with patch("frappe.friday_core.llm.provider.get_provider_for_profile", return_value=provider):
			fr.cache.return_value.lock.return_value.acquire.return_value = True

			def pass_(history_msgs, message, reply, prov):
				self.assertEqual(reply, "hello")
				return [{"type": "action", "kind": "gate_decision"}], {"total_tokens": 3}

			events = self._run(provider, pass_, fr)

		joined = "".join(events)
		self.assertIn('"type": "token"', joined)
		self.assertIn('"type": "action"', joined)
		self.assertTrue(events[-1].startswith('data: {"type": "done"}'))
		# Both calls' usage handed to the audit.
		rec.assert_called_once()
		self.assertEqual(rec.call_args.kwargs["usages"], [{"total_tokens": 7}, {"total_tokens": 3}])

	@patch(f"{_S}.record_turn")
	@patch(f"{_S}.history", return_value=[])
	@patch(f"{_S}.frappe")
	def test_structured_pass_failure_never_breaks_the_stream(self, fr, hist, rec):
		provider = MagicMock()
		provider.chat.return_value = {"content": "hello", "usage": {}}
		with patch("frappe.friday_core.llm.provider.get_provider_for_profile", return_value=provider):
			fr.cache.return_value.lock.return_value.acquire.return_value = True

			def boom(*a):
				raise RuntimeError("pass down")

			events = self._run(provider, boom, fr)
		self.assertTrue(events[-1].startswith('data: {"type": "done"}'))  # stream still closes

	@patch(f"{_S}.record_turn")
	@patch(f"{_S}.history", return_value=[])
	@patch(f"{_S}.frappe")
	def test_empty_reply_becomes_the_nudge_never_blank(self, fr, hist, rec):
		provider = MagicMock()
		provider.chat.return_value = {"content": "<think>only reasoning</think>", "usage": {}}
		with patch("frappe.friday_core.llm.provider.get_provider_for_profile", return_value=provider):
			fr.cache.return_value.lock.return_value.acquire.return_value = True
			events = self._run(provider, None, fr)
		joined = "".join(events)
		# The anti-blank guard fired (match a fragment that survives JSON \u-escaping).
		self.assertIn("could you tell me a little more", joined)
		# ...and the nudge is what got persisted as the reply.
		self.assertEqual(rec.call_args.args[2], spine.EMPTY_FALLBACK)


if __name__ == "__main__":
	unittest.main()
