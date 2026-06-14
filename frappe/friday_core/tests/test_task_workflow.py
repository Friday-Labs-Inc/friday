# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""
Unit tests for the task workflow state-machine hook.

Covers: dispatchable derivation, started_at/completed_at timestamps,
assigned_to_profile clearing on cancel, and Redis pub/sub emission.
"""

import unittest
from unittest.mock import MagicMock, patch


def _mock_doc(**attrs):
	"""
	Return a MagicMock doc with has_value_changed pre-wired as a side-effect
	function so tests can control the return for each call independently.
	"""
	doc = MagicMock(**attrs)
	# has_value_changed must be a callable that returns the expected bool.
	# Using a real MagicMock so chained calls like
	#   doc.has_value_changed("workflow_state").return_value = X
	# work correctly.
	doc.has_value_changed = MagicMock()
	return doc


class TestDispatchableStates(unittest.TestCase):
	"""DISPATCHABLE_STATES is a frozen frozenset with Pending and Assigned."""

	def test_dispatchable_states_is_frozenset(self):
		from frappe.friday_core.tasks.workflow import DISPATCHABLE_STATES

		self.assertIsInstance(DISPATCHABLE_STATES, frozenset)

	def test_dispatchable_states_contains_pending_and_assigned(self):
		from frappe.friday_core.tasks.workflow import DISPATCHABLE_STATES

		self.assertIn("Pending", DISPATCHABLE_STATES)
		self.assertIn("Assigned", DISPATCHABLE_STATES)

	def test_dispatchable_states_does_not_contain_other_states(self):
		from frappe.friday_core.tasks.workflow import DISPATCHABLE_STATES

		for state in ("Executing", "Blocked", "Review", "Completed", "Cancelled"):
			self.assertNotIn(state, DISPATCHABLE_STATES)


class TestOnStateChangeDispatchable(unittest.TestCase):
	"""on_state_change sets dispatchable from workflow_state."""

	@patch("frappe.friday_core.tasks.workflow.frappe")
	def test_pending_sets_dispatchable_true(self, mock_frappe):
		from frappe.friday_core.tasks.workflow import on_state_change

		doc = _mock_doc(workflow_state="Pending", dispatchable=False)

		on_state_change(doc, "on_update")

		self.assertTrue(doc.dispatchable)

	@patch("frappe.friday_core.tasks.workflow.frappe")
	def test_assigned_sets_dispatchable_true(self, mock_frappe):
		from frappe.friday_core.tasks.workflow import on_state_change

		doc = _mock_doc(workflow_state="Assigned", dispatchable=False)

		on_state_change(doc, "on_update")

		self.assertTrue(doc.dispatchable)

	@patch("frappe.friday_core.tasks.workflow.frappe")
	def test_executing_sets_dispatchable_false(self, mock_frappe):
		from frappe.friday_core.tasks.workflow import on_state_change

		doc = _mock_doc(workflow_state="Executing", dispatchable=True)

		on_state_change(doc, "on_update")

		self.assertFalse(doc.dispatchable)


class TestStartedAt(unittest.TestCase):
	"""started_at is recorded when entering the Executing state."""

	@patch("frappe.friday_core.tasks.workflow.frappe")
	def test_transitioning_to_executing_sets_started_at(self, mock_frappe):
		from frappe.friday_core.tasks.workflow import on_state_change

		mock_frappe.utils.now_datetime.return_value = "2026-01-01 12:00:00"

		doc = _mock_doc(workflow_state="Executing", started_at=None)
		doc.has_value_changed.return_value = True

		on_state_change(doc, "on_update")

		self.assertEqual(doc.started_at, "2026-01-01 12:00:00")

	@patch("frappe.friday_core.tasks.workflow.frappe")
	def test_started_at_not_overwritten_if_already_set(self, mock_frappe):
		from frappe.friday_core.tasks.workflow import on_state_change

		existing = "2025-12-01 09:00:00"
		mock_frappe.utils.now_datetime.return_value = "2026-01-01 12:00:00"

		doc = _mock_doc(workflow_state="Executing", started_at=existing)
		doc.has_value_changed.return_value = True

		on_state_change(doc, "on_update")

		# Should remain the pre-existing value.
		self.assertEqual(doc.started_at, existing)


class TestCompletedAt(unittest.TestCase):
	"""completed_at is recorded when entering Completed or Cancelled."""

	@patch("frappe.friday_core.tasks.workflow.frappe")
	def test_completing_sets_completed_at(self, mock_frappe):
		from frappe.friday_core.tasks.workflow import on_state_change

		mock_frappe.utils.now_datetime.return_value = "2026-01-01 18:00:00"

		doc = _mock_doc(workflow_state="Completed", completed_at=None)
		doc.has_value_changed.return_value = True

		on_state_change(doc, "on_update")

		self.assertEqual(doc.completed_at, "2026-01-01 18:00:00")

	@patch("frappe.friday_core.tasks.workflow.frappe")
	def test_cancelling_sets_completed_at(self, mock_frappe):
		from frappe.friday_core.tasks.workflow import on_state_change

		mock_frappe.utils.now_datetime.return_value = "2026-01-01 18:00:00"

		doc = _mock_doc(workflow_state="Cancelled", completed_at=None)
		doc.has_value_changed.return_value = True

		on_state_change(doc, "on_update")

		self.assertEqual(doc.completed_at, "2026-01-01 18:00:00")


class TestAssignedToProfileClearing(unittest.TestCase):
	"""assigned_to_profile is cleared when transitioning to Cancelled."""

	@patch("frappe.friday_core.tasks.workflow.frappe")
	def test_cancelling_clears_assigned_to_profile(self, mock_frappe):
		from frappe.friday_core.tasks.workflow import on_state_change

		doc = _mock_doc(workflow_state="Cancelled", assigned_to_profile="note_taker", completed_at=None)
		doc.has_value_changed.return_value = True

		on_state_change(doc, "on_update")

		self.assertIsNone(doc.assigned_to_profile)


class TestRunnerEnqueue(unittest.TestCase):
	"""The runner is enqueued when transitioning to Assigned with a profile change.

	This is the single trigger chokepoint. It is an RQ ``frappe.enqueue`` — NOT
	``publish_realtime`` (which is browser-only on the server side and would
	leave the task stalled in Assigned forever).
	"""

	@patch("frappe.friday_core.tasks.workflow.frappe")
	def test_enqueues_runner_on_pending_to_assigned(self, mock_frappe):
		from frappe.friday_core.tasks.workflow import on_state_change

		doc = _mock_doc(
			workflow_state="Assigned",
			assigned_to_profile="note_taker",
			completed_at=None,
		)
		# MagicMock(name="AT-000042") sets the mock's debug name, not doc.name.
		# Set it explicitly so doc.name returns the real string.
		type(doc).name = property(lambda self: "AT-000042")
		# First call: workflow_state changed → True
		# Second call: assigned_to_profile changed → True
		doc.has_value_changed.side_effect = lambda key: True

		on_state_change(doc, "on_update")

		mock_frappe.enqueue.assert_called_once()
		call_args = mock_frappe.enqueue.call_args
		self.assertEqual(
			call_args.args[0],
			"frappe.friday_core.tasks.runner.on_agent_task_assigned",
		)
		# Design 61 Q4 (LOCKED): dedicated 'friday' queue isolates agent work
		# from Frappe housekeeping and matches what RandomPack already uses.
		self.assertEqual(call_args.kwargs["queue"], "friday")
		self.assertEqual(call_args.kwargs["job_name"], "task:AT-000042")
		self.assertTrue(call_args.kwargs["enqueue_after_commit"])
		actual_message = call_args.kwargs["message"]
		self.assertEqual(actual_message["task_name"], "AT-000042")
		self.assertEqual(actual_message["assigned_to_profile"], "note_taker")
		self.assertEqual(actual_message["workflow_state"], "Assigned")

	@patch("frappe.friday_core.tasks.workflow.frappe")
	def test_uses_enqueue_not_publish_realtime(self, mock_frappe):
		from frappe.friday_core.tasks.workflow import on_state_change

		doc = _mock_doc(
			workflow_state="Assigned",
			assigned_to_profile="note_taker",
			completed_at=None,
		)
		type(doc).name = property(lambda self: "AT-000042")
		doc.has_value_changed.side_effect = lambda key: True

		on_state_change(doc, "on_update")

		mock_frappe.publish_realtime.assert_not_called()

	@patch("frappe.friday_core.tasks.workflow.frappe")
	def test_no_enqueue_when_assigned_but_profile_unchanged(self, mock_frappe):
		from frappe.friday_core.tasks.workflow import on_state_change

		doc = _mock_doc(
			workflow_state="Assigned",
			assigned_to_profile="note_taker",
			completed_at=None,
			name="AT-000042",
		)
		# workflow_state changed → True, but assigned_to_profile unchanged → False
		doc.has_value_changed.side_effect = lambda key: key != "assigned_to_profile"

		on_state_change(doc, "on_update")

		mock_frappe.enqueue.assert_not_called()


class TestSideEffectsPersisted(unittest.TestCase):
	"""Derived/side-effect fields are persisted via db_set even without a state change.

	on_state_change runs ON on_update, so it uses db_set (not save) to avoid
	re-firing on_update → infinite recursion.
	"""

	@patch("frappe.friday_core.tasks.workflow.frappe")
	def test_db_set_called_even_when_no_state_change(self, mock_frappe):
		from frappe.friday_core.tasks.workflow import on_state_change

		doc = _mock_doc(workflow_state="Executing", dispatchable=False)
		doc.has_value_changed.return_value = False

		on_state_change(doc, "on_update")

		doc.db_set.assert_called_once()
		doc.save.assert_not_called()


class TestExecutingTokenRelease(unittest.TestCase):
	"""executing_token (the runner's claim) is released on every state but Executing.

	A leftover token strands a reset task: the dispatcher's claim guard skips any
	row where COALESCE(executing_token,'') != ''. Deriving the release in the hook
	keeps the failure→Blocked and reset→Pending paths consistent.
	"""

	@patch("frappe.friday_core.tasks.workflow.frappe")
	def test_non_executing_states_release_token(self, mock_frappe):
		from frappe.friday_core.tasks.workflow import on_state_change

		for state in ("Pending", "Assigned", "Blocked", "Review", "Completed", "Cancelled"):
			doc = _mock_doc(workflow_state=state, executing_token="tok123")
			doc.has_value_changed.return_value = False

			on_state_change(doc, "on_update")

			self.assertIsNone(doc.executing_token, f"{state} must release the token")
			persisted = doc.db_set.call_args.args[0]
			self.assertIn("executing_token", persisted, f"{state} must persist the release")
			self.assertIsNone(persisted["executing_token"])

	@patch("frappe.friday_core.tasks.workflow.frappe")
	def test_executing_state_preserves_token(self, mock_frappe):
		"""While Executing the hook must NOT touch the token — the runner's atomic
		raw-SQL claim owns it; writing a stale in-memory value would clobber it."""
		from frappe.friday_core.tasks.workflow import on_state_change

		doc = _mock_doc(workflow_state="Executing", executing_token="tok123")
		doc.has_value_changed.return_value = False

		on_state_change(doc, "on_update")

		self.assertEqual(doc.executing_token, "tok123")
		persisted = doc.db_set.call_args.args[0]
		self.assertNotIn("executing_token", persisted)

	@patch("frappe.friday_core.tasks.workflow.frappe")
	def test_retry_reset_blocked_to_pending_is_redispatchable(self, mock_frappe):
		"""The reported bug: a Blocked task reset to Pending must clear the token
		AND become dispatchable=1, or the dispatcher never re-claims it."""
		from frappe.friday_core.tasks.workflow import on_state_change

		# the reset moved state to Pending but a stale claim token lingers
		doc = _mock_doc(
			workflow_state="Pending",
			executing_token="f0173bca820f90cc",
			dispatchable=False,
		)
		doc.has_value_changed.return_value = True

		on_state_change(doc, "on_update")

		self.assertIsNone(doc.executing_token)  # claim released
		self.assertTrue(doc.dispatchable)  # and re-dispatchable
		persisted = doc.db_set.call_args.args[0]
		self.assertEqual(persisted["dispatchable"], 1)
		self.assertIsNone(persisted["executing_token"])


if __name__ == "__main__":
	unittest.main()
