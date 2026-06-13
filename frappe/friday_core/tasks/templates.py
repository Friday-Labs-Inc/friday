# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt

"""
The RandomPack pipeline template (design 60, Q4 — TEMPLATE-FIRST).

PLAIN ENGLISH
=============
RandomPack is a productized service: fixed price, fixed 10-day shape, two
client decision gates. So the project plan is a deterministic TEMPLATE —
the same phases, dependencies, and gates every time — while the *content* of
each phase is intelligent: every agentic task references the client's Brand
Brief (@BB-xxxx), and the executing agent pulls the brief itself through the
@-reference/skill machinery at run time.

Gates are `milestone` tasks: never auto-dispatched; completed by the
`gate.decided` event (or a human in Desk). Everything downstream of a gate
AND-depends on it, so the pipeline pauses exactly where the client decides.

Freeform LLM decomposition for non-productized work is the disclosed
follow-up — this module is intentionally boring.
"""

from __future__ import annotations

import frappe

# key → spec. depends_on lists KEYS (resolved to task names at instantiation).
# backend_ref is the phase slug the write-back bridge sends to the backend.
RANDOMPACK_PIPELINE: list[dict] = [
	{
		"key": "strategy",
		"title": "Strategy & positioning draft",
		"mode": "agentic",
		"skills": ["get-brand-brief"],
		"depends_on": [],
		"description": (
			"Read the client's Brand Brief {brief} (use get-brand-brief). Draft the "
			"strategy and positioning: market position, audience insight, the one "
			"differentiating idea, and a positioning statement. Reply with the full "
			"draft — a human strategist refines it before the client sees anything."
		),
	},
	{
		"key": "naming",
		"title": "Naming candidates",
		"mode": "agentic",
		"skills": ["get-brand-brief"],
		"depends_on": ["strategy"],
		"description": (
			"Based on Brand Brief {brief} (read it with get-brand-brief) and the "
			"completed strategy draft, produce 8-12 name candidates with a one-line "
			"rationale each and basic screening notes (pronunciation, obvious "
			"conflicts). Humans shortlist; trademark/domain checks are theirs."
		),
	},
	{
		"key": "directions",
		"title": "Three creative directions",
		"mode": "agentic",
		"skills": ["get-brand-brief", "create-brand-direction"],
		"depends_on": ["strategy"],
		"description": (
			"Read Brand Brief {brief} with get-brand-brief, then generate THREE "
			"genuinely distinct brand directions and persist each with "
			"create-brand-direction (palette, typography, designer-ready logo "
			"concept, taglines). Reply with a one-paragraph summary of each."
		),
	},
	{
		"key": "gate1_prep",
		"title": "Gate 1 prep — direction presentation",
		"mode": "agentic",
		"skills": ["get-brand-brief"],
		"depends_on": ["naming", "directions"],
		"description": (
			"Assemble the client-facing summary for decision gate 1: the three "
			"directions (one paragraph each, written for the client of Brand Brief "
			"{brief}), naming shortlist context, and a recommendation with "
			"reasoning. Reply with the full presentation text."
		),
	},
	{
		"key": "gate1",
		"title": "Gate 1 — client picks a direction",
		"mode": "milestone",
		"skills": [],
		"depends_on": ["gate1_prep"],
		"description": "Client decision gate. Completed by the gate.decided event — never auto-dispatched.",
	},
	{
		"key": "buildout",
		"title": "Build-out of the chosen direction",
		"mode": "agentic",
		"skills": ["get-brand-brief"],
		"depends_on": ["gate1"],
		"description": (
			"The client of Brand Brief {brief} has chosen a direction (see the "
			"gate 1 decision in project memory). Produce the build-out package: "
			"refined palette system, typography hierarchy, voice & tone rules, "
			"application copy (web hero, about, boilerplate), and designer-ready "
			"specs for every core asset. Reply with the full package."
		),
	},
	{
		"key": "gate2_prep",
		"title": "Gate 2 prep — final presentation",
		"mode": "agentic",
		"skills": ["get-brand-brief"],
		"depends_on": ["buildout"],
		"description": (
			"Assemble the client-facing final-review summary for Brand Brief "
			"{brief}: what was built, the decisions made, and what delivery "
			"contains. Reply with the full presentation text."
		),
	},
	{
		"key": "gate2",
		"title": "Gate 2 — client final approval",
		"mode": "milestone",
		"skills": [],
		"depends_on": ["gate2_prep"],
		"description": "Client decision gate. Completed by the gate.decided event — never auto-dispatched.",
	},
	{
		"key": "guidelines",
		"title": "Brand guidelines draft",
		"mode": "agentic",
		"skills": ["get-brand-brief"],
		"depends_on": ["gate2"],
		"description": (
			"Draft the complete brand guidelines document for Brand Brief {brief}: "
			"strategy recap, logo usage rules (from the designer-ready specs), "
			"palette with values, typography, voice & tone with examples, and "
			"application do/don'ts. Reply with the full document in Markdown — "
			"humans finalize and export."
		),
	},
]


def instantiate_pipeline(project_name: str, backend_ref: str, brief_name: str) -> list[str]:
	"""Create the template's Tasks under a Friday Project. Returns task names.

	Idempotent per project: if the project already has tasks with these
	backend phase slugs, nothing is created (a replayed project.created event
	is a no-op).
	"""
	existing = frappe.get_all(
		"Task", filters={"project": project_name}, fields=["backend_ref"], limit_page_length=0
	)
	existing_slugs = {row.backend_ref for row in existing if row.backend_ref}

	created: dict[str, str] = {}
	names: list[str] = []
	for spec in RANDOMPACK_PIPELINE:
		if spec["key"] in existing_slugs:
			continue
		task = frappe.get_doc(
			{
				"doctype": "Task",
				"title": spec["title"],
				"description": spec["description"].format(brief=brief_name),
				"project": project_name,
				"workflow_state": "Pending",
				"execution_mode": spec["mode"],
				"backend_ref": spec["key"],
				"required_skills": [{"skill": s} for s in spec["skills"]],
				"depends_on": [{"task": created[dep]} for dep in spec["depends_on"] if dep in created],
			}
		)
		task.insert(ignore_permissions=True)
		created[spec["key"]] = task.name
		names.append(task.name)
	return names
