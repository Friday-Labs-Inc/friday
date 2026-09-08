# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt

"""
Governance guard for the metadata-driven engine (Design 75).

WHY THIS EXISTS (the load-bearing bit — critic CRITICAL-1)
==========================================================
Frappe only enforces a Workflow transition's `allowed` role against the
*current session user*. Inside a background (RQ) worker the session user is
`Administrator`, and Frappe waves Administrator through every transition
(`get_transitions` returns all of them). So if the engine fired a workflow
transition as-is, role-gating would silently NOT apply — any agent could fire
any step, including human-only client gates.

The fix is simple and absolute: before firing ANY workflow transition, switch
the acting user to the one that is actually authorised (the agent's own system
user, or a gate's gateway account), then always switch back. `apply_workflow`
then sees a user that holds only its own role and refuses anything else.

Use it as a `with` block so the restore happens even if the transition throws:

    with acting_as(agent_user):
        apply_workflow(work_item, action)
"""

from __future__ import annotations

from contextlib import contextmanager

import frappe


@contextmanager
def acting_as(user: str):
	"""Run the wrapped block as `user`, then always restore the prior user.

	Design 99: delegates to the framework's `frappe.acting_as`, which restores
	BOTH the session user and the actor context (who is acting: agent / human /
	system) — so a transition fired as an agent's user is stamped as that agent
	on every row it writes, and the worker never stays impersonating anyone.
	"""
	with frappe.acting_as(user):
		yield
