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

# Marker phases for the study sidecars. NOT engine phases: no transition meta
# carries them, and the tasks carry no work_item — both advance.py and the
# bridge ignore them. The ledger counts observations/drafts by these keys.
OBSERVE_PHASE_KEY = "cd_observe"
DRAFT_PHASE_KEY = "cd_draft"

APPRENTICE_TAG = "cd-apprentice"

# Slice 3 — the graduation flag (design 95: "per-capability flags on the CD
# agent's profile... flipped on, the CD Creative stage becomes agent drafts →
# human curates"). A Custom Field so the DOMAIN concern stays out of the core
# Agent Profile doctype (same pattern as File.is_customer_facing). The
# operator flips it on the profile form; every flag is reversible.
GRADUATION_FLAG = "may_draft_directions"

_NOTES_PATTERN = "cd-refinement-notes-r%"
_PACKAGE_PATTERN = "production-package%"
_EXCERPT_CHARS = 400

# Production phases whose Completed tasks count as "productions attempted"
# in the ledger (buildout = the legacy name kept for in-flight briefs).
_PRODUCTION_PHASES = ("production", "buildout")

# Keyword buckets for the per-dimension ledger counts. Honest label: these
# are MENTIONS in the stored lessons, not a taxonomy — cheap, deterministic,
# and good enough to see where the apprentice's evidence is thin.
_DIMENSIONS: dict[str, tuple[str, ...]] = {
	"palette": ("palette", "color", "colour", "hex"),
	"typography": ("typograph", "typeface", "font"),
	"logo": ("logo", "mark", "symbol", "monogram"),
	"layout": ("layout", "grid", "spacing", "composition"),
}


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

		# Slice 3 — graduated capability: entering CD Creative with the flag ON
		# spawns a DRAFT sidecar (agent drafts → human curates → human still
		# fires Creative Ready). Independent of the branches above: a brief can
		# leave one watched state and enter another in the same transition.
		if new == "CD Creative":
			_maybe_spawn_draft_task(doc)
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
		f'(subject: "{APPRENTICE_TAG}", memory_type: "general", scope: "global" — these '
		"are craft lessons you must recall on FUTURE projects). Each lesson pairs the "
		"brief with the choice: 'Given <personality/industry/audience>, he chose "
		"<palette / typography / logo route / layout rule>; notes: <his stated reasoning "
		"if any>'. Name concrete values (hex codes, typeface names) when his files give "
		"them.\n\n"
		"Rules: no judgment, no advice, no production — pairing only. Do not attach "
		"files, do not advance anything. If you cannot read his files, remember nothing "
		"and complete with a note saying what was unreadable."
	)


# ---------------------------------------------------------------------------
# Slice 3, signal 3 — the graduated draft task (flag-gated)
# ---------------------------------------------------------------------------


def _may_draft() -> bool:
	"""The operator's graduation decision, read live from the profile flag."""
	return bool(frappe.db.get_value("Agent Profile", CD_AGENT_PROFILE, GRADUATION_FLAG))


def _maybe_spawn_draft_task(doc) -> None:
	"""When a brief ENTERS CD Creative and the operator has flipped
	`may_draft_directions` on, the apprentice drafts direction concepts FOR the
	human to curate. Same sidecar isolation as the observe task: no work_item,
	so nothing advances and nothing crosses the customer seam. The human still
	creates/edits/decides and still fires Creative Ready — this changes what is
	on his desk when he sits down, not who holds the pen."""
	if not _may_draft():
		return
	profile = _apprentice_profile()
	if not profile:
		return

	title = f"Draft {doc.name} — direction concepts for the human CD to curate"
	if frappe.db.exists(
		"Task",
		{
			"phase_key": DRAFT_PHASE_KEY,
			"title": title,
			"workflow_state": ["not in", ["Completed", "Cancelled"]],
		},
	):
		return

	task = frappe.get_doc(
		{
			"doctype": "Task",
			"title": title,
			"description": _draft_prompt(doc),
			"phase_key": DRAFT_PHASE_KEY,
			"project": doc.get("project"),
			"assigned_to_profile": profile,
			"workflow_state": "Assigned",
			"assigned_at": frappe.utils.now_datetime(),
			"execution_mode": "agentic",
			"priority": "normal",
		}
	)
	task.insert(ignore_permissions=True)


def _draft_prompt(doc) -> str:
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
		"DRAFT TASK (design 95 — graduated capability: the operator has enabled "
		"may_draft_directions; you draft, the human Creative Director decides).\n\n"
		f"A new brief just reached his creative stage: {doc.name}.\n"
		f"The brief:\n{brief_facts}\n\n"
		"Do this:\n"
		"1. Ground yourself in the human CD's accumulated taste — your cd-apprentice "
		"memories (his past choices and every correction he has given). Where his "
		"taste is unknown for this kind of brief, stay conservative and say so.\n"
		"2. Draft 2-3 DIRECTION CONCEPTS. Each: a name, the concept in two sentences, "
		"palette (hex values), typography (typeface names + roles), logo route, and "
		"1-2 layout principles.\n"
		f"3. Attach ONE markdown file named draft-directions-{doc.name}.md to the "
		"project with attach-deliverable. This is INTERNAL working material for the "
		"human CD to curate, edit, or discard.\n\n"
		"Rules: you are drafting FOR his review, not deciding — he still creates the "
		"identity and fires Creative Ready. Never present drafts as client material, "
		"and do not advance anything."
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

	# project=None ON PURPOSE (design 95): recall is project-scoped (design 73),
	# and a project-tagged lesson would be invisible on every FUTURE brief —
	# defeating the apprenticeship. Gate lessons are the CD's craft, not one
	# client's private facts; the brief stays traceable via source_session.
	row = frappe.get_doc(
		{
			"doctype": "Agent Memory",
			"memory": memory,
			"agent_profile": profile,
			"project": None,
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


# ---------------------------------------------------------------------------
# Slice 3 — provisioning (after_migrate) + the confidence ledger
# ---------------------------------------------------------------------------


def ensure_graduation_flags() -> None:
	"""Create the graduation Custom Field on Agent Profile (idempotent;
	after_migrate). A Custom Field keeps the domain concern out of the core
	doctype — the operator flips it on the apprentice's profile form."""
	if frappe.db.exists("Custom Field", {"dt": "Agent Profile", "fieldname": GRADUATION_FLAG}):
		return
	from frappe.custom.doctype.custom_field.custom_field import create_custom_field

	create_custom_field(
		"Agent Profile",
		{
			"fieldname": GRADUATION_FLAG,
			"label": "May Draft Directions (design 95 graduation)",
			"fieldtype": "Check",
			"default": "0",
			"insert_after": "system_prompt",
			"description": (
				"Apprenticeship graduation flag — an OPERATOR decision, evidence-informed "
				"(see the Studio ledger), never automatic. ON: when a brief enters CD "
				"Creative, this agent drafts direction concepts for the human Creative "
				"Director to curate; the human still creates, edits, and fires Creative "
				"Ready. Reversible at any time."
			),
		},
	)


def ledger_snapshot() -> dict:
	"""The confidence ledger (design 95: 'is it ready?' must be a number you
	can look at, not a feeling). Counted live from Agent Memory + Tasks —
	no new machinery, no model calls."""
	mems = frappe.get_all(
		"Agent Memory",
		filters={"agent_profile": CD_AGENT_PROFILE, "subject": APPRENTICE_TAG, "status": "Active"},
		fields=["name", "memory", "source_session", "creation"],
		order_by="creation asc",
		limit_page_length=0,
	)
	approvals = [m for m in mems if "Gate APPROVE" in (m.get("memory") or "")]
	refines = [m for m in mems if "Gate REFINE" in (m.get("memory") or "")]
	gate_names = {m["name"] for m in approvals} | {m["name"] for m in refines}
	lessons = [m for m in mems if m["name"] not in gate_names]

	decided = len(approvals) + len(refines)
	approve_rate = round(100 * len(approvals) / decided) if decided else None

	return {
		"flags": {GRADUATION_FLAG: _may_draft()},
		"observations": {
			"completed": _task_count(OBSERVE_PHASE_KEY, ("Completed",)),
			"open": _task_count(OBSERVE_PHASE_KEY, None),
		},
		"drafts_completed": _task_count(DRAFT_PHASE_KEY, ("Completed",)),
		"productions_attempted": sum(_task_count(phase, ("Completed",)) for phase in _PRODUCTION_PHASES),
		"lessons_stored": len(lessons),
		"gates": {
			"approvals": len(approvals),
			"refinements": len(refines),
			"approve_rate": approve_rate,
		},
		"dimensions": _dimension_mentions(lessons + refines),
		"briefs": _per_brief_rows(approvals, refines),
	}


def _task_count(phase_key: str, states: tuple[str, ...] | None) -> int:
	"""Count study tasks by phase. states=None counts OPEN (non-terminal)."""
	filters: dict = {"phase_key": phase_key}
	if states:
		filters["workflow_state"] = ["in", list(states)]
	else:
		filters["workflow_state"] = ["not in", ["Completed", "Cancelled"]]
	return frappe.db.count("Task", filters)


def _dimension_mentions(memories: list[dict]) -> dict[str, int]:
	texts = [(m.get("memory") or "").lower() for m in memories]
	return {
		dim: sum(1 for t in texts if any(k in t for k in keywords)) for dim, keywords in _DIMENSIONS.items()
	}


def _per_brief_rows(approvals: list[dict], refines: list[dict]) -> list[dict]:
	"""One row per brief that reached the CD gate: refinement rounds + outcome.
	The refinement-loop TREND is this list read newest-first."""
	briefs: dict[str, dict] = {}
	for m in refines:
		brief = (m.get("source_session") or "").removeprefix("study::")
		if not brief:
			continue
		row = briefs.setdefault(brief, {"brief": brief, "refinements": 0, "approved": False})
		row["refinements"] += 1
	for m in approvals:
		brief = (m.get("source_session") or "").removeprefix("study::")
		if not brief:
			continue
		row = briefs.setdefault(brief, {"brief": brief, "refinements": 0, "approved": False})
		row["approved"] = True
	for row in briefs.values():
		row["business_name"] = (
			frappe.db.get_value("Brand Brief", row["brief"], "business_name") or row["brief"]
		)
	return sorted(briefs.values(), key=lambda r: r["brief"], reverse=True)
