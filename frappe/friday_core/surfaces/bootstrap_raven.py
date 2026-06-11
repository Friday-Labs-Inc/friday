# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt

"""
One-command provisioning for the Raven surface (design 58, Q5).

Idempotently seeds everything the surface needs — run AFTER Raven is
installed on the site:

  1. The "Friday" Raven Bot (Raven auto-creates/links its bot Raven User).
  2. The FRIDAY_WAR_ROOM channel — the existing warroom publisher activates
     by itself the moment this exists (zero new code), so task/delegation
     posts start appearing.
  3. Bot membership in the War Room.
  4. The `raven` Chat Platform row: dispatch_mode "async" (the dedicated
     friday worker) + default_agent_profile (the agent behind the bot).

    bench --site friday.localhost execute \\
        frappe.friday_core.surfaces.bootstrap_raven.provision
"""

from __future__ import annotations

import frappe

from frappe.friday_core.surfaces.raven_adapter import FRIDAY_BOT_NAME, RAVEN_PLATFORM

WAR_ROOM_CHANNEL_NAME = "FRIDAY_WAR_ROOM"  # must match warroom/publisher.CHANNEL_NAME
WORKSPACE_NAME = "Friday"


def provision(profile_name: str = "Friday") -> dict:
	"""Seed workspace, bot, War Room, membership, and the platform row. Idempotent."""
	if not frappe.db.table_exists("Raven Channel"):
		frappe.throw(
			frappe._(
				"Raven is not installed on this site. Install it first:\n"
				"  bench get-app https://github.com/The-Commit-Company/raven\n"
				"  bench --site {0} install-app raven\n"
				"then re-run this command."
			).format(frappe.local.site)
		)

	# Raven's channel after_insert enrolls frappe.session.user as a member, so
	# the operator running this command must be a Raven User first.
	_ensure_raven_user(frappe.session.user)
	workspace = _ensure_workspace()
	bot_user = _ensure_bot()
	channel_id = _ensure_war_room(workspace)
	_ensure_membership(channel_id, bot_user)
	_ensure_platform_row(profile_name)

	# Manual commit is required: provision() runs via `bench execute` (no
	# request lifecycle to commit for us) and must persist before returning.
	frappe.db.commit()  # nosemgrep: frappe-semgrep-rules.rules.frappe-manual-commit

	summary = {
		"bot": FRIDAY_BOT_NAME,
		"bot_user": bot_user,
		"war_room": channel_id,
		"platform": RAVEN_PLATFORM,
		"profile": profile_name,
	}
	print(f"✓ Raven surface provisioned: {summary}")
	return summary


def _ensure_bot() -> str:
	"""Create the Friday Raven Bot; return its Raven User id."""
	if not frappe.db.exists("Raven Bot", FRIDAY_BOT_NAME):
		frappe.get_doc(
			{
				"doctype": "Raven Bot",
				"bot_name": FRIDAY_BOT_NAME,
				"description": "Friday — the governed agent. DM me or @mention me in a channel.",
			}
		).insert(ignore_permissions=True)

	bot_user = frappe.db.get_value("Raven Bot", FRIDAY_BOT_NAME, "raven_user")
	if not bot_user:
		# Raven normally creates/links the bot user in its own hooks; if this
		# Raven version didn't, create it explicitly and link it.
		user = frappe.get_doc(
			{
				"doctype": "Raven User",
				"full_name": FRIDAY_BOT_NAME,
				"type": "Bot",
				"bot": FRIDAY_BOT_NAME,
			}
		)
		user.insert(ignore_permissions=True)
		frappe.db.set_value("Raven Bot", FRIDAY_BOT_NAME, "raven_user", user.name)
		bot_user = user.name
	return bot_user


def _ensure_raven_user(user_id: str) -> str | None:
	"""Enroll a Frappe User as a Raven User (idempotent). Returns its name.

	Skips the Guest/empty session. Raven normally enrolls users via its own
	UI; for headless provisioning we enroll the operator so channel creation
	(which auto-adds the creator as a member) succeeds.
	"""
	if not user_id or user_id == "Guest":
		return None
	existing = frappe.db.get_value("Raven User", {"user": user_id}, "name")
	if existing:
		return existing
	ru = frappe.get_doc({"doctype": "Raven User", "user": user_id, "type": "User"})
	ru.insert(ignore_permissions=True)
	return ru.name


def _ensure_workspace() -> str:
	"""Create the 'Friday' Raven Workspace if missing; return its name.

	Newer Raven versions require every non-DM channel to belong to a
	workspace (the channel's autoname is `<workspace>-<channel_name>`).
	"""
	if frappe.db.exists("Raven Workspace", WORKSPACE_NAME):
		return WORKSPACE_NAME
	ws = frappe.get_doc(
		{
			"doctype": "Raven Workspace",
			"workspace_name": WORKSPACE_NAME,
			"type": "Public",
			"description": "Friday's governed-agent workspace.",
		}
	)
	ws.insert(ignore_permissions=True)
	return ws.name


def _ensure_war_room(workspace: str) -> str:
	"""Create the FRIDAY_WAR_ROOM channel (open) if missing; return its id.

	Raven LOWERCASES channel_name on save (stored as `friday_war_room`), so
	idempotency and lookups must use the lowercased slug — not the constant.
	"""
	slug = WAR_ROOM_CHANNEL_NAME.strip().lower().replace(" ", "-")
	existing = frappe.db.get_value(
		"Raven Channel", {"channel_name": slug, "workspace": workspace}, "name"
	)
	if existing:
		return existing
	channel = frappe.get_doc(
		{
			"doctype": "Raven Channel",
			"channel_name": WAR_ROOM_CHANNEL_NAME,
			"channel_description": "Friday ops: task, delegation, and failure updates.",
			"type": "Open",
			"workspace": workspace,
		}
	)
	channel.insert(ignore_permissions=True)
	return channel.name


def _ensure_membership(channel_id: str, bot_user: str) -> None:
	if frappe.db.exists("Raven Channel Member", {"channel_id": channel_id, "user_id": bot_user}):
		return
	frappe.get_doc(
		{
			"doctype": "Raven Channel Member",
			"channel_id": channel_id,
			"user_id": bot_user,
		}
	).insert(ignore_permissions=True)


def _ensure_platform_row(profile_name: str) -> None:
	if frappe.db.exists("Chat Platform", RAVEN_PLATFORM):
		frappe.db.set_value(
			"Chat Platform",
			RAVEN_PLATFORM,
			{"default_agent_profile": profile_name, "dispatch_mode": "async", "enabled": 1},
			update_modified=False,
		)
		return
	frappe.get_doc(
		{
			"doctype": "Chat Platform",
			"platform_name": RAVEN_PLATFORM,
			"adapter_module": "frappe.friday_core.surfaces.raven_adapter",
			"enabled": 1,
			"dispatch_mode": "async",  # the dedicated friday worker (design 55)
			"default_agent_profile": profile_name,
			"batch_idle_ms": 0,
		}
	).insert(ignore_permissions=True)
