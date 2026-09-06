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

_I = "friday.friday_core.gateway.interrupt"
_C = "friday.friday_core.gateway.commands"


class TestForceKillSession(unittest.TestCase):
	# Mimic frappe's create_job_id transform ({site}|| prefix, ':'→'|') so the
	# test pins that the chat job id is TRANSFORMED before send_stop_job_command.
	# (The original bug: the RAW id was passed → NoSuchJob → nothing was killed.
	# The old test mocked send_stop and never asserted the id, so it stayed green.)
	@patch("frappe.utils.background_jobs.create_job_id", side_effect=lambda j: f"SITE||{j.replace(':', '|')}")
	@patch(f"{_I}._emit_force_kill")
	@patch(f"{_I}.send_stop_job_command")
	@patch(f"{_I}.get_queue")
	@patch(f"{_I}.collect_active_subtree", return_value=["T1", "T2"])
	@patch(f"{_I}.request_interrupt")
	@patch(f"{_I}.frappe")
	def test_kills_chat_job_transformed_and_cooperatively_stops_tasks(
		self, fr, req, _sub, _gq, stop, _emit, _cji
	):
		from friday.friday_core.gateway import interrupt

		fr.get_all.return_value = [{"job_id": "friday-gw::CM-9::lock0"}]
		fr.utils.now_datetime.return_value = "NOW"

		result = interrupt.force_kill_session("S-1", "op@x.com")

		# THE FIX: the chat job is SIGTERM'd with the create_job_id-TRANSFORMED key,
		# exactly once. Tasks are NOT send_stop'd by name (their rq id is a UUID).
		stopped = [c.args[1] for c in stop.call_args_list]
		self.assertEqual(stopped, ["SITE||friday-gw||CM-9||lock0"])
		self.assertNotIn("task:T1", stopped)
		self.assertEqual(result["jobs_cancelled"], 1)  # only the chat job

		# Tasks are stopped cooperatively (interrupt flag on task:: session) and
		# marked ForceKilled with the audit fields.
		req.assert_any_call("S-1")  # chat session
		req.assert_any_call("task::T1")
		req.assert_any_call("task::T2")
		self.assertEqual(set(result["tasks_now_forcekilled"]), {"T1", "T2"})
		task_writes = [c for c in fr.db.set_value.call_args_list if c.args[0] == "Task"]
		self.assertEqual(len(task_writes), 2)
		payload = task_writes[0].args[2]
		self.assertEqual(payload["workflow_state"], "ForceKilled")
		self.assertEqual(payload["force_killed_by"], "op@x.com")

	@patch("frappe.utils.background_jobs.create_job_id", side_effect=lambda j: f"SITE||{j}")
	@patch(f"{_I}._emit_force_kill")
	@patch(f"{_I}.send_stop_job_command", side_effect=Exception("InvalidJobOperation"))
	@patch(f"{_I}.get_queue")
	@patch(f"{_I}.collect_active_subtree", return_value=[])
	@patch(f"{_I}.request_interrupt")
	@patch(f"{_I}.frappe")
	def test_already_finished_job_is_idempotent(self, fr, req, _sub, _gq, _stop, _emit, _cji):
		from friday.friday_core.gateway import interrupt

		fr.get_all.return_value = [{"job_id": "friday-gw::CM-9::lock0"}]
		result = interrupt.force_kill_session("S-1", "op@x.com")
		# a job that's already finished → no-op, counted, never an error
		self.assertEqual(result["jobs_cancelled"], 0)
		self.assertEqual(result["jobs_already_done"], 1)

	@patch("frappe.utils.background_jobs.create_job_id", side_effect=lambda j: f"SITE||{j}")
	@patch(f"{_I}._emit_force_kill")
	@patch(f"{_I}.send_stop_job_command")
	@patch(f"{_I}.get_queue")
	@patch(f"{_I}.collect_active_subtree", return_value=[])
	@patch(f"{_I}.request_interrupt")
	@patch(f"{_I}.frappe")
	def test_nothing_running_is_safe(self, fr, req, _sub, _gq, stop, _emit, _cji):
		from friday.friday_core.gateway import interrupt

		fr.get_all.return_value = []  # no running turn for this session
		result = interrupt.force_kill_session("S-1", "op@x.com")
		stop.assert_not_called()
		self.assertEqual(result["jobs_cancelled"], 0)
		self.assertEqual(result["tasks_now_forcekilled"], [])


class TestStopForceCommand(unittest.TestCase):
	@patch(f"{_C}.frappe")
	def test_stop_force_calls_force_kill_for_operator(self, fr):
		from friday.friday_core.gateway import commands

		fr.get_roles.return_value = ["Friday Operator"]
		with patch(
			"friday.friday_core.gateway.interrupt.force_kill_session",
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
		from friday.friday_core.gateway import commands

		fr.get_roles.return_value = []  # not an operator → gated at dispatch
		with patch("friday.friday_core.gateway.interrupt.force_kill_session") as fk:
			result = commands.dispatch_command(
				platform="raven", session_id="S-1", user="x@x.com", raw="/stop force"
			)
		fk.assert_not_called()
		self.assertFalse(result.ok)

	@patch(f"{_C}.frappe")
	def test_plain_stop_stays_cooperative(self, fr):
		from friday.friday_core.gateway import commands

		fr.get_roles.return_value = ["Friday Operator"]
		with (
			patch("friday.friday_core.gateway.interrupt.request_interrupt"),
			patch("friday.friday_core.gateway.interrupt.cascade_interrupt", return_value=0),
			patch("friday.friday_core.gateway.interrupt.force_kill_session") as fk,
		):
			result = commands.dispatch_command(
				platform="raven", session_id="S-1", user="op@x.com", raw="/stop"
			)
		fk.assert_not_called()  # plain /stop must NOT hard-kill
		self.assertTrue(result.ok)


if __name__ == "__main__":
	unittest.main()
