# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""
Unit tests for the kernel's command loop (design 60b, LOCKED).

Mock-based — no DB, no model. Pins:
  - dispatcher gating (Q3/Q7): milestones never dispatch; AND-deps must all
    be Completed; On Hold projects park their pipeline
  - the agentic runner (Q2): delegation-style isolation, summary envelope,
    Blocked + Issue on failure
  - the Project command-loop skills: validation + state changes

The domain halves (the write-back bridge and the studio event handlers) live
with their app, as design_studio/tests/test_command_center.py. The pipeline
template tests went with the pre-Design-75 pipeline they covered.
"""

import unittest
from unittest.mock import MagicMock, patch

from frappe.friday_core.skills import handlers_project
from frappe.friday_core.tasks import dispatcher as task_dispatcher

_D = "frappe.friday_core.tasks.dispatcher"
_H = "frappe.friday_core.skills.handlers_project"
_RUN = "frappe.friday_core.agent_runner.runner.run_turn"


def _task_doc(mode="agentic", deps=(), project="PRJ-1"):
	doc = MagicMock()
	values = {"execution_mode": mode, "depends_on": [MagicMock(task=d) for d in deps], "project": project}
	doc.get.side_effect = values.get
	doc.project = project
	return doc


class TestDispatcherGating(unittest.TestCase):
	@patch(f"{_D}.frappe")
	def test_milestones_never_dispatch(self, mock_frappe):
		self.assertFalse(task_dispatcher._ready_to_dispatch(_task_doc(mode="milestone")))
		mock_frappe.db.get_value.assert_not_called()

	@patch(f"{_D}.frappe")
	def test_incomplete_dependency_parks_task(self, mock_frappe):
		mock_frappe.db.get_value.return_value = "Executing"
		self.assertFalse(task_dispatcher._ready_to_dispatch(_task_doc(deps=["T-1"])))

	@patch(f"{_D}.frappe")
	def test_all_deps_completed_and_project_active_dispatches(self, mock_frappe):
		mock_frappe.db.get_value.side_effect = ["Completed", "Completed", "Active"]
		self.assertTrue(task_dispatcher._ready_to_dispatch(_task_doc(deps=["T-1", "T-2"])))

	@patch(f"{_D}.frappe")
	def test_on_hold_project_parks_pipeline(self, mock_frappe):
		mock_frappe.db.get_value.return_value = "On Hold"
		self.assertFalse(task_dispatcher._ready_to_dispatch(_task_doc(deps=())))


class TestAgenticRunner(unittest.TestCase):
	def _task(self):
		task = MagicMock()
		task.name = "TASK-7"
		task.title = "Strategy draft"
		task.description = "Read BB-0005 and draft."
		task.get.side_effect = {"execution_mode": "agentic"}.get
		return task

	@patch("frappe.friday_core.tasks.runner.now_datetime")
	@patch(_RUN, return_value="Strategy drafted.")
	@patch("frappe.friday_core.tasks.runner.frappe")
	def test_agentic_success_isolation_and_envelope(self, mock_frappe, mock_run, mock_now):
		from frappe.friday_core.tasks import runner

		task = self._task()
		runner._run_task_agentic(task, "Friday")
		kwargs = mock_run.call_args.kwargs
		self.assertEqual(kwargs["session_id"], "task::TASK-7")
		self.assertIn("Instructions:", kwargs["inbound_content"])
		mock_frappe.as_json.assert_called_with({"status": "success", "summary": "Strategy drafted."})
		self.assertEqual(task.workflow_state, "Completed")

	@patch("frappe.friday_core.tasks.runner.now_datetime")
	@patch("frappe.friday_core.tasks.runner._post_warroom")
	@patch("frappe.friday_core.tasks.runner._raise_failure_issue", return_value="ISS-9")
	@patch(_RUN, side_effect=RuntimeError("model down"))
	@patch("frappe.friday_core.tasks.runner.frappe")
	def test_agentic_failure_blocks_and_files_issue(
		self, mock_frappe, mock_run, mock_issue, mock_war, mock_now
	):
		from frappe.friday_core.tasks import runner

		task = self._task()
		runner._run_task_agentic(task, "Friday")
		self.assertEqual(task.workflow_state, "Blocked")
		mock_issue.assert_called_once()
		mock_war.assert_called_once()


class TestCommandSkills(unittest.TestCase):
	@patch(f"{_H}.frappe")
	def test_update_task_requires_valid_action(self, mock_frappe):
		with self.assertRaises(ValueError):
			handlers_project.update_task("update-task", {"task": "T-1", "action": "explode"})

	@patch(f"{_H}.frappe")
	def test_pause_and_resume_set_project_status(self, mock_frappe):
		mock_frappe.db.exists.return_value = True
		handlers_project.pause_project("pause-project", {"project": "PRJ-1"})
		self.assertEqual(mock_frappe.db.set_value.call_args[0][3], "On Hold")
		handlers_project.pause_project("pause-project", {"project": "PRJ-1", "resume": True})
		self.assertEqual(mock_frappe.db.set_value.call_args[0][3], "Open")

	def test_every_command_skill_is_registered(self):
		from frappe.friday_core.agent_runner import dispatcher

		# plan-project is gone: it instantiated the pre-Design-75 pipeline from
		# tasks/templates.py, which the metadata engine replaced.
		for name in ("project-status", "update-task", "pause-project", "list-projects"):
			self.assertIn(name, dispatcher._SKILL_HANDLERS)


if __name__ == "__main__":
	unittest.main()
