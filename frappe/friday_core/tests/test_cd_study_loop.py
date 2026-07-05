# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""Design 95 Slice 2 — the CD apprenticeship study loop.

DB-free. Pins the study contract:
  - Leaving CD Creative spawns ONE observe task for the apprentice — with NO
    work_item fields, so it can never advance the pipeline (advance.py keys on
    work_item) and never crosses the RandomPack seam (the bridge writeback
    keys on the work-item too).
  - CD Internal Gate decisions become labeled Agent Memory rows, written
    directly (no model call): APPROVE is a positive label; REFINE quotes the
    cd-refinement-notes file the Studio saved before the transition.
  - Memories are tagged subject="cd-apprentice" for recall + the Slice-3 ledger.
  - The states/transitions the loop watches exist in the ACTUAL domain machine
    (lockstep — machine drift breaks a test, not silently the loop).
  - A study failure never breaks the workflow save.
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from frappe.friday_core.domains import randompack_brand
from frappe.friday_core.domains import randompack_study as study

_M = "frappe.friday_core.domains.randompack_study"


def _brief(old_state: str, new_state: str, **fields) -> MagicMock:
	doc = MagicMock()
	doc.name = "BB-1"
	doc.has_value_changed.return_value = True
	before = MagicMock()
	before.get.side_effect = lambda k, d=None: {"workflow_state": old_state}.get(k, d)
	doc.get_doc_before_save.return_value = before
	values = {
		"workflow_state": new_state,
		"business_name": "Friday Labs Inc",
		"industry": "Robotics & AI",
		"project": "PROJ-1",
		**fields,
	}
	doc.get.side_effect = lambda k, d=None: values.get(k, d)
	return doc


class TestLockstepWithDomainMachine(unittest.TestCase):
	def test_watched_states_and_transitions_exist(self):
		state_names = {s for s, _ in randompack_brand.STATES}
		self.assertIn("CD Creative", state_names)
		self.assertIn("CD Internal Gate", state_names)
		# The two gate outcomes the loop labels are real CD-gated transitions.
		transitions = {(f, n): a for f, _act, n, a in randompack_brand.TRANSITIONS}
		self.assertEqual(transitions.get(("CD Internal Gate", "Gate 2 Prep")), randompack_brand.CD_ROLE)
		self.assertEqual(transitions.get(("CD Internal Gate", "AI Production")), randompack_brand.CD_ROLE)

	def test_apprentice_profile_is_provisioned_with_remember(self):
		spec = next(p for p in randompack_brand.PROFILES if p["profile_name"] == study.CD_AGENT_PROFILE)
		self.assertIn("remember", spec["skills"])
		self.assertIn("list-project-files", spec["skills"])
		self.assertIn("get-project-file", spec["skills"])

	def test_observe_phase_key_is_not_an_engine_phase(self):
		engine_phases = {t[1] for t in randompack_brand.TRANSITIONS}  # action names
		self.assertNotIn(study.OBSERVE_PHASE_KEY, engine_phases)
		self.assertNotIn(study.DRAFT_PHASE_KEY, engine_phases)


class TestObserveTask(unittest.TestCase):
	@patch(f"{_M}.frappe")
	def test_leaving_cd_creative_spawns_sidecar_task(self, fr):
		fr.db.get_value.return_value = "Creative Director"
		fr.db.exists.return_value = False
		task_doc = MagicMock()
		fr.get_doc.return_value = task_doc

		study.on_brief_study_signal(_brief("CD Creative", "Gate 1 Prep"))

		payload = fr.get_doc.call_args[0][0]
		self.assertEqual(payload["doctype"], "Task")
		self.assertEqual(payload["phase_key"], study.OBSERVE_PHASE_KEY)
		self.assertEqual(payload["assigned_to_profile"], "Creative Director")
		self.assertEqual(payload["workflow_state"], "Assigned")
		self.assertEqual(payload["project"], "PROJ-1")
		# THE isolation property: no work_item linkage → engine + bridge inert.
		self.assertNotIn("work_item_doctype", payload)
		self.assertNotIn("work_item_name", payload)
		# The prompt teaches pairing via remember with the apprentice tag.
		self.assertIn("remember", payload["description"])
		self.assertIn(study.APPRENTICE_TAG, payload["description"])
		self.assertIn("Friday Labs Inc", payload["description"])
		task_doc.insert.assert_called_once()

	@patch(f"{_M}.frappe")
	def test_open_observe_task_deduped(self, fr):
		fr.db.get_value.return_value = "Creative Director"
		fr.db.exists.return_value = True  # one already open
		study.on_brief_study_signal(_brief("CD Creative", "Gate 1 Prep"))
		fr.get_doc.assert_not_called()

	@patch(f"{_M}.frappe")
	def test_missing_apprentice_profile_logs_and_drops(self, fr):
		fr.db.get_value.return_value = None
		study.on_brief_study_signal(_brief("CD Creative", "Gate 1 Prep"))
		fr.get_doc.assert_not_called()
		fr.log_error.assert_called()


class TestGateMemories(unittest.TestCase):
	@patch(f"{_M}.frappe")
	def test_approve_writes_positive_label(self, fr):
		fr.db.get_value.return_value = "Creative Director"
		fr.db.count.return_value = 2  # two refinement rounds happened first
		fr.get_all.return_value = [{"name": "fpkg", "file_name": "production-package99dc58.md"}]
		mem_doc = MagicMock()
		fr.get_doc.return_value = mem_doc

		study.on_brief_study_signal(_brief("CD Internal Gate", "Gate 2 Prep"))

		payload = fr.get_doc.call_args[0][0]
		self.assertEqual(payload["doctype"], "Agent Memory")
		self.assertEqual(payload["subject"], study.APPRENTICE_TAG)
		self.assertEqual(payload["agent_profile"], "Creative Director")
		# GLOBAL on purpose: recall is project-scoped (design 73), and a
		# project-tagged lesson would be invisible on every future brief.
		self.assertIsNone(payload["project"])
		self.assertEqual(payload["source_session"], "study::BB-1")
		self.assertIn("APPROVE", payload["memory"])
		self.assertIn("Friday Labs Inc", payload["memory"])
		self.assertIn("2 refinement round(s)", payload["memory"])
		self.assertIn("production-package99dc58.md", payload["memory"])
		mem_doc.insert.assert_called_once()

	@patch(f"{_M}.frappe")
	def test_refine_quotes_the_notes_file(self, fr):
		fr.db.get_value.return_value = "Creative Director"
		fr.db.count.return_value = 1

		def get_all(doctype, filters=None, **k):
			pattern = filters["file_name"][1]
			if pattern.startswith("cd-refinement-notes"):
				return [{"name": "fnotes", "file_name": "cd-refinement-notes-r1.md"}]
			return [{"name": "fpkg", "file_name": "production-package93e487.md"}]

		fr.get_all.side_effect = get_all

		file_doc = MagicMock()
		file_doc.get_content.return_value = (
			"# CD Refinement Notes — Round 1\n\nMark is too heavy; thin the strokes.".encode()
		)
		mem_doc = MagicMock()
		fr.get_doc.side_effect = lambda *a: file_doc if a[0] == "File" else mem_doc

		study.on_brief_study_signal(_brief("CD Internal Gate", "AI Production"))

		payload = next(c for c in fr.get_doc.call_args_list if c[0][0] != "File")[0][0]
		self.assertEqual(payload["doctype"], "Agent Memory")
		self.assertIn("REFINE", payload["memory"])
		self.assertIn("Mark is too heavy; thin the strokes.", payload["memory"])
		self.assertIn("cd-refinement-notes-r1.md", payload["memory"])
		self.assertIn("round 1", payload["memory"])
		mem_doc.insert.assert_called_once()

	@patch(f"{_M}.frappe")
	def test_refine_without_notes_file_still_records(self, fr):
		# Gate fired from the raw Desk form (not the Studio) — no notes file.
		fr.db.get_value.return_value = "Creative Director"
		fr.db.count.return_value = 0
		fr.get_all.return_value = []
		mem_doc = MagicMock()
		fr.get_doc.return_value = mem_doc

		study.on_brief_study_signal(_brief("CD Internal Gate", "AI Production"))

		payload = fr.get_doc.call_args[0][0]
		self.assertIn("REFINE", payload["memory"])
		self.assertIn("not on file", payload["memory"])
		mem_doc.insert.assert_called_once()


class TestGraduatedDrafting(unittest.TestCase):
	"""Slice 3 — entering CD Creative with the operator's flag ON spawns a
	draft sidecar; OFF (the default) changes nothing."""

	def _fr_with_flag(self, fr, flag: int):
		# get_value serves both the flag read and the profile-active check.
		def get_value(doctype, name_or_filters, field=None, **k):
			if field == study.GRADUATION_FLAG:
				return flag
			return "Creative Director"

		fr.db.get_value.side_effect = get_value
		fr.db.exists.return_value = False

	@patch(f"{_M}.frappe")
	def test_flag_off_is_the_default_no_op(self, fr):
		self._fr_with_flag(fr, 0)
		study.on_brief_study_signal(_brief("Naming", "CD Creative"))
		fr.get_doc.assert_not_called()

	@patch(f"{_M}.frappe")
	def test_flag_on_spawns_draft_sidecar(self, fr):
		self._fr_with_flag(fr, 1)
		task_doc = MagicMock()
		fr.get_doc.return_value = task_doc

		study.on_brief_study_signal(_brief("Naming", "CD Creative"))

		payload = fr.get_doc.call_args[0][0]
		self.assertEqual(payload["doctype"], "Task")
		self.assertEqual(payload["phase_key"], study.DRAFT_PHASE_KEY)
		# Same isolation properties as the observe task.
		self.assertNotIn("work_item_doctype", payload)
		self.assertNotIn("work_item_name", payload)
		# The prompt keeps the human in charge and the drafts internal.
		self.assertIn("curate", payload["description"])
		self.assertIn("cd-apprentice", payload["description"])
		self.assertIn("INTERNAL", payload["description"])
		self.assertIn("Creative Ready", payload["description"])
		task_doc.insert.assert_called_once()

	@patch(f"{_M}.frappe")
	def test_open_draft_task_deduped(self, fr):
		self._fr_with_flag(fr, 1)
		fr.db.exists.return_value = True
		study.on_brief_study_signal(_brief("Naming", "CD Creative"))
		fr.get_doc.assert_not_called()

	@patch(f"{_M}.frappe")
	def test_leaving_cd_creative_still_observes_when_flag_on(self, fr):
		# Leaving CD Creative → observe fires (the draft branch only fires on ENTRY).
		self._fr_with_flag(fr, 1)
		task_doc = MagicMock()
		fr.get_doc.return_value = task_doc
		study.on_brief_study_signal(_brief("CD Creative", "Gate 1 Prep"))
		payload = fr.get_doc.call_args[0][0]
		self.assertEqual(payload["phase_key"], study.OBSERVE_PHASE_KEY)


class TestEnsureGraduationFlags(unittest.TestCase):
	@patch(f"{_M}.frappe")
	def test_idempotent_when_field_exists(self, fr):
		fr.db.exists.return_value = True
		study.ensure_graduation_flags()  # must short-circuit before create
		fr.db.exists.assert_called_once()


class TestLedgerSnapshot(unittest.TestCase):
	@patch(f"{_M}.frappe")
	def test_counts_rates_dimensions_and_trend(self, fr):
		fr.get_all.return_value = [
			{
				"name": "m1",
				"memory": "[cd-apprentice] Gate APPROVE — A (x): ...",
				"source_session": "study::BB-1",
			},
			{
				"name": "m2",
				"memory": "[cd-apprentice] Gate REFINE — B: palette too dark",
				"source_session": "study::BB-2",
			},
			{
				"name": "m3",
				"memory": "[cd-apprentice] Gate REFINE — B: typeface too playful",
				"source_session": "study::BB-2",
			},
			{
				"name": "m4",
				"memory": "Given tech-minimal briefs he chose a monochrome palette",
				"source_session": "t",
			},
			{
				"name": "m5",
				"memory": "He pairs a grotesque typeface with generous spacing",
				"source_session": "t",
			},
		]
		fr.db.count.return_value = 3  # every Task count
		fr.db.get_value.side_effect = lambda dt, name, field=None, **k: (
			1 if field == study.GRADUATION_FLAG else "Biz " + str(name)
		)

		ledger = study.ledger_snapshot()

		self.assertEqual(ledger["lessons_stored"], 2)
		self.assertEqual(ledger["gates"]["approvals"], 1)
		self.assertEqual(ledger["gates"]["refinements"], 2)
		self.assertEqual(ledger["gates"]["approve_rate"], 33)  # 1 of 3
		self.assertTrue(ledger["flags"][study.GRADUATION_FLAG])
		# dimensions count MENTIONS across lessons + refine corrections
		self.assertEqual(ledger["dimensions"]["palette"], 2)  # m2 + m4
		self.assertEqual(ledger["dimensions"]["typography"], 2)  # m3 + m5
		self.assertEqual(ledger["dimensions"]["layout"], 1)  # m5 spacing
		# per-brief trend rows
		rows = {r["brief"]: r for r in ledger["briefs"]}
		self.assertTrue(rows["BB-1"]["approved"])
		self.assertEqual(rows["BB-2"]["refinements"], 2)
		self.assertFalse(rows["BB-2"]["approved"])

	@patch(f"{_M}.frappe")
	def test_no_gates_yet_means_no_rate(self, fr):
		fr.get_all.return_value = []
		fr.db.count.return_value = 0
		fr.db.get_value.return_value = 0
		ledger = study.ledger_snapshot()
		self.assertIsNone(ledger["gates"]["approve_rate"])
		self.assertEqual(ledger["briefs"], [])


class TestNonSignals(unittest.TestCase):
	@patch(f"{_M}.frappe")
	def test_unwatched_transition_is_a_no_op(self, fr):
		study.on_brief_study_signal(_brief("Strategy", "Naming"))
		fr.get_doc.assert_not_called()

	@patch(f"{_M}.frappe")
	def test_no_state_change_is_a_no_op(self, fr):
		doc = _brief("CD Creative", "Gate 1 Prep")
		doc.has_value_changed.return_value = False
		study.on_brief_study_signal(doc)
		fr.get_doc.assert_not_called()

	@patch(f"{_M}.frappe")
	def test_study_failure_never_breaks_the_save(self, fr):
		fr.db.get_value.side_effect = RuntimeError("db exploded")
		study.on_brief_study_signal(_brief("CD Internal Gate", "Gate 2 Prep"))  # must not raise
		fr.log_error.assert_called()


if __name__ == "__main__":
	unittest.main()
