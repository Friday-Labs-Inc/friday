# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt
"""One row per document an AGENT wrote — written by the framework's actor-write
seam (Design 99), not by the skill dispatcher. So a write that bypasses the
dispatcher still leaves a trail. Append-only: no edit, no delete from Desk."""

import frappe
from frappe.model.document import Document


class AgentWriteLog(Document):
	def validate(self):
		if not self.is_new():
			frappe.throw("Agent Write Log rows are append-only")

	def on_trash(self):
		if not frappe.flags.in_test and not frappe.flags.in_install:
			frappe.throw("Agent Write Log rows cannot be deleted")
