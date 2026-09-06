# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt

"""
Agent Memory — one durable fact per row (design 59, Q1).

PLAIN ENGLISH
=============
Friday's long-term memory. Each row is one fact, preference, or decision
("Loop Coffee hates serif fonts") scoped to one Agent Profile. Every turn,
`llm/memory.recall_block` injects the profile's Active memories into the
prompt inside a reference-only fence — so the agent *knows* without being
*re-told*. Hermes keeps this in MEMORY.md files; Friday keeps it in rows:
auditable, editable in Desk, archivable instead of deletable.
"""

from frappe.model.document import Document


class AgentMemory(Document):
	pass
