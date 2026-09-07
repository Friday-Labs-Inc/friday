# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""
Unit tests for the human-approval workflow (Feature H2, doc 04 Layer 6 / S10).

Mock-based — no DB. Covers the approvals logic (the gate condition, request
creation, approve-resumes-execution, reject) and the dispatcher gate (a
`requires_approval` skill pauses without executing; `skip_approval` bypasses it).
The DB-backed integration (real Workflow Request rows, a Frappe Workflow with
role-gated transitions) runs on a bench.
"""

import json
import unittest
from unittest.mock import MagicMock, patch

from friday.friday_core.agent_runner.dispatcher import dispatch
from friday.friday_core.approvals.workflow import (
	approve,
	create_request,
	reject,
	requires_approval,
)

_W = "friday.friday_core.approvals.workflow"
_D = "friday.friday_core.agent_runner.dispatcher"


class _ValErr(Exception):
	"""Stand-in for frappe.ValidationError under a mocked frappe."""


# --- The approvals logic ----------------------------------------------------


class TestRequiresApproval(unittest.TestCase):
	@patch(f"{_W}.frappe")
	def test_reads_the_skill_flag(self, mock_frappe):
		mock_frappe.db.get_value.return_value = 1
		self.assertTrue(requires_approval("danger-skill"))
		mock_frappe.db.get_value.return_value = 0
		self.assertFalse(requires_approval("safe-skill"))

	def test_empty_skill_name_is_false(self):
		self.assertFalse(requires_approval(""))


class TestCreateRequest(unittest.TestCase):
	@patch(f"{_W}.frappe")
	def test_creates_a_pending_request(self, mock_frappe):
		mock_frappe.as_json = lambda x: json.dumps(x)
		mock_frappe.db.get_value.return_value = "high"  # risk_level
		doc = MagicMock()
		doc.name = "WR-7"
		mock_frappe.get_doc.return_value = doc

		name = create_request(
			agent_profile="P",
			skill_name="danger-skill",
			parameters={"x": 1},
			session_id="S",
			tool_call_id="c1",
		)

		self.assertEqual(name, "WR-7")
		built = mock_frappe.get_doc.call_args.args[0]
		self.assertEqual(built["doctype"], "Workflow Request")
		self.assertEqual(built["status"], "Pending")
		self.assertEqual(built["skill"], "danger-skill")
		self.assertEqual(built["risk_level"], "high")
		self.assertEqual(json.loads(built["parameters"]), {"x": 1})
		doc.insert.assert_called_once()


def _approve_req(**over):
	"""A SimpleNamespace mimicking the as_dict row approve() reads via db.get_value."""
	import types

	base = dict(
		skill="danger-skill", parameters='{"x": 1}', session_id="S", tool_call_id="c1", agent_profile="P"
	)
	base.update(over)
	return types.SimpleNamespace(**base)


class TestApprove(unittest.TestCase):
	@patch(f"{_D}.dispatch")
	@patch(f"{_W}.frappe")
	def test_approve_claims_then_resumes_execution(self, mock_frappe, mock_dispatch):
		mock_frappe.ValidationError = _ValErr
		mock_frappe.as_json = lambda x: json.dumps(x)
		mock_frappe.parse_json = lambda x: json.loads(x) if isinstance(x, str) else x
		mock_frappe.session.user = "admin@x.com"
		mock_frappe.db.get_value.return_value = _approve_req()
		mock_frappe.db._cursor.rowcount = 1  # we won the atomic claim
		mock_dispatch.return_value = MagicMock(execution_log_name="EL-1")

		result = approve("WR-1", approved_by="admin@x.com", reason="looks fine")

		# The Pending → Approved claim ran as a guarded conditional UPDATE.
		self.assertTrue(mock_frappe.db.sql.called)
		self.assertIn("status = 'Pending'", mock_frappe.db.sql.call_args[0][0])
		self.assertEqual(mock_frappe.db.sql.call_args[0][1]["status"], "Approved")
		# Re-dispatched once, bypassing the gate so it doesn't re-pause.
		mock_dispatch.assert_called_once()
		self.assertTrue(mock_dispatch.call_args.kwargs["skip_approval"])
		self.assertEqual(mock_dispatch.call_args.kwargs["tool_call"]["name"], "danger-skill")
		# Execution Log linked back to the request.
		mock_frappe.db.set_value.assert_called_once()
		self.assertEqual(mock_frappe.db.set_value.call_args[0][3], "EL-1")
		self.assertIs(result, mock_dispatch.return_value)

	@patch(f"{_D}.dispatch")
	@patch(f"{_W}.frappe")
	def test_lost_claim_does_not_double_dispatch(self, mock_frappe, mock_dispatch):
		# A concurrent approver already decided the row → our claim matches 0 rows → we
		# MUST raise WITHOUT dispatching. This is the no-double-execute guarantee.
		mock_frappe.ValidationError = _ValErr
		mock_frappe.session.user = "admin@x.com"
		mock_frappe.db.get_value.return_value = _approve_req()
		mock_frappe.db._cursor.rowcount = 0  # lost the claim
		with self.assertRaises(_ValErr):
			approve("WR-1", approved_by="admin@x.com")
		mock_dispatch.assert_not_called()

	@patch(f"{_D}.dispatch")
	@patch(f"{_W}.frappe")
	def test_approve_missing_request_raises(self, mock_frappe, mock_dispatch):
		mock_frappe.ValidationError = _ValErr
		mock_frappe.session.user = "admin@x.com"
		mock_frappe.db.get_value.return_value = None
		with self.assertRaises(_ValErr):
			approve("WR-1")
		mock_dispatch.assert_not_called()


class TestReject(unittest.TestCase):
	@patch(f"{_W}.frappe")
	def test_reject_claims_rejected_without_executing(self, mock_frappe):
		mock_frappe.ValidationError = _ValErr
		mock_frappe.session.user = "admin@x.com"
		mock_frappe.db._cursor.rowcount = 1
		reject("WR-1", approved_by="admin@x.com", reason="too risky")
		params = mock_frappe.db.sql.call_args[0][1]
		self.assertEqual(params["status"], "Rejected")
		self.assertEqual(params["reason"], "too risky")

	@patch(f"{_W}.frappe")
	def test_reject_non_pending_raises(self, mock_frappe):
		mock_frappe.ValidationError = _ValErr
		mock_frappe.db._cursor.rowcount = 0  # not Pending → claim matches nothing
		with self.assertRaises(_ValErr):
			reject("WR-1", approved_by="admin@x.com")


# --- The dispatcher gate ----------------------------------------------------


class TestDispatcherApprovalGate(unittest.TestCase):
	@patch(f"{_D}._write_execution_log")
	@patch(f"{_D}.create_request", return_value="WR-9")
	@patch(f"{_D}.requires_approval", return_value=True)
	@patch(f"{_D}.matrix_check")
	def test_requires_approval_skill_pauses_without_executing(
		self, mock_matrix, mock_req, mock_create, mock_log
	):
		mock_matrix.return_value = MagicMock(allowed=True, reason="ok")
		tool_call = {"id": "c1", "name": "danger-skill", "arguments": '{"x": 1}'}

		result = dispatch(tool_call=tool_call, agent_profile="P", session_id="S")

		self.assertTrue(result.pending_approval)
		self.assertFalse(result.success)
		self.assertIn("WR-9", result.content)
		mock_create.assert_called_once()
		# The skill did NOT execute — but the GATE TRIGGER is audited (G2): an immutable
		# `pending_approval` Execution Log records that the agent reached a gated action.
		mock_log.assert_called_once()
		self.assertEqual(mock_log.call_args.kwargs["status"], "pending_approval")
		self.assertEqual(mock_log.call_args.kwargs["result"]["workflow_request"], "WR-9")

	@patch(f"{_D}._write_execution_log", return_value="EL-err")
	@patch(f"{_D}.create_request")
	@patch(f"{_D}.requires_approval")
	@patch(f"{_D}.matrix_check")
	def test_skip_approval_bypasses_the_gate(self, mock_matrix, mock_req, mock_create, mock_log):
		mock_matrix.return_value = MagicMock(allowed=True, reason="ok")
		# Unknown skill → the execution path returns early, but the point is the
		# gate is never consulted when skip_approval=True.
		tool_call = {"id": "c1", "name": "unknown-skill", "arguments": "{}"}

		result = dispatch(tool_call=tool_call, agent_profile="P", session_id="S", skip_approval=True)

		mock_req.assert_not_called()  # short-circuited by skip_approval
		mock_create.assert_not_called()
		self.assertFalse(result.pending_approval)


if __name__ == "__main__":
	unittest.main()
