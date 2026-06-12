# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt

"""
RandomPack Event — one durable row per webhook envelope (design 60, Q1).

The receiver inserts a row per event (UUID-unique — a duplicate delivery is
a 200 no-op), acks fast, and processing happens on the dedicated friday
queue. Replays from the backend re-run Failed events and skip Processed
ones; the row IS the idempotency ledger and the audit trail.
"""

from frappe.model.document import Document


class RandomPackEvent(Document):
	pass
