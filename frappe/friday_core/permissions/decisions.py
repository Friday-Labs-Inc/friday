# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt

"""
The audit-log writer for permission decisions.

PLAIN ENGLISH
=============

Every time the permission engine answers the question "can this agent
run this skill?" — for allow OR deny — we write one row to the
**Permission Decision Log** DocType. That row is then *submitted*,
which in Frappe means it becomes immutable: nobody can edit or delete
it later, not even an admin.

Why so paranoid? Because the decision log is what auditors,
regulators, and incident-responders read after the fact to answer
questions like:

  - "Did the Research Agent have permission to create that Note
    on March 12th?"
  - "Why was the Research Agent denied access to Contact records last
    week?"
  - "Show me every time Agent X was allowed to do something risky."

If those rows could be quietly edited, the log is worthless. So:
write once, never change.

WHAT WE STORE PER DECISION
==========================

  - `agent_profile` — which agent asked (link to Agent Profile).
  - `skill`         — which skill they wanted (link to Skill).
  - `decision`      — "allowed" or "denied".
  - `reason`        — the human-readable string from the Decision
                      ("Allowed" / "Profile lacks 'write' on …").
  - `matrix_snapshot` — JSON dump of the PermissionMatrix that was used.
                        This makes the decision *reproducible later*
                        even after the agent's roles change or skills
                        get edited.
  - `decided_at`    — timestamp of the decision.

The matrix snapshot is the important one. Without it, "the agent was
denied at 2pm" tells you nothing if at 3pm someone changed the
permissions. With it, you can reconstruct exactly what the world
looked like to the engine at decision time.

WHY `ignore_permissions=True` WHEN INSERTING
============================================

By default, Frappe checks the *current user's* permissions before
inserting a record. But this code path runs as part of the *system*
recording its own audit — there isn't really a "user" with a role
that says "may create Permission Decision Log rows". Skipping the
permission check is correct here: we are the audit machinery, not a
user-driven write.

If we left the permission check on, the log writes would fail for
most callers, which would either crash the agent or — worse — silently
swallow the failure and let actions proceed without a log row. Neither
is acceptable for an audit log.

WHY THIS IS ITS OWN FILE
========================

Could've been one more function on `matrix.py`. We split it because
audit-log writing is a *different concern* than permission deciding:
different DocType, different I/O pattern, different reasons to change
(e.g. one day we might add a webhook on each decision; that change
should not touch the decision logic). Single Responsibility, applied.
"""

from __future__ import annotations

import frappe

from frappe.friday_core.permissions.matrix import Decision, PermissionMatrix


def record(
	profile_name: str,
	skill_name: str,
	decision: Decision,
	matrix: PermissionMatrix,
) -> str:
	"""Insert and submit one Permission Decision Log row. Returns docname.

	Arguments:

	- `profile_name`: the Agent Profile name (Frappe primary key).
	- `skill_name`: the Skill name (Frappe primary key).
	- `decision`: the Decision object from `matrix.evaluate` /
	  `matrix.check`. Both fields go into the row.
	- `matrix`: the PermissionMatrix that produced the decision.
	  Serialized to JSON into the `matrix_snapshot` field so the
	  decision is reproducible after the fact.

	Returns the name (primary key) of the newly created log row — useful
	for tests and for callers that want to reference the audit trail.

	Side effect: writes one row to Permission Decision Log and submits
	it (makes it immutable). No update path — if you need to "fix" a
	row later, you write a new row instead.
	"""
	doc = frappe.get_doc(
		{
			"doctype": "Permission Decision Log",
			"agent_profile": profile_name,
			"skill": skill_name,
			# Permission Decision Log's `decision` field is a Select with
			# exactly these two values; using anything else would fail
			# Frappe's validation.
			"decision": "allowed" if decision.allowed else "denied",
			"reason": decision.reason,
			# `frappe.as_json` is Frappe's preferred JSON serializer —
			# handles dates, sets, and DocType-ish dicts consistently.
			"matrix_snapshot": frappe.as_json(matrix.to_dict()),
			"decided_at": frappe.utils.now_datetime(),
		}
	)
	# `ignore_permissions=True` — see the module docstring for why.
	doc.insert(ignore_permissions=True)
	# Submitting makes the row immutable. Reads still work; writes don't.
	doc.submit()
	return doc.name
