# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""
Scheduled OAuth token refresh (design 63b-OAuth, Q6 — the cron backstop).

On-use refresh in ``tokens.get_fresh_access_token`` is the primary guarantee (a
token is never used stale). This cron is the backstop: every 30 minutes it
refreshes any OAuth provider whose access token is expiring, so a long-idle
provider stays warm and a broken refresh surfaces (logged + an Issue) BEFORE an
agent needs it mid-task — never a silent failure.

Wired into ``hooks.scheduler_events.cron['*/30 * * * *']``. Failure-isolated per
provider: one bad provider is logged and skipped, never aborting the sweep.
"""

from __future__ import annotations

import frappe
from frappe.friday_core.llm.oauth import tokens


def tick() -> dict:
	"""Refresh every expiring OAuth provider. Returns a summary."""
	refreshed = 0
	failed: list[str] = []

	for name in frappe.get_all("LLM Provider", filters={"auth_mode": "oauth"}, pluck="name"):
		try:
			doc = frappe.get_doc("LLM Provider", name)
			if tokens.is_expiring(doc.oauth_expires_at):
				tokens._refresh_for_flavor(doc)
				refreshed += 1
		except Exception:
			frappe.log_error(
				title=f"oauth_token_refresh: refresh failed for {name!r}",
				message=frappe.get_traceback(),
			)
			failed.append(name)

	frappe.db.commit()  # nosemgrep: frappe-semgrep-rules.rules.frappe-manual-commit
	return {"refreshed": refreshed, "failed": failed}
