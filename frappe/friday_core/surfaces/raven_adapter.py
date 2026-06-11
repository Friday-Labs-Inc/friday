# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt

"""
The Raven surface adapter — Friday in your team's chat (design 58, LOCKED).

PLAIN ENGLISH
=============
Two thin hooks, rows in / rows out, exactly like every Friday surface:

  INBOUND   a human DMs the Friday bot (or @mentions it in a channel)
            → we write ONE inbound Chat Message row (platform "raven",
              session = the Raven channel id)
            → Gateway v2 does everything else (dedicated worker, locks,
              audit, cost).

  OUTBOUND  the gateway writes an outbound Chat Message row for platform
            "raven" → we post it back into the channel via Raven's own
            `Raven Bot.send_message` API (markdown in, HTML out).

THE GUARDRAILS (Q3/Q6, locked)
==============================
- DMs: answered only when the Friday bot is a MEMBER of the DM channel.
- Channels: answered only when the bot is explicitly @mentioned (Raven
  extracts mentions server-side into `doc.mentions` — no HTML parsing here).
- Bot-authored messages are skipped (`is_bot_message`) — no self-loops.
- Raven absent → every function no-ops (the Raven Message hook can only
  fire when Raven is installed; the outbound hook checks the table).

This module never imports `agent_runner` (design 47 §9 — the one rule).
"""

from __future__ import annotations

import frappe

RAVEN_PLATFORM = "raven"
FRIDAY_BOT_NAME = "Friday"


# ---------------------------------------------------------------------------
# INBOUND — Raven Message → Chat Message row
# ---------------------------------------------------------------------------


def handle_raven_message(doc, method=None) -> None:
	"""`Raven Message.after_insert` hook: route human messages to the gateway.

	Only fires when Raven is installed (no Raven Message rows exist
	otherwise). Filters per the locked design, then writes the inbound
	Chat Message row — the gateway hook on that row takes over.
	"""
	# Q6 — never react to bot messages (our own replies included).
	if doc.get("is_bot_message") or doc.get("bot"):
		return

	# v0.1 surface scope: text messages only (files/images disclosed later).
	if (doc.get("message_type") or "Text") != "Text":
		return

	content = (doc.get("content") or "").strip()
	if not content:
		return

	bot_user = _friday_bot_user()
	if not bot_user:
		# Surface not provisioned yet (`bench friday setup-raven`).
		return

	channel = frappe.db.get_value(
		"Raven Channel", doc.channel_id, ["is_direct_message", "is_self_message"], as_dict=True
	)
	if not channel or channel.is_self_message:
		return

	if channel.is_direct_message:
		# Q3 — DMs: answer only in DM channels the bot belongs to (a DM
		# between two humans is none of our business).
		if not frappe.db.exists(
			"Raven Channel Member", {"channel_id": doc.channel_id, "user_id": bot_user}
		):
			return
	else:
		# Q3 — channels: answer only when the bot is explicitly mentioned.
		# Raven extracts mentions into the child table on validate.
		mentioned = {row.user for row in (doc.get("mentions") or [])}
		if bot_user not in mentioned:
			return

	profile = _resolve_profile()
	if not profile:
		frappe.logger("friday.raven").warning(
			"Raven message received but no agent profile resolves for the "
			"'raven' Chat Platform — run `bench friday setup-raven`."
		)
		return

	# The row IS the handoff: gateway v2's Chat Message hook routes it to
	# the dedicated friday worker (or inline fallback).
	frappe.get_doc(
		{
			"doctype": "Chat Message",
			"session_id": doc.channel_id,  # Q4 — session per channel/DM
			"platform": RAVEN_PLATFORM,
			"direction": "inbound",
			"sender_id": doc.owner,
			"agent_profile": profile,
			"content": content,
			"timestamp": frappe.utils.now_datetime(),
			"processed": 0,
		}
	).insert(ignore_permissions=True)


# ---------------------------------------------------------------------------
# OUTBOUND — Chat Message row → Raven post
# ---------------------------------------------------------------------------


def handle_outbound_to_raven(doc, method=None) -> None:
	"""`Chat Message.after_insert` hook: post raven-bound replies into Raven.

	Runs for EVERY Chat Message insert (alongside the gateway hook) and
	returns immediately unless this is an outbound row for the raven
	platform. Best-effort with a savepoint: a Raven posting failure must
	never break the gateway pipeline that wrote the row.
	"""
	if doc.direction != "outbound" or doc.platform != RAVEN_PLATFORM:
		return
	if not frappe.db.table_exists("Raven Channel"):
		return

	try:
		# Savepoint: a failed statement inside Raven's API must not poison
		# the surrounding Postgres transaction (same pattern as the War
		# Room publisher).
		frappe.db.savepoint("friday_raven_post")
		bot = frappe.get_doc("Raven Bot", FRIDAY_BOT_NAME)
		bot.send_message(
			channel_id=doc.session_id,
			text=doc.content or "",
			markdown=True,
		)
	except Exception:
		frappe.db.rollback(save_point="friday_raven_post")
		frappe.log_error(title="friday.raven outbound post failed")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _friday_bot_user() -> str | None:
	"""The Raven User id the Friday bot posts as, or None when unprovisioned."""
	if not frappe.db.exists("Raven Bot", FRIDAY_BOT_NAME):
		return None
	return frappe.db.get_value("Raven Bot", FRIDAY_BOT_NAME, "raven_user")


def _resolve_profile() -> str | None:
	"""Q4 — the agent behind the bot, via the existing platform routing."""
	from frappe.friday_core.routing.resolve import resolve_profile

	return resolve_profile(platform=RAVEN_PLATFORM)
