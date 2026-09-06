# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""
Task Completion Summary — one permanent row per terminal task.

Counterpart to `Dispatcher Event` (which is purged after 30 days). The
workflow hook writes one row here on every terminal state transition
(Completed / Cancelled / Blocked-non-transient), capturing the compact
audit trail: final state, event count, total LLM cost, duration, blocked
reason if any. Grows only with project/task count — bounded forever.

The Lifecycle Trace tab joins to this when the operator opens a task
whose raw events have been purged: the summary still answers "what
happened to this task" at a high level.
"""

from frappe.model.document import Document


class TaskCompletionSummary(Document):
	"""Permanent audit row. Written by the workflow hook on terminal transitions."""

	pass
