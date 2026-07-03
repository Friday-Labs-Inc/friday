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
		# Design 95: Gate 1 approval enters the AI Production stage (was Buildout).
		self.assertEqual(frappe.db.get_value("Brand Brief", b, "workflow_state"), "AI Production")
		self.assertEqual(frappe.db.get_value("Brand Brief", b, "chosen_direction"), "Glacial Mist")

	def test_project_created_creates_local_friday_project(self):
		"""Design 77 — handle_project_created must also create a LOCAL Friday
		Project record (idempotent by backend_ref) and set the brief's 'project'
		Link field so phase_dispatcher carries the Project docname onto every
		engine Task."""
		surface.handle_payment_received({"brief": "OB-T77"}, _Evt())
		frappe.set_user("Guest")
		surface.handle_project_created(
			{"project": "RP-PROJ-77", "brief": "OB-T77",
			 "brief_snapshot": json.dumps({"company": "T77Co"})},
			_Evt(),
		)
		frappe.set_user("Administrator")
		b = _brief("OB-T77")
		self.assertTrue(b)
		project_docname = frappe.db.get_value("Brand Brief", b, "project")
		self.assertTrue(project_docname, "Brand Brief.project must be set after project.created")
		# The local Friday Project must exist with the matching backend_ref.
		backend_ref = frappe.db.get_value("Project", project_docname, "backend_ref")
		self.assertEqual(backend_ref, "RP-PROJ-77")

	def test_project_created_replay_reuses_existing_friday_project(self):
		"""Replay of project.created (same backend_ref) must not create a
		second Friday Project row — idempotent by backend_ref."""
		surface.handle_payment_received({"brief": "OB-T77B"}, _Evt())
		frappe.set_user("Guest")
		surface.handle_project_created(
			{"project": "RP-PROJ-77B", "brief": "OB-T77B",
			 "brief_snapshot": json.dumps({"company": "T77BCo"})},
			_Evt(),
		)
		first_project = frappe.db.get_value(
			"Brand Brief", {"rp_brief": "OB-T77B"}, "project"
		)
		# Replay
		surface.handle_project_created(
			{"project": "RP-PROJ-77B", "brief": "OB-T77B",
			 "brief_snapshot": json.dumps({"company": "T77BCo"})},
			_Evt(),
		)
		frappe.set_user("Administrator")
		second_project = frappe.db.get_value(
			"Brand Brief", {"rp_brief": "OB-T77B"}, "project"
		)
		self.assertEqual(first_project, second_project, "replay must reuse the same local Project")
		# And there must be only one Project row with that backend_ref.
		count = frappe.db.count("Project", filters={"backend_ref": "RP-PROJ-77B"})
		self.assertEqual(count, 1)

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

	# ─── Design 77 — local Friday Project + union deliverable push ───

	def test_push_deliverables_unions_brief_and_friday_project_files(self):
		"""_push_deliverables must read files attached to BOTH the Brand Brief
		(images from generate-image) AND the linked local Friday Project
		(text/PDF deliverables from attach-deliverable + materialize.py).
		Without this, customers see only images. Dedup by file_url."""
		# A brief linked to a local Friday Project via the Design 77 'project' field.
		project = frappe.get_doc({
			"doctype": "Project", "project_name": "Test Project 77",
			"status": "Open", "backend_ref": "BR-77-PROJ",
		}).insert(ignore_permissions=True)
		brief = frappe.get_doc({
			"doctype": "Brand Brief", "business_name": "BridgeCo77",
			"rp_project": "RP-PROJ-77", "project": project.name,
		}).insert(ignore_permissions=True)

		# Capture the union of file queries via mocked get_all.
		def fake_get_all(doctype, filters=None, fields=None, **k):
			if doctype != "File":
				return []
			if filters.get("attached_to_doctype") == "Brand Brief":
				return [frappe._dict(name="f-img", file_name="logo.jpg", file_url="/files/logo.jpg")]
			if filters.get("attached_to_doctype") == "Project":
				return [frappe._dict(name="f-md", file_name="brand-guidelines.md",
				                     file_url="/files/brand-guidelines.md")]
			return []

		captured = []
		fake_doc = frappe._dict(get_content=lambda: b"BYTES")
		with patch("frappe.get_all", side_effect=fake_get_all), \
		     patch("frappe.get_doc", return_value=fake_doc), \
		     patch(
			"frappe.friday_core.integrations.randompack_client.attach_deliverable",
			side_effect=lambda rp, file_name, content, description="": captured.append(file_name),
		):
			bridge._push_deliverables("RP-PROJ-77", brief.name)

		# Both files must have been pushed — brief image AND project markdown.
		self.assertIn("logo.jpg", captured)
		self.assertIn("brand-guidelines.md", captured)

	def test_on_brief_state_change_fires_only_on_transition_to_delivered(self):
		"""The on_update hook must push only when state JUST changed to
		Delivered — not on every re-save while already Delivered, and not on
		any other state change. Without this guard, the bridge would push the
		full deliverable set repeatedly."""
		doc = frappe._dict(
			name="BB-T77", workflow_state="Delivered", rp_project="RP-PROJ-X",
			get=lambda k, default=None: {"workflow_state": "Delivered", "rp_project": "RP-PROJ-X"}.get(k, default),
			has_value_changed=lambda f: True,  # state just changed
		)
		with patch.object(bridge, "_push_deliverables") as m_push:
			bridge.on_brief_state_change(doc)
		m_push.assert_called_once_with("RP-PROJ-X", "BB-T77")

	def test_on_brief_state_change_silent_when_state_unchanged(self):
		"""A re-save while the brief is already at Delivered must not push
		again — has_value_changed returns False."""
		doc = frappe._dict(
			name="BB-T78", workflow_state="Delivered", rp_project="RP-PROJ-X",
			get=lambda k, default=None: {"workflow_state": "Delivered", "rp_project": "RP-PROJ-X"}.get(k, default),
			has_value_changed=lambda f: False,
		)
		with patch.object(bridge, "_push_deliverables") as m_push:
			bridge.on_brief_state_change(doc)
		m_push.assert_not_called()

	def test_on_brief_state_change_silent_for_non_delivered_state(self):
		"""Other state transitions (Strategy, Naming, etc.) must not push."""
		doc = frappe._dict(
			name="BB-T79", workflow_state="Naming", rp_project="RP-PROJ-X",
			get=lambda k, default=None: {"workflow_state": "Naming", "rp_project": "RP-PROJ-X"}.get(k, default),
			has_value_changed=lambda f: True,
		)
		with patch.object(bridge, "_push_deliverables") as m_push:
			bridge.on_brief_state_change(doc)
		m_push.assert_not_called()
