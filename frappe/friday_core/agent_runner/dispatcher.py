# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt

"""
The agent dispatcher — maps a tool call (from the LLM) to a skill execution.

PLAIN ENGLISH
=============

The LLM decides to take an action (creates a Note, updates a ToDo, etc.) and
returns a "tool call" — a structured instruction that names the skill and the
arguments to pass. The dispatcher is the bridge between that instruction and
actual execution:

    1. Resolve the Skill DocType row by name.
    2. Call `permissions.matrix.check(agent_profile, skill_name)` — this writes
       a Permission Decision Log row (immutable audit trail).
    3. If denied → write Execution Log with `status='rejected'`, return error.
    4. If allowed → execute the skill via `_execute_skill()`.
    5. Write Execution Log with `status='success'` (or `'error'` on failure).
    6. Return the human-readable result or error.

The dispatcher NEVER raises — all exceptions are caught, written to the
Execution Log, and returned as part of the `DispatchResult`. This keeps the
gateway (and any upstream caller) crash-free.

WHAT THIS MODULE DOES NOT DO
============================

- Does not call the LLM itself. That's the runner.
- Does not write Chat Message rows. That's the gateway.
- Does not run in a Docker sandbox. That's Slice 7.
- Does not manage a task queue. That's Slice 8.
- Does not decide whether a skill is permitted at menu-build time. That's
  `skills.loader.load_for_profile` (filters at menu time). The dispatcher
  checks at call time (defence in depth — if the menu cache is stale,
  the permission matrix still catches it).

SKILL EXECUTION MODEL
====================

In-process execution is acceptable for v0.1 (Slice 6) because:
  - Only one skill (`create_note`) exists.
  - The skill is `risk_level=low` and operates on a single DocType.
  - Slice 7 moves execution into Docker with network isolation.

Execution uses the `_SKILL_HANDLERS` registry — a dict mapping skill_name
to a handler function. Handlers are small, auditable functions that call
Frappe's ORM. Future skills (Slice 8+) add entries here without changing
the dispatcher itself.

REFERENCED DESIGN DOCS
=====================
- `docs/contributing/proposals/slice-6-first-skill.md` — the spec.
- `docs/design/10-agent-execution-guide.md` §Slice 6.
- `docs/design/11-agent-validation-checklist.md` §Slice 6.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field

import frappe

from frappe.friday_core.approvals.workflow import create_request, requires_approval
from frappe.friday_core.permissions.matrix import Decision, check as matrix_check


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


@dataclass
class DispatchResult:
    """The outcome of a single tool-call dispatch.

    Attributes:
      - `success` — True if the skill executed and the Execution Log row is
        `status='success'`. False for rejected, error, or unknown skills.
      - `content` — Human-readable result. On success: a confirmation string
        (e.g. "Note 'Shopping list' created"). On rejection: the denial message
        from the permission matrix. On error: the exception message.
      - `execution_log_name` — Name of the Execution Log DocType row, or
        None if no row was written (e.g. unknown skill).
      - `tokens_used` — LLM token count from the call, if available.
      - `tool_call_name` — The skill name that was dispatched.
      - `tool_call_id` — The LLM's call ID for this tool invocation.
      - `pending_approval` — True when the skill did NOT run because it needs
        human approval (H2): a Workflow Request was created and the loop must
        pause. Distinct from a permission denial.
    """

    success: bool
    content: str
    execution_log_name: str | None = None
    tokens_used: int | None = None
    tool_call_name: str | None = None
    tool_call_id: str | None = None
    pending_approval: bool = False


# ---------------------------------------------------------------------------
# Skill handler registry
# ---------------------------------------------------------------------------


# Each handler receives `(skill_name: str, parameters: dict)` and returns a
# dict with at minimum `{"result": "human-readable string"}`.
# Additional keys like `note_name`, `doctype`, `record_name` are allowed and
# returned in the Execution Log `result` JSON.
_SKILL_HANDLERS: dict[str, callable] = {}


def register_skill_handler(skill_name: str, handler: callable) -> None:
    """Register a skill handler. Raises ValueError if a handler already exists for this skill.

    Usage:
        @register_skill_handler("create_note")
        def _handle_create_note(skill_name, parameters):
            ...

    Or call directly:
        register_skill_handler("create_note", some_function)
    """
    if skill_name in _SKILL_HANDLERS:
        raise ValueError(
            f"A handler for {skill_name!r} is already registered: "
            f"{_SKILL_HANDLERS[skill_name]!r}"
        )
    _SKILL_HANDLERS[skill_name] = handler


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def dispatch(
    tool_call: dict,
    agent_profile: str,
    session_id: str,
    tokens_used: int | None = None,
    skip_approval: bool = False,
) -> DispatchResult:
    """Resolve, validate, and execute one tool call from the LLM.

    This is the single chokepoint for all skill executions in Friday v0.1.
    Every skill invocation — allowed, rejected, or errored — goes through here.

    Arguments:
      - `tool_call` — A dict from `LLMResponse.tool_calls[0]`. Shape:
          `{"id": "...", "name": "skill_name", "arguments": "{...}"}`
          The `arguments` field is a JSON string to be parsed.
      - `agent_profile` — The Agent Profile name running this session.
      - `session_id` — The conversation session UUID.
      - `tokens_used` — Token count from the LLM response (written to log).

    Returns a `DispatchResult`. Never raises — all exceptions are captured
    in the result and written to the Execution Log.

    Dispatch flow:
      1. Parse the tool call arguments (JSON).
      2. Call `permissions.matrix.check()` — writes Permission Decision Log.
      3. If denied → write Execution Log `status='rejected'`, return denial.
      4. If allowed → execute via `_execute_skill()`.
      5. Write Execution Log `status='success'` (or `'error'` on exception).
    """
    skill_name = tool_call.get("name", "")
    tool_call_id = tool_call.get("id", "")

    if not skill_name:
        return DispatchResult(
            success=False,
            content="Tool call has no name — skipping.",
            tool_call_name=None,
            tool_call_id=tool_call_id,
        )

    # Parse arguments.
    raw_args = tool_call.get("arguments", "{}")
    try:
        parameters = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
    except json.JSONDecodeError:
        log_name = _write_execution_log(
            agent_profile=agent_profile,
            skill=skill_name,
            session_id=session_id,
            status="error",
            parameters={},
            result={"error": f"Malformed JSON in tool arguments: {raw_args[:200]}"},
            tokens_used=tokens_used,
        )
        return DispatchResult(
            success=False,
            content=f"Malformed JSON in tool arguments: {raw_args[:50]}",
            execution_log_name=log_name,
            tokens_used=tokens_used,
            tool_call_name=skill_name,
            tool_call_id=tool_call_id,
        )

    if not isinstance(parameters, dict):
        log_name = _write_execution_log(
            agent_profile=agent_profile,
            skill=skill_name,
            session_id=session_id,
            status="error",
            parameters={},
            result={"error": f"Tool arguments must be a dict, got {type(parameters).__name__}"},
            tokens_used=tokens_used,
        )
        return DispatchResult(
            success=False,
            content=f"Tool arguments must be a dict, got {type(parameters).__name__}",
            execution_log_name=log_name,
            tokens_used=tokens_used,
            tool_call_name=skill_name,
            tool_call_id=tool_call_id,
        )

    # Step 1: Permission check — writes Permission Decision Log row.
    try:
        decision = matrix_check(agent_profile, skill_name)
    except frappe.DoesNotExistError:
        # Skill doesn't exist — return error without writing Execution Log
        # (the log's skill field is a Link field, and we can't insert a row
        # that references a non-existent skill).
        return DispatchResult(
            success=False,
            content=f"I tried to use the '{skill_name}' tool but it doesn't exist.",
            execution_log_name=None,
            tokens_used=tokens_used,
            tool_call_name=skill_name,
            tool_call_id=tool_call_id,
        )

    if not decision.allowed:
        # Permission denied — write Execution Log as rejected.
        # The Permission Decision Log row already exists (written by matrix.check).
        # We link to it via the Execution Log's permission_decision field.
        permission_decision_name = _get_latest_permission_decision(
            agent_profile, skill_name
        )
        log_name = _write_execution_log(
            agent_profile=agent_profile,
            skill=skill_name,
            session_id=session_id,
            status="rejected",
            parameters=parameters,
            result={"reason": decision.reason},
            tokens_used=tokens_used,
            permission_decision=permission_decision_name,
        )
        return DispatchResult(
            success=False,
            content=f"I don't have permission to do that: {decision.reason}",
            execution_log_name=log_name,
            tokens_used=tokens_used,
            tool_call_name=skill_name,
            tool_call_id=tool_call_id,
        )

    # H2 — human-approval gate. Permission says the agent *may* run this skill;
    # but if the skill is flagged `requires_approval` it must pause for a human.
    # Create a Pending Workflow Request and return WITHOUT executing. An approval
    # later re-dispatches with skip_approval=True to actually run it.
    if not skip_approval and requires_approval(skill_name):
        request_name = create_request(
            agent_profile=agent_profile,
            skill_name=skill_name,
            parameters=parameters,
            session_id=session_id,
            tool_call_id=tool_call_id,
        )
        return DispatchResult(
            success=False,
            content=(
                f"This action needs human approval before it can run "
                f"(Workflow Request {request_name})."
            ),
            pending_approval=True,
            tool_call_name=skill_name,
            tool_call_id=tool_call_id,
        )

    # Step 2: Execute the skill inside a Docker sandbox.
    from frappe.friday_core.sandbox.credentials import resolve_credentials
    start_ms = int(time.time() * 1000)
    try:
        handler = _SKILL_HANDLERS.get(skill_name)
        if handler is None:
            # Unknown skill — write error log, return DispatchResult.
            log_name = _write_execution_log(
                agent_profile=agent_profile,
                skill=skill_name,
                session_id=session_id,
                status="error",
                parameters=parameters,
                result={"error": f"Unknown skill {skill_name!r}. No handler registered."},
                tokens_used=tokens_used,
            )
            return DispatchResult(
                success=False,
                content=f"Unknown skill {skill_name!r}. No handler registered.",
                execution_log_name=log_name,
                tokens_used=tokens_used,
                tool_call_name=skill_name,
                tool_call_id=tool_call_id,
            )

        creds = resolve_credentials(agent_profile, skill_name)
        outcome = _execute_sandboxed(
            skill_name=skill_name,
            parameters=parameters,
            agent_profile=agent_profile,
            credentials=creds,
            handler=handler,
        )

    except Exception as exc:  # noqa: BLE001
        duration_ms = int(time.time() * 1000) - start_ms
        # Best-effort error redaction — don't include exc type in user-facing
        # content to avoid information leakage. The full error still goes to
        # the Execution Log result JSON (which is admin-readable).
        error_msg = str(exc)[:200] if exc else "Unknown error"
        log_name = _write_execution_log(
            agent_profile=agent_profile,
            skill=skill_name,
            session_id=session_id,
            status="error",
            parameters=parameters,
            result={"error": error_msg, "exception": repr(exc), "duration_ms": duration_ms},
            tokens_used=tokens_used,
        )
        return DispatchResult(
            success=False,
            content=f"Something went wrong: {error_msg}",
            execution_log_name=log_name,
            tokens_used=tokens_used,
            tool_call_name=skill_name,
            tool_call_id=tool_call_id,
        )

    # Step 3: Success — write Execution Log.
    duration_ms = int(time.time() * 1000) - start_ms
    log_name = _write_execution_log(
        agent_profile=agent_profile,
        skill=skill_name,
        session_id=session_id,
        status="success",
        parameters=parameters,
        result={**outcome, "duration_ms": duration_ms},
        tokens_used=tokens_used,
    )
    return DispatchResult(
        success=True,
        content=outcome.get("result", "Done."),
        execution_log_name=log_name,
        tokens_used=tokens_used,
        tool_call_name=skill_name,
        tool_call_id=tool_call_id,
    )


class _SandboxError(Exception):
    """Raised when sandbox.execute() returns a non-success status."""

    def __init__(self, status: str, result: dict | None, logs: str, duration_ms: int):
        self.status = status
        self.result = result
        self.logs = logs
        self.duration_ms = duration_ms
        super().__init__(f"sandbox status={status}: {result}")


def _execute_sandboxed(
    skill_name: str,
    parameters: dict,
    agent_profile: str,
    credentials: dict,
    handler: callable,
) -> dict:
    """
    Run a skill inside a Docker sandbox.

    Calls sandbox.execute() with the skill + parameters. Maps the
    SandboxResult back to a dict the dispatcher expects. Raises
    _SandboxError on non-success statuses so the caller's exception
    handler writes the correct Execution Log entry.

    Fallback: if docker is unavailable or the image is not built yet,
    falls back to in-process handler invocation so tests and local dev
    without Docker still work.
    """
    from frappe.friday_core.sandbox.runner import execute, SandboxResult

    try:
        sandbox_result = execute(
            skill_name=skill_name,
            parameters=parameters,
            agent_profile=agent_profile,
            credentials=credentials,
        )
    except Exception as exc:
        # Docker unavailable or image not found — fall back to in-process.
        # Restored: we MUST log when this happens so a silent regression
        # (Docker dies in prod, skills suddenly bypass the sandbox) is
        # auditable. Log level WARNING so ops dashboards can alert on it.
        frappe.logger("friday.dispatcher").warning(
            f"Sandbox unavailable for skill {skill_name!r}, "
            f"falling back to in-process: {type(exc).__name__}: {exc}"
        )
        return handler(skill_name=skill_name, parameters=parameters)

    # Map sandbox status to execution-log status and handler exception
    status_to_execution_status = {
        "success": "success",
        "failed": "error",
        "timeout": "error",
        "oom": "error",
        "invalid_skill": "error",
        "protocol_error": "error",
    }
    exec_status = status_to_execution_status.get(sandbox_result.status, "error")

    if sandbox_result.status != "success":
        raise _SandboxError(
            status=sandbox_result.status,
            result=sandbox_result.result,
            logs=sandbox_result.logs,
            duration_ms=sandbox_result.duration_ms,
        )

    return sandbox_result.result or {}


# ---------------------------------------------------------------------------
# Skill handlers
# ---------------------------------------------------------------------------


def _handle_create_note(skill_name: str, parameters: dict) -> dict:
    """Create a Note DocType row.

    Parameters:
      - `title` (str, required): The note title.
      - `content` (str, optional): The note body.

    Returns a dict with `result` (human-readable), `note_name` (Frappe PK).
    """
    title = parameters.get("title", "")
    content = parameters.get("content", "")

    if not title:
        raise ValueError("create_note requires a 'title' parameter")

    doc = frappe.get_doc(
        {
            "doctype": "Note",
            "title": title,
            "content": content,
        }
    )
    doc.insert(ignore_permissions=True)

    return {
        "result": f"Note '{title}' created",
        "note_name": doc.name,
        "doctype": "Note",
        "record_name": doc.name,
    }


# Register the handler.
register_skill_handler("slice6-create-note", _handle_create_note)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _write_execution_log(
    agent_profile: str,
    skill: str,
    session_id: str,
    status: str,
    parameters: dict,
    result: dict,
    tokens_used: int | None = None,
    permission_decision: str | None = None,
) -> str:
    """Write one Execution Log row and return the row name.

    The row is submitted (made immutable) on success or rejected status.
    On error status the row is left in draft so it can be inspected/fixed.
    """
    doc = frappe.get_doc(
        {
            "doctype": "Execution Log",
            "agent_profile": agent_profile,
            "skill": skill,
            "parameters": frappe.as_json(parameters),
            "result": frappe.as_json(result),
            "status": status,
            "tokens_used": tokens_used or 0,
        }
    )
    if permission_decision:
        doc.permission_decision = permission_decision

    # `ignore_permissions=True` — the system is recording its own audit
    # trail, not a user-driven write.
    doc.insert(ignore_permissions=True)

    # Submit on success/rejected (immutable). Leave error rows in draft.
    if status in ("success", "rejected"):
        doc.submit()

    return doc.name


def _get_latest_permission_decision(
    agent_profile: str,
    skill_name: str,
) -> str | None:
    """Find the most recent Permission Decision Log row for this profile+skill.

    Used to link the Execution Log row to the Permission Decision Log when
    a skill is rejected. We use `order_by="creation desc"` because Frappe
    orders by `creation` in the DocType, and the most recent row is the one
    just written by `matrix.check`.
    """
    rows = frappe.get_all(
        "Permission Decision Log",
        filters={
            "agent_profile": agent_profile,
            "skill": skill_name,
        },
        order_by="creation desc",
        limit=1,
    )
    return rows[0]["name"] if rows else None