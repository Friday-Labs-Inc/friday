# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt

"""
Brand Brief — the client questionnaire as a durable record (design 56, Q1).

PLAIN ENGLISH
=============
One row per client branding job. The team (or, later, a client-facing form)
fills in what the business is, who it speaks to, and what vibe it wants.
The agent reads this record via the `get-brand-brief` skill and generates
Brand Direction records from it — one chat command, three creative
directions, all traceable back to this brief.
"""

from frappe.model.document import Document


class BrandBrief(Document):
	pass
