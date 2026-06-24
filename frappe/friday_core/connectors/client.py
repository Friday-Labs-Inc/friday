# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt

"""Generic outbound client for `system` connectors (Design 81a).

PLAIN ENGLISH
=============
A typed, never-raises POST to an external system's Frappe-style API, with auth
sourced from the Connector row's encrypted secrets (token key:secret). This is
the generalisation of the old `randompack_client.send` — the transport is
generic; the connector's specific endpoint names + payload shapes stay in its
domain adapter (which resolves the dotted `path` and calls us).

RELIABILITY CONTRACT (ported verbatim): `send()` never raises into a caller's
turn — failures log and return None. Calls that MUST happen eventually go
through `enqueue_send()` (the `friday` queue retries).
"""

from __future__ import annotations

import requests

import frappe

_TIMEOUT_SECONDS = 20


def _connector(connector_name: str):
	"""Return the enabled Connector doc, or None if disabled/missing."""
	if not frappe.db.exists("Connector", connector_name):
		return None
	connector = frappe.get_cached_doc("Connector", connector_name)
	if not connector.enabled:
		return None
	return connector


def _headers(connector) -> dict:
	# get_password RAISES (not None) when the encrypted field was never set —
	# an unconfigured secret must mean "send unauthenticated", not "crash".
	try:
		secret = connector.get_password("api_secret") or ""
	except Exception:
		secret = ""
	return {"Authorization": f"token {connector.api_key}:{secret}"}


def send(connector_name: str, path: str, payload: dict, files: dict | None = None) -> dict | None:
	"""POST one external API call through `connector_name`. NEVER raises.

	`path` is the fully-resolved dotted endpoint (the domain adapter handles any
	module prefixing). Full URL: {api_base_url}/api/method/{path}.
	"""
	connector = _connector(connector_name)
	if connector is None:
		frappe.logger("friday.connector").warning(
			f"Connector {connector_name!r} disabled/missing — dropped outbound {path!r}"
		)
		return None
	url = f"{(connector.api_base_url or '').rstrip('/')}/api/method/{path}"
	try:
		if files:
			response = requests.post(
				url, data=payload, files=files, headers=_headers(connector), timeout=_TIMEOUT_SECONDS
			)
		else:
			response = requests.post(url, json=payload, headers=_headers(connector), timeout=_TIMEOUT_SECONDS)
		response.raise_for_status()
		return response.json()
	except Exception as exc:
		frappe.logger("friday.connector").warning(
			f"Outbound {path!r} on {connector_name!r} failed: {type(exc).__name__}"
		)
		frappe.log_error(title=f"friday.connector outbound failed: {connector_name}/{path}")
		return None


def enqueue_send(connector_name: str, path: str, payload: dict) -> None:
	"""Fire-and-forget with the queue's retry semantics (for must-deliver calls)."""
	frappe.enqueue(
		"frappe.friday_core.connectors.client.send",
		connector_name=connector_name,
		path=path,
		payload=payload,
		queue="friday",
		timeout=120,
		enqueue_after_commit=True,
	)
