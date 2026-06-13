# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""
Provider model discovery (design 63).

Why this exists, in plain English
=================================
An ``LLM Provider`` row stores ``default_model`` as free text. There was
no way to SEE what models a provider offers — you had to know the exact
string and type it by hand, and a typo failed the first chat turn. The
user's words: "Minimax has many models, I don't have the option."

This module asks the provider's own ``/v1/models`` endpoint for the live
list, and falls back to a small curated catalog when the key is missing
or the endpoint is unreachable — so the picker is never empty.

Faithful to Hermes
==================
Ports the pattern in Hermes' ``hermes_cli/models.py``:
``provider_model_ids`` calls each provider's live ``/models`` with the
right auth header (Anthropic ``x-api-key``; OpenAI-compat Bearer) and
falls back to a static ``_PROVIDER_MODELS`` catalog. Live is always
authoritative when reachable.
"""

from __future__ import annotations

import requests

import frappe

# How long we wait on a provider's /models endpoint before falling back.
_TIMEOUT_SECONDS = 10

# Default API hosts per provider type, mirroring the provider classes in
# provider.py. Used when the LLM Provider row doesn't override base_url.
_DEFAULT_BASE_URL = {
	"openai": "https://api.openai.com",
	"anthropic": "https://api.anthropic.com",
	"minimax": "https://api.minimax.io",
	"openrouter": "https://openrouter.ai/api",
}

# Thin fallback catalogs — a handful of stable, well-known model IDs per
# provider so the picker is never empty when the live call can't run. Live
# discovery (when a valid key is present) always supersedes these.
_CATALOG = {
	"openai": ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "o1", "o1-mini"],
	"anthropic": [
		"claude-3-5-sonnet-20241022",
		"claude-3-5-haiku-20241022",
		"claude-3-opus-20240229",
	],
	"minimax": ["MiniMax-M2", "MiniMax-Text-01", "abab6.5s-chat"],
	"openrouter": [
		"anthropic/claude-3.5-sonnet",
		"openai/gpt-4o",
		"google/gemini-pro-1.5",
	],
}


def fetch_models(provider_type: str, api_key: str, base_url: str | None) -> dict:
	"""
	Return the model list for a provider.

	Returns ``{"models": [...], "source": "live"|"catalog", "error": str|None}``.

	- ``live``: the provider's ``/v1/models`` endpoint answered; ``models``
	  is the real, current list.
	- ``catalog``: live couldn't run (no key, network error, non-200,
	  unsupported); ``models`` is the curated fallback and ``error`` says why.
	- unknown provider type: ``models=[]`` with an ``error``.
	"""
	provider_type = (provider_type or "").strip().lower()
	if provider_type not in _DEFAULT_BASE_URL:
		return {"models": [], "source": "catalog", "error": f"unknown provider type {provider_type!r}"}

	base = (base_url or _DEFAULT_BASE_URL[provider_type]).rstrip("/")

	if not api_key:
		return {
			"models": _CATALOG.get(provider_type, []),
			"source": "catalog",
			"error": "no api key configured — showing the built-in catalog",
		}

	try:
		url = f"{base}/v1/models"
		if provider_type == "anthropic":
			headers = {"x-api-key": api_key, "anthropic-version": "2023-06-01"}
		else:
			headers = {"Authorization": f"Bearer {api_key}"}

		resp = requests.get(url, headers=headers, timeout=_TIMEOUT_SECONDS)
		if resp.status_code != 200:
			return {
				"models": _CATALOG.get(provider_type, []),
				"source": "catalog",
				"error": f"{url} returned {resp.status_code} — showing the built-in catalog",
			}

		models = _parse_model_ids(resp.json())
		if not models:
			return {
				"models": _CATALOG.get(provider_type, []),
				"source": "catalog",
				"error": "endpoint returned no models — showing the built-in catalog",
			}
		return {"models": models, "source": "live", "error": None}
	except Exception as exc:
		return {
			"models": _CATALOG.get(provider_type, []),
			"source": "catalog",
			"error": f"{type(exc).__name__}: {exc} — showing the built-in catalog",
		}


def _parse_model_ids(payload: dict) -> list[str]:
	"""Pull model IDs out of a /v1/models response.

	Both OpenAI and Anthropic return ``{"data": [{"id": "..."}, ...]}``;
	OpenRouter the same. We read ``data[].id``, skip blanks, preserve order.
	"""
	data = (payload or {}).get("data") or []
	ids = []
	for row in data:
		mid = (row or {}).get("id")
		if mid:
			ids.append(mid)
	return ids


@frappe.whitelist()
def list_models(provider_name: str) -> dict:
	"""
	Whitelisted: return the model list for an ``LLM Provider`` row.

	Resolves the row's ``provider_type``, ``base_url``, and (decrypted)
	``api_key``, then delegates to :func:`fetch_models`. The Desk model
	picker calls this so the operator chooses from the real list instead
	of typing a model string by hand.
	"""
	doc = frappe.get_doc("LLM Provider", provider_name)

	# get_password raises when the encrypted field was never set — treat
	# that as "no key" (catalog fallback) rather than an error.
	try:
		api_key = doc.get_password("api_key") or ""
	except Exception:
		api_key = ""

	result = fetch_models(doc.provider_type, api_key, doc.base_url or "")
	result["provider"] = provider_name
	result["provider_type"] = doc.provider_type
	return result
