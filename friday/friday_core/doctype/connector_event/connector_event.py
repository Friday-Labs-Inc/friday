# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt

"""The Connector Event audit row (Design 81).

PLAIN ENGLISH
=============
Every inbound signed event a Connector receives becomes one Connector Event
row — the unified, governed audit trail across all integrations (the
surpass-Hermes line: Hermes has per-adapter config but no single audited
integration surface). `event_id` is unique, so a duplicate delivery is a clean
no-op. This DocType is the generic successor of the RandomPack-specific event
ledger (renamed in place to preserve history).
"""

from __future__ import annotations

from frappe.model.document import Document


class ConnectorEvent(Document):
	pass
