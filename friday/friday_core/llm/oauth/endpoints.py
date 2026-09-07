# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""
Whitelisted OAuth login endpoints for the Desk UI (design 63b-OAuth).

Thin, System-Manager-gated wrappers the LLM Provider form / setup wizard call.
They never return secrets — only an authorize URL, a status, or ``{ok}``.

Anthropic Claude (63b-1): ``start_claude_login`` → returns the authorize URL the
operator opens; ``complete_claude_login`` → takes the pasted ``code#state`` and
exchanges it. Codex device-code endpoints land in 63b-2.
"""

from __future__ import annotations

import frappe
from friday.friday_core.llm.oauth import tokens


@frappe.whitelist()
def start_claude_login(provider_name: str) -> dict:
	"""Flip the provider to Claude OAuth and return the authorize URL to open."""
	frappe.only_for("System Manager")
	doc = frappe.get_doc("LLM Provider", provider_name)
	doc.auth_mode = "oauth"
	doc.oauth_flavor = "anthropic-claude"
	doc.provider_type = "anthropic"
	doc.save(ignore_permissions=True)

	from friday.friday_core.llm.oauth import anthropic

	return {"authorize_url": anthropic.build_authorize_url(provider_name)}


@frappe.whitelist()
def complete_claude_login(provider_name: str, pasted: str) -> dict:
	"""Exchange the pasted ``code#state`` for tokens; return the new status."""
	frappe.only_for("System Manager")
	from friday.friday_core.llm.oauth import anthropic

	anthropic.exchange_code(provider_name, pasted)
	return oauth_status(provider_name)


@frappe.whitelist()
def start_codex_login(provider_name: str) -> dict:
	"""Begin the Codex device login; return the user code + verification URL."""
	frappe.only_for("System Manager")
	from friday.friday_core.llm.oauth import codex

	return codex.start_device(provider_name)


@frappe.whitelist()
def poll_codex_login(provider_name: str) -> dict:
	"""Poll the Codex device login once. ``{pending: true}`` until approved."""
	frappe.only_for("System Manager")
	from friday.friday_core.llm.oauth import codex

	return codex.poll_device(provider_name)


@frappe.whitelist()
def oauth_status(provider_name: str) -> dict:
	"""Return the provider's OAuth status (never the token itself)."""
	frappe.only_for("System Manager")
	doc = frappe.get_doc("LLM Provider", provider_name)
	return {
		"auth_mode": doc.auth_mode,
		"oauth_flavor": doc.oauth_flavor,
		"logged_in": bool(tokens.get_secret(doc, "oauth_access_token")),
		"expires_at": str(doc.oauth_expires_at) if doc.oauth_expires_at else None,
	}
