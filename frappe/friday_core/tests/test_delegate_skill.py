# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""
Unit tests for the delegate-task skill (design 57, LOCKED).

Mock-based — no DB, no model. Pins the locked contract:
  Q1 every delegation creates a Task row (state Executing — never Assigned,
     so the mechanical task machinery doesn't double-run it)
  Q2 sync: the child's summary lands on Task.result and returns to the parent
  Q3 isolation: the child runs in a fresh `task::<name>` session and sees only
     the task framing (never the parent's conversation)
  Q4 depth cap: a child (task:: session) may not delegate
  Q5 named profile wins; else the existing capability matcher; actionable
     error when nothing matches
  failure path: child error → Task Blocked + actionable ValueError (type
     name only, redaction policy)
"""

import unittest
from unittest.mock import MagicMock, patch

from frappe.friday_core.skills import handlers_delegate

_H = "frappe.friday_core.skills.handlers_delegate"
_RUN = "frappe.friday_core.agent_runner.runner.run_turn"
_MATCH = "frappe.friday_core.tasks.dispatcher._match_profiles"


def _params(**overrides):
	p = {
		"title": "Draft taglines",
		"instructions": "Write 3 tagline options for Loop Coffee. Warm, crafted, honest.",
		"profile": "Copywriter",
	}
	p.update(overrides)
	return p


def _ctx_frappe(mock_frappe, session="chat-session-1", profile="Friday"):
	"""Wire the dispatch-context flags + a Task doc mock onto a patched frappe."""
	mock_frappe.flags.get.return_value = {"session_id": session, "agent_profile": profile}
	task = MagicMock()
	task.name = "TASK-0007"
	mock_frappe.get_doc.return_value = task
	mock_frappe.db.exists.return_value = True
	mock_frappe.db.get_value.return_value = "Active"
	return task


class TestDepthAndValidation(unittest.TestCase):
	@patch(f"{_H}.frappe")
	def test_child_session_cannot_delegate(self, mock_frappe):
		_ctx_frappe(mock_frappe, session="task::TASK-0001")
		with self.assertRaises(ValueError) as ctx:
			handlers_delegate.delegate_task("delegate-task", _params())
		self.assertIn("depth", str(ctx.exception))

	@patch(f"{_H}.frappe")
	def test_missing_title_and_instructions_raise(self, mock_frappe):
		_ctx_frappe(mock_frappe)
		for missing in ("title", "instructions"):
			with self.assertRaises(ValueError) as ctx:
				handlers_delegate.delegate_task("delegate-task", _params(**{missing: ""}))
			self.assertIn(missing, str(ctx.exception))

	@patch(f"{_H}.frappe")
	def test_unknown_named_profile_raises(self, mock_frappe):
		_ctx_frappe(mock_frappe)
		mock_frappe.db.exists.return_value = False
		with self.assertRaises(ValueError) as ctx:
			handlers_delegate.delegate_task("delegate-task", _params(profile="Ghost"))
		self.assertIn("Ghost", str(ctx.exception))

	@patch(f"{_H}.frappe")
	def test_inactive_named_profile_raises(self, mock_frappe):
		_ctx_frappe(mock_frappe)
		mock_frappe.db.get_value.return_value = "Draft"
		with self.assertRaises(ValueError) as ctx:
			handlers_delegate.delegate_task("delegate-task", _params())
		self.assertIn("Active", str(ctx.exception))


class TestProfileResolution(unittest.TestCase):
	@patch(_MATCH)
	@patch(_RUN, return_value="done")
	@patch(f"{_H}.frappe")
	def test_named_profile_wins_matcher_not_called(self, mock_frappe, mock_run, mock_match):
		_ctx_frappe(mock_frappe)
		handlers_delegate.delegate_task("delegate-task", _params(profile="Copywriter"))
		mock_match.assert_not_called()
		self.assertEqual(mock_run.call_args.kwargs["profile_name"], "Copywriter")

	@patch(_MATCH, return_value=["Copywriter", "Generalist"])
	@patch(_RUN, return_value="done")
	@patch(f"{_H}.frappe")
	def test_auto_match_first_active_when_no_profile_named(self, mock_frappe, mock_run, mock_match):
		_ctx_frappe(mock_frappe)
		handlers_delegate.delegate_task(
			"delegate-task", _params(profile="", required_skills=["create-brand-direction"])
		)
		mock_match.assert_called_once()
		self.assertEqual(mock_run.call_args.kwargs["profile_name"], "Copywriter")

	@patch(_MATCH, return_value=[])
	@patch(f"{_H}.frappe")
	def test_no_match_raises_actionable_error(self, mock_frappe, mock_match):
		_ctx_frappe(mock_frappe)
		with self.assertRaises(ValueError) as ctx:
			handlers_delegate.delegate_task(
				"delegate-task", _params(profile="", required_skills=["x-skill"])
			)
		self.assertIn("x-skill", str(ctx.exception))

	def test_skill_list_normalisation_accepts_string(self):
		self.assertEqual(
			handlers_delegate._normalise_skill_list("a, b\nc"), ["a", "b", "c"]
		)
		self.assertEqual(handlers_delegate._normalise_skill_list(["a", " b "]), ["a", "b"])
		self.assertEqual(handlers_delegate._normalise_skill_list(None), [])


class TestHappyPath(unittest.TestCase):
	@patch(_RUN, return_value="Taglines drafted: A, B, C.")
	@patch(f"{_H}.frappe")
	def test_task_row_child_isolation_and_summary(self, mock_frappe, mock_run):
		task = _ctx_frappe(mock_frappe, session="parent-session", profile="Friday")

		out = handlers_delegate.delegate_task("delegate-task", _params())

		# Q1 — Task row created in Executing state (never Assigned).
		payload = mock_frappe.get_doc.call_args[0][0]
		self.assertEqual(payload["doctype"], "Task")
		self.assertEqual(payload["workflow_state"], "Executing")
		self.assertEqual(payload["assigned_to_profile"], "Copywriter")
		self.assertIn("Friday", payload["description"])  # audit breadcrumb
		task.insert.assert_called_once_with(ignore_permissions=True)

		# Q3 — child isolation: fresh task:: session, framing only.
		kwargs = mock_run.call_args.kwargs
		self.assertEqual(kwargs["session_id"], "task::TASK-0007")
		self.assertIn("Instructions:", kwargs["inbound_content"])
		self.assertIn("Loop Coffee", kwargs["inbound_content"])
		self.assertNotIn("parent-session", kwargs["inbound_content"])

		# Q2 — summary stored (JSON envelope — Task.result is a JSON column)
		# and returned to the parent.
		mock_frappe.as_json.assert_called_with(
			{"status": "success", "summary": "Taglines drafted: A, B, C."}
		)
		self.assertEqual(task.result, mock_frappe.as_json.return_value)
		self.assertEqual(task.workflow_state, "Completed")
		task.save.assert_called_with(ignore_permissions=True)
		self.assertIn("Taglines drafted", out["result"])
		self.assertEqual(out["record_name"], "TASK-0007")
		self.assertEqual(out["assigned_profile"], "Copywriter")

	@patch(_RUN, side_effect=RuntimeError("model exploded with secret details"))
	@patch(f"{_H}.frappe")
	def test_child_failure_blocks_task_and_raises_actionably(self, mock_frappe, mock_run):
		task = _ctx_frappe(mock_frappe)
		with self.assertRaises(ValueError) as ctx:
			handlers_delegate.delegate_task("delegate-task", _params())
		self.assertEqual(task.workflow_state, "Blocked")
		msg = str(ctx.exception)
		self.assertIn("TASK-0007", msg)
		self.assertIn("RuntimeError", msg)  # type name only...
		self.assertNotIn("secret details", msg)  # ...never the raw message


class TestRegistrationAndBootstrap(unittest.TestCase):
	def test_registered_with_dispatcher(self):
		from frappe.friday_core.agent_runner import dispatcher

		self.assertIs(
			dispatcher._SKILL_HANDLERS.get("delegate-task"),
			handlers_delegate.delegate_task,
		)

	def test_bootstrap_spec_is_valid(self):
		import json as _json

		from frappe.friday_core.skills.bootstrap_delegate import _SKILL

		schema = _SKILL["parameters_schema"]
		_json.dumps(schema)
		for required_field in schema["required"]:
			self.assertIn(required_field, schema["properties"])
		self.assertEqual(
			_SKILL["required_doctypes"], [{"target_doctype": "Task", "operation": "create"}]
		)


if __name__ == "__main__":
	unittest.main()
