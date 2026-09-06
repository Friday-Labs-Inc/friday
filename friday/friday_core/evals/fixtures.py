# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt

"""Sandbox fixtures the seed suite depends on.

Some scenarios need a known record to exist to test the *right* thing. The
clearest case: `project-status-by-name`. If you ask an agent for the status of a
project that doesn't exist, it will (correctly) call `list-projects` to find it —
which is NOT the tool that scenario means to exercise. So the eval first ensures a
known project exists, giving the scenario a real target.

Idempotent and **sandbox-only**: it writes a row, so it runs as part of `run.run`,
which already refuses to be pointed at production. The first real run of the
harness (2026-06-25) surfaced exactly this gap — the harness grading its own seeds.
"""

from __future__ import annotations

import frappe

# A Project is autonamed `field:project_name`, so its `name` IS this string —
# which is what an agent passes to `project-status`.
EVAL_PROJECT = "Eval Sample Project"


def ensure_eval_fixtures() -> dict:
	"""Create the fixtures the seed suite references. Idempotent. Returns a summary."""
	created: list[str] = []
	if not frappe.db.exists("Agent Project", EVAL_PROJECT):
		frappe.get_doc(
			{
				"doctype": "Agent Project",
				"project_name": EVAL_PROJECT,
				"status": "Open",
				"description": "Fixture for the Friday eval harness (Design 91). Safe to delete.",
			}
		).insert(ignore_permissions=True)
		created.append(EVAL_PROJECT)
	return {"project": EVAL_PROJECT, "created": created}
