# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt

"""
Human-in-the-loop approval workflow (Feature H2, doc 04 Layer 6 / doc 51 S10).

PLAIN ENGLISH
=============

Some skills are too sensitive to run on the agent's say-so. Such a Skill carries
`requires_approval = 1`. When the dispatcher is about to run one, instead of
executing it now, it:

  1. creates a **Workflow Request** row (status = Pending) holding the skill +
     the exact arguments, and
  2. **pauses** — the agent's turn ends with "this needs approval," and no
     resources are held.

Later a human (Agent Supervisor / System Manager) approves or rejects it:

  - `approve()` flips the row to Approved and **resumes** — it runs the skill
    through the normal dispatcher (so the permission check + sandbox + audit log
    all still happen) and links the resulting Execution Log back to the request.
  - `reject()` flips it to Rejected and nothing runs.

WHY THE DISPATCHER, NOT THE GATEWAY
===================================
doc 04 says "the gateway creates the request," but Friday's real chokepoint for
*every* skill execution is the dispatcher (doc 51 S10: "the matrix/dispatch path
creates one"). Putting the gate there means approval is enforced no matter who
calls a skill — the ReAct loop, a task, or a future surface.

REFERENCED DESIGN
=================
- `docs/design/04-security-model.md` Layer 6 — the approval flow.
- `docs/design/05-module-design.md` — the Workflow Request target schema.
- `docs/design/51-hermes-core-port-roadmap.md` S10 — the locked acceptance.
"""

from __future__ import annotations

import frappe


def requires_approval(skill_name: str) -> bool:
	"""True when the Skill is flagged `requires_approval` (the H2 gate condition)."""
	if not skill_name:
		return False
	return bool(frappe.db.get_value("Skill", skill_name, "requires_approval"))


def create_request(
	*,
	agent_profile: str,
	skill_name: str,
	parameters: dict | None = None,
	session_id: str = "",
	tool_call_id: str = "",
) -> str:
	"""Create a Pending Workflow Request and return its name.

	Captures everything needed to run the skill later (`approve()` replays it).
	Does NOT execute anything — that's the whole point of the pause.
	"""
	risk_level = frappe.db.get_value("Skill", skill_name, "risk_level") or ""
	doc = frappe.get_doc(
		{
			"doctype": "Workflow Request",
			"agent_profile": agent_profile,
			"skill": skill_name,
			"risk_level": risk_level,
			"status": "Pending",
			"parameters": frappe.as_json(parameters or {}),
			"session_id": session_id,
			"tool_call_id": tool_call_id,
			"requested_at": frappe.utils.now_datetime(),
		}
	)
	doc.insert(ignore_permissions=True)
	return doc.name


def _claim_decision(request_name: str, new_status: str, approver: str, reason: str) -> None:
	"""Atomically transition a Workflow Request from Pending → `new_status`.

	The decision (Approve/Reject) is a SINGLE-WINNER claim: a conditional UPDATE that
	only matches a still-Pending row, then a check of the affected row count. Without
	this, two concurrent `/approve` calls both pass a plain `status == "Pending"` read
	and both re-dispatch the gated skill — the high-risk action runs TWICE. Postgres
	row-locking serializes the two UPDATEs, so exactly one sees rowcount 1.

	Raises `frappe.ValidationError` (without mutating) if the row is missing or already
	decided. Mirrors the task dispatcher's `_claim_task` conditional-UPDATE pattern.
	"""
	frappe.db.sql(
		"""
		UPDATE `tabWorkflow Request`
		SET status = %(status)s, approved_by = %(by)s, decision_reason = %(reason)s,
		    modified = NOW(), modified_by = %(by)s
		WHERE name = %(name)s AND status = 'Pending'
		""",
		{"status": new_status, "by": approver, "reason": reason, "name": request_name},
	)
	if (frappe.db._cursor.rowcount or 0) != 1:
		current = frappe.db.get_value("Workflow Request", request_name, "status")
		raise frappe.ValidationError(
			f"Workflow Request {request_name} is {current or 'missing'}, not Pending "
			f"(already decided, or a concurrent decision won)."
		)


def approve(request_name: str, *, approved_by: str | None = None, reason: str = ""):
	"""Approve a Pending request and run the deferred skill (the 'resume').

	Re-dispatches with `skip_approval=True` so it doesn't re-gate, but still goes
	through the permission check + sandbox + audit log. Links the resulting
	Execution Log to the request. Returns the dispatch `DispatchResult`.

	Raises `frappe.ValidationError` if the request isn't Pending (no double-spend) —
	the Pending→Approved transition is claimed ATOMICALLY before dispatch, so a
	concurrent approver cannot also reach `dispatch()`.
	"""
	# Lazy import: the dispatcher imports this module for the gate, so importing
	# it at top-level here would be a cycle.
	from frappe.friday_core.agent_runner.dispatcher import dispatch

	approver = approved_by or frappe.session.user
	# Read what we need to replay the skill BEFORE the claim (the claim re-checks
	# Pending atomically; reading first is harmless).
	req = frappe.db.get_value(
		"Workflow Request",
		request_name,
		["skill", "parameters", "session_id", "tool_call_id", "agent_profile"],
		as_dict=True,
	)
	if not req:
		raise frappe.ValidationError(f"Workflow Request {request_name} not found.")

	# ATOMIC CLAIM — only the winner proceeds to dispatch. Done BEFORE dispatch so that
	# even if dispatch() commits internally, a loser can never also execute the skill.
	_claim_decision(request_name, "Approved", approver, reason)

	parameters = frappe.parse_json(req.parameters) if req.parameters else {}
	tool_call = {
		"id": req.tool_call_id or "",
		"name": req.skill,
		"arguments": frappe.as_json(parameters),
	}
	result = dispatch(
		tool_call=tool_call,
		agent_profile=req.agent_profile,
		session_id=req.session_id or "",
		skip_approval=True,
	)

	frappe.db.set_value(
		"Workflow Request", request_name, "execution_log", result.execution_log_name, update_modified=False
	)
	return result


def reject(request_name: str, *, approved_by: str | None = None, reason: str = "") -> None:
	"""Reject a Pending request. Nothing executes.

	The Pending→Rejected transition is claimed atomically too, so a `/deny` racing a
	concurrent `/approve` can't both win — exactly one decision takes effect.
	"""
	_claim_decision(request_name, "Rejected", approved_by or frappe.session.user, reason)
