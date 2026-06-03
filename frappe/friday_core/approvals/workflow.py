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


def approve(request_name: str, *, approved_by: str | None = None, reason: str = ""):
    """Approve a Pending request and run the deferred skill (the 'resume').

    Re-dispatches with `skip_approval=True` so it doesn't re-gate, but still goes
    through the permission check + sandbox + audit log. Links the resulting
    Execution Log to the request. Returns the dispatch `DispatchResult`.

    Raises `frappe.ValidationError` if the request isn't Pending (no double-spend).
    """
    # Lazy import: the dispatcher imports this module for the gate, so importing
    # it at top-level here would be a cycle.
    from frappe.friday_core.agent_runner.dispatcher import dispatch

    req = frappe.get_doc("Workflow Request", request_name)
    if req.status != "Pending":
        raise frappe.ValidationError(
            f"Workflow Request {request_name} is {req.status}, not Pending."
        )

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

    req.status = "Approved"
    req.approved_by = approved_by or frappe.session.user
    req.decision_reason = reason
    req.execution_log = result.execution_log_name
    req.save(ignore_permissions=True)
    return result


def reject(request_name: str, *, approved_by: str | None = None, reason: str = "") -> None:
    """Reject a Pending request. Nothing executes."""
    req = frappe.get_doc("Workflow Request", request_name)
    if req.status != "Pending":
        raise frappe.ValidationError(
            f"Workflow Request {request_name} is {req.status}, not Pending."
        )
    req.status = "Rejected"
    req.approved_by = approved_by or frappe.session.user
    req.decision_reason = reason
    req.save(ignore_permissions=True)
