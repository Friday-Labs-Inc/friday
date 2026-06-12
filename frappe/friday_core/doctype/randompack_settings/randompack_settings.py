# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt

"""
RandomPack Settings — one row per environment (design 60, Q1/security).

Holds the integration's two secrets (webhook HMAC secret, API secret) in
encrypted Password fields — the same pattern as LLM Provider keys — plus the
backend URL and the signature tolerance window. The `enabled` switch is the
integration's master kill switch.
"""

from frappe.model.document import Document


class RandomPackSettings(Document):
	pass
