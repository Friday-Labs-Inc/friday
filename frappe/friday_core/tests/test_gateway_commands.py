# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""
Tests for the gateway command surface (Design 82, LOCKED).

Tests-first: these pin the `gateway/commands.py` dispatcher contract BEFORE the
handler code exists, per the workflow rule. Mock-based — no DB, no redis — so
they run on the dev Mac and in CI.

What they pin (the LOCKED decisions):
  D1  — a leading "/" is a command; anything else is NOT (adapter routes plain
        text to run_turn unchanged).
  Q1  — one shared `dispatch_command()`; adapters only detect + deliver.
  Q2  — v1 set is /approve, /deny, /status, /help. Unknown → friendly error.
  Q4  — operator-tier commands (/approve, /deny) require the `Friday Operator`
        Frappe role; open commands (/status, /help) require none.
  Q5  — bare /approve targets the channel's OLDEST Pending Workflow Request
        (order_by creation asc, limit 1); an explicit id overrides.
"""

import unittest
from unittest.mock import MagicMock, patch

_C = "frappe.friday_core.gateway.commands"


class TestCommandDetection(unittest.TestCase):
	"""D1 — what counts as a command."""

	def test_leading_slash_is_a_command(self):
		from frappe.friday_core.gateway import commands

		self.assertTrue(commands.is_command("/status"))
		self.assertTrue(commands.is_command("  /approve BB-0034  "))  # leading space tolerated

	def test_plain_text_is_not_a_command(self):
		# The regression guard: normal conversation must still reach run_turn.
		from frappe.friday_core.gateway import commands

		self.assertFalse(commands.is_command("hello there"))
		self.assertFalse(commands.is_command("what's the status?"))
		self.assertFalse(commands.is_command(""))

	def test_parse_splits_name_and_args(self):
		from frappe.friday_core.gateway import commands

		name, args = commands.parse_command("/approve BB-0034 looks good")
		self.assertEqual(name, "approve")
		self.assertEqual(args, ["BB-0034", "looks", "good"])

		name, args = commands.parse_command("/status")
		self.assertEqual(name, "status")
		self.assertEqual(args, [])


class TestUnknownCommand(unittest.TestCase):
	"""Q2 — unknown command is handled (not passed to the agent), with help."""

	def test_unknown_command_returns_friendly_error(self):
		from frappe.friday_core.gateway import commands

		with patch(f"{_C}.frappe"):
			result = commands.dispatch_command(
				platform="raven", session_id="S-1", user="op@x.com", raw="/wat"
			)
		self.assertTrue(result.handled)
		self.assertFalse(result.ok)
		self.assertIn("help", result.reply.lower())


class TestOpenCommands(unittest.TestCase):
	"""Q4 — /status and /help need no role."""

	def test_status_needs_no_role_and_reports_state(self):
		from frappe.friday_core.gateway import commands

		with patch(f"{_C}.frappe") as fr:
			fr.get_roles.return_value = []  # no operator role
			result = commands.dispatch_command(
				platform="raven", session_id="S-1", user="anyone@x.com", raw="/status"
			)
		self.assertTrue(result.ok)
		# status is read-only: it must NOT touch the approval workflow.
		self.assertTrue(result.handled)

	def test_help_lists_v1_commands(self):
		from frappe.friday_core.gateway import commands

		with patch(f"{_C}.frappe") as fr:
			fr.get_roles.return_value = []
			result = commands.dispatch_command(
				platform="raven", session_id="S-1", user="anyone@x.com", raw="/help"
			)
		self.assertTrue(result.ok)
		for cmd in ("/approve", "/deny", "/status"):
			self.assertIn(cmd, result.reply)


class TestApprovePermission(unittest.TestCase):
	"""Q4 — /approve requires the Friday Operator role."""

	def test_approve_refused_without_operator_role(self):
		from frappe.friday_core.gateway import commands

		with (
			patch(f"{_C}.frappe") as fr,
			patch(f"{_C}.approve") as mock_approve,
		):
			fr.get_roles.return_value = ["Some Other Role"]
			result = commands.dispatch_command(
				platform="raven", session_id="S-1", user="nobody@x.com", raw="/approve"
			)
		self.assertTrue(result.handled)
		self.assertFalse(result.ok)
		mock_approve.assert_not_called()  # the gate held


class TestApproveTargeting(unittest.TestCase):
	"""Q5 — which Workflow Request /approve acts on."""

	def test_bare_approve_targets_oldest_pending_in_channel(self):
		from frappe.friday_core.gateway import commands

		with (
			patch(f"{_C}.frappe") as fr,
			patch(f"{_C}.approve") as mock_approve,
		):
			fr.get_roles.return_value = ["Friday Operator"]
			# Oldest-first, limited to one: the dispatcher must ask for asc/limit 1.
			fr.get_all.return_value = [{"name": "WR-OLDEST"}]
			result = commands.dispatch_command(
				platform="raven", session_id="S-1", user="op@x.com", raw="/approve"
			)

		# It resolved via a session-scoped, Pending, oldest-first query.
		self.assertTrue(fr.get_all.called)
		gkw = fr.get_all.call_args.kwargs
		self.assertEqual(gkw["filters"]["session_id"], "S-1")
		self.assertEqual(gkw["filters"]["status"], "Pending")
		self.assertEqual(gkw["order_by"], "creation asc")
		self.assertEqual(gkw["limit"], 1)
		# And approved exactly that request.
		mock_approve.assert_called_once()
		self.assertEqual(mock_approve.call_args.args[0], "WR-OLDEST")
		self.assertTrue(result.ok)

	def test_explicit_id_overrides_resolution(self):
		from frappe.friday_core.gateway import commands

		with (
			patch(f"{_C}.frappe") as fr,
			patch(f"{_C}.approve") as mock_approve,
		):
			fr.get_roles.return_value = ["Friday Operator"]
			result = commands.dispatch_command(
				platform="raven", session_id="S-1", user="op@x.com", raw="/approve WR-NAMED"
			)
		# Explicit id: no need to query for the oldest.
		mock_approve.assert_called_once()
		self.assertEqual(mock_approve.call_args.args[0], "WR-NAMED")
		self.assertTrue(result.ok)

	def test_approve_with_no_pending_reports_nothing_to_do(self):
		from frappe.friday_core.gateway import commands

		with (
			patch(f"{_C}.frappe") as fr,
			patch(f"{_C}.approve") as mock_approve,
		):
			fr.get_roles.return_value = ["Friday Operator"]
			fr.get_all.return_value = []  # nothing pending
			result = commands.dispatch_command(
				platform="raven", session_id="S-1", user="op@x.com", raw="/approve"
			)
		mock_approve.assert_not_called()
		self.assertTrue(result.handled)
		self.assertFalse(result.ok)
		self.assertIn("pending", result.reply.lower())


class TestDeny(unittest.TestCase):
	"""Q2/Q5 — /deny mirrors /approve and records a reason."""

	def test_deny_rejects_oldest_with_reason(self):
		from frappe.friday_core.gateway import commands

		with (
			patch(f"{_C}.frappe") as fr,
			patch(f"{_C}.reject") as mock_reject,
		):
			fr.get_roles.return_value = ["Friday Operator"]
			fr.get_all.return_value = [{"name": "WR-OLDEST"}]
			result = commands.dispatch_command(
				platform="raven", session_id="S-1", user="op@x.com", raw="/deny too risky"
			)
		mock_reject.assert_called_once()
		self.assertEqual(mock_reject.call_args.args[0], "WR-OLDEST")
		# The free-text reason rides along.
		self.assertIn("too risky", mock_reject.call_args.kwargs.get("reason", ""))
		self.assertTrue(result.ok)


class TestStop(unittest.TestCase):
	"""Design 83 — /stop sets the session interrupt flag (operator-tier)."""

	@patch("frappe.friday_core.gateway.interrupt.cascade_interrupt", return_value=0)
	@patch("frappe.friday_core.gateway.interrupt.request_interrupt")
	@patch(f"{_C}.frappe")
	def test_stop_sets_interrupt_flag_for_operator(self, fr, mock_request, _cascade):
		from frappe.friday_core.gateway import commands

		fr.get_roles.return_value = ["Friday Operator"]
		result = commands.dispatch_command(
			platform="raven", session_id="S-1", user="op@x.com", raw="/stop"
		)
		mock_request.assert_called_once_with("S-1")
		self.assertTrue(result.ok)
		self.assertIn("stop", result.reply.lower())

	@patch("frappe.friday_core.gateway.interrupt.request_interrupt")
	@patch(f"{_C}.frappe")
	def test_stop_refused_without_operator_role(self, fr, mock_request):
		from frappe.friday_core.gateway import commands

		fr.get_roles.return_value = ["Some Other Role"]
		result = commands.dispatch_command(
			platform="raven", session_id="S-1", user="nobody@x.com", raw="/stop"
		)
		mock_request.assert_not_called()  # the gate held — no interrupt set
		self.assertFalse(result.ok)


class TestSteer(unittest.TestCase):
	"""Design 84 — /steer pushes a mid-turn nudge (operator-tier)."""

	@patch("frappe.friday_core.gateway.steer.push_steer")
	@patch(f"{_C}.frappe")
	def test_steer_pushes_text_for_operator(self, fr, mock_push):
		from frappe.friday_core.gateway import commands

		fr.get_roles.return_value = ["Friday Operator"]
		result = commands.dispatch_command(
			platform="raven", session_id="S-1", user="op@x.com", raw="/steer use the staging DB"
		)
		mock_push.assert_called_once_with("S-1", "use the staging DB")
		self.assertTrue(result.ok)

	@patch("frappe.friday_core.gateway.steer.push_steer")
	@patch(f"{_C}.frappe")
	def test_steer_without_text_is_rejected(self, fr, mock_push):
		from frappe.friday_core.gateway import commands

		fr.get_roles.return_value = ["Friday Operator"]
		result = commands.dispatch_command(
			platform="raven", session_id="S-1", user="op@x.com", raw="/steer"
		)
		mock_push.assert_not_called()
		self.assertFalse(result.ok)
		self.assertIn("usage", result.reply.lower())

	@patch("frappe.friday_core.gateway.steer.push_steer")
	@patch(f"{_C}.frappe")
	def test_steer_refused_without_operator_role(self, fr, mock_push):
		from frappe.friday_core.gateway import commands

		fr.get_roles.return_value = []
		result = commands.dispatch_command(
			platform="raven", session_id="S-1", user="nobody@x.com", raw="/steer hi"
		)
		mock_push.assert_not_called()
		self.assertFalse(result.ok)


if __name__ == "__main__":
	unittest.main()
