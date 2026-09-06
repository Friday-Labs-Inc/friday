# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""
Unit tests for the native-view provisioner (design 65b).

65b gives the project module its ERPNext-grade *views* using Frappe's built-in
machinery — Number Cards, Dashboard Charts, a state Kanban, and a "Projects"
Workspace — created idempotently on every migrate. No bespoke UI code; we
configure what Frappe already renders.

Two couplings matter and are pinned by tests here:
  1. The Kanban columns MUST equal the Task ``workflow_state`` Select options,
     or cards land in no column. ``test_kanban_columns_match_task_state_options``
     reads the real ``task.json`` and asserts equality.
  2. The Workspace ``content`` blob references cards/charts by the label of
     their child rows; ``test_workspace_content_references_children`` parses the
     blob and checks every reference resolves.

Pure unit tests with ``frappe`` mocked — same style as ``test_agent_identity``.
"""

import json
import os
import unittest
from unittest.mock import patch


class _FakeDoc(dict):
	def __getattr__(self, k):
		try:
			return self[k]
		except KeyError as e:
			raise AttributeError(k) from e

	def __setattr__(self, k, v):
		self[k] = v

	def append(self, field, row):
		self.setdefault(field, []).append(row)
		return row

	def insert(self, *a, **kw):
		self["_inserted"] = True
		return self

	def save(self, *a, **kw):
		self["_saved"] = True
		return self


def _task_json_path():
	here = os.path.dirname(__file__)
	return os.path.normpath(os.path.join(here, "..", "doctype", "task", "task.json"))


class TestTaskStateField(unittest.TestCase):
	"""``workflow_state`` is a Select whose options are the canonical state set."""

	def test_workflow_state_is_select_with_canonical_options(self):
		from friday.friday_core.console.provision_console import TASK_STATES

		with open(_task_json_path()) as fh:
			task = json.load(fh)
		field = next(f for f in task["fields"] if f["fieldname"] == "workflow_state")
		self.assertEqual(field["fieldtype"], "Select")
		options = [o for o in field["options"].split("\n") if o]
		self.assertEqual(options, TASK_STATES)


class TestNumberCards(unittest.TestCase):
	@patch("friday.friday_core.console.provision_console.frappe")
	def test_creates_cards_when_absent(self, mock_frappe):
		from friday.friday_core.console.provision_console import NUMBER_CARDS, provision_console

		built = []
		mock_frappe.db.exists.return_value = False
		mock_frappe.get_doc.side_effect = lambda spec: (
			built.append(spec) if isinstance(spec, dict) and spec.get("doctype") == "Number Card" else None,
			_FakeDoc(spec if isinstance(spec, dict) else {}),
		)[1]

		provision_console()

		labels = {c["label"] for c in built}
		self.assertEqual(labels, {c["label"] for c in NUMBER_CARDS})
		# Each card targets a real DocType + Count function with a filter blob.
		for c in built:
			self.assertEqual(c["function"], "Count")
			self.assertIn(c["document_type"], {"Project", "Task", "Issue"})
			json.loads(c["filters_json"])  # must be valid JSON

	@patch("friday.friday_core.console.provision_console.frappe")
	def test_idempotent_when_card_exists(self, mock_frappe):
		from friday.friday_core.console.provision_console import provision_console

		# Everything already exists → nothing inserted.
		mock_frappe.db.exists.return_value = True
		mock_frappe.get_doc.side_effect = lambda *a, **k: _FakeDoc(
			{"columns": [], "number_cards": [], "charts": [], "shortcuts": []}
		)

		summary = provision_console()
		self.assertEqual(summary["created"], [])


class TestDashboardCharts(unittest.TestCase):
	@patch("friday.friday_core.console.provision_console.frappe")
	def test_creates_charts_when_absent(self, mock_frappe):
		from friday.friday_core.console.provision_console import DASHBOARD_CHARTS, provision_console

		built = []
		mock_frappe.db.exists.return_value = False

		def _get_doc(spec):
			if isinstance(spec, dict) and spec.get("doctype") == "Dashboard Chart":
				built.append(spec)
			return _FakeDoc(spec if isinstance(spec, dict) else {})

		mock_frappe.get_doc.side_effect = _get_doc
		provision_console()

		names = {c["chart_name"] for c in built}
		self.assertEqual(names, {c["chart_name"] for c in DASHBOARD_CHARTS})


class TestKanbanBoard(unittest.TestCase):
	@patch("friday.friday_core.console.provision_console.frappe")
	def test_kanban_created_on_task_workflow_state(self, mock_frappe):
		from friday.friday_core.console.provision_console import (
			KANBAN_NAME,
			TASK_STATES,
			provision_console,
		)

		built = {}
		mock_frappe.db.exists.return_value = False

		def _get_doc(spec):
			doc = _FakeDoc(spec if isinstance(spec, dict) else {})
			if isinstance(spec, dict) and spec.get("doctype") == "Kanban Board":
				built["k"] = doc
			return doc

		mock_frappe.get_doc.side_effect = _get_doc
		provision_console()

		k = built["k"]
		self.assertEqual(k["kanban_board_name"], KANBAN_NAME)
		self.assertEqual(k["reference_doctype"], "Task")
		self.assertEqual(k["field_name"], "workflow_state")
		columns = [c["column_name"] for c in k["columns"]]
		self.assertEqual(columns, TASK_STATES)

	def test_kanban_columns_match_task_state_options(self):
		"""The Kanban columns and the Task Select options must be identical."""
		from friday.friday_core.console.provision_console import TASK_STATES

		with open(_task_json_path()) as fh:
			task = json.load(fh)
		field = next(f for f in task["fields"] if f["fieldname"] == "workflow_state")
		options = [o for o in field["options"].split("\n") if o]
		self.assertEqual(options, TASK_STATES)


class TestWorkspace(unittest.TestCase):
	@patch("friday.friday_core.console.provision_console.frappe")
	def test_workspace_created_with_children(self, mock_frappe):
		from friday.friday_core.console.provision_console import (
			DASHBOARD_CHARTS,
			NUMBER_CARDS,
			WORKSPACE_NAME,
			provision_console,
		)

		built = {}
		mock_frappe.db.exists.return_value = False

		def _get_doc(spec):
			doc = _FakeDoc(spec if isinstance(spec, dict) else {})
			if isinstance(spec, dict) and spec.get("doctype") == "Workspace":
				built["ws"] = doc
			return doc

		mock_frappe.get_doc.side_effect = _get_doc
		provision_console()

		ws = built["ws"]
		self.assertEqual(ws["label"], WORKSPACE_NAME)
		self.assertEqual(ws["public"], 1)
		card_refs = {r["number_card_name"] for r in ws["number_cards"]}
		self.assertEqual(card_refs, {c["label"] for c in NUMBER_CARDS})
		chart_refs = {r["chart_name"] for r in ws["charts"]}
		self.assertEqual(chart_refs, {c["chart_name"] for c in DASHBOARD_CHARTS})
		# Shortcuts to the Task Kanban + Project list at minimum.
		shortcut_targets = {(s["type"], s["link_to"]) for s in ws["shortcuts"]}
		self.assertIn(("DocType", "Project"), shortcut_targets)
		self.assertIn(("DocType", "Task"), shortcut_targets)

	@patch("friday.friday_core.console.provision_console.frappe")
	def test_workspace_content_references_children(self, mock_frappe):
		from friday.friday_core.console.provision_console import provision_console

		built = {}
		mock_frappe.db.exists.return_value = False

		def _get_doc(spec):
			doc = _FakeDoc(spec if isinstance(spec, dict) else {})
			if isinstance(spec, dict) and spec.get("doctype") == "Workspace":
				built["ws"] = doc
			return doc

		mock_frappe.get_doc.side_effect = _get_doc
		provision_console()

		ws = built["ws"]
		content = json.loads(ws["content"])  # must be a valid JSON string
		card_labels = {r["number_card_name"] for r in ws["number_cards"]}
		chart_labels = {r["chart_name"] for r in ws["charts"]}
		for block in content:
			if block["type"] == "number_card":
				self.assertIn(block["data"]["number_card_name"], card_labels)
			elif block["type"] == "chart":
				self.assertIn(block["data"]["chart_name"], chart_labels)


class TestHubWorkspace(unittest.TestCase):
	"""The top-level "Friday" navigation hub workspace."""

	def _provision_and_capture_hub(self, mock_frappe):
		"""Run provision_console with frappe mocked; return the built hub doc.

		Both the hub and the "Projects" workspace are Workspace docs, so we key
		capture on the hub's title to grab the right one.
		"""
		from friday.friday_core.console.provision_console import (
			HUB_WORKSPACE_NAME,
			provision_console,
		)

		built = {}

		# DocType-existence checks (the hub's link guard) must read True so every
		# curated link is included; every other exists() check (does this
		# Workspace/Card/etc. already exist?) reads False so artifacts get created.
		def _exists(doctype, name=None):
			return doctype == "DocType"

		mock_frappe.db.exists.side_effect = _exists

		def _get_doc(spec):
			doc = _FakeDoc(spec if isinstance(spec, dict) else {})
			if isinstance(spec, dict) and spec.get("title") == HUB_WORKSPACE_NAME:
				built["hub"] = doc
			return doc

		mock_frappe.get_doc.side_effect = _get_doc
		provision_console()
		return built["hub"]

	@patch("friday.friday_core.console.provision_console.frappe")
	def test_hub_created_public_and_sorts_first(self, mock_frappe):
		from friday.friday_core.console.provision_console import HUB_WORKSPACE_NAME

		hub = self._provision_and_capture_hub(mock_frappe)
		self.assertEqual(hub["label"], HUB_WORKSPACE_NAME)
		self.assertEqual(hub["public"], 1)
		# Negative sequence so it lands above the default workspaces (min is 0).
		self.assertLess(hub["sequence_id"], 0)

	@patch("friday.friday_core.console.provision_console.frappe")
	def test_hub_has_all_shortcuts_and_cards(self, mock_frappe):
		from friday.friday_core.console.provision_console import HUB_CARDS, HUB_SHORTCUTS

		hub = self._provision_and_capture_hub(mock_frappe)
		# every shortcut tile present
		self.assertEqual(
			{s["label"] for s in hub["shortcuts"]},
			{s["label"] for s in HUB_SHORTCUTS},
		)
		# every nav card present as a Card Break
		breaks = {l["label"] for l in hub["links"] if l["type"] == "Card Break"}
		self.assertEqual(breaks, {c["label"] for c in HUB_CARDS})
		# every declared DocType link present under some card
		link_targets = {l["link_to"] for l in hub["links"] if l["type"] == "Link"}
		for card in HUB_CARDS:
			for dt in card["links"]:
				self.assertIn(dt, link_targets)

	@patch("friday.friday_core.console.provision_console.frappe")
	def test_hub_content_references_resolve(self, mock_frappe):
		hub = self._provision_and_capture_hub(mock_frappe)
		content = json.loads(hub["content"])  # must be a valid JSON string
		shortcut_labels = {s["label"] for s in hub["shortcuts"]}
		card_labels = {l["label"] for l in hub["links"] if l["type"] == "Card Break"}
		for block in content:
			if block["type"] == "shortcut":
				self.assertIn(block["data"]["shortcut_name"], shortcut_labels)
			elif block["type"] == "card":
				self.assertIn(block["data"]["card_name"], card_labels)


class TestFailureIsolation(unittest.TestCase):
	@patch("friday.friday_core.console.provision_console.frappe")
	def test_one_failure_does_not_abort_the_rest(self, mock_frappe):
		from friday.friday_core.console.provision_console import provision_console

		mock_frappe.db.exists.return_value = False
		calls = {"n": 0}

		def _get_doc(spec):
			calls["n"] += 1
			# Fail the very first insert; the rest must still run.
			if calls["n"] == 1:
				raise RuntimeError("boom")
			return _FakeDoc(spec if isinstance(spec, dict) else {})

		mock_frappe.get_doc.side_effect = _get_doc

		summary = provision_console()
		self.assertTrue(summary["failed"])
		self.assertTrue(mock_frappe.log_error.called)
		# More than one artifact was attempted despite the first failing.
		self.assertGreater(calls["n"], 1)


if __name__ == "__main__":
	unittest.main()
