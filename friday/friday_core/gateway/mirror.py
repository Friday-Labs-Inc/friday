# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt

"""
Transcript mirroring — keep the agent's own history complete (port of Hermes
`gateway/mirror.py`, adapted to Frappe's row model).

THE PROBLEM (plain English)
===========================
Most of what an agent "says" is already a `Chat Message` row, so it shows up in
the next turn's prompt automatically. But some sends go out **out-of-band** — the
clearest case is `share-deliverables`, which posts files straight to Raven via
`bot.send_message(...)` and writes NO row. The files reach the humans, but the
agent's own session transcript never records that it shared them. Next turn the
agent has forgotten its own action.

This module is the missing record. `mirror_to_session(...)` writes ONE compact,
marked row (`is_mirror=1`) into the session so the agent sees its out-of-band post
in history — without that row being re-posted to the channel.

WHY THIS IS SMALLER THAN HERMES (disclosed divergence)
======================================================
Hermes mirrors into the *target* session so the receiving agent has context. In
Friday that's already free: the Design-86 `DeliveryRouter` writes a
session-attributed `Chat Message` row into the target (`session_id == channel id`),
so the receiving side is covered by the substrate. Hermes also needs a
`sessions.json` scan to map `platform:chat_id → session_id`; Friday's session id
*is* the channel id, so there's nothing to disambiguate. What's left — and all this
module does — is the **origin/out-of-band** case Hermes' `send_message` mirror
covers: a post that bypasses the row model entirely.

The outbound surface adapters (`raven_adapter`, `slack_adapter`) skip `is_mirror`
rows, so a mirror is recorded-for-context but never delivered. `_load_history`
does not filter on `is_mirror`, so the agent sees it (as an assistant message).

Best-effort, exactly like Hermes: a mirror failure must NEVER break the caller.
"""

from __future__ import annotations

import frappe

_SAVEPOINT = "friday_mirror"


def mirror_to_session(
	session_id: str,
	content: str,
	*,
	source_label: str = "agent",
	platform: str = "raven",
) -> str | None:
	"""Append a compact mirror row to `session_id`'s transcript. Never raises.

	Arguments:
	  - `session_id`   the session to record into (a Raven channel id, …).
	  - `content`      the human-readable note (the agent's voice — what it did).
	  - `source_label` what produced this (e.g. "share-deliverables"); kept in
	                   the content marker for the audit trail.
	  - `platform`     the row's platform Link (default "raven"); the row is never
	                   re-posted (adapters skip `is_mirror`), this is for audit.

	Returns the new row name, or None if nothing was written (empty input or a
	swallowed error — mirroring is best-effort and must not break the caller).
	"""
	session_id = (session_id or "").strip()
	content = (content or "").strip()
	if not session_id or not content:
		return None

	try:
		# Savepoint: a failed insert must not poison the surrounding transaction
		# (same discipline as the Raven outbound post).
		frappe.db.savepoint(_SAVEPOINT)
		doc = frappe.get_doc(
			{
				"doctype": "Chat Message",
				"session_id": session_id,
				"platform": platform,
				"direction": "outbound",  # → role "assistant" in _load_history
				"sender_id": "system",
				"content": f"[shared out-of-band · {source_label}] {content}",
				"timestamp": frappe.utils.now_datetime(),
				"processed": 1,  # not a turn to run
				"is_mirror": 1,  # recorded for context, never re-delivered
			}
		)
		doc.insert(ignore_permissions=True)
		return doc.name
	except Exception:
		frappe.db.rollback(save_point=_SAVEPOINT)
		frappe.log_error(title="friday.mirror write failed")
		return None
