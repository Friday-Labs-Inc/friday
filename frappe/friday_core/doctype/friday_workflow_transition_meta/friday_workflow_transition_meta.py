# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt

"""
Friday Workflow Transition Meta (Design 75) — the agentic metadata bound to ONE
Frappe Workflow transition.

WHY A STANDALONE DOCTYPE (not a child of Workflow Transition)
=============================================================
`Workflow Transition` is a Frappe *core* `istable` doctype. Frappe's ORM does not
support nested child tables, and patching a core doctype's JSON is not
upgrade-safe (a `bench migrate` would overwrite it). So the clean, upgrade-safe
binding is a standalone doctype keyed to the transition by
`(workflow, from_state, action)`.

The generic engine resolves the row by `(workflow, current_state, action)` and
reads `agent_role` (the routing key), the prompt template, and the limits. The
`action` it carries is exactly what `apply_workflow` fires — there is no
redundant "next action" field; the matched Frappe transition is the source of
truth for the next state.
"""

from __future__ import annotations

import frappe
from frappe.model.document import Document


class FridayWorkflowTransitionMeta(Document):
	def validate(self) -> None:
		self._unique_phase_key()
		self._unique_transition()
		self._validate_template()

	def _unique_phase_key(self) -> None:
		"""phase_key must be unique within its workflow (back-edge disambiguation
		relies on this — two transitions into the same state get distinct keys)."""
		if frappe.db.exists(
			"Friday Workflow Transition Meta",
			{"workflow": self.workflow, "phase_key": self.phase_key, "name": ("!=", self.name)},
		):
			frappe.throw(
				frappe._("phase_key {0} is already used in workflow {1}").format(
					frappe.bold(self.phase_key), frappe.bold(self.workflow)
				)
			)

	def _unique_transition(self) -> None:
		"""One meta row per (workflow, from_state, action) — the natural key of a
		Frappe Workflow transition."""
		if frappe.db.exists(
			"Friday Workflow Transition Meta",
			{
				"workflow": self.workflow,
				"from_state": self.from_state,
				"action": self.action,
				"name": ("!=", self.name),
			},
		):
			frappe.throw(
				frappe._("a transition-meta row already exists for ({0}, {1}, {2})").format(
					self.workflow, self.from_state, self.action
				)
			)

	def _validate_template(self) -> None:
		"""Test-render the Jinja template at save so a syntax error fails loudly
		HERE rather than as an opaque runner_lost when a task is dispatched
		(critic LOW-10). Undefined variables render empty (Frappe's default), so
		this catches genuine syntax errors, not every field reference."""
		template = (self.prompt_template or "").strip()
		if not template:
			return
		try:
			frappe.render_template(template, {})
		except Exception as exc:
			frappe.throw(
				frappe._("prompt_template has a Jinja error — fix it before saving: {0}: {1}").format(
					type(exc).__name__, exc
				)
			)
