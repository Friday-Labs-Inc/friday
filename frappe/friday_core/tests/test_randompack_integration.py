# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt

"""
Tests for the RandomPack ⇄ Friday integration wired to the Design 75 metadata
engine.

Inbound: payment.received idles the brief at "Intake" (no dispatch); only
project.created starts the engine (with rp_project set first); gate.decided
fires the gate transition as the gateway. Outbound: the bridge resolves the
backend's REAL task docname (via get_project + the subject map), never the old
synthetic slug. The runner and all HTTP are mocked; nothing is committed.
"""

from __future__ import annotations

import json
import unittest
from unittest.mock import patch

import frappe

from frappe.friday_core.integrations import randompack_bridge as bridge
from frappe.friday_core.surfaces import randompack as surface


class _Evt:
	event_id = "evt-test-integration"


def _brief(rp_brief: str) -> str | None:
	return frappe.db.get_value("Brand Brief", {"rp_brief": rp_brief}, "name")


class TestRandompackInbound(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		frappe.db.rollback()
		cls._patches = [
			patch("frappe.enqueue", lambda *a, **k: None),  # no runner
			patch("frappe.friday_core.integrations.randompack_client.send", return_value=None),  # no HTTP
		]
		for p in cls._patches:
			p.start()

	@classmethod
	def tearDownClass(cls):
		for p in cls._patches:
			p.stop()
		frappe.db.rollback()

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def test_payment_received_idles_at_intake(self):
		surface.handle_payment_received({"brief": "OB-T1", "brief_snapshot": {"business_name": "T1Co"}}, _Evt())
		b = _brief("OB-T1")
		self.assertTrue(b)
		self.assertEqual(frappe.db.get_value("Brand Brief", b, "workflow_state"), "Intake")
		self.assertEqual(
			frappe.get_all("Task", filters={"work_item_doctype": "Brand Brief", "work_item_name": b}), []
		)

	def test_project_created_creates_brief_and_starts(self):
		# Real flow: payment.received carries NO snapshot, so no brief yet.
		surface.handle_payment_received({"brief": "OB-T2"}, _Evt())
		self.assertIsNone(_brief("OB-T2"))
		# project.created carries the frozen snapshot AS A JSON STRING (Frappe JSON
		# field) → it creates the brief and starts it. Run as Guest to mimic the
		# webhook worker — the handler must self-elevate for the start transition.
		frappe.set_user("Guest")
		surface.handle_project_created(
			{"project": "PROJ-T2", "brief": "OB-T2", "brief_snapshot": json.dumps({"company": "T2Co"})}, _Evt()
		)
		frappe.set_user("Administrator")
		b = _brief("OB-T2")
		self.assertTrue(b, "project.created should create the brief from its snapshot")
		self.assertEqual(frappe.db.get_value("Brand Brief", b, "workflow_state"), "Strategy")
		self.assertEqual(frappe.db.get_value("Brand Brief", b, "rp_project"), "PROJ-T2")
		phases = [
			t.phase_key
			for t in frappe.get_all("Task", filters={"work_item_name": b}, fields=["phase_key"])
		]
		self.assertIn("strategy", phases)

	def test_project_created_replay_is_noop(self):
		surface.handle_payment_received({"brief": "OB-T5", "brief_snapshot": {"business_name": "T5Co"}}, _Evt())
		surface.handle_project_created({"project": "PROJ-T5", "brief": "OB-T5", "brief_snapshot": {}}, _Evt())
		b = _brief("OB-T5")
		frappe.db.set_value("Brand Brief", b, "workflow_state", "Directions")  # pretend it advanced
		surface.handle_project_created({"project": "PROJ-T5", "brief": "OB-T5", "brief_snapshot": {}}, _Evt())
		# replay must NOT reset it back to Strategy
		self.assertEqual(frappe.db.get_value("Brand Brief", b, "workflow_state"), "Directions")

	def test_gate1_decided_advances_as_gateway(self):
		surface.handle_payment_received({"brief": "OB-T3", "brief_snapshot": {"business_name": "T3Co"}}, _Evt())
		surface.handle_project_created({"project": "PROJ-T3", "brief": "OB-T3", "brief_snapshot": {}}, _Evt())
		b = _brief("OB-T3")
		frappe.db.set_value("Brand Brief", b, "workflow_state", "Gate 1 Review")
		surface.handle_gate_decided(
			{"project": "PROJ-T3", "decision": "Approved", "chosen_direction": "Glacial Mist"}, _Evt()
		)
		self.assertEqual(frappe.db.get_value("Brand Brief", b, "workflow_state"), "Buildout")
		self.assertEqual(frappe.db.get_value("Brand Brief", b, "chosen_direction"), "Glacial Mist")

	def test_refinement_requested_does_not_advance(self):
		surface.handle_payment_received({"brief": "OB-T4", "brief_snapshot": {"business_name": "T4Co"}}, _Evt())
		surface.handle_project_created({"project": "PROJ-T4", "brief": "OB-T4", "brief_snapshot": {}}, _Evt())
		b = _brief("OB-T4")
		frappe.db.set_value("Brand Brief", b, "workflow_state", "Gate 1 Review")
		surface.handle_gate_decided(
			{"project": "PROJ-T4", "decision": "Refinement Requested", "client_comments": "redo"}, _Evt()
		)
		self.assertEqual(frappe.db.get_value("Brand Brief", b, "workflow_state"), "Gate 1 Review")


class TestRandompackBridge(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		frappe.db.rollback()
		cls._enq = patch("frappe.enqueue", lambda *a, **k: None)
		cls._enq.start()

	@classmethod
	def tearDownClass(cls):
		cls._enq.stop()
		frappe.db.rollback()

	def tearDown(self):
		frappe.db.rollback()

	_PROJECT_STATE = {
		"message": {
			"tasks": [
				{"name": "TASK-77", "subject": "Three directions"},
				{"name": "TASK-30", "subject": "Strategy & naming"},
			]
		}
	}

	def test_resolve_rp_task_maps_phase_to_real_docname(self):
		with patch(
			"frappe.friday_core.integrations.randompack_client.get_project_state",
			return_value=self._PROJECT_STATE,
		):
			self.assertEqual(bridge._resolve_rp_task("PROJ-X", "directions"), "TASK-77")
			self.assertEqual(bridge._resolve_rp_task("PROJ-X", "strategy"), "TASK-30")
			self.assertIsNone(bridge._resolve_rp_task("PROJ-X", "no_such_phase"))

	def test_engine_writeback_uses_real_docname_not_slug(self):
		doc = frappe.get_doc(
			{"doctype": "Brand Brief", "business_name": "BridgeCo", "rp_project": "PROJ-Y"}
		).insert(ignore_permissions=True)
		task = frappe._dict(
			work_item_doctype="Brand Brief",
			work_item_name=doc.name,
			phase_key="directions",
			title="directions",
			result=json.dumps({"summary": "three directions"}),
		)
		captured = {}
		with patch(
			"frappe.friday_core.integrations.randompack_client.get_project_state",
			return_value=self._PROJECT_STATE,
		), patch(
			"frappe.friday_core.integrations.randompack_client.update_task_progress",
			side_effect=lambda task_ref, **k: captured.update(task_ref=task_ref, **k),
		), patch(
			"frappe.friday_core.integrations.randompack_client.post_project_note",
			lambda *a, **k: None,
		):
			bridge.on_task_transition(task, "Completed")
		# the real backend docname, NOT "PROJ-Y:directions"
		self.assertEqual(captured.get("task_ref"), "TASK-77")
		self.assertEqual(captured.get("status"), "Completed")

	def test_engine_writeback_skips_when_no_rp_project(self):
		doc = frappe.get_doc({"doctype": "Brand Brief", "business_name": "InternalCo"}).insert(
			ignore_permissions=True
		)
		task = frappe._dict(
			work_item_doctype="Brand Brief", work_item_name=doc.name, phase_key="directions", title="d"
		)
		with patch(
			"frappe.friday_core.integrations.randompack_client.update_task_progress"
		) as m_utp:
			bridge.on_task_transition(task, "Completed")
		m_utp.assert_not_called()
