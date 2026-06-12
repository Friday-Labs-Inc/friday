# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""
Unit tests for the command center (design 60b, LOCKED).

Mock-based — no DB, no model. Pins:
  - dispatcher gating (Q3/Q7): milestones never dispatch; AND-deps must all
    be Completed; On Hold projects park their pipeline
  - the pipeline template (Q4): structure, gates as milestones, dependency
    wiring, brief interpolation, idempotent re-instantiation
  - the agentic runner (Q2): delegation-style isolation, summary envelope,
    Blocked + Issue on failure
  - the write-back bridge (Q5): state map, gate-prep → request_gate_open,
    Pending Review shape, no-backend-ref no-op, never raises
  - event handlers: project.created plans once, gate.decided completes the
    milestone, refinement round ≥ 3 flags scope, the kill switch cancels
  - the command-loop skills: validation + state changes
"""

import unittest
from unittest.mock import MagicMock, patch

from frappe.friday_core.integrations import randompack_bridge as bridge
from frappe.friday_core.skills import handlers_project
from frappe.friday_core.surfaces import randompack
from frappe.friday_core.tasks import dispatcher as task_dispatcher
from frappe.friday_core.tasks import templates

_D = "frappe.friday_core.tasks.dispatcher"
_T = "frappe.friday_core.tasks.templates"
_B = "frappe.friday_core.integrations.randompack_bridge"
_S = "frappe.friday_core.surfaces.randompack"
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


class TestPipelineTemplate(unittest.TestCase):
	def test_template_shape_gates_and_deps(self):
		keys = [s["key"] for s in templates.RANDOMPACK_PIPELINE]
		self.assertEqual(keys[0], "strategy")
		gates = [s for s in templates.RANDOMPACK_PIPELINE if s["mode"] == "milestone"]
		self.assertEqual([g["key"] for g in gates], ["gate1", "gate2"])
		by_key = {s["key"]: s for s in templates.RANDOMPACK_PIPELINE}
		self.assertIn("gate1", by_key["buildout"]["depends_on"])  # gate gates the build
		self.assertIn("gate2", by_key["guidelines"]["depends_on"])
		for spec in templates.RANDOMPACK_PIPELINE:
			for dep in spec["depends_on"]:
				self.assertLess(keys.index(dep), keys.index(spec["key"]))  # DAG order

	@patch(f"{_T}.frappe")
	def test_instantiation_wires_deps_and_interpolates_brief(self, mock_frappe):
		mock_frappe.get_all.return_value = []
		made = []

		def fake_get_doc(payload):
			doc = MagicMock()
			doc.name = f"TASK-{len(made)}"
			made.append(payload)
			return doc

		mock_frappe.get_doc.side_effect = fake_get_doc
		names = templates.instantiate_pipeline("PRJ-1", "RP-100", "BB-0005")
		self.assertEqual(len(names), len(templates.RANDOMPACK_PIPELINE))
		strategy = made[0]
		self.assertIn("BB-0005", strategy["description"])
		gate1 = next(p for p in made if p["backend_ref"] == "gate1")
		self.assertEqual(gate1["execution_mode"], "milestone")
		buildout = next(p for p in made if p["backend_ref"] == "buildout")
		self.assertTrue(buildout["depends_on"])  # depends on gate1's task name

	@patch(f"{_T}.frappe")
	def test_reinstantiation_is_idempotent(self, mock_frappe):
		mock_frappe.get_all.return_value = [
			MagicMock(backend_ref=s["key"]) for s in templates.RANDOMPACK_PIPELINE
		]
		self.assertEqual(templates.instantiate_pipeline("PRJ-1", "RP-100", "BB-0005"), [])
		mock_frappe.get_doc.assert_not_called()


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
	def test_agentic_failure_blocks_and_files_issue(self, mock_frappe, mock_run, mock_issue, mock_war, mock_now):
		from frappe.friday_core.tasks import runner

		task = self._task()
		runner._run_task_agentic(task, "Friday")
		self.assertEqual(task.workflow_state, "Blocked")
		mock_issue.assert_called_once()
		mock_war.assert_called_once()


class TestBridge(unittest.TestCase):
	def _task(self, phase="strategy", project="PRJ-1", result=None):
		task = MagicMock()
		task.title = "Strategy draft"
		task.project = project
		values = {"backend_ref": phase, "project": project, "result": result}
		task.get.side_effect = values.get
		return task

	@patch(f"{_B}.client")
	@patch(f"{_B}.frappe")
	def test_no_backend_ref_is_a_noop(self, mock_frappe, mock_client):
		bridge.on_task_transition(self._task(phase=None), "Completed")
		mock_client.update_task_progress.assert_not_called()

	@patch(f"{_B}.client")
	@patch(f"{_B}.frappe")
	def test_completed_maps_with_progress_and_note(self, mock_frappe, mock_client):
		mock_frappe.db.get_value.return_value = "RP-100"
		bridge.on_task_transition(
			self._task(result={"status": "success", "summary": "done well"}), "Completed"
		)
		mock_client.update_task_progress.assert_called_once_with(
			"RP-100:strategy", status="completed", progress=100
		)
		note = mock_client.post_project_note.call_args.kwargs["note"]
		self.assertIn("done well", note)

	@patch(f"{_B}.client")
	@patch(f"{_B}.frappe")
	def test_gate_prep_completion_requests_gate_open(self, mock_frappe, mock_client):
		mock_frappe.db.get_value.return_value = "RP-100"
		bridge.on_task_transition(self._task(phase="gate1_prep"), "Completed")
		mock_client.request_gate_open.assert_called_once()
		self.assertEqual(mock_client.request_gate_open.call_args.kwargs["gate"], "gate1")

	@patch(f"{_B}.client")
	@patch(f"{_B}.frappe")
	def test_blocked_signals_pending_review(self, mock_frappe, mock_client):
		mock_frappe.db.get_value.return_value = "RP-100"
		bridge.on_task_transition(self._task(), "Blocked")
		mock_client.signal_pending_review.assert_called_once()

	@patch(f"{_B}.client")
	@patch(f"{_B}.frappe")
	def test_bridge_never_raises(self, mock_frappe, mock_client):
		mock_frappe.db.get_value.side_effect = RuntimeError("db down")
		bridge.on_task_transition(self._task(), "Completed")  # must not raise
		mock_frappe.log_error.assert_called_once()


class TestEventHandlers(unittest.TestCase):
	@patch(f"{_S}._remember")
	@patch(f"{_S}._warroom")
	@patch(f"{_S}.frappe")
	def test_gate_decided_completes_milestone_once(self, mock_frappe, mock_war, mock_rem):
		mock_frappe.db.get_value.side_effect = ["PRJ-1", "TASK-G1"]
		gate_task = MagicMock()
		gate_task.workflow_state = "Pending"
		mock_frappe.get_doc.return_value = gate_task
		randompack.handle_gate_decided({"project_id": "RP-100", "gate": "gate1", "decision": "Midnight Roast"}, MagicMock())
		self.assertEqual(gate_task.workflow_state, "Completed")
		gate_task.save.assert_called_once()

	@patch(f"{_S}._remember")
	@patch(f"{_S}._warroom")
	@patch(f"{_S}._find_brief", return_value="BB-0005")
	@patch(f"{_S}._find_project", return_value="PRJ-1")
	@patch(f"{_S}.frappe")
	def test_refinement_round_three_flags_scope(self, mock_frappe, _p, _b, mock_war, mock_rem):
		randompack.handle_refinement_requested(
			{"project_id": "RP-100", "round": 3, "request": "less navy"}, MagicMock()
		)
		payload = mock_frappe.get_doc.call_args[0][0]
		self.assertEqual(payload["execution_mode"], "agentic")
		self.assertIn("round 3", payload["title"].lower())
		mock_rem.assert_called_once()  # scope memory
		self.assertIn("scope", mock_war.call_args[0][0].lower())

	@patch(f"{_S}._warroom")
	@patch(f"{_S}._find_project", return_value="PRJ-1")
	@patch(f"{_S}.frappe")
	def test_kill_switch_cancels_open_tasks(self, mock_frappe, _p, mock_war):
		mock_frappe.get_all.return_value = ["T-1", "T-2"]
		open_task = MagicMock()
		mock_frappe.get_doc.return_value = open_task
		event = MagicMock()
		event.event_type = "project.cancelled"
		randompack.handle_kill_switch({"project_id": "RP-100"}, event)
		self.assertEqual(open_task.workflow_state, "Cancelled")
		self.assertEqual(mock_frappe.get_doc.call_count, 2)
		mock_frappe.db.set_value.assert_called_once()  # project → Cancelled


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

	def test_all_four_skills_registered(self):
		from frappe.friday_core.agent_runner import dispatcher

		for name in ("plan-project", "project-status", "update-task", "pause-project"):
			self.assertIn(name, dispatcher._SKILL_HANDLERS)


if __name__ == "__main__":
	unittest.main()
