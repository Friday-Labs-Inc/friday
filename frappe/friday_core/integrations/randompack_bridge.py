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

# gate-prep phase → the RP GATE TASK's subject. E2E finding #13: on RandomPack a
# gate only actually OPENS (client card renders, gate.opened fires, the advisor's
# action passes validation) when its Task flips to status="Working" —
# request_gate_open alone is signal-only (a comment). The bridge now flips the
# gate task itself, which the E2E had to do by hand at both gates.
_GATE_TASK_SUBJECT = {"gate1_prep": "Gate 1 — choose direction", "gate2_prep": "Gate 2 — final review"}

# gate-prep phase → the presentation file that gate reviews. E2E finding #6: the
# client's gate opened over an EMPTY portal because the presentation only lived
# on Friday's bench. The bridge now pushes it (branded, human-named,
# customer-facing) BEFORE opening the gate.
_GATE_DOC_PREFIX = {"gate1_prep": "gate1-client-presentation", "gate2_prep": "gate2-final-review"}
_GATE_DOC_TITLE = {"gate1_prep": "Direction Presentation (Gate 1)", "gate2_prep": "Final Review (Gate 2)"}

# Friday phase_key → RandomPack template-task SUBJECT (the stable display string
# in the 'Essentials — 10 Day' template). RandomPack owns the docnames; we match
# by subject. `naming` shares the strategy task; Intake/Delivery have no phase.
# E2E finding #13 (second half): the Design-95 machine renamed the build phase to
# `production` — the map spoke only the OLD vocabulary, so RP's "Build system"
# task never advanced. Both vocabularies are mapped (buildout = legacy briefs).
_SUBJECT_MAP = {
	"strategy": "Strategy & naming",
	"naming": "Strategy & naming",
	"directions": "Three directions",
	"gate1_prep": "Gate 1 — choose direction",
	"production": "Build system",
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
			# E2E findings #6 + #13, in order: the client must have the document
			# BEFORE the gate opens, and the gate only opens when its RP task
			# flips to Working (request_gate_open is signal-only).
			_push_gate_presentation(rp_project, brief_name, phase)
			client.request_gate_open(
				rp_project, gate=gate, summary=f"{task.get('title') or phase} is ready for client review."
			)
			gate_task = _resolve_rp_task_by_subject(rp_project, _GATE_TASK_SUBJECT.get(phase))
			if gate_task:
				client.update_task_progress(gate_task, status="Working")
		# Design 77: _push_deliverables fires from on_brief_state_change when the
		# brief reaches Delivered, NOT here, so the project-level materialize
		# package (assemble_project_package) has time to land first.


def _resolve_rp_task(rp_project: str, phase: str) -> str | None:
	"""Map our phase to the backend's real Task docname by matching subjects from
	get_project. Returns None if no match (write-back degrades to a project note)."""
	return _resolve_rp_task_by_subject(rp_project, _SUBJECT_MAP.get(phase))


def _resolve_rp_task_by_subject(rp_project: str, subject: "str | None") -> str | None:
	if not subject:
		return None
	state = client.get_project_state(rp_project) or {}
	tasks = (state.get("message") or state).get("tasks") or []
	for t in tasks:
		if (t.get("subject") or "") == subject:
			return t.get("name")
	return None


def _push_gate_presentation(rp_project: str, brief_name: str, phase: str) -> None:
	"""Push the gate's review document to RP as a branded, human-named PDF —
	BEFORE the gate opens (E2E finding #6). Best-effort: a render/push hiccup
	must not block the gate-open signal; the operator can re-push."""
	from frappe.friday_core.deliverables import materialize

	prefix = _GATE_DOC_PREFIX.get(phase)
	project = frappe.db.get_value("Brand Brief", brief_name, "project")
	if not prefix or not project:
		return
	files = frappe.get_all(
		"File",
		filters={"attached_to_doctype": "Project", "attached_to_name": project},
		fields=["name", "file_name", "creation"],
	)
	candidates = [
		f
		for f in files
		if str(f.get("file_name") or "").startswith(prefix) and str(f.get("file_name") or "").endswith(".md")
	]
	if not candidates:
		return
	latest = sorted(candidates, key=lambda f: str(f.get("creation") or ""))[-1]
	try:
		content = frappe.get_doc("File", latest["name"]).get_content()
		if isinstance(content, bytes):
			content = content.decode("utf-8")
	except Exception:
		return

	ctx = materialize._work_item_context_for("Brand Brief", brief_name, project)
	company = ctx.get("company") or ""
	title = _GATE_DOC_TITLE.get(phase, "Gate Review")
	display = f"{company} — {title}" if company else title
	pdf = materialize._render_pdf(display, content, brand_context=ctx)
	payload = pdf if pdf else content.encode("utf-8")
	out_name = f"{display}.pdf" if pdf else f"{display}.md"
	client.attach_deliverable(
		rp_project, file_name=out_name, content=payload, description=display
	)


def _push_deliverables(rp_project: str, brief_name: str) -> None:
	"""Send the CUSTOMER-FACING files attached to the Brand Brief or the linked
	Friday Project to RandomPack as deliverables.

	Design 96 Slice 2 — the push filters on `is_customer_facing=1`. The Friday
	Labs E2E pushed EVERYTHING on both targets, which delivered the Creative
	Director's internal refinement notes and raw hash-named drafts to the
	customer. Now: the customer-materialize step flags its branded PDFs, the CD
	flags his final assets (logo SVG/PNG) in Desk, and nothing else crosses.

	Idempotency: a file is identified by its file_url; the union-dedup means
	a file linked from both targets is pushed once.
	"""
	from frappe.friday_core.deliverables.materialize import CUSTOMER_FLAG_FIELD

	collected: dict[str, dict] = {}  # file_url -> {name, file_name}
	brief_files = frappe.get_all(
		"File",
		filters={
			"attached_to_doctype": "Brand Brief",
			"attached_to_name": brief_name,
			CUSTOMER_FLAG_FIELD: 1,
		},
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
			filters={
				"attached_to_doctype": "Project",
				"attached_to_name": friday_project,
				CUSTOMER_FLAG_FIELD: 1,
			},
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
		display = str(entry["file_name"] or "").rsplit(".", 1)[0]
		client.attach_deliverable(
			rp_project, file_name=entry["file_name"], content=content,
			description=display or entry["file_name"],
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
		# Design 96 Slice 2: render the customer package FIRST (branded PDFs with
		# human names, flagged customer-facing), then push exactly the flagged set.
		from frappe.friday_core.deliverables.materialize import materialize_for_customer

		try:
			materialize_for_customer(doc.doctype, doc.name)
		except Exception:
			frappe.log_error(title="friday.randompack materialize_for_customer failed")
		_push_deliverables(rp_project, doc.name)
	except Exception:
		frappe.log_error(title="friday.randompack on_brief_state_change failed")
