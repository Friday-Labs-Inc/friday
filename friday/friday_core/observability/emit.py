# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""
emit() — single entry point for Dispatcher Event writes (Design 72).

Usage:

    from friday.friday_core.observability import emit

    emit(
        "workflow.state_change",
        task=task_name,
        trigger_source="dispatcher_claim",
        summary=f"{task_name}: Pending -> Assigned",
        payload={"from": "Pending", "to": "Assigned"},
    )

Safety contract
---------------
- **Savepoint-guarded.** Every emit wraps in `frappe.db.savepoint("dispatcher_emit")`
  and rolls back the savepoint on any failure. A failed emit cannot poison the
  surrounding transaction — mirrors the proven `_post_warroom` pattern in
  `tasks/runner.py` and `tasks/workflow.py`.
- **Never raises.** All exceptions are swallowed with a logger.warning. The
  caller's code path continues unaffected.
- **Additive only.** If this whole module is removed, every existing write
  site keeps working — emits are decoration, not load-bearing logic.
- **No-op friendly.** A `task=None` emit is fine (system-wide events like
  reconciler ticks have no task to attach to).
- **De-dup window.** `emit_skip_deduped(task, reason, window_seconds=60)` emits
  a `dispatcher.skip` at most once per (task, reason) within the window — keeps
  a busy dispatcher tick from flooding the table.

The function is intentionally tolerant: payloads are coerced to JSON-safe
strings, missing optional fields are dropped, unknown extras get folded into
the payload. The contract favours emit-anything-from-anywhere over strictness,
because the goal is to capture EVERY framework event without the caller
worrying about schema.
"""

from __future__ import annotations

import json

import frappe
from frappe.utils import now_datetime

_logger = frappe.logger("friday.observability.emit")

_SAVEPOINT = "dispatcher_emit"


def emit(
	event_type: str,
	*,
	task: "str | None" = None,
	project: "str | None" = None,
	agent_profile: "str | None" = None,
	trigger_source: "str | None" = None,
	summary: "str | None" = None,
	payload: "dict | None" = None,
) -> "str | None":
	"""Write one Dispatcher Event row.

	Args:
		event_type: Dotted type, e.g. ``"workflow.state_change"``,
			``"dispatcher.skip"``, ``"llm.call_summary"``.
		task: Optional Task name. If given and ``project`` is not, the
			project is auto-derived from the task row (so callers don't
			have to look it up).
		project: Optional Project name.
		agent_profile: Optional Agent Profile name.
		trigger_source: What triggered this event (``manual_save``,
			``dispatcher_claim``, ``reconciler_reset``, etc.).
		summary: Short human-readable line shown in the trace timeline.
		payload: Structured event-specific payload (dict; coerced to JSON).

	Returns:
		The new ``Dispatcher Event`` name on success, ``None`` on any failure.

	Never raises. The caller can ignore the return value.
	"""
	try:
		frappe.db.savepoint(_SAVEPOINT)

		# Validate at the boundary: tests frequently inject MagicMock objects
		# for these Link fields, and Postgres can't adapt non-string values to
		# its query params — that error poisons the surrounding transaction
		# even with a savepoint rollback (the failed statement is what aborts
		# the txn, not the exception). Coerce non-strings to None so the row
		# still gets recorded (without the bogus link) and tests stay clean.
		task = task if isinstance(task, str) else None
		project = project if isinstance(project, str) else None
		agent_profile = agent_profile if isinstance(agent_profile, str) else None
		trigger_source = trigger_source if isinstance(trigger_source, str) else None
		event_type = event_type if isinstance(event_type, str) else "unknown"

		project_name = project
		if task and not project_name:
			try:
				project_name = frappe.db.get_value("Task", task, "project")
				# Defence-in-depth: get_value may return a Mock when the DB is
				# stubbed by a test — only keep it if it's a real string.
				if not isinstance(project_name, str):
					project_name = None
			except Exception:
				project_name = None

		payload_str = _coerce_payload(payload)

		doc = frappe.get_doc(
			{
				"doctype": "Dispatcher Event",
				"event_type": event_type,
				"trigger_source": trigger_source,
				"task": task,
				"project": project_name,
				"agent_profile": agent_profile,
				"summary": _truncate(summary, 1000),
				"payload_json": payload_str,
			}
		)
		doc.insert(ignore_permissions=True)
		return doc.name
	except Exception:
		try:
			frappe.db.rollback(save_point=_SAVEPOINT)
		except Exception:
			pass
		_logger.warning(
			"emit() failed for event_type=%s task=%s — swallowed", event_type, task, exc_info=True
		)
		return None


def emit_skip_deduped(
	task: str,
	reason: str,
	*,
	agent_profile: "str | None" = None,
	window_seconds: int = 60,
	summary: "str | None" = None,
	payload: "dict | None" = None,
) -> "str | None":
	"""Emit ``dispatcher.skip`` with a per-(task, reason) dedup window.

	The dispatcher's hot path may consider the same unclaimed task on every
	tick (one tick per second on a busy site). Without dedup, the same skip
	reason would flood the table. This helper checks for a recent emit and
	suppresses duplicates within ``window_seconds``.

	Returns ``None`` if suppressed (a duplicate within the window) or the
	emit failed. Returns the new ``Dispatcher Event`` name if a fresh row
	was written.
	"""
	try:
		cutoff = frappe.utils.add_to_date(now_datetime(), seconds=-window_seconds)
		existing = frappe.db.sql(
			"""
			SELECT name FROM `tabDispatcher Event`
			WHERE event_type = 'dispatcher.skip'
			  AND task = %s
			  AND trigger_source = %s
			  AND creation >= %s
			LIMIT 1
			""",
			(task, reason, cutoff),
		)
		if existing:
			return None
	except Exception:
		# If the dedup check fails (e.g. doctype not migrated yet), fall through
		# and just emit. Better to over-emit once than swallow legitimate signal.
		pass

	return emit(
		"dispatcher.skip",
		task=task,
		agent_profile=agent_profile,
		trigger_source=reason,
		summary=summary or f"skip: {reason}",
		payload=payload,
	)


def _coerce_payload(payload: "dict | None") -> "str | None":
	"""Coerce a payload dict to a JSON string. Returns None for empty input.

	Non-serializable values get ``default=str`` so the emit can't fail on
	objects like datetimes. Captures everything; lossy is fine here.
	"""
	if not payload:
		return None
	try:
		return json.dumps(payload, default=str)
	except Exception:
		return json.dumps({"_coerce_error": "payload was not JSON-encodable"})


def _truncate(text: "str | None", limit: int) -> "str | None":
	if text is None:
		return None
	text = str(text)
	if len(text) <= limit:
		return text
	return text[: limit - 3] + "..."
