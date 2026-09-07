# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class AgentSettings(Document):
	"""Singleton settings document for the Friday agent framework.

	There should be exactly one row of this type, named "Agent Settings".
	It holds global defaults — primarily which LLM Provider to use when
	an Agent Profile doesn't specify one.

	The `autoincrement=False` in the JSON schema enforces that Frappe
	will not auto-create additional rows. The `after_migrate` hook in
	`frappe/hooks.py` creates the singleton on first site setup.
	"""

	pass
