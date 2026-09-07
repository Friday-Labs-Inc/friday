# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt

"""
The orphan recovery sweeper — Q5 half-step.

PLAIN ENGLISH
=============

In async dispatch mode, the gateway runs in an RQ worker (separate
process). The inbound Chat Message row is committed before the worker
picks up the job. If the worker dies mid-turn (OOM, timeout, crash),
the inbound row sits there with `processed=0` and no outbound was ever
written. The user (or webhook caller) is left hanging.

This module runs every minute as a Frappe scheduled task. It finds those
orphaned rows and re-runs them, up to 3 retries. After 3 failures it
writes a system-error outbound and gives up.

SYNC MODE DOES NOT NEED THIS
============================

When dispatch_mode is "sync" (CLI path), the gateway runs INSIDE the
inbound row's transaction. If anything raises, the inbound row never
persists — Frappe rolls it back. There's nothing to recover. This
sweeper is correct dead code on a CLI-only deployment; it activates
the moment the first async surface (Telegram, Slack, Raven webhook)
lands.

TUNING (locked per §4 Q5)
==========================

- Stale-threshold: 5 minutes. An inbound row older than this with
  processed=0 is considered orphaned. Long enough that legitimately-
  slow agent runs don't trigger false positives; short enough that
  users don't wait forever.
- Max retries: 3. Standard.
- On final give-up: write a system-error outbound, mark
  processed=1, populate failure_reason. The user sees the error
  message; audit trail records why.

REFERENCED DOCS
===============

- `docs/design/47-gateway-design-decisions.md` §4 Q5 — the contract.
- `feedback-single-tenant-not-saas` — sizing rationale.
"""

from __future__ import annotations

from datetime import timedelta

import frappe

STALE_AGE_MINUTES = 5
MAX_RETRIES = 3


def sweep_orphans() -> dict:
	"""Find orphaned inbound rows and re-enqueue them.

	Scheduled via `scheduler_events` in hooks.py to run every minute.
	Returns a small stats dict (handy for tests and ops dashboards).

	"Orphaned" means: direction=inbound, processed=0, older than the
	stale threshold, on a platform with dispatch_mode=async.
	"""
	cutoff = frappe.utils.add_to_date(frappe.utils.now_datetime(), minutes=-STALE_AGE_MINUTES)

	# Two-step: find async-mode platforms first, then query inbound rows
	# on those platforms. Avoids a complex JOIN at the DocType-query
	# level (which Frappe's get_all doesn't do cleanly).
	async_platforms = frappe.get_all(
		"Chat Platform",
		filters={"dispatch_mode": "async"},
		pluck="name",
	)
	if not async_platforms:
		# Pure sync deployment (v0.1 CLI-only): nothing to sweep.
		return {"checked": 0, "reenqueued": 0, "gave_up": 0}

	orphans = frappe.get_all(
		"Chat Message",
		filters={
			"direction": "inbound",
			"processed": 0,
			"platform": ("in", async_platforms),
			"creation": ("<", cutoff),
		},
		fields=["name", "retry_count"],
	)

	reenqueued = 0
	gave_up = 0
	for row in orphans:
		current_retries = row["retry_count"] or 0
		if current_retries >= MAX_RETRIES:
			_give_up(row["name"])
			gave_up += 1
		else:
			_reenqueue(row["name"], current_retries + 1)
			reenqueued += 1

	return {
		"checked": len(orphans),
		"reenqueued": reenqueued,
		"gave_up": gave_up,
	}


def _reenqueue(row_name: str, new_retry_count: int) -> None:
	"""Bump retry_count and enqueue another pipeline run.

	Gateway v2 (design 55): retries go to the DEDICATED friday queue with
	the same timeout the router uses — orphan recovery must not land agent
	turns back on the shared default queue. Falls back to inline execution
	when no friday worker is alive (same Q1 fallback as the router).
	"""
	from friday.friday_core.gateway.service import (
		FRIDAY_JOB_TIMEOUT_SECONDS,
		FRIDAY_QUEUE,
		_friday_worker_alive,
		run_pipeline_for_row,
	)

	frappe.db.set_value(
		"Chat Message",
		row_name,
		{"retry_count": new_retry_count},
		update_modified=False,
	)
	frappe.db.commit()
	if _friday_worker_alive():
		frappe.enqueue(
			"friday.friday_core.gateway.service.run_pipeline_for_row",
			row_name=row_name,
			queue=FRIDAY_QUEUE,
			timeout=FRIDAY_JOB_TIMEOUT_SECONDS,
		)
	else:
		run_pipeline_for_row(row_name)


def _give_up(row_name: str) -> None:
	"""Write a system-error outbound and mark the inbound row processed."""
	# Reload the doc so we can read the linked fields needed for the
	# outbound write.
	inbound = frappe.get_doc("Chat Message", row_name)
	frappe.get_doc(
		{
			"doctype": "Chat Message",
			"session_id": inbound.session_id,
			"platform": inbound.platform,
			"direction": "outbound",
			"sender_id": "system",
			"agent_profile": inbound.agent_profile,
			"content": "(agent failed to respond after 3 retries — see audit log)",
			"timestamp": frappe.utils.now_datetime(),
			"processed": 1,
		}
	).insert(ignore_permissions=True)
	frappe.db.set_value(
		"Chat Message",
		row_name,
		{
			"processed": 1,
			"failure_reason": "Exceeded MAX_RETRIES (3) in recovery sweeper.",
		},
		update_modified=False,
	)
	frappe.db.commit()
