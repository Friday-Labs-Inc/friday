# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt

"""
The generic workflow interpreter (Design 75).

PLAIN ENGLISH
=============
This is the doc_events["<work-item>"]["on_update"] handler. Every time a
governed work-item is saved, it asks one question: "the work-item just landed
in a new state — is there an AGENT step waiting at this state?" If yes, it
hands off to the phase dispatcher to create the agent's task. If the state is a
human gate, a terminal state, or anything with no agentic step, it does
nothing and waits.

The interpreter knows NOTHING about brands, data centers, or research. It only
reads data: the Domain Bundle (which workflow governs this DocType), the
Workflow (the states + transitions), and the Friday Workflow Transition Meta
rows (the agentic config bound to each transition). Add a new domain by adding
data — never by editing this file.

Phase 1 is sequential-only (Design 75 §8): each state has at most one outgoing
agentic transition. A state with two would be a parallel fan-out, which is
Phase 2; the interpreter logs and takes the first so a misconfig degrades
loudly rather than crashing a save.
"""

from __future__ import annotations

import frappe

from frappe.friday_core.engine import bundle, phase_dispatcher


def on_work_item_update(doc, method: str | None = None) -> None:
	"""Fire on every save of a governed work-item; dispatch the agentic step (if
	any) waiting at the work-item's current state."""
	workflow = bundle.workflow_for(doc.doctype)
	if not workflow:
		return  # not a governed DocType — the hook is a no-op here

	state_field = bundle.state_field_for(workflow)
	state = doc.get(state_field)
	if not state:
		return

	# Only react when the STATE actually changed. An unrelated field edit on a
	# work-item sitting mid-pipeline must not re-dispatch the current phase.
	if not doc.has_value_changed(state_field):
		return

	meta = _agentic_meta_for_state(workflow, state)
	if not meta:
		return  # human gate / terminal / no agent step here

	if _has_active_task(doc, meta.phase_key):
		return  # belt-and-suspenders: never double-dispatch one state-occupancy

	phase_dispatcher.dispatch(doc, meta.name)


def _agentic_meta_for_state(workflow: str, state: str):
	"""The agentic transition-meta leaving `state`, or None. Returns the row's
	name + phase_key. Phase 1 expects at most one; more than one is a fan-out
	(Phase 2) — we log loudly and take the first."""
	rows = frappe.get_all(
		"Friday Workflow Transition Meta",
		filters={"workflow": workflow, "from_state": state, "execution_mode": "agentic"},
		fields=["name", "phase_key"],
		order_by="creation asc",
		limit_page_length=0,
	)
	if not rows:
		return None
	if len(rows) > 1:
		frappe.log_error(
			message=(
				f"Workflow {workflow!r} state {state!r} has {len(rows)} agentic outgoing "
				"transitions. Phase 1 is sequential-only (Design 75 §8); a true fan-out is "
				f"Phase 2. Dispatching the first ({rows[0].phase_key!r}); the rest are ignored."
			),
			title="Design 75 engine — unexpected fan-out",
		)
	return rows[0]


def _has_active_task(doc, phase_key: str) -> bool:
	"""True if a non-terminal Task already exists for this work-item + phase. A
	*completed* task does NOT block re-dispatch, so back-edges (a 'revise' loop
	re-entering a state) correctly spawn fresh work."""
	return bool(
		frappe.db.exists(
			"Task",
			{
				"work_item_doctype": doc.doctype,
				"work_item_name": doc.name,
				"phase_key": phase_key,
				"workflow_state": ["not in", ["Completed", "Cancelled"]],
			},
		)
	)
