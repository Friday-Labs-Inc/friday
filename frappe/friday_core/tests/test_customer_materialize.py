# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""Design 96 Slice 2 — the customer materialize layer + the filtered bridge push.

DB-free. Pins the E2E lessons:
  - #18: the customer gets branded, HUMAN-named PDFs — not hash-named raw markdown.
  - The leak: internal files (the CD's refinement notes) must NEVER be selected or
    pushed — only the title-mapped phase outputs and explicitly flagged files.
  - #6: the gate presentation is pushed BEFORE the gate-open signal.
  - #13: the gate actually opens (RP task → Working) and the Design-95 phase
    vocabulary (`production`) maps to RP's task subjects.
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, call, patch

from frappe.friday_core.deliverables import materialize
from frappe.friday_core.integrations import randompack_bridge as bridge

_M = "frappe.friday_core.deliverables.materialize"


class TestSelectCustomerSources(unittest.TestCase):
	def test_latest_version_wins_per_pattern(self):
		files = [
			{"name": "f1", "file_name": "production-package93e487.md", "creation": "2026-07-04 10:00:00"},
			{"name": "f2", "file_name": "production-package99dc58.md", "creation": "2026-07-05 08:00:00"},
		]
		out = materialize.select_customer_sources(files)
		self.assertEqual(len(out), 1)
		title, row = out[0]
		self.assertEqual(title, "Brand System — Production Package")
		self.assertEqual(row["name"], "f2")  # the refined r2 package, not the draft

	def test_internal_files_are_never_selected(self):
		# The E2E leak: refinement notes + the CD's working doc went to the customer.
		files = [
			{"name": "f1", "file_name": "cd-refinement-notes-r1.md", "creation": "t"},
			{"name": "f2", "file_name": "friday-labs-design-system.md", "creation": "t"},
			{"name": "f3", "file_name": "random-scratch.md", "creation": "t"},
		]
		self.assertEqual(materialize.select_customer_sources(files), [])

	def test_full_pipeline_set_selected_with_human_titles(self):
		files = [
			{"name": "a", "file_name": "strategy28fb97.md", "creation": "1"},
			{"name": "b", "file_name": "naming-candidatese11bd5.md", "creation": "2"},
			{"name": "c", "file_name": "gate1-client-presentationa116f7.md", "creation": "3"},
			{"name": "d", "file_name": "production-package99dc58.md", "creation": "4"},
			{"name": "e", "file_name": "gate2-final-reviewf736ea.md", "creation": "5"},
			{"name": "f", "file_name": "brand-guidelines8e02e8.md", "creation": "6"},
			{"name": "g", "file_name": "cd-refinement-notes-r1.md", "creation": "7"},  # never
		]
		out = materialize.select_customer_sources(files)
		titles = [t for t, _ in out]
		self.assertEqual(
			titles,
			[
				"Brand Guidelines",
				"Brand System — Production Package",
				"Final Review (Gate 2)",
				"Direction Presentation (Gate 1)",
				"Naming Candidates",
				"Brand Strategy",
			],
		)

	def test_non_md_files_are_not_sources(self):
		# The rendered PDFs themselves (or images) must not be re-selected as sources.
		files = [{"name": "p", "file_name": "brand-guidelines8e02e8.pdf", "creation": "t"}]
		self.assertEqual(materialize.select_customer_sources(files), [])


class TestDeliverableHtml(unittest.TestCase):
	def test_brand_context_injects_company_accent_and_logo(self):
		html = materialize._deliverable_html(
			"Friday Labs Inc — Brand Guidelines",
			"<p>body</p>",
			{"company": "Friday Labs Inc", "accent": "#3DD6C4", "logo_data_uri": "data:image/png;base64,AAA"},
		)
		self.assertIn("Friday Labs Inc", html)
		self.assertIn("#3DD6C4", html)
		self.assertIn("data:image/png;base64,AAA", html)

	def test_no_context_renders_plain(self):
		html = materialize._deliverable_html("Title", "<p>x</p>", None)
		self.assertNotIn("<img", html)
		self.assertIn("Title", html)


class TestEnsureCustomerFacingField(unittest.TestCase):
	@patch(f"{_M}.frappe")
	def test_idempotent_when_field_exists(self, fr):
		fr.db.exists.return_value = True
		materialize.ensure_customer_facing_field()  # must not attempt creation
		# create_custom_field is imported lazily — existence short-circuits before it.
		fr.db.exists.assert_called_once()


class TestBridgeMapsSpeakDesign95(unittest.TestCase):
	"""E2E finding #13 (second half): the maps only spoke the OLD phase vocabulary,
	so RP's Build system task never advanced on the new machine."""

	def test_production_phase_maps_to_build_system(self):
		self.assertEqual(bridge._SUBJECT_MAP["production"], "Build system")
		self.assertEqual(bridge._SUBJECT_MAP["buildout"], "Build system")  # legacy kept

	def test_gate_task_and_doc_maps_cover_both_gates(self):
		for phase in ("gate1_prep", "gate2_prep"):
			self.assertIn(phase, bridge._GATE_TASK_SUBJECT)
			self.assertIn(phase, bridge._GATE_DOC_PREFIX)
			self.assertIn(phase, bridge._GATE_DOC_TITLE)


class TestGateOpenSequence(unittest.TestCase):
	"""E2E findings #6 + #13: on a gate-prep completion the bridge must (in order)
	push the presentation → signal gate-open → flip the RP gate task to Working."""

	@patch.object(bridge, "_push_gate_presentation")
	@patch.object(bridge, "_resolve_rp_task_by_subject")
	@patch.object(bridge, "_resolve_rp_task")
	@patch.object(bridge, "client")
	@patch.object(bridge, "frappe")
	def test_gate_prep_completion_pushes_then_opens_then_flips(
		self, fr, m_client, m_resolve, m_resolve_by_subject, m_push_gate
	):
		fr.db.get_value.return_value = "RP-PROJ-1"  # brief → rp_project
		m_resolve.return_value = "RP-TASK-PREP"
		m_resolve_by_subject.return_value = "RP-TASK-GATE1"

		order: list[str] = []
		m_push_gate.side_effect = lambda *a, **k: order.append("push_presentation")
		m_client.request_gate_open.side_effect = lambda *a, **k: order.append("gate_open")
		m_client.update_task_progress.side_effect = lambda *a, **k: order.append(
			f"task:{k.get('status') or (a[1] if len(a) > 1 else '')}"
		)

		task = MagicMock()
		task.work_item_name = "BB-1"
		task.phase_key = "gate1_prep"
		task.get.side_effect = lambda k, d=None: {
			"title": "Gate 1 Prep",
			"result": '{"status": "success", "summary": "ready"}',
		}.get(k, d)

		bridge._engine_writeback(task, "Completed")

		# The presentation crosses the seam BEFORE the gate opens; the gate task
		# flips to Working AFTER the signal (the actual open mechanism on RP).
		self.assertIn("push_presentation", order)
		self.assertIn("gate_open", order)
		self.assertLess(order.index("push_presentation"), order.index("gate_open"))
		self.assertIn("task:Working", order)
		self.assertLess(order.index("gate_open"), order.index("task:Working"))

	@patch.object(bridge, "_push_gate_presentation")
	@patch.object(bridge, "_resolve_rp_task")
	@patch.object(bridge, "client")
	@patch.object(bridge, "frappe")
	def test_non_gate_phase_does_not_touch_gate_machinery(self, fr, m_client, m_resolve, m_push_gate):
		fr.db.get_value.return_value = "RP-PROJ-1"
		m_resolve.return_value = "RP-TASK-PROD"
		task = MagicMock()
		task.work_item_name = "BB-1"
		task.phase_key = "production"
		task.get.side_effect = lambda k, d=None: {"title": "Production", "result": "{}"}.get(k, d)

		bridge._engine_writeback(task, "Completed")

		m_push_gate.assert_not_called()
		m_client.request_gate_open.assert_not_called()


class TestFilteredPush(unittest.TestCase):
	"""The customer push must query ONLY is_customer_facing=1 files (the leak fix)."""

	@patch.object(bridge, "client")
	@patch.object(bridge, "frappe")
	def test_push_queries_filter_on_customer_flag(self, fr, m_client):
		seen_filters: list[dict] = []

		def fake_get_all(doctype, filters=None, fields=None, **k):
			seen_filters.append(dict(filters or {}))
			return []

		fr.get_all.side_effect = fake_get_all
		fr.db.get_value.return_value = "PROJ-LOCAL"

		bridge._push_deliverables("RP-PROJ-1", "BB-1")

		self.assertEqual(len(seen_filters), 2)  # brief files + project files
		for f in seen_filters:
			self.assertEqual(f.get(materialize.CUSTOMER_FLAG_FIELD), 1)
		m_client.attach_deliverable.assert_not_called()  # nothing flagged → nothing pushed


if __name__ == "__main__":
	unittest.main()
