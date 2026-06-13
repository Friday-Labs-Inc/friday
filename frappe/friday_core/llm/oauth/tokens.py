# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""
Shared OAuth token store + freshness for LLM Provider rows (design 63b-OAuth).

Tokens live in encrypted Password fields on the ``LLM Provider`` row
(``oauth_access_token`` / ``oauth_refresh_token``), with ``oauth_expires_at`` as
a plain Datetime. This module is the one place that:

- stores tokens after a login/refresh (and clears the transient PKCE/state),
- decides when an access token is *expiring* (a 120s skew, matching Hermes),
- hands the provider layer a guaranteed-fresh access token, refreshing in-line
  via the right flavour module if the current one is about to expire.

Refresh failures raise ``OAuthError`` — they are surfaced loud (the caller logs
+ marks the provider needing re-login), never swallowed into a stale token.
"""

from __future__ import annotations

import frappe
from frappe.utils import add_to_date, get_datetime, now_datetime

# Refresh when the access token has <= this many seconds of life left. 120s
# matches Hermes' CODEX/Anthropic skew so a token is never used on its last legs.
REFRESH_SKEW_SECONDS = 120


class OAuthError(Exception):
	"""An OAuth login/refresh/use failure. A real class so it raises cleanly
	even when ``frappe`` is mocked in unit tests (unlike ``frappe.throw``)."""


def get_secret(doc, fieldname: str) -> str:
	"""Decrypt a Password field, returning '' when unset (never raising)."""
	try:
		return doc.get_password(fieldname, raise_exception=False) or ""
	except Exception:
		return ""


def is_expiring(expires_at, skew: int = REFRESH_SKEW_SECONDS) -> bool:
	"""True if the access token is unset or within ``skew`` seconds of expiry.

	An unknown/blank expiry is treated as expiring, so we always refresh-or-verify
	rather than gamble on a token we can't date.
	"""
	if not expires_at:
		return True
	cutoff = add_to_date(now_datetime(), seconds=skew)
	return get_datetime(expires_at) <= get_datetime(cutoff)


def store_tokens(
	provider_name: str,
	*,
	access_token: str,
	refresh_token: str | None = None,
	expires_at=None,
	account_id: str | None = None,
) -> None:
	"""Persist tokens onto the provider row and clear the transient login state.

	Password fields are encrypted by Frappe on save. The PKCE verifier, CSRF
	state, and device id are wiped here — they only live between starting and
	completing a login.
	"""
	doc = frappe.get_doc("LLM Provider", provider_name)
	doc.oauth_access_token = access_token
	if refresh_token:
		doc.oauth_refresh_token = refresh_token
	if expires_at is not None:
		doc.oauth_expires_at = expires_at
	if account_id is not None:
		doc.oauth_account_id = account_id
	# Clear transient login state — it must never linger after exchange.
	doc.oauth_pkce_verifier = None
	doc.oauth_state = None
	doc.oauth_device_id = None
	doc.save(ignore_permissions=True)


def get_fresh_access_token(provider_row) -> str:
	"""Return a valid access token for the provider, refreshing if it's expiring.

	``provider_row`` may be a row dict (with ``name``) or a provider name string.
	Raises ``OAuthError`` if there is no token after a refresh attempt.
	"""
	name = provider_row["name"] if isinstance(provider_row, dict) else provider_row
	doc = frappe.get_doc("LLM Provider", name)

	if is_expiring(doc.oauth_expires_at):
		_refresh_for_flavor(doc)
		doc = frappe.get_doc("LLM Provider", name)

	token = get_secret(doc, "oauth_access_token")
	if not token:
		raise OAuthError(f"LLM Provider {name!r} has no OAuth access token — log in first.")
	return token


def _refresh_for_flavor(doc) -> None:
	"""Dispatch a refresh to the provider's OAuth flavour module (lazy import)."""
	flavor = doc.oauth_flavor
	if flavor == "anthropic-claude":
		from frappe.friday_core.llm.oauth import anthropic

		anthropic.refresh(doc.name)
	elif flavor == "openai-codex":
		from frappe.friday_core.llm.oauth import codex

		codex.refresh(doc.name)
	else:
		raise OAuthError(f"LLM Provider {doc.name!r} has unknown oauth_flavor {flavor!r}.")
