# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt

"""
Governance tests for the Design 75 metadata engine — the load-bearing bit.

PLAIN ENGLISH
=============
The single most important property of the engine is that role-gating on a
workflow transition is REAL even inside a background worker. Frappe waves
`Administrator` through every transition, and a worker's session IS
Administrator — so the engine must switch to the acting user before firing a
transition (engine.governance.acting_as). These tests prove:

  - an agent CANNOT fire a transition it doesn't own (wrong agent) — raises,
  - an agent CANNOT open a human client gate — raises,
  - the gateway account (which holds only the gate role) CAN open the gate,
  - two Active profiles cannot share a discriminator_role (loud, not silent).

They reuse the provisioned `randompack-brand` bundle and roll everything back —
nothing is committed, and the runner is stubbed so no LLM is ever called.

    bench --site <test-site> run-tests \\
        --module frappe.friday_core.tests.test_engine_governance
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

import frappe
from frappe.model.workflow import apply_workflow

from frappe.friday_core.domains import randompack_brand as bundle
from frappe.friday_core.engine.governance import acting_as


def _user(profile: str) -> str:
	return frappe.db.get_value("Agent Profile", profile, "frappe_user")


def _new_brief() -> "frappe.model.document.Document":
	"""A brand brief that starts in the first agentic state, so the engine
	immediately dispatches the strategy phase."""
	return frappe.get_doc(
		{
			"doctype": "Brand Brief",
			"business_name": "Test Co",
			"industry": "SaaS",
			"what_they_do": "things",
			"target_audience": "people",
			"status": "Ready",
			"workflow_state": "Strategy",
		}
	).insert(ignore_permissions=True)


class TestEngineGovernance(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		frappe.db.rollback()
		bundle.provision()  # idempotent — ensures the bundle exists on any site
		# Stub the runner so a dispatched (Assigned) task never calls the LLM.
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

	def test_wrong_agent_cannot_fire_transition(self):
		"""The copywriter must not be able to fire the strategist's transition."""
		brief = _new_brief()
		brief.reload()
		with self.assertRaises(Exception):
			with acting_as(_user("Brand Copywriter")):
				apply_workflow(brief, "Complete Strategy")
		brief.reload()
		self.assertEqual(brief.workflow_state, "Strategy", "state must not have advanced")

	def test_correct_agent_advances_state(self):
		"""The strategist owns 'Complete Strategy' and may fire it."""
		brief = _new_brief()
		brief.reload()
		with acting_as(_user("Brand Strategist")):
			apply_workflow(brief, "Complete Strategy")
		brief.reload()
		self.assertEqual(brief.workflow_state, "Naming")

	def test_agent_cannot_open_client_gate(self):
		"""No agent holds the gate role, so none can fire a client gate."""
		brief = _new_brief()
		# Drive to Gate 1 Review as the correct agents.
		chain = [
			("Complete Strategy", "Brand Strategist"),
			("Complete Naming", "Brand Copywriter"),
			("Complete Directions", "Creative Director"),
			("Complete Gate 1 Prep", "Brand Strategist"),
		]
		for action, actor in chain:
			brief.reload()
			with acting_as(_user(actor)):
				apply_workflow(brief, action)
		brief.reload()
		self.assertEqual(brief.workflow_state, "Gate 1 Review")
		with self.assertRaises(Exception):
			with acting_as(_user("Creative Director")):
				apply_workflow(brief, "Approve Direction")

	def test_gateway_can_open_client_gate(self):
		"""The gateway account (only the gate role) opens the gate."""
		brief = _new_brief()
		for action, actor in [
			("Complete Strategy", "Brand Strategist"),
			("Complete Naming", "Brand Copywriter"),
			("Complete Directions", "Creative Director"),
			("Complete Gate 1 Prep", "Brand Strategist"),
		]:
			brief.reload()
			with acting_as(_user(actor)):
				apply_workflow(brief, action)
		brief.reload()
		with acting_as(bundle.GATEWAY_USER):
			apply_workflow(brief, "Approve Direction")
		brief.reload()
		self.assertEqual(brief.workflow_state, "Buildout")

	def test_duplicate_discriminator_role_blocked(self):
		"""A second Active profile claiming an in-use discriminator_role fails."""
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(
				{
					"doctype": "Agent Profile",
					"profile_name": "Dup Strategist (test)",
					"agent_role": "Specialist",
					"status": "Active",
					"discriminator_role": "Brand Strategist",
				}
			).insert(ignore_permissions=True)
