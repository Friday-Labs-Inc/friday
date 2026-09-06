# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""
Dispatcher Event — one row per framework-mechanics thing-that-happened.

The Dispatcher Console (Design 72) reads this table to show the Lifecycle
Trace for any task and to drive cells on the Pulse panel. Every write site
in the framework — dispatcher, reconciler, runner, workflow hook, LLM
provider, War Room publisher, Issue raiser — goes through the single
`friday_core.observability.emit.emit(...)` helper. Direct inserts are not
expected anywhere else.

Retention is bounded: a daily scheduler job purges rows older than 30 days
(Q6 of Design 72). The compact, permanent counterpart is `Task Completion
Summary`, written once per terminal task transition.
"""

from frappe.model.document import Document


class DispatcherEvent(Document):
	"""Append-only event row. No mutation; not user-editable."""

	pass
