# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt

"""
One-step provisioning for a working agent — the `hermes setup` equivalent.

PLAIN ENGLISH
=============

In Hermes you run `hermes setup` and it writes your model/provider config to a
file. Friday keeps the same information as **database records** (DocTypes), so
"setup" means creating two rows:

  1. an **LLM Provider** — which model API to call, with the API key stored in
     Frappe's encrypted `Password` field (never on disk in plain text), and
  2. an **Agent Profile** — the agent's identity (its provider + system prompt),
     which `bench friday chat` then talks to.

These functions are small and idempotent (re-running updates the existing rows),
and they take the API key as a plain argument — the *caller* (the CLI command)
is responsible for getting it from a hidden prompt or an env var, never a code
literal. That keeps secrets out of source control entirely.

SECURITY
========
`api_key` lands only in `LLM Provider.api_key` (a `Password` field, encrypted at
rest by Frappe). It is never logged, echoed, or written to a tracked file.
"""

from __future__ import annotations

import frappe
from frappe.friday_core.doctype.agent_settings.agent_settings import (
	SETTINGS_DOCTYPE as _SETTINGS,
)
from frappe.friday_core.doctype.agent_settings.agent_settings import (
	SETTINGS_NAME as _SETTINGS_NAME,
)

# Sensible default model per provider, so `friday setup --provider-type X` works
# with no extra flags.
DEFAULT_MODELS = {
	"minimax": "MiniMax-M2",
	"openai": "gpt-4o",
	"anthropic": "claude-3-5-sonnet-20241022",
}

_DEFAULT_SYSTEM_PROMPT = (
	"You are Friday, a governed AI agent running inside this organisation's "
	"system. Be concise and helpful. Use a tool only when it is the right way "
	"to act; otherwise answer directly."
)


def provision_provider(
	*,
	provider_name: str,
	provider_type: str,
	api_key: str,
	default_model: str,
	base_url: str | None = None,
) -> str:
	"""Create or update an LLM Provider row; return its name. Idempotent.

	`api_key` is written to the encrypted `Password` field — never elsewhere.
	"""
	if frappe.db.exists("LLM Provider", provider_name):
		doc = frappe.get_doc("LLM Provider", provider_name)
	else:
		doc = frappe.new_doc("LLM Provider")
		doc.provider_name = provider_name

	doc.provider_type = provider_type
	doc.default_model = default_model
	if base_url:
		doc.base_url = base_url
	doc.is_active = 1
	doc.api_key = api_key  # Password field — Frappe encrypts at rest.
	doc.save(ignore_permissions=True)
	return doc.name


def provision_profile(
	*,
	profile_name: str,
	provider_name: str,
	system_prompt: str | None = None,
	model_name: str | None = None,
) -> str:
	"""Create or update an Agent Profile linked to a provider; return its name."""
	if frappe.db.exists("Agent Profile", profile_name):
		doc = frappe.get_doc("Agent Profile", profile_name)
	else:
		doc = frappe.new_doc("Agent Profile")
		doc.profile_name = profile_name

	doc.model_provider = provider_name
	if model_name:
		doc.model_name = model_name
	doc.system_prompt = system_prompt or _DEFAULT_SYSTEM_PROMPT
	doc.status = "Active"
	doc.save(ignore_permissions=True)
	return doc.name


def set_default_provider(provider_name: str) -> None:
	"""Point Agent Settings.default_provider at the provider (best-effort)."""
	if frappe.db.exists(_SETTINGS, {"name": _SETTINGS_NAME}):
		frappe.db.set_value(_SETTINGS, _SETTINGS_NAME, "default_provider", provider_name)


def run_setup(
	*,
	provider_name: str,
	provider_type: str,
	api_key: str,
	default_model: str,
	profile_name: str,
	base_url: str | None = None,
	system_prompt: str | None = None,
	make_default: bool = True,
) -> dict:
	"""Provision a provider + profile (+ default) in one call. Returns a summary.

	The end state: `bench friday chat --profile <profile_name>` talks to a live
	agent backed by the configured model.
	"""
	provider = provision_provider(
		provider_name=provider_name,
		provider_type=provider_type,
		api_key=api_key,
		default_model=default_model,
		base_url=base_url,
	)
	profile = provision_profile(
		profile_name=profile_name,
		provider_name=provider,
		system_prompt=system_prompt,
	)
	if make_default:
		set_default_provider(provider)
	frappe.db.commit()
	return {"provider": provider, "profile": profile, "model": default_model}
