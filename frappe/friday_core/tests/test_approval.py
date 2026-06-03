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

from frappe.friday_core.agent_runner.dispatcher import dispatch
from frappe.friday_core.approvals.workflow import (
	approve,
	create_request,
	reject,
	requires_approval,
)

_W = "frappe.friday_core.approvals.workflow"
_D = "frappe.friday_core.agent_runner.dispatcher"


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
			agent_profile="P", skill_name="danger-skill",
			parameters={"x": 1}, session_id="S", tool_call_id="c1",
		)

		self.assertEqual(name, "WR-7")
		built = mock_frappe.get_doc.call_args.args[0]
		self.assertEqual(built["doctype"], "Workflow Request")
		self.assertEqual(built["status"], "Pending")
		self.assertEqual(built["skill"], "danger-skill")
		self.assertEqual(built["risk_level"], "high")
		self.assertEqual(json.loads(built["parameters"]), {"x": 1})
		doc.insert.assert_called_once()


class TestApprove(unittest.TestCase):
	@patch(f"{_D}.dispatch")
	@patch(f"{_W}.frappe")
	def test_approve_resumes_execution(self, mock_frappe, mock_dispatch):
		mock_frappe.ValidationError = _ValErr
		mock_frappe.as_json = lambda x: json.dumps(x)
		mock_frappe.parse_json = lambda x: json.loads(x) if isinstance(x, str) else x
		req = MagicMock(status="Pending", parameters='{"x": 1}', skill="danger-skill",
		                tool_call_id="c1", agent_profile="P", session_id="S")
		mock_frappe.get_doc.return_value = req
		mock_dispatch.return_value = MagicMock(execution_log_name="EL-1")

		result = approve("WR-1", approved_by="admin@x.com", reason="looks fine")

		# Re-dispatched, bypassing the gate so it doesn't re-pause.
		mock_dispatch.assert_called_once()
		self.assertTrue(mock_dispatch.call_args.kwargs["skip_approval"])
		self.assertEqual(mock_dispatch.call_args.kwargs["tool_call"]["name"], "danger-skill")
		# Request closed out + linked to the execution.
		self.assertEqual(req.status, "Approved")
		self.assertEqual(req.approved_by, "admin@x.com")
		self.assertEqual(req.execution_log, "EL-1")
		req.save.assert_called_once()
		self.assertIs(result, mock_dispatch.return_value)

	@patch(f"{_W}.frappe")
	def test_approve_non_pending_raises(self, mock_frappe):
		mock_frappe.ValidationError = _ValErr
		mock_frappe.get_doc.return_value = MagicMock(status="Approved")
		with self.assertRaises(_ValErr):
			approve("WR-1", approved_by="admin@x.com")


class TestReject(unittest.TestCase):
	@patch(f"{_W}.frappe")
	def test_reject_marks_rejected_without_executing(self, mock_frappe):
		mock_frappe.ValidationError = _ValErr
		req = MagicMock(status="Pending")
		mock_frappe.get_doc.return_value = req
		reject("WR-1", approved_by="admin@x.com", reason="too risky")
		self.assertEqual(req.status, "Rejected")
		self.assertEqual(req.decision_reason, "too risky")
		req.save.assert_called_once()

	@patch(f"{_W}.frappe")
	def test_reject_non_pending_raises(self, mock_frappe):
		mock_frappe.ValidationError = _ValErr
		mock_frappe.get_doc.return_value = MagicMock(status="Rejected")
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
		# Paused BEFORE execution: no Execution Log row was written.
		mock_log.assert_not_called()

	@patch(f"{_D}._write_execution_log", return_value="EL-err")
	@patch(f"{_D}.create_request")
	@patch(f"{_D}.requires_approval")
	@patch(f"{_D}.matrix_check")
	def test_skip_approval_bypasses_the_gate(
		self, mock_matrix, mock_req, mock_create, mock_log
	):
		mock_matrix.return_value = MagicMock(allowed=True, reason="ok")
		# Unknown skill → the execution path returns early, but the point is the
		# gate is never consulted when skip_approval=True.
		tool_call = {"id": "c1", "name": "unknown-skill", "arguments": "{}"}

		result = dispatch(
			tool_call=tool_call, agent_profile="P", session_id="S", skip_approval=True
		)

		mock_req.assert_not_called()  # short-circuited by skip_approval
		mock_create.assert_not_called()
		self.assertFalse(result.pending_approval)


if __name__ == "__main__":
	unittest.main()
