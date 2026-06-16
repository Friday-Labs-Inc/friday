# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt

"""
Domain Bundle (Design 75) — the unit that defines a whole domain as DATA.

A domain (RandomPack brand identity, data-center ops, a research project) is a
bundle of: a work-item DocType + a Frappe Workflow on it + the per-transition
agentic config (Friday Workflow Transition Meta) + the agent profiles/roles +
the skills. This doctype is the manifest + the export/import unit: exporting a
bundle gathers all of those into one JSON; importing provisions them idempotently
on a fresh install. No domain code is deployed — the engine reads the data.
"""

from __future__ import annotations

import frappe
from frappe.model.document import Document


class DomainBundle(Document):
	def validate(self) -> None:
		self._single_active_per_doctype()

	def _single_active_per_doctype(self) -> None:
		"""At most one active bundle per work-item DocType — so the engine can
		unambiguously find which bundle governs a given work item. Mirrors
		Frappe Workflow's one-active-per-document_type rule."""
		if not self.is_active:
			return
		clash = frappe.db.exists(
			"Domain Bundle",
			{
				"domain_doctype": self.domain_doctype,
				"is_active": 1,
				"name": ("!=", self.name),
			},
		)
		if clash:
			frappe.throw(
				frappe._(
					"Domain Bundle {0} is already the active bundle for {1}. "
					"Deactivate it first, or set this one inactive."
				).format(frappe.bold(clash), frappe.bold(self.domain_doctype))
			)
