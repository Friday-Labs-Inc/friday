# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""
Tests for the project status snapshot (Design 73, Slice 3).

The snapshot is what the orchestrator sees when it's standing in a project
room: status, open tasks, and deliverables — injected fresh every turn by the
prompt builder.

These tests are COMMIT-FREE — every row is created inside the test transaction
and discarded in tearDown via rollback, so running them never pollutes the live
site's data. No Raven needed: project resolution uses a ``task::`` session.

Coverage:
- snapshot carries the status + the anti-bleed scoping instruction.
- snapshot lists OPEN tasks and excludes terminal (Completed/Cancelled) ones.
- snapshot says "none yet" when there are no deliverable files.
- project_snapshot_block(missing) is None (never breaks a turn).
- build() injects the snapshot for a project (task::) session, and NOT for a
  plain DM / uuid session.
"""

from __future__ import annotations

import unittest
import uuid

import frappe
from friday.friday_core.llm.project_context import project_snapshot_block


def _project(name: str, status: str = "In Progress") -> str:
	return (
		frappe.get_doc({"doctype": "Agent Project", "project_name": name, "status": status})
		.insert(ignore_permissions=True)
		.name
	)


def _task(project: str, title: str, state: str) -> str:
	return (
		frappe.get_doc(
			{
				"doctype": "Agent Task",
				"title": title,
				"project": project,
				"priority": "normal",
				"workflow_state": state,
				"dispatchable": 0,
			}
		)
		.insert(ignore_permissions=True)
		.name
	)


class TestProjectSnapshot(unittest.TestCase):
	def setUp(self):
		self.project = _project("D73S3 Snapshot Proj")
		_task(self.project, "Design the logo", "Executing")
		_task(self.project, "Write the website copy", "Pending")
		_task(self.project, "Strategy draft", "Completed")  # terminal — excluded

	def tearDown(self):
		frappe.db.rollback()

	def test_snapshot_has_status_and_scoping(self):
		block = project_snapshot_block(self.project)
		self.assertIsNotNone(block)
		self.assertIn("PROJECT CONTEXT", block)
		self.assertIn(self.project, block)
		self.assertIn("Status: In Progress", block)

	def test_snapshot_lists_open_tasks(self):
		block = project_snapshot_block(self.project)
		self.assertIn("Design the logo", block)
		self.assertIn("Write the website copy", block)
		self.assertIn("Executing", block)

	def test_snapshot_excludes_terminal_tasks(self):
		block = project_snapshot_block(self.project)
		# The Completed task must not appear in the open-tasks list.
		self.assertNotIn("Strategy draft", block)

	def test_snapshot_deliverables_none_yet(self):
		block = project_snapshot_block(self.project)
		self.assertIn("Deliverables: none yet", block)

	def test_missing_project_returns_none(self):
		self.assertIsNone(project_snapshot_block("D73S3-does-not-exist-999"))


class TestBuildInjectsSnapshot(unittest.TestCase):
	def setUp(self):
		self.profile = "D73S3-CTX-PROFILE"
		if not frappe.db.exists("Agent Profile", self.profile):
			frappe.get_doc(
				{"doctype": "Agent Profile", "profile_name": self.profile, "status": "Active"}
			).insert(ignore_permissions=True)
		self.project = _project("D73S3 Build Proj")
		self.task = _task(self.project, "a task in the room", "Pending")

	def tearDown(self):
		frappe.db.rollback()

	def test_task_session_injects_snapshot(self):
		from friday.friday_core.llm.prompt_builder import build

		prompt = build(
			profile_name=self.profile,
			session_id=f"task::{self.task}",
			inbound_content="where are we?",
			tools=None,
		)
		system_texts = " ".join(m["content"] for m in prompt["messages"] if m["role"] == "system")
		self.assertIn("CURRENT STATE", system_texts)
		self.assertIn(self.project, system_texts)

	def test_uuid_session_has_no_snapshot(self):
		from friday.friday_core.llm.prompt_builder import build

		prompt = build(
			profile_name=self.profile,
			session_id=str(uuid.uuid4()),
			inbound_content="hi",
			tools=None,
		)
		system_texts = " ".join(m["content"] for m in prompt["messages"] if m["role"] == "system")
		self.assertNotIn("CURRENT STATE", system_texts)


if __name__ == "__main__":
	unittest.main()
