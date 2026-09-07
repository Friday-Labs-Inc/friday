# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""
Agent Profile controller.

Most behaviour lives elsewhere — this controller exists to apply the role
contract (design 68) at insert time. The role drives two things on creation:
the default approval threshold, and (for Orchestrators only) a default seed of
broad read tools so a new orchestrator can plan against the project without
the operator having to remember which baseline skills to grant.

Operator-set values are NEVER overridden — defaults fill only when the
relevant field is blank or empty. Editing an existing profile doesn't reseed.
"""

from __future__ import annotations

import frappe
from frappe.model.document import Document

# Per-role defaults — keep tight; complexity here is paid back nowhere.
_DEFAULT_APPROVAL = {
	"Orchestrator": "high",
	"Specialist": "medium",
	"Worker": "low",
}

# Orchestrators get a baseline of read tools so they can survey state and plan
# without the operator having to pick the obvious ones. Workers and Specialists
# stay blank — too many use cases to seed sensibly.
_ORCHESTRATOR_DEFAULT_SKILLS = ("read_record", "list_records", "list_project_files")


class AgentProfile(Document):
	def before_insert(self):
		apply_role_defaults(self)

	def validate(self):
		self._single_active_per_discriminator_role()

	def _single_active_per_discriminator_role(self) -> None:
		"""At most one Active profile may hold a given discriminator_role
		(Design 75, critic MEDIUM-7). The engine routes a transition's
		agent_role to THE active profile whose discriminator_role matches; a
		second active claimant would make that O(1) lookup ambiguous (one would
		silently shadow the other), so we fail loudly at save instead. Suspended
		and Retired profiles are exempt — only one *Active* owner is required.
		"""
		if not self.discriminator_role or self.status != "Active":
			return
		clash = frappe.db.exists(
			"Agent Profile",
			{
				"discriminator_role": self.discriminator_role,
				"status": "Active",
				"name": ("!=", self.name),
			},
		)
		if clash:
			frappe.throw(
				frappe._(
					"Agent Profile {0} is already the Active profile for discriminator role {1}. "
					"Two active profiles cannot share a discriminator role — suspend one first."
				).format(frappe.bold(clash), frappe.bold(self.discriminator_role))
			)


def apply_role_defaults(doc) -> None:
	"""Fill role-driven defaults on a new Agent Profile (idempotent).

	Pulled out as a free function so the test suite can run it against a plain
	dict-like fake without spinning up Frappe — same pattern used elsewhere in
	friday_core for testable controller logic.
	"""
	role = doc.get("agent_role") or "Specialist"

	# Default approval threshold (Q5 of design 68). Only fill when blank — an
	# operator who explicitly chose "always" or "low" wins over the default.
	if not doc.get("requires_approval_above_risk"):
		doc.requires_approval_above_risk = _DEFAULT_APPROVAL.get(role, "medium")

	# Orchestrator skill seed (Q4). Only seed when the table is empty — the
	# operator picking custom skills is the signal that they've decided.
	if role == "Orchestrator" and not (doc.get("permitted_skills") or []):
		for skill_name in _ORCHESTRATOR_DEFAULT_SKILLS:
			doc.append("permitted_skills", {"skill": skill_name})
