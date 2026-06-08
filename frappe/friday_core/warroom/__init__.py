# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""
Friday War Room Bridge

Posts Task status transitions to the Raven FRIDAY_WAR_ROOM channel.
Designed for graceful degradation — logs a warning if Raven is not installed,
raises no exceptions, and never blocks the task pipeline.
"""

from frappe.friday_core.warroom.publisher import post_task_update

__all__ = ["post_task_update"]