# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt

"""
The `propose_skill_change` skill — the GOVERNED half of the learning loop.

PLAIN ENGLISH
=============

Hermes lets an agent edit its own skill files. Friday does not — agents never
mutate governed skills. Instead, when the self-improvement review spots a
reusable how-to lesson, it calls THIS skill to record ONE `Skill Proposal` row
(status Pending). A human reviews it in Desk and approves/rejects; applying the
change is a deliberate human act. The agent learns *how to work* without ever
rewriting its own permission surface.

Like `remember`, the calling profile + session come from the dispatch-context
flags, so every proposal is attributed to the agent and session that raised it.
"""

from __future__ import annotations

import frappe
from friday.friday_core.agent_runner.dispatcher import register_skill_handler

PROPOSE_SKILL_CHANGE = "propose_skill_change"

_VALID_TYPES = ("new_skill", "update_skill", "add_reference")


def propose_skill_change(skill_name: str, parameters: dict) -> dict:
	"""Record ONE Pending Skill Proposal for human review. Validation errors raise."""
	title = (parameters.get("title") or "").strip()
	if not title:
		raise ValueError("propose_skill_change requires a 'title' — a short name for the change")

	ctx = frappe.flags.get("friday_dispatch_context") or {}
	profile = ctx.get("agent_profile") or ""
	if not profile:
		raise ValueError("propose_skill_change could not determine the calling agent profile")

	proposal_type = (parameters.get("proposal_type") or "new_skill").strip()
	if proposal_type not in _VALID_TYPES:
		proposal_type = "new_skill"

	doc = frappe.get_doc(
		{
			"doctype": "Skill Proposal",
			"agent_profile": profile,
			"session_id": ctx.get("session_id") or "",
			"proposal_type": proposal_type,
			"target_skill": (parameters.get("target_skill") or "").strip(),
			"title": title[:200],
			"rationale": (parameters.get("rationale") or "").strip()[:1000],
			"proposed_content": (parameters.get("proposed_content") or "").strip(),
			"status": "Pending",
		}
	)
	doc.insert(ignore_permissions=True)

	return {
		"result": f"Proposed for human review (Pending): {title}",
		"doctype": "Skill Proposal",
		"record_name": doc.name,
	}


register_skill_handler(PROPOSE_SKILL_CHANGE, propose_skill_change)
