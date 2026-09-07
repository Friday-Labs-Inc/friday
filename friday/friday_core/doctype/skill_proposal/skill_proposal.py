# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt

"""
Skill Proposal — the human-review surface for the learning loop's skill half.

PLAIN ENGLISH
=============

When the self-improvement review notices a reusable how-to lesson, it does NOT
edit a skill (agents never mutate governed skills). It records ONE Skill
Proposal row here, in status "Pending", describing the change it suggests. A
human reads it in Desk and Approves or Rejects — applying the change is a
deliberate human act. This is the governance gate that lets the agent learn
*how to work* without ever rewriting its own permissions surface.

`decided_by` / `decided_at` stamp who ruled and when (audit). Applying an
approved proposal (creating/editing the actual Skill) is intentionally a manual
step in v0.1 — the proposal carries the content; a human applies it.
"""

from frappe.model.document import Document


class SkillProposal(Document):
	pass
