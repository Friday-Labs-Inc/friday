# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""
Anthropic Claude OAuth — the manual-paste PKCE login (design 63b-OAuth).

This is the Claude Pro/Max subscription login (the same public OAuth protocol
Claude Code uses). It is **out-of-band**: there is no callback route. We build a
``claude.ai/oauth/authorize`` URL, the operator approves in the browser,
Anthropic's own page shows a ``code#state`` string, and the operator pastes it
back into Desk. We validate the CSRF ``state``, exchange the code (with the
stored PKCE verifier) for tokens, and persist them encrypted.

Protocol constants are the literal public values (verified against the Claude
Code / Hermes implementation); the client is public (no secret).
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from urllib.parse import urlencode

import requests

import frappe
from friday.friday_core.llm.oauth import tokens
from friday.friday_core.llm.oauth.tokens import OAuthError
from frappe.utils import add_to_date, now_datetime

CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
AUTHORIZE_URL = "https://claude.ai/oauth/authorize"
# Primary then fallback host (both seen accepting the token grant).
TOKEN_URLS = (
	"https://console.anthropic.com/v1/oauth/token",
	"https://platform.claude.com/v1/oauth/token",
)
REDIRECT_URI = "https://console.anthropic.com/oauth/code/callback"
SCOPES = "org:create_api_key user:profile user:inference"
_TIMEOUT = 30


def _b64url(raw: bytes) -> str:
	"""URL-safe base64, no padding (the PKCE encoding)."""
	return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def code_challenge(verifier: str) -> str:
	"""S256 PKCE challenge for a verifier (pure; unit-tested with a known vector)."""
	return _b64url(hashlib.sha256(verifier.encode()).digest())


def build_authorize_url(provider_name: str) -> str:
	"""Start a login: mint PKCE + state, persist them transiently, return the URL."""
	verifier = _b64url(secrets.token_bytes(32))
	state = secrets.token_urlsafe(32)

	doc = frappe.get_doc("LLM Provider", provider_name)
	doc.oauth_pkce_verifier = verifier
	doc.oauth_state = state
	doc.save(ignore_permissions=True)

	params = {
		"code": "true",
		"client_id": CLIENT_ID,
		"response_type": "code",
		"redirect_uri": REDIRECT_URI,
		"scope": SCOPES,
		"code_challenge": code_challenge(verifier),
		"code_challenge_method": "S256",
		"state": state,
	}
	return f"{AUTHORIZE_URL}?{urlencode(params)}"


def exchange_code(provider_name: str, pasted: str) -> dict:
	"""Complete a login: validate state, exchange the code, store tokens."""
	doc = frappe.get_doc("LLM Provider", provider_name)
	verifier = tokens.get_secret(doc, "oauth_pkce_verifier")
	expected_state = doc.oauth_state

	code, _, received_state = (pasted or "").strip().partition("#")
	if not code:
		raise OAuthError("No authorization code was provided.")
	# CSRF: if the paste carried a state, it MUST match the one we issued.
	if received_state and expected_state and received_state != expected_state:
		raise OAuthError("OAuth state mismatch — aborting (possible CSRF / stale paste).")
	if not verifier:
		raise OAuthError("No PKCE verifier on file — start the login again.")

	data = _post_token(
		{
			"grant_type": "authorization_code",
			"client_id": CLIENT_ID,
			"code": code,
			"state": received_state or expected_state,
			"redirect_uri": REDIRECT_URI,
			"code_verifier": verifier,
		},
		json_body=True,
	)
	_store_from_response(provider_name, data)
	return {"ok": True}


def refresh(provider_name: str) -> None:
	"""Renew the access token using the refresh token (form-encoded grant)."""
	doc = frappe.get_doc("LLM Provider", provider_name)
	refresh_token = tokens.get_secret(doc, "oauth_refresh_token")
	if not refresh_token:
		raise OAuthError(f"LLM Provider {provider_name!r} has no refresh token — re-login required.")

	data = _post_token(
		{"grant_type": "refresh_token", "refresh_token": refresh_token, "client_id": CLIENT_ID},
		json_body=False,
	)
	_store_from_response(provider_name, data)


def _store_from_response(provider_name: str, data: dict) -> None:
	access = data.get("access_token")
	if not access:
		raise OAuthError(f"Anthropic token response had no access_token (keys={sorted(data.keys())}).")
	expires_in = data.get("expires_in")
	expires_at = add_to_date(now_datetime(), seconds=int(expires_in)) if expires_in else None
	tokens.store_tokens(
		provider_name,
		access_token=access,
		refresh_token=data.get("refresh_token"),
		expires_at=expires_at,
	)


def _post_token(body: dict, *, json_body: bool) -> dict:
	"""POST the token request, trying the primary then fallback host."""
	last_err = None
	for url in TOKEN_URLS:
		try:
			if json_body:
				resp = requests.post(url, json=body, timeout=_TIMEOUT)
			else:
				resp = requests.post(url, data=body, timeout=_TIMEOUT)
			if resp.status_code == 200:
				return resp.json()
			# Don't leak the body's secrets — status + a short, safe slice only.
			last_err = f"HTTP {resp.status_code}"
		except Exception as exc:  # network/timeout — try the next host
			last_err = type(exc).__name__
	raise OAuthError(f"Anthropic OAuth token request failed ({last_err}).")
