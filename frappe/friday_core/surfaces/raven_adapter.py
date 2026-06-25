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

import re

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
		if not frappe.db.exists("Raven Channel Member", {"channel_id": doc.channel_id, "user_id": bot_user}):
			return
	else:
		# Q3 — channels: answer only when the bot is explicitly mentioned.
		# Raven extracts mentions into the child table on validate.
		mentioned = {row.user for row in (doc.get("mentions") or [])}
		if bot_user not in mentioned:
			return

	# Design 82 — slash commands are caught at the edge, BEFORE a conversational
	# row is written. A command never reaches run_turn; it is dispatched here and
	# its reply posted straight back into the channel.
	#
	# In a CHANNEL the bot must be @mentioned (above), so Raven stores the content
	# as e.g. "@Friday /help" — which does NOT start with "/", so is_command() would
	# miss it and every operator command (/approve, /deny, /stop, /steer) would be
	# unreachable from a channel. Strip the leading bot mention before the command
	# check so commands work identically in channels and DMs (DM content is already
	# bare "/help", so the strip is a no-op there). The strip feeds command
	# detection only; the conversational path keeps the original content.
	from frappe.friday_core.gateway.commands import is_command

	# DMs need no strip (content is already bare "/help"); only channels carry the
	# required leading mention, so only they pay for the lookup + strip.
	command_content = content
	if not channel.is_direct_message:
		bot_label = frappe.db.get_value("Raven User", bot_user, "full_name") or ""
		command_content = _strip_leading_mention(content, bot_label)

	if is_command(command_content):
		_handle_command(doc.channel_id, doc.owner, command_content)
		return

	profile = _resolve_profile(doc.channel_id)
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
	# Mirror rows are recorded for the agent's own history only — never re-posted
	# to the channel (the actual content already went out out-of-band). See
	# gateway/mirror.py.
	if doc.is_mirror:
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
# Commands (Design 82)
# ---------------------------------------------------------------------------


def _handle_command(channel_id: str, owner: str, content: str) -> None:
	"""Dispatch a slash command and audit it as two `is_command` rows.

	The command and its reply are recorded as Chat Message rows so governance
	actions (e.g. `/approve`) leave a trail — but both carry `is_command=1`, so
	the gateway hook skips them (no conversational turn) and the reply row is
	posted into Raven by the normal `handle_outbound_to_raven` path.
	"""
	from frappe.friday_core.gateway.commands import dispatch_command

	result = dispatch_command(platform=RAVEN_PLATFORM, session_id=channel_id, user=owner, raw=content)

	# Audit the command itself (inbound, already handled).
	_insert_command_row(channel_id, sender_id=owner, content=content, direction="inbound")
	# The reply (outbound) — its insert fires handle_outbound_to_raven, which
	# posts it into the channel.
	_insert_command_row(channel_id, sender_id="system", content=result.reply, direction="outbound")


def _insert_command_row(channel_id: str, sender_id: str, content: str, direction: str) -> None:
	"""Insert one `is_command=1` Chat Message row (processed, never run)."""
	frappe.get_doc(
		{
			"doctype": "Chat Message",
			"session_id": channel_id,
			"platform": RAVEN_PLATFORM,
			"direction": direction,
			"sender_id": sender_id,
			"content": content,
			"timestamp": frappe.utils.now_datetime(),
			"processed": 1,
			"is_command": 1,
		}
	).insert(ignore_permissions=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _strip_leading_mention(content: str, label: str | None) -> str:
	"""Drop a leading "@<bot>" mention so a channel "/command" is detected.

	Pure (no DB) and used only for command detection. Tries the bot's exact
	display `label` first (case-insensitive), then falls back to a generic leading
	"@token" — so it still works if the label is unknown or renamed. A message with
	no leading mention (every DM) is returned unchanged.

	    "@Friday /help"  → "/help"
	    "@Friday hello"  → "hello"   (is_command() is then False → conversational)
	    "/help"          → "/help"   (no-op)
	"""
	if label:
		stripped = re.sub(rf"^\s*@{re.escape(label)}\s+", "", content, count=1, flags=re.IGNORECASE)
		if stripped != content:
			return stripped
	return re.sub(r"^\s*@\S+\s+", "", content, count=1)


def _friday_bot_user() -> str | None:
	"""The Raven User id the Friday bot posts as, or None when unprovisioned."""
	if not frappe.db.exists("Raven Bot", FRIDAY_BOT_NAME):
		return None
	return frappe.db.get_value("Raven Bot", FRIDAY_BOT_NAME, "raven_user")


def _resolve_profile(channel_id: str | None = None) -> str | None:
	"""The agent behind the bot for this message.

	The project's lead when this is a project room, else the platform default
	(Q4 + Design 73, Slice 3). `resolve_profile` maps the channel id to the
	project; passing it is what makes a project channel reach its own commander.
	"""
	from frappe.friday_core.routing.resolve import resolve_profile

	return resolve_profile(platform=RAVEN_PLATFORM, chat_id=channel_id)
