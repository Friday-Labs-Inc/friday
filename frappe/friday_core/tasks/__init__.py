# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""
Friday Tasks Module

Orchestrates asynchronous execution of Tasks via the warm container pool.

Sub-modules
-----------
workflow : Workflow state-machine hook for Task documents.
dispatcher : Cron-scheduled task fetcher and profile matcher.
runner : Event-driven task executor that resumes paused containers.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
	from frappe.friday_core.doctype.agent_profile.agent_profile import AgentProfile
	from frappe.friday_core.doctype.task.task import Task

__all__ = ["dispatcher", "runner", "warroom", "workflow"]
