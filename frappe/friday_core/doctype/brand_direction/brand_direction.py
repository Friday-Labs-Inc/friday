# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt

"""
Brand Direction — one agent-generated creative direction (design 56, Q2).

PLAIN ENGLISH
=============
One row per direction the agent proposes for a Brand Brief — typically three
per brief. Each carries everything a designer needs to start: the concept
story, palette, typography, a designer-ready logo description, and tagline
options. The design team refines the winner right here in Desk (statuses:
Proposed → Shortlisted → Refined / Rejected). Written ONLY via the
`create-brand-direction` skill, so every row is permission-checked and has an
Execution Log entry behind it.
"""

from frappe.model.document import Document


class BrandDirection(Document):
	pass
