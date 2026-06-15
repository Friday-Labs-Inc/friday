# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""
Framework observability — Dispatcher Event emission (Design 72).

The single entry point is `emit()` — every framework write site (dispatcher,
reconciler, runner, workflow hook, LLM provider, War Room publisher, Issue
raiser) calls it to record what just happened. Reads land in the Dispatcher
Console (`/desk/dispatcher-console`).

Safety contract: `emit()` is savepoint-guarded and never raises. A bug in
the emit subsystem must not poison the surrounding transaction or break
production code paths.
"""

from frappe.friday_core.observability.emit import emit
from frappe.friday_core.observability.retention import (
	is_terminal,
	purge_old_events,
	write_task_completion_summary,
)

__all__ = ["emit", "is_terminal", "purge_old_events", "write_task_completion_summary"]
