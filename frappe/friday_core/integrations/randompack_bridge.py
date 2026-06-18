# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt

"""
The state bridge — Friday Task transitions → RandomPack write-back.

PLAIN ENGLISH
=============
When a pipeline Task changes state, we mirror that to the RandomPack backend so
the client sees progress, gate-ready signals, and the finished deliverables on
their own project. One module owns the mapping; it is called from the Task
workflow hook on every transition and NEVER raises.

TWO PATHS
=========
- **Engine tasks (Design 75)** — the metadata engine creates Tasks carrying
  `work_item_doctype='Brand Brief'` + `work_item_name` + `phase_key`. We resolve
  the RandomPack project from the Brand Brief (`rp_project`), then map our phase
  to the backend's *real* Task docname (RandomPack identifies tasks by Frappe
  docname, not by our slug) via `get_project` + a Friday-owned subject map.
- **Legacy tasks** — the old Project-pipeline tasks carried `backend_ref` (a
  phase slug) under a `Project.backend_ref`. Kept working for back-compat.

  Executing → in_progress;  Completed → completed (+ note);  gate-prep done →
  request_gate_open (signal-only, humans own it);  Blocked → Pending Review;
  Cancelled → terminal. The guidelines (final) phase also pushes the brief's
  attached files back as deliverables.
"""

from __future__ import annotations

import json

import frappe
from frappe.friday_core.integrations import randompack_client as client

# gate-prep phase → the gate label RandomPack's request_gate_open expects.
_GATE_PREP = {"gate1_prep": "Gate 1", "gate2_prep": "Gate 2"}

# Friday phase_key → RandomPack template-task SUBJECT (the stable display string
# in the 'Essentials — 10 Day' template). RandomPack owns the docnames; we match
# by subject. `naming` shares the strategy task; Intake/Delivery have no phase.
_SUBJECT_MAP = {
	"strategy": "Strategy & naming",
	"naming": "Strategy & naming",
	"directions": "Three directions",
	"gate1_prep": "Gate 1 — choose direction",
	"buildout": "Build system",
	"gate2_prep": "Gate 2 — final review",
	"guidelines": "Delivery & handoff",
}

# Phase after which Friday pushes the brief's attached files as deliverables.
_DELIVERABLE_PHASE = "guidelines"

# Friday Task state → RandomPack task status. RandomPack only accepts
# Open / Working / Pending Review / Completed (api/v1.update_task_progress);
# any other value is rejected. Cancelled has no RandomPack equivalent → no
# status write-back (the bridge returns early when the map misses).
_STATUS_MAP = {
	"Executing": "Working",
	"Completed": "Completed",
}


def on_task_transition(task, state: str) -> None:
	"""Mirror one Friday Task transition to RandomPack. Never raises."""
	try:
		if task.get("work_item_doctype") == "Brand Brief" and task.get("work_item_name") and task.get("phase_key"):
			_engine_writeback(task, state)
		elif task.get("backend_ref") and task.get("project"):
			_legacy_writeback(task, state)
	except Exception:
		frappe.log_error(title="friday.randompack bridge failed")


# ── Design 75 engine path ────────────────────────────────────────────────────


def _engine_writeback(task, state: str) -> None:
	brief_name = task.work_item_name
	rp_project = frappe.db.get_value("Brand Brief", brief_name, "rp_project")
	if not rp_project:
		return  # brief did not originate from a RandomPack project — stay internal

	phase = task.phase_key
	rp_task = _resolve_rp_task(rp_project, phase)  # real backend Task docname, or None

	if state == "Blocked":
		if rp_task:
			client.signal_pending_review(
				rp_task, issue_name="see FRIDAY_WAR_ROOM",
				summary=f"{task.get('title') or phase} is blocked and needs a human decision.",
			)
		return

	status = _STATUS_MAP.get(state)
	if not status:
		return

	if rp_task:
		client.update_task_progress(
			rp_task, status=status, progress=100 if state == "Completed" else None
		)

	if state == "Completed":
		summary = _result_summary(task)
		if summary:
			client.post_project_note(rp_project, note=f"[{phase}] {summary[:2000]}", task_ref=rp_task)
		gate = _GATE_PREP.get(phase)
		if gate:
			client.request_gate_open(
				rp_project, gate=gate, summary=f"{task.get('title') or phase} is ready for client review."
			)
		# Design 77: _push_deliverables fires from on_brief_state_change when the
		# brief reaches Delivered, NOT here, so the project-level materialize
		# package (assemble_project_package) has time to land first.


def _resolve_rp_task(rp_project: str, phase: str) -> str | None:
	"""Map our phase to the backend's real Task docname by matching subjects from
	get_project. Returns None if no match (write-back degrades to a project note)."""
	subject = _SUBJECT_MAP.get(phase)
	if not subject:
		return None
	state = client.get_project_state(rp_project) or {}
	tasks = (state.get("message") or state).get("tasks") or []
	for t in tasks:
		if (t.get("subject") or "") == subject:
			return t.get("name")
	return None


def _push_deliverables(rp_project: str, brief_name: str) -> None:
	"""Send every deliverable file attached to either the Brand Brief OR the
	linked local Friday Project to RandomPack as a deliverable.

	Design 77 — files now land on two attachment targets: generate-image
	attaches to the Brand Brief (images), while attach-deliverable (called by
	agents in their per-phase prompt) and materialize.py both attach to the
	local Friday Project (text/PDF deliverables). The bridge must push from
	BOTH or the customer sees only the images.

	Idempotency: a file is identified by its file_url; the union-dedup means
	a file linked from both targets is pushed once.
	"""
	collected: dict[str, dict] = {}  # file_url -> {name, file_name}
	brief_files = frappe.get_all(
		"File",
		filters={"attached_to_doctype": "Brand Brief", "attached_to_name": brief_name},
		fields=["name", "file_name", "file_url"],
	)
	for f in brief_files:
		if f.file_url and f.file_url not in collected:
			collected[f.file_url] = {"name": f.name, "file_name": f.file_name}

	# Resolve the linked Friday Project (Design 77 new field), then add its files.
	friday_project = frappe.db.get_value("Brand Brief", brief_name, "project")
	if friday_project:
		project_files = frappe.get_all(
			"File",
			filters={"attached_to_doctype": "Project", "attached_to_name": friday_project},
			fields=["name", "file_name", "file_url"],
		)
		for f in project_files:
			if f.file_url and f.file_url not in collected:
				collected[f.file_url] = {"name": f.name, "file_name": f.file_name}

	for entry in collected.values():
		try:
			content = frappe.get_doc("File", entry["name"]).get_content()
		except Exception:
			continue
		if isinstance(content, str):
			content = content.encode("utf-8")
		client.attach_deliverable(
			rp_project, file_name=entry["file_name"], content=content,
			description=f"Brand deliverable: {entry['file_name']}",
		)


# ── Legacy Project-pipeline path (back-compat) ───────────────────────────────


def _legacy_writeback(task, state: str) -> None:
	phase = task.get("backend_ref")
	project_ref = frappe.db.get_value("Project", task.project, "backend_ref")
	if not project_ref:
		return
	task_ref = f"{project_ref}:{phase}"

	if state == "Blocked":
		client.signal_pending_review(
			task_ref, issue_name="see FRIDAY_WAR_ROOM",
			summary=f"{task.title} is blocked and needs a human decision.",
		)
		return

	status = _STATUS_MAP.get(state)
	if not status:
		return

	client.update_task_progress(task_ref, status=status, progress=100 if state == "Completed" else None)

	if state == "Completed":
		summary = _result_summary(task)
		if summary:
			client.post_project_note(
				project_ref, note=f"[{phase}] completed:\n{summary[:2000]}", task_ref=task_ref
			)
		gate = _GATE_PREP.get(phase)
		if gate:
			client.request_gate_open(
				project_ref, gate=gate, summary=f"{task.title} is ready for client review."
			)


def _result_summary(task) -> str:
	raw = task.get("result")
	if not raw:
		return ""
	data = raw if isinstance(raw, dict) else {}
	if isinstance(raw, str):
		try:
			data = json.loads(raw)
		except (TypeError, ValueError):
			return str(raw)
	return str(data.get("summary") or "")


# ── Design 77: brief-state-change hook (fires the union deliverable push) ─────


def on_brief_state_change(doc, method: str | None = None) -> None:
	"""Wired in hooks.py as a second Brand Brief on_update. When the brief
	reaches workflow_state='Delivered', push the union of brief + Friday
	Project deliverables back to RandomPack. Idempotent: only fires when the
	state JUST changed to Delivered (not on unrelated re-saves while already
	Delivered)."""
	try:
		if doc.get("workflow_state") != "Delivered":
			return
		if not doc.has_value_changed("workflow_state"):
			return
		rp_project = doc.get("rp_project")
		if not rp_project:
			return  # brief did not originate from a RandomPack project — stay internal
		_push_deliverables(rp_project, doc.name)
	except Exception:
		frappe.log_error(title="friday.randompack on_brief_state_change failed")
