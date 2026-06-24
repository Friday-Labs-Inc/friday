# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""
Tests for `/stop force` — hard-kill an in-flight turn (Design 83b, CORRECTED).

The original locked design had three errors (caught before implementation):
  - it killed via Job.cancel() — which does NOT stop a RUNNING job, only dequeues
    a not-yet-started one. We use rq's send_stop_job_command (SIGTERMs the horse).
  - it found jobs by kwargs.message.session_id — a kwarg Friday's job never has.
    We use Chat Message.job_id (the chat turn) + the Design 85 cascade subtree
    (delegated task jobs named `task:{name}`).
  - it changed the reconciler's stale-Executing auto-heal to ForceKilled, which
    removes the retry budget. We leave the reconciler alone — ForceKilled is
    operator-initiated ONLY.

These pin the corrected behavior. Mock-based.
"""

import unittest
from unittest.mock import patch

_I = "frappe.friday_core.gateway.interrupt"
_C = "frappe.friday_core.gateway.commands"


class TestForceKillSession(unittest.TestCase):
	@patch(f"{_I}._emit_force_kill")
	@patch(f"{_I}.send_stop_job_command")
	@patch(f"{_I}.get_queue")
	@patch(f"{_I}.collect_active_subtree", return_value=["T1", "T2"])
	@patch(f"{_I}.request_interrupt")
	@patch(f"{_I}.frappe")
	def test_kills_chat_job_and_forcekills_subtree(self, fr, req, _sub, _gq, stop, _emit):
		from frappe.friday_core.gateway import interrupt

		fr.get_all.return_value = [{"job_id": "friday-gw::CM-9::lock0"}]
		fr.utils.now_datetime.return_value = "NOW"

		result = interrupt.force_kill_session("S-1", "op@x.com")

		# belt-and-suspenders cooperative flag is set too
		req.assert_called_once_with("S-1")
		# the chat turn job AND both delegated task jobs are stopped (the REAL
		# primitive: send_stop_job_command, not Job.cancel)
		stopped = [c.args[1] for c in stop.call_args_list]
		self.assertIn("friday-gw::CM-9::lock0", stopped)
		self.assertIn("task:T1", stopped)
		self.assertIn("task:T2", stopped)
		self.assertEqual(result["jobs_cancelled"], 3)
		# the delegated tasks are marked ForceKilled with the audit fields
		self.assertEqual(set(result["tasks_now_forcekilled"]), {"T1", "T2"})
		task_writes = [c for c in fr.db.set_value.call_args_list if c.args[0] == "Task"]
		self.assertEqual(len(task_writes), 2)
		payload = task_writes[0].args[2]
		self.assertEqual(payload["workflow_state"], "ForceKilled")
		self.assertEqual(payload["force_killed_by"], "op@x.com")
		self.assertEqual(payload["force_kill_reason"], "operator /stop force")

	@patch(f"{_I}._emit_force_kill")
	@patch(f"{_I}.send_stop_job_command", side_effect=Exception("InvalidJobOperation"))
	@patch(f"{_I}.get_queue")
	@patch(f"{_I}.collect_active_subtree", return_value=[])
	@patch(f"{_I}.request_interrupt")
	@patch(f"{_I}.frappe")
	def test_already_finished_job_is_idempotent(self, fr, req, _sub, _gq, _stop, _emit):
		from frappe.friday_core.gateway import interrupt

		fr.get_all.return_value = [{"job_id": "friday-gw::CM-9::lock0"}]
		result = interrupt.force_kill_session("S-1", "op@x.com")
		# a job that's already finished → no-op, counted, never an error
		self.assertEqual(result["jobs_cancelled"], 0)
		self.assertEqual(result["jobs_already_done"], 1)

	@patch(f"{_I}._emit_force_kill")
	@patch(f"{_I}.send_stop_job_command")
	@patch(f"{_I}.get_queue")
	@patch(f"{_I}.collect_active_subtree", return_value=[])
	@patch(f"{_I}.request_interrupt")
	@patch(f"{_I}.frappe")
	def test_nothing_running_is_safe(self, fr, req, _sub, _gq, stop, _emit):
		from frappe.friday_core.gateway import interrupt

		fr.get_all.return_value = []  # no running turn for this session
		result = interrupt.force_kill_session("S-1", "op@x.com")
		stop.assert_not_called()
		self.assertEqual(result["jobs_cancelled"], 0)
		self.assertEqual(result["tasks_now_forcekilled"], [])


class TestStopForceCommand(unittest.TestCase):
	@patch(f"{_C}.frappe")
	def test_stop_force_calls_force_kill_for_operator(self, fr):
		from frappe.friday_core.gateway import commands

		fr.get_roles.return_value = ["Friday Operator"]
		with patch(
			"frappe.friday_core.gateway.interrupt.force_kill_session",
			return_value={"jobs_cancelled": 2, "jobs_already_done": 0, "tasks_now_forcekilled": ["T1"]},
		) as fk:
			result = commands.dispatch_command(
				platform="raven", session_id="S-1", user="op@x.com", raw="/stop force"
			)
		fk.assert_called_once_with("S-1", "op@x.com")
		self.assertTrue(result.ok)
		self.assertIn("force", result.reply.lower())

	@patch(f"{_C}.frappe")
	def test_stop_force_refused_for_non_operator(self, fr):
		from frappe.friday_core.gateway import commands

		fr.get_roles.return_value = []  # not an operator → gated at dispatch
		with patch("frappe.friday_core.gateway.interrupt.force_kill_session") as fk:
			result = commands.dispatch_command(
				platform="raven", session_id="S-1", user="x@x.com", raw="/stop force"
			)
		fk.assert_not_called()
		self.assertFalse(result.ok)

	@patch(f"{_C}.frappe")
	def test_plain_stop_stays_cooperative(self, fr):
		from frappe.friday_core.gateway import commands

		fr.get_roles.return_value = ["Friday Operator"]
		with (
			patch("frappe.friday_core.gateway.interrupt.request_interrupt"),
			patch("frappe.friday_core.gateway.interrupt.cascade_interrupt", return_value=0),
			patch("frappe.friday_core.gateway.interrupt.force_kill_session") as fk,
		):
			result = commands.dispatch_command(
				platform="raven", session_id="S-1", user="op@x.com", raw="/stop"
			)
		fk.assert_not_called()  # plain /stop must NOT hard-kill
		self.assertTrue(result.ok)


if __name__ == "__main__":
	unittest.main()
