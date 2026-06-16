# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt

"""
Routing + flow tests for the Design 75 metadata engine.

PLAIN ENGLISH
=============
These prove the engine's two core moves, with no LLM and nothing committed:

  - DISPATCH BY METADATA: saving a work-item into an agentic state creates a
    Task assigned to the profile whose discriminator_role matches the
    transition's agent_role (O(1) routing, not skill-subset guessing).
  - AUTO-ADVANCE: when that Task completes, the work-item advances to the next
    state and the next phase's Task is dispatched to the next owner — the chain
    flows on its own.
  - A human-gate state dispatches nothing.

The runner is stubbed so a dispatched (Assigned) task never runs; we instead
mark the task Completed by hand to drive the advance, which is exactly what the
real runner would do after the agent's turn. The advance enqueue runs
synchronously under `frappe.flags.in_test`, so the chain is observable in-test.

    bench --site <test-site> run-tests \\
        --module frappe.friday_core.tests.test_engine_routing
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

import frappe

from frappe.friday_core.domains import randompack_brand as bundle
from frappe.friday_core.engine import workflow_engine


def _new_brief():
	return frappe.get_doc(
		{
			"doctype": "Brand Brief",
			"business_name": "Routing Co",
			"industry": "Retail",
			"what_they_do": "sells",
			"target_audience": "shoppers",
			"status": "Ready",
			"workflow_state": "Strategy",
		}
	).insert(ignore_permissions=True)


def _task_for(brief_name: str, phase_key: str):
	rows = frappe.get_all(
		"Task",
		filters={"work_item_doctype": "Brand Brief", "work_item_name": brief_name, "phase_key": phase_key},
		fields=["name", "assigned_to_profile", "workflow_state", "execution_mode"],
	)
	return rows[0] if rows else None


def _complete(task_name: str):
	"""Mark a dispatched task Completed, as the real runner would. Triggers the
	advance handler (Task on_update)."""
	task = frappe.get_doc("Task", task_name)
	task.workflow_state = "Completed"
	task.save(ignore_permissions=True)


class TestEngineRouting(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		frappe.db.rollback()
		bundle.provision()
		cls._runner = patch(
			"frappe.friday_core.tasks.runner.on_agent_task_assigned", lambda **kw: None
		)
		cls._runner.start()

	@classmethod
	def tearDownClass(cls):
		cls._runner.stop()
		frappe.db.rollback()

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def test_dispatch_routes_by_discriminator_role(self):
		brief = _new_brief()
		task = _task_for(brief.name, "strategy")
		self.assertIsNotNone(task, "engine should dispatch a strategy task on entry")
		self.assertEqual(task.assigned_to_profile, "Brand Strategist")
		self.assertEqual(task.workflow_state, "Assigned")
		self.assertEqual(task.execution_mode, "agentic")

	def test_complete_advances_and_dispatches_next(self):
		brief = _new_brief()
		strategy = _task_for(brief.name, "strategy")
		_complete(strategy.name)  # runner finishes -> advance fires (in_test => sync)

		brief.reload()
		self.assertEqual(brief.workflow_state, "Naming")
		naming = _task_for(brief.name, "naming")
		self.assertIsNotNone(naming, "advancing to Naming should dispatch the naming task")
		self.assertEqual(naming.assigned_to_profile, "Brand Copywriter")

	def test_human_gate_state_dispatches_nothing(self):
		brief = _new_brief()
		# Walk to Gate 1 Review by completing each agentic phase in turn.
		for pk in ["strategy", "naming", "directions", "gate1_prep"]:
			task = _task_for(brief.name, pk)
			self.assertIsNotNone(task, f"expected a dispatched task for {pk}")
			_complete(task.name)
		brief.reload()
		self.assertEqual(brief.workflow_state, "Gate 1 Review")
		# A gate is a human transition — the engine must NOT create an agent task.
		gate_tasks = frappe.get_all(
			"Task",
			filters={
				"work_item_doctype": "Brand Brief",
				"work_item_name": brief.name,
				"workflow_state": ["!=", "Completed"],
			},
		)
		self.assertEqual(gate_tasks, [], "no agent task should be waiting at a human gate")

	def test_meta_resolves_only_agentic_outgoing(self):
		wf = bundle.WORKFLOW_NAME
		# Strategy has an agentic outgoing transition.
		self.assertIsNotNone(workflow_engine._agentic_meta_for_state(wf, "Strategy"))
		# Gate 1 Review's only outgoing transition is the human gate -> None.
		self.assertIsNone(workflow_engine._agentic_meta_for_state(wf, "Gate 1 Review"))
		# Delivered is terminal -> None.
		self.assertIsNone(workflow_engine._agentic_meta_for_state(wf, "Delivered"))
