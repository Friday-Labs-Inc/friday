# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""Design 96 Slice 3 — the Studio Workspace ("The Bench") endpoints.

DB-free. Pins the Bench contract:
  - The queue shows exactly the two human-CD states, longest-waiting first.
  - The Bench's per-state actions stay in lockstep with the ACTUAL
    randompack_brand TRANSITIONS (drift = failing test, not a silent no-op UI).
  - Request Refinement REQUIRES notes, and the notes file is written to the
    project BEFORE the workflow transition fires (the production phase reads
    it the moment it starts) — private and unflagged so the slice-2 leak
    guard keeps it internal.
  - Actions invalid for the brief's current state are rejected.
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from frappe.friday_core.console import studio_api
from frappe.friday_core.domains import randompack_brand

_M = "frappe.friday_core.console.studio_api"


class TestActionsMatchDomainMachine(unittest.TestCase):
	"""The Bench offers only real transitions, gated to the CD role."""

	def test_every_bench_action_is_a_cd_transition(self):
		transitions = {(frm, action): allowed for frm, action, _nxt, allowed in randompack_brand.TRANSITIONS}
		for state, actions in studio_api.STATE_ACTIONS.items():
			for action in actions:
				self.assertIn((state, action), transitions, f"{action} is not a transition from {state}")
				self.assertEqual(
					transitions[(state, action)],
					randompack_brand.CD_ROLE,
					f"{action} from {state} is not CD-gated",
				)

	def test_bench_states_are_the_cd_states(self):
		cd_states = {state for state, role in randompack_brand.STATES if role == randompack_brand.CD_ROLE}
		self.assertEqual(set(studio_api.CD_STATES), cd_states)


class TestStudioSnapshot(unittest.TestCase):
	@patch(f"{_M}.frappe")
	def test_queue_filters_cd_states_and_computes_meta(self, fr):
		fr.get_all.return_value = [
			{
				"name": "BB-1",
				"business_name": "Friday Labs Inc",
				"workflow_state": "CD Internal Gate",
				"modified": "2026-07-01 09:00:00",
				"project": "PROJ-1",
			}
		]
		fr.db.count.side_effect = [2, 1]  # packages, notes rounds
		fr.utils.date_diff.return_value = 4

		snap = studio_api.studio_snapshot()

		self.assertNotIn("error", snap)
		_, kwargs = fr.get_all.call_args
		self.assertEqual(kwargs["filters"]["workflow_state"], ["in", list(studio_api.CD_STATES)])
		self.assertEqual(kwargs["order_by"], "modified asc")  # longest-waiting first
		row = snap["queue"][0]
		self.assertEqual(row["days_waiting"], 4)
		self.assertEqual(row["package_count"], 2)
		self.assertEqual(row["refine_round"], 1)
		self.assertEqual(row["actions"], ["Approve Production", "Request Refinement"])

	@patch(f"{_M}.frappe")
	def test_error_envelope_never_a_silent_empty_queue(self, fr):
		fr.get_all.side_effect = RuntimeError("db down")
		snap = studio_api.studio_snapshot()
		self.assertIn("error", snap)
		self.assertEqual(snap["queue"], [])

	@patch(f"{_M}.frappe")
	def test_read_permission_required(self, fr):
		fr.has_permission.return_value = False
		fr.throw.side_effect = PermissionError("nope")
		with self.assertRaises(PermissionError):
			studio_api.studio_snapshot()


class TestApprenticeLedgerEndpoint(unittest.TestCase):
	@patch("frappe.friday_core.domains.randompack_study.ledger_snapshot")
	@patch(f"{_M}.frappe")
	def test_wraps_ledger_with_envelope(self, fr, m_ledger):
		m_ledger.return_value = {"lessons_stored": 3}
		out = studio_api.apprentice_ledger()
		self.assertNotIn("error", out)
		self.assertEqual(out["ledger"], {"lessons_stored": 3})

	@patch("frappe.friday_core.domains.randompack_study.ledger_snapshot")
	@patch(f"{_M}.frappe")
	def test_fail_loud_envelope(self, fr, m_ledger):
		m_ledger.side_effect = RuntimeError("db down")
		out = studio_api.apprentice_ledger()
		self.assertIn("error", out)
		self.assertIsNone(out["ledger"])


class TestStudioAction(unittest.TestCase):
	def _doc(self, state="CD Internal Gate", project="PROJ-1"):
		doc = MagicMock()
		doc.name = "BB-1"
		doc.workflow_state = state
		doc.project = project
		return doc

	@patch(f"{_M}.frappe")
	def test_action_invalid_for_state_rejected(self, fr):
		fr.get_doc.return_value = self._doc(state="CD Creative")
		fr.throw.side_effect = Exception("thrown")
		with self.assertRaises(Exception):
			studio_api.studio_action("BB-1", "Approve Production")

	@patch(f"{_M}.frappe")
	def test_refinement_without_notes_rejected_before_any_side_effect(self, fr):
		fr.get_doc.return_value = self._doc()
		fr.throw.side_effect = Exception("thrown")
		with (
			patch("frappe.model.workflow.apply_workflow") as m_apply,
			patch("frappe.utils.file_manager.save_file") as m_save,
		):
			with self.assertRaises(Exception):
				studio_api.studio_action("BB-1", "Request Refinement", notes="   ")
			m_apply.assert_not_called()
			m_save.assert_not_called()

	@patch(f"{_M}.frappe")
	def test_refinement_saves_notes_before_transition(self, fr):
		fr.get_doc.return_value = self._doc()
		fr.db.count.return_value = 1  # one prior round → this is r2

		order: list[str] = []
		with (
			patch("frappe.model.workflow.apply_workflow") as m_apply,
			patch("frappe.utils.file_manager.save_file") as m_save,
		):
			m_save.side_effect = lambda *a, **k: order.append("save_notes")
			updated = MagicMock()
			updated.workflow_state = "AI Production"
			m_apply.side_effect = lambda *a, **k: order.append("apply_workflow") or updated

			out = studio_api.studio_action("BB-1", "Request Refinement", notes="Mark is too heavy.")

			self.assertEqual(order, ["save_notes", "apply_workflow"])
			file_name, content = m_save.call_args[0][0], m_save.call_args[0][1]
			self.assertEqual(file_name, "cd-refinement-notes-r2.md")
			self.assertIn(b"Mark is too heavy.", content)
			self.assertIn(b"Round 2", content)
			self.assertTrue(m_save.call_args.kwargs.get("is_private"))
			m_apply.assert_called_once()
			self.assertEqual(m_apply.call_args[0][1], "Request Refinement")
			self.assertEqual(out["new_state"], "AI Production")
			self.assertEqual(out["notes_file"], "cd-refinement-notes-r2.md")

	@patch(f"{_M}.frappe")
	def test_approve_fires_workflow_without_notes_file(self, fr):
		fr.get_doc.return_value = self._doc()
		with (
			patch("frappe.model.workflow.apply_workflow") as m_apply,
			patch("frappe.utils.file_manager.save_file") as m_save,
		):
			updated = MagicMock()
			updated.workflow_state = "Gate 2 Prep"
			m_apply.return_value = updated

			out = studio_api.studio_action("BB-1", "Approve Production")

			m_save.assert_not_called()
			self.assertEqual(out["new_state"], "Gate 2 Prep")
			self.assertIsNone(out["notes_file"])


class TestPackagePreview(unittest.TestCase):
	@patch("frappe.utils.md_to_html")
	@patch(f"{_M}.frappe")
	def test_versions_rendered_newest_first(self, fr, m_md):
		fr.db.get_value.return_value = "PROJ-1"
		fr.get_all.return_value = [
			{"name": "f2", "file_name": "production-package99dc58.md", "creation": "2026-07-05"},
			{"name": "f1", "file_name": "production-package93e487.md", "creation": "2026-07-04"},
		]
		file_doc = MagicMock()
		file_doc.get_content.return_value = b"# Package"
		fr.get_doc.return_value = file_doc
		m_md.return_value = "<h1>Package</h1>"

		out = studio_api.package_preview("BB-1")

		_, kwargs = fr.get_all.call_args
		self.assertEqual(kwargs["order_by"], "creation desc")
		self.assertEqual(kwargs["filters"]["file_name"], ["like", "production-package%"])
		self.assertEqual(len(out["versions"]), 2)
		self.assertEqual(out["versions"][0]["file_name"], "production-package99dc58.md")
		self.assertEqual(out["versions"][0]["html"], "<h1>Package</h1>")

	@patch(f"{_M}.frappe")
	def test_no_project_returns_empty(self, fr):
		fr.db.get_value.return_value = None
		out = studio_api.package_preview("BB-1")
		self.assertEqual(out["versions"], [])


if __name__ == "__main__":
	unittest.main()
