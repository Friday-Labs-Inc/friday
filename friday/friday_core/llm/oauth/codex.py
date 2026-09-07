# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""
OpenAI Codex OAuth — the device-code login (design 63b-2).

The ChatGPT/Codex subscription login. This is OpenAI's *proprietary* device-code
chain (not RFC 8628): request a user code, the operator enters it at
``auth.openai.com/codex/device``, we poll until approved, then exchange the
returned authorization code (with the **server-supplied** PKCE verifier) for
tokens. The access token is a JWT — its ``exp`` gives expiry and the
``chatgpt_account_id`` claim gives the account header inference needs.

The Desk UI does the waiting: it calls ``poll_device`` on an interval; each call
does exactly ONE server poll and returns ``{pending: true}`` until approved, so
we never block a worker.

Refresh tokens are single-use (rotation). A ``refresh_token_reused`` (409) means
another client consumed it — we fail loud and require re-login, never a silent
stale token.
"""

from __future__ import annotations

import base64
import json
import time

import requests

import frappe
from friday.friday_core.llm.oauth import tokens
from friday.friday_core.llm.oauth.tokens import OAuthError
from frappe.utils import add_to_date, now_datetime

CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
DEVICE_USERCODE_URL = "https://auth.openai.com/api/accounts/deviceauth/usercode"
DEVICE_TOKEN_URL = "https://auth.openai.com/api/accounts/deviceauth/token"
OAUTH_TOKEN_URL = "https://auth.openai.com/oauth/token"
DEVICE_REDIRECT_URI = "https://auth.openai.com/deviceauth/callback"
VERIFICATION_URL = "https://auth.openai.com/codex/device"
DEFAULT_BASE_URL = "https://chatgpt.com/backend-api/codex"
# The access-token JWT nests the account id under this claim object.
_AUTH_CLAIM = "https://api.openai.com/auth"
_TIMEOUT = 30


def jwt_claims(token: str) -> dict:
	"""Decode a JWT payload WITHOUT verification (it's our own token) — for the
	``exp`` and account-id claims. Returns {} on any malformed input."""
	try:
		payload = token.split(".")[1]
		payload += "=" * (-len(payload) % 4)  # restore base64 padding
		return json.loads(base64.urlsafe_b64decode(payload))
	except Exception:
		return {}


def start_device(provider_name: str) -> dict:
	"""Begin the device login: get a user code, persist the device id transiently."""
	resp = requests.post(DEVICE_USERCODE_URL, json={"client_id": CLIENT_ID}, timeout=_TIMEOUT)
	if resp.status_code != 200:
		raise OAuthError(f"Codex device-auth request failed (HTTP {resp.status_code}).")
	data = resp.json()

	doc = frappe.get_doc("LLM Provider", provider_name)
	doc.auth_mode = "oauth"
	doc.oauth_flavor = "openai-codex"
	doc.provider_type = "openai"
	doc.oauth_device_id = data.get("device_auth_id")
	doc.oauth_state = data.get("user_code")  # reuse the transient slot for the user code
	doc.save(ignore_permissions=True)

	return {
		"user_code": data.get("user_code"),
		"verification_url": VERIFICATION_URL,
		"interval": int(data.get("interval") or 5),
	}


def poll_device(provider_name: str) -> dict:
	"""Poll once. ``{pending: true}`` until approved, then exchange + store."""
	doc = frappe.get_doc("LLM Provider", provider_name)
	device_id = doc.oauth_device_id
	user_code = doc.oauth_state
	if not device_id:
		raise OAuthError("No device login in progress — start the Codex login again.")

	resp = requests.post(
		DEVICE_TOKEN_URL,
		json={"device_auth_id": device_id, "user_code": user_code},
		timeout=_TIMEOUT,
	)
	if resp.status_code in (403, 404):
		return {"pending": True}
	if resp.status_code != 200:
		raise OAuthError(f"Codex device poll failed (HTTP {resp.status_code}).")

	data = resp.json()
	token_data = _exchange_code(data["authorization_code"], data["code_verifier"])
	_store(provider_name, token_data)
	return {"pending": False, "logged_in": True}


def refresh(provider_name: str) -> None:
	"""Rotation-aware refresh. A reused (409) token forces re-login (loud)."""
	doc = frappe.get_doc("LLM Provider", provider_name)
	refresh_token = tokens.get_secret(doc, "oauth_refresh_token")
	if not refresh_token:
		raise OAuthError(f"LLM Provider {provider_name!r} has no Codex refresh token — re-login required.")

	resp = requests.post(
		OAUTH_TOKEN_URL,
		data={"grant_type": "refresh_token", "refresh_token": refresh_token, "client_id": CLIENT_ID},
		timeout=_TIMEOUT,
	)
	if resp.status_code == 409:
		raise OAuthError("Codex refresh token was already used elsewhere — re-login required.")
	if resp.status_code != 200:
		raise OAuthError(f"Codex token refresh failed (HTTP {resp.status_code}).")
	_store(provider_name, resp.json())


def _exchange_code(code: str, code_verifier: str) -> dict:
	resp = requests.post(
		OAUTH_TOKEN_URL,
		data={
			"grant_type": "authorization_code",
			"code": code,
			"redirect_uri": DEVICE_REDIRECT_URI,
			"client_id": CLIENT_ID,
			"code_verifier": code_verifier,
		},
		timeout=_TIMEOUT,
	)
	if resp.status_code != 200:
		raise OAuthError(f"Codex code exchange failed (HTTP {resp.status_code}).")
	return resp.json()


def _store(provider_name: str, token_data: dict) -> None:
	access = token_data.get("access_token")
	if not access:
		raise OAuthError("Codex token response had no access_token.")
	claims = jwt_claims(access)
	exp = claims.get("exp")
	account_id = (claims.get(_AUTH_CLAIM) or {}).get("chatgpt_account_id")
	# Codex tokens carry no expires_in — derive remaining life from the JWT exp.
	expires_at = add_to_date(now_datetime(), seconds=max(0, int(exp - time.time()))) if exp else None
	tokens.store_tokens(
		provider_name,
		access_token=access,
		refresh_token=token_data.get("refresh_token"),
		expires_at=expires_at,
		account_id=account_id,
	)
