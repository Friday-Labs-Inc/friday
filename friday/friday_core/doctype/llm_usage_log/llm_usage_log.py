# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt

"""
One row per LLM API call: tokens billed + estimated cost.

PLAIN ENGLISH
=============
Every time the agent calls a model, the runner records what it cost — input
tokens, output tokens, and (when the LLM Provider row has per-million-token
rates set) an estimated USD cost. This makes "what is the agent costing us,
per session / per profile / per day" a Desk report query instead of a mystery.

Written best-effort by `llm/usage.py::record_usage` — a usage-log failure must
never break a turn. Rows are system-written; supervisors get read access.
"""

from frappe.model.document import Document


class LLMUsageLog(Document):
	pass
