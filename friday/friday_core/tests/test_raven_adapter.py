# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""
Unit tests for the Raven surface adapter (design 58, LOCKED).

Mock-based — no DB, no Raven app needed. Pins the locked contract:
  Q3 — DMs answered only when the bot is a channel member; channels only on
       an explicit bot @mention (read from Raven's extracted mentions table)
  Q4 — session = the Raven channel id; profile via platform routing
  Q6 — bot-authored messages never re-enter (no self-loops); a Raven posting
       failure rolls back to a savepoint and never breaks the gateway
  absent-Raven → outbound is a no-op (table guard)
"""

import unittest
from unittest.mock import MagicMock, patch

from friday.friday_core.surfaces import raven_adapter

_A = "friday.friday_core.surfaces.raven_adapter"


def _raven_msg(**overrides):
	values = {
		"is_bot_message": 0,
		"bot": None,
		"message_type": "Text",
		"content": "hello friday",
		"mentions": [],
	}
	values.update(overrides)
	doc = MagicMock()
	doc.get.side_effect = lambda k: values.get(k)
	doc.channel_id = values.get("channel_id", "CH-001")
	doc.owner = values.get("owner", "human@example.com")
	return doc


def _channel(is_dm=1, is_self=0):
	ch = MagicMock()
	ch.is_direct_message = is_dm
	ch.is_self_message = is_self
	return ch


class TestInbound(unittest.TestCase):
	@patch(f"{_A}.frappe")
	def test_bot_messages_are_skipped(self, mock_frappe):
		raven_adapter.handle_raven_message(_raven_msg(is_bot_message=1))
		mock_frappe.get_doc.assert_not_called()

	@patch(f"{_A}.frappe")
	def test_non_text_messages_are_skipped(self, mock_frappe):
		raven_adapter.handle_raven_message(_raven_msg(message_type="Image"))
		mock_frappe.get_doc.assert_not_called()

	@patch(f"{_A}._friday_bot_user", return_value=None)
	@patch(f"{_A}.frappe")
	def test_unprovisioned_surface_is_a_noop(self, mock_frappe, _bot):
		raven_adapter.handle_raven_message(_raven_msg())
		mock_frappe.get_doc.assert_not_called()

	@patch(f"{_A}._resolve_profile", return_value="Friday")
	@patch(f"{_A}._friday_bot_user", return_value="friday-bot")
	@patch(f"{_A}.frappe")
	def test_dm_without_bot_membership_is_skipped(self, mock_frappe, _bot, _prof):
		mock_frappe.db.get_value.return_value = _channel(is_dm=1)
		mock_frappe.db.exists.return_value = False  # bot not a member
		raven_adapter.handle_raven_message(_raven_msg())
		mock_frappe.get_doc.assert_not_called()

	@patch(f"{_A}._resolve_profile", return_value="Friday")
	@patch(f"{_A}._friday_bot_user", return_value="friday-bot")
	@patch(f"{_A}.frappe")
	def test_dm_with_membership_writes_inbound_row(self, mock_frappe, _bot, _prof):
		mock_frappe.db.get_value.return_value = _channel(is_dm=1)
		mock_frappe.db.exists.return_value = True
		raven_adapter.handle_raven_message(_raven_msg(content="hi there"))
		payload = mock_frappe.get_doc.call_args[0][0]
		self.assertEqual(payload["doctype"], "Chat Message")
		self.assertEqual(payload["platform"], "raven")
		self.assertEqual(payload["direction"], "inbound")
		self.assertEqual(payload["session_id"], "CH-001")  # Q4
		self.assertEqual(payload["agent_profile"], "Friday")
		self.assertEqual(payload["content"], "hi there")
		self.assertEqual(payload["sender_id"], "human@example.com")

	@patch(f"{_A}._resolve_profile", return_value="Friday")
	@patch(f"{_A}._friday_bot_user", return_value="friday-bot")
	@patch(f"{_A}.frappe")
	def test_channel_without_mention_is_skipped(self, mock_frappe, _bot, _prof):
		mock_frappe.db.get_value.return_value = _channel(is_dm=0)
		other = MagicMock()
		other.user = "someone-else"
		raven_adapter.handle_raven_message(_raven_msg(mentions=[other]))
		mock_frappe.get_doc.assert_not_called()

	@patch(f"{_A}._resolve_profile", return_value="Friday")
	@patch(f"{_A}._friday_bot_user", return_value="friday-bot")
	@patch(f"{_A}.frappe")
	def test_channel_with_bot_mention_writes_inbound_row(self, mock_frappe, _bot, _prof):
		# The channel path now does two get_value lookups: the channel, then the
		# bot's display label (for the mention strip). Distinguish by doctype.
		mock_frappe.db.get_value.side_effect = lambda dt, *a, **k: (
			_channel(is_dm=0) if dt == "Raven Channel" else "Friday"
		)
		mention = MagicMock()
		mention.user = "friday-bot"
		raven_adapter.handle_raven_message(_raven_msg(mentions=[mention]))
		self.assertEqual(mock_frappe.get_doc.call_args[0][0]["platform"], "raven")

	@patch(f"{_A}._resolve_profile", return_value="Friday")
	@patch(f"{_A}._friday_bot_user", return_value="friday-bot")
	@patch(f"{_A}.frappe")
	def test_self_message_channel_is_skipped(self, mock_frappe, _bot, _prof):
		mock_frappe.db.get_value.return_value = _channel(is_dm=1, is_self=1)
		raven_adapter.handle_raven_message(_raven_msg())
		mock_frappe.get_doc.assert_not_called()


class TestOutbound(unittest.TestCase):
	def _outbound(self, platform="raven"):
		doc = MagicMock()
		doc.direction = "outbound"
		doc.platform = platform
		doc.session_id = "CH-001"
		doc.content = "**reply** from the agent"
		doc.is_mirror = 0
		return doc

	@patch(f"{_A}.frappe")
	def test_non_raven_rows_are_ignored(self, mock_frappe):
		raven_adapter.handle_outbound_to_raven(self._outbound(platform="cli"))
		mock_frappe.get_doc.assert_not_called()

	@patch(f"{_A}.frappe")
	def test_absent_raven_is_a_noop(self, mock_frappe):
		mock_frappe.db.table_exists.return_value = False
		raven_adapter.handle_outbound_to_raven(self._outbound())
		mock_frappe.get_doc.assert_not_called()

	@patch(f"{_A}.frappe")
	def test_posts_via_bot_send_message_markdown(self, mock_frappe):
		mock_frappe.db.table_exists.return_value = True
		bot = MagicMock()
		mock_frappe.get_doc.return_value = bot
		raven_adapter.handle_outbound_to_raven(self._outbound())
		mock_frappe.get_doc.assert_called_once_with("Raven Bot", "Friday")
		bot.send_message.assert_called_once_with(
			channel_id="CH-001", text="**reply** from the agent", markdown=True
		)

	@patch(f"{_A}.frappe")
	def test_post_failure_rolls_back_savepoint_and_never_raises(self, mock_frappe):
		mock_frappe.db.table_exists.return_value = True
		mock_frappe.get_doc.side_effect = RuntimeError("raven exploded")
		raven_adapter.handle_outbound_to_raven(self._outbound())  # must not raise
		mock_frappe.db.rollback.assert_called_once_with(save_point="friday_raven_post")
		mock_frappe.log_error.assert_called_once()

	@patch(f"{_A}.frappe")
	def test_mirror_row_is_not_posted(self, mock_frappe):
		# A mirror row is recorded for the agent's history only — never re-posted.
		mock_frappe.db.table_exists.return_value = True
		row = self._outbound()
		row.is_mirror = 1
		raven_adapter.handle_outbound_to_raven(row)
		mock_frappe.get_doc.assert_not_called()


class TestCommands(unittest.TestCase):
	"""Design 82 — slash commands are caught at the edge, never run as a turn."""

	@patch(f"{_A}._handle_command")
	@patch(f"{_A}._friday_bot_user", return_value="friday-bot")
	@patch(f"{_A}.frappe")
	def test_dm_command_is_dispatched_not_conversational(self, mock_frappe, _bot, mock_handle):
		mock_frappe.db.get_value.return_value = _channel(is_dm=1)
		mock_frappe.db.exists.return_value = True  # bot is a member
		raven_adapter.handle_raven_message(_raven_msg(content="/status"))
		# Routed to the command handler, with the channel + sender + raw text.
		mock_handle.assert_called_once_with("CH-001", "human@example.com", "/status")
		# No conversational inbound row written by handle_raven_message itself.
		mock_frappe.get_doc.assert_not_called()

	@patch("friday.friday_core.gateway.commands.dispatch_command")
	@patch(f"{_A}.frappe")
	def test_handle_command_writes_two_audit_rows(self, mock_frappe, mock_dispatch):
		result = MagicMock()
		result.reply = "Session CH-001 — 0 pending approval(s)."
		mock_dispatch.return_value = result

		raven_adapter._handle_command("CH-001", "op@example.com", "/status")

		mock_dispatch.assert_called_once()
		# Two rows: the command (inbound) and its reply (outbound), both audited.
		self.assertEqual(mock_frappe.get_doc.call_count, 2)
		rows = [c[0][0] for c in mock_frappe.get_doc.call_args_list]
		self.assertTrue(all(r["is_command"] == 1 for r in rows))
		self.assertTrue(all(r["processed"] == 1 for r in rows))
		self.assertEqual(rows[0]["direction"], "inbound")
		self.assertEqual(rows[0]["content"], "/status")
		self.assertEqual(rows[1]["direction"], "outbound")
		self.assertEqual(rows[1]["content"], result.reply)
		self.assertEqual(rows[1]["sender_id"], "system")

	@patch(f"{_A}._handle_command")
	@patch(f"{_A}._friday_bot_user", return_value="friday-bot")
	@patch(f"{_A}.frappe")
	def test_channel_command_strips_mention_and_dispatches(self, mock_frappe, _bot, mock_handle):
		"""Regression: a channel "@Friday /status" must dispatch exactly like a DM
		"/status". Before the mention strip, is_command("@Friday /status") was False,
		so every operator command was unreachable from a channel (Design 82 break)."""
		mock_frappe.db.get_value.side_effect = lambda dt, *a, **k: (
			_channel(is_dm=0) if dt == "Raven Channel" else "Friday"
		)
		mention = MagicMock()
		mention.user = "friday-bot"
		raven_adapter.handle_raven_message(_raven_msg(content="@Friday /status", mentions=[mention]))
		# Dispatched with the mention stripped — identical to the DM path.
		mock_handle.assert_called_once_with("CH-001", "human@example.com", "/status")
		mock_frappe.get_doc.assert_not_called()

	@patch(f"{_A}._handle_command")
	@patch(f"{_A}._resolve_profile", return_value="Friday")
	@patch(f"{_A}._friday_bot_user", return_value="friday-bot")
	@patch(f"{_A}.frappe")
	def test_channel_mention_without_command_stays_conversational(
		self, mock_frappe, _bot, _prof, mock_handle
	):
		"""A plain "@Friday hello" must NOT be treated as a command — the strip
		feeds command detection only, and the remainder isn't a slash command."""
		mock_frappe.db.get_value.side_effect = lambda dt, *a, **k: (
			_channel(is_dm=0) if dt == "Raven Channel" else "Friday"
		)
		mention = MagicMock()
		mention.user = "friday-bot"
		raven_adapter.handle_raven_message(_raven_msg(content="@Friday hello", mentions=[mention]))
		mock_handle.assert_not_called()
		# Falls through to the conversational inbound row (original content kept).
		self.assertEqual(mock_frappe.get_doc.call_args[0][0]["content"], "@Friday hello")


class TestStripLeadingMention(unittest.TestCase):
	"""Pure (no-DB) coverage of the channel mention strip."""

	def test_strips_exact_label_then_command_survives(self):
		self.assertEqual(raven_adapter._strip_leading_mention("@Friday /help", "Friday"), "/help")

	def test_label_match_is_case_insensitive(self):
		self.assertEqual(raven_adapter._strip_leading_mention("@friday /stop", "Friday"), "/stop")

	def test_falls_back_to_generic_token_when_label_unknown(self):
		self.assertEqual(raven_adapter._strip_leading_mention("@Friday /deny", ""), "/deny")

	def test_non_command_mention_is_stripped_but_not_a_command(self):
		# Strip happens, but the remainder isn't a slash command → conversational.
		self.assertEqual(raven_adapter._strip_leading_mention("@Friday hello there", "Friday"), "hello there")

	def test_bare_command_is_unchanged(self):
		self.assertEqual(raven_adapter._strip_leading_mention("/help", "Friday"), "/help")


if __name__ == "__main__":
	unittest.main()
