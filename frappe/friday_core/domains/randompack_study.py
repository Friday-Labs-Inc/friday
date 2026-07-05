# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""
The CD apprenticeship study loop (design 95, Slice 2).

PLAIN ENGLISH
=============
The founder's vision, verbatim: "the creative director agent slowly should
study and learn from human director feeds, once its confident we can allow it
to create logo and brandings." This module is the STUDY half: it watches the
two places the human Creative Director's taste shows up, and turns each into
durable Agent Memory for the apprentice (the "Creative Director" agent profile):

1. **Observation (CD Creative → onwards).** When the human fires Creative
   Ready, the apprentice gets an *observe task*: read the brief and the
   human's uploaded artifacts (design system, boards) and `remember` 1–3
   structured lessons — "given this brief, he chose {palette, type, logo
   route}". No judgment, just pairing. The task is a side-study: it carries
   NO work_item link, so it can never advance the pipeline (engine/advance.py
   ignores tasks without work_item fields) and never crosses the RandomPack
   seam (the bridge writeback keys on the work-item).

2. **Labeled feedback (CD Internal Gate decisions).** Every gate decision on
   the AI's production is a labeled example, recorded DIRECTLY (no model
   call — cheap and honest): Approve Production = a positive label; Request
   Refinement = the correction, quoting the cd-refinement-notes file the
   Studio Bench just wrote (studio_api saves it BEFORE the transition, so it
   is always there on this path).

Memories are tagged via `subject="cd-apprentice"` so future recall and the
Slice-3 confidence ledger can find and count them.

Wired in hooks.py as a third Brand Brief on_update handler (after the engine
and the bridge). Failure-isolated: a study outage must NEVER break a
workflow save — every entry point is wrapped.

Compare with Hermes: no equivalent — Hermes agents have session memory but no
observational apprenticeship channel. This is the Design 95 divergence: taste
is accumulated from a human's real decisions, not prompt-engineered.
"""

from __future__ import annotations

import frappe

# The apprentice seat (randompack_brand.PROFILES — the AI keeps the seat's
# name per design 95 Q2; the human holds the Brand Creative Director role).
CD_AGENT_PROFILE = "Creative Director"

# Marker phase for observe tasks. NOT an engine phase: no transition meta
# carries it, and observe tasks carry no work_item — both advance.py and the
# bridge ignore them. The ledger (Slice 3) counts observations by this key.
OBSERVE_PHASE_KEY = "cd_observe"

APPRENTICE_TAG = "cd-apprentice"

_NOTES_PATTERN = "cd-refinement-notes-r%"
_PACKAGE_PATTERN = "production-package%"
_EXCERPT_CHARS = 400


def on_brief_study_signal(doc, method: str | None = None) -> None:
	"""Brand Brief on_update: harvest study signals from CD-owned transitions.

	- leaving "CD Creative"                    → spawn the observe task
	- "CD Internal Gate" → "Gate 2 Prep"       → labeled memory: APPROVE
	- "CD Internal Gate" → "AI Production"     → labeled memory: REFINE (+ notes)
	"""
	try:
		if not doc.has_value_changed("workflow_state"):
			return
		before = doc.get_doc_before_save()
		old = before.get("workflow_state") if before else None
		new = doc.get("workflow_state")
		if not old or old == new:
			return

		if old == "CD Creative":
			_spawn_observe_task(doc)
		elif old == "CD Internal Gate" and new == "Gate 2 Prep":
			_record_gate_memory(doc, approved=True)
		elif old == "CD Internal Gate" and new == "AI Production":
			_record_gate_memory(doc, approved=False)
	except Exception:
		# The study loop is an observer — it must never break the engine save.
		frappe.log_error(title="friday.study on_brief_study_signal failed")


# ---------------------------------------------------------------------------
# Signal 1 — the observe task
# ---------------------------------------------------------------------------


def _spawn_observe_task(doc) -> None:
	"""One side-study task for the apprentice: read what the human made and
	remember the pairing. Deliberately NO work_item fields — see module doc."""
	profile = _apprentice_profile()
	if not profile:
		return

	title = f"Observe {doc.name} — study the human CD's creative choices"
	if frappe.db.exists(
		"Task",
		{
			"phase_key": OBSERVE_PHASE_KEY,
			"title": title,
			"workflow_state": ["not in", ["Completed", "Cancelled"]],
		},
	):
		return  # an open observe task for this brief already exists

	task = frappe.get_doc(
		{
			"doctype": "Task",
			"title": title,
			"description": _observe_prompt(doc),
			"phase_key": OBSERVE_PHASE_KEY,
			"project": doc.get("project"),
			"assigned_to_profile": profile,
			"workflow_state": "Assigned",
			"assigned_at": frappe.utils.now_datetime(),
			"execution_mode": "agentic",
			"priority": "normal",
		}
	)
	task.insert(ignore_permissions=True)


def _observe_prompt(doc) -> str:
	"""The observe task's instruction. Pairing only — brief traits → the
	human's choices — phrased so the lessons recall well on future briefs."""
	brief_facts = "\n".join(
		f"- {label}: {doc.get(field)}"
		for label, field in (
			("Business", "business_name"),
			("Industry", "industry"),
			("What they do", "what_they_do"),
			("Audience", "target_audience"),
			("Personality", "brand_personality"),
			("Color preferences", "color_preferences"),
			("Inspirations", "inspirations"),
		)
		if doc.get(field)
	)
	return (
		"STUDY TASK (design 95 apprenticeship — you are observing, not producing).\n\n"
		f"The human Creative Director just finished the creative stage for brief {doc.name}.\n"
		f"The brief:\n{brief_facts}\n\n"
		"Do this:\n"
		"1. Call list-project-files, then get-project-file on the Creative Director's "
		"uploads (the design system document, direction boards, logo files).\n"
		"2. Distill 1-3 lessons about HIS choices, and store each with `remember` "
		f'(subject: "{APPRENTICE_TAG}", memory_type: "general"). Each lesson pairs the '
		"brief with the choice: 'Given <personality/industry/audience>, he chose "
		"<palette / typography / logo route / layout rule>; notes: <his stated reasoning "
		"if any>'. Name concrete values (hex codes, typeface names) when his files give "
		"them.\n\n"
		"Rules: no judgment, no advice, no production — pairing only. Do not attach "
		"files, do not advance anything. If you cannot read his files, remember nothing "
		"and complete with a note saying what was unreadable."
	)


# ---------------------------------------------------------------------------
# Signal 2 — labeled gate memories (direct writes, no model call)
# ---------------------------------------------------------------------------


def _record_gate_memory(doc, approved: bool) -> None:
	profile = _apprentice_profile()
	if not profile:
		return

	project = doc.get("project")
	business = doc.get("business_name") or doc.name
	industry = doc.get("industry") or "unspecified industry"
	rounds = _file_count(project, _NOTES_PATTERN)
	package = _latest_file_name(project, _PACKAGE_PATTERN) or "no package on file"

	if approved:
		memory = (
			f"[{APPRENTICE_TAG}] Gate APPROVE — {business} ({industry}): the human CD "
			f"approved the production package as-is after {rounds} refinement round(s). "
			f"Package: {package}."
		)
	else:
		notes_name, excerpt = _latest_notes(project)
		correction = excerpt or "correction notes not on file (gate fired outside the Studio)"
		memory = (
			f"[{APPRENTICE_TAG}] Gate REFINE — {business} ({industry}), round {rounds}: "
			f'the human CD sent production back with this correction: "{correction}" '
			f"(full notes: {notes_name or 'n/a'}; package: {package})."
		)

	row = frappe.get_doc(
		{
			"doctype": "Agent Memory",
			"memory": memory,
			"agent_profile": profile,
			"project": project,
			"subject": APPRENTICE_TAG,
			"memory_type": "general",
			"source_session": f"study::{doc.name}",
			"status": "Active",
		}
	)
	row.insert(ignore_permissions=True)

	# Embed for semantic recall (design 80) — best-effort, like the remember skill.
	try:
		from frappe.friday_core.llm.embed import enqueue_embed

		enqueue_embed(row.name)
	except Exception:
		pass  # no embedding just means keyword+recency recall


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _apprentice_profile() -> str | None:
	"""The Active apprentice profile, or None (logged — study signals are lost
	loudly, never silently)."""
	profile = frappe.db.get_value("Agent Profile", {"name": CD_AGENT_PROFILE, "status": "Active"}, "name")
	if not profile:
		frappe.log_error(
			message=(
				f"No Active Agent Profile named {CD_AGENT_PROFILE!r} — a design-95 study "
				"signal was dropped. Provision the apprentice profile."
			),
			title="friday.study apprentice profile missing",
		)
	return profile


def _file_count(project: str | None, pattern: str) -> int:
	if not project:
		return 0
	return frappe.db.count(
		"File",
		{"attached_to_doctype": "Project", "attached_to_name": project, "file_name": ["like", pattern]},
	)


def _latest_file(project: str | None, pattern: str) -> dict | None:
	if not project:
		return None
	rows = frappe.get_all(
		"File",
		filters={
			"attached_to_doctype": "Project",
			"attached_to_name": project,
			"file_name": ["like", pattern],
		},
		fields=["name", "file_name"],
		order_by="creation desc",
		limit=1,
	)
	return rows[0] if rows else None


def _latest_file_name(project: str | None, pattern: str) -> str | None:
	row = _latest_file(project, pattern)
	return row["file_name"] if row else None


def _latest_notes(project: str | None) -> tuple[str | None, str | None]:
	"""(file_name, excerpt) of the newest refinement-notes file, best-effort."""
	row = _latest_file(project, _NOTES_PATTERN)
	if not row:
		return None, None
	try:
		content = frappe.get_doc("File", row["name"]).get_content()
		if isinstance(content, bytes):
			content = content.decode("utf-8", errors="replace")
		excerpt = " ".join(content.split())[:_EXCERPT_CHARS]
		return row["file_name"], excerpt
	except Exception:
		return row["file_name"], None
