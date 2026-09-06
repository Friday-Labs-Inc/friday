# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt

"""The Connector registry row (Design 81).

PLAIN ENGLISH
=============
One Connector record = one governed integration with an external ecosystem
(a CRM, RandomPack, an MCP server, another agent). It is DATA: the modality
("system" for a signed-event business system), the direction, the encrypted
secrets, and a thin adapter pointer (`handler_module`). The connector framework
(generic intake / dispatch / outbound client) is core; the *meaning* of a
connector's events stays in its domain module. See docs/design/81-connector-framework.md.
"""

from __future__ import annotations

from frappe.model.document import Document


class Connector(Document):
	pass
