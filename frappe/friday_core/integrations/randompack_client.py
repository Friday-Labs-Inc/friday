# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt

"""
Outbound client for the RandomPack backend (design 60a, Q5).

The five calls of the locked contract:
  - update_task_progress  (now heartbeat-safe: optional progress 0–100 that
    never touches status unless one is explicitly passed)
  - attach_deliverable    (two-step: multipart to Frappe-native upload_file
    with our API token → pass the returned file_url)
  - post_project_note
  - request_gate_open     (signal-only; humans own the gate)
  - read endpoints        (project state / comments — rehydration w/o replay)

RELIABILITY CONTRACT: `send()` never raises into a caller's turn — failures
log and return None (the gateway/War Room pattern). Calls that MUST happen
eventually should go through `enqueue_send()` (the friday queue retries are
the backend's replay-mirror on our side). Needs-human is signalled as status
"Pending Review" + a note carrying the Issue reference — never "failed".

Auth: Frappe token auth (`Authorization: token key:secret`) — the backend's
"Friday Integration" API user. Secret lives encrypted in RandomPack Settings.
"""

from __future__ import annotations

import requests

import frappe

_TIMEOUT_SECONDS = 20
PENDING_REVIEW = "Pending Review"  # the locked needs-human status


def _settings():
	settings = frappe.get_cached_doc("RandomPack Settings")
	if not settings.enabled:
		return None
	return settings


def _headers(settings) -> dict:
	# get_password RAISES (not None) when the encrypted field was never set —
	# an unconfigured secret must mean "send unauthenticated", not "crash".
	try:
		secret = settings.get_password("api_secret") or ""
	except Exception:
		secret = ""
	return {"Authorization": f"token {settings.api_key}:{secret}"}


def send(method: str, payload: dict, files: dict | None = None) -> dict | None:
	"""POST one backend API call. NEVER raises — returns the JSON or None.

	`method` is the dotted endpoint name (e.g. "update_task_progress" or a
	full "x.y.z" path); bare names resolve under the backend's API module.
	"""
	settings = _settings()
	if settings is None:
		frappe.logger("friday.randompack").warning(
			f"RandomPack integration disabled — dropped outbound {method!r}"
		)
		return None
	path = method if "." in method else f"randompack.api.{method}"
	url = f"{(settings.api_base_url or '').rstrip('/')}/api/method/{path}"
	try:
		if files:
			response = requests.post(
				url, data=payload, files=files, headers=_headers(settings), timeout=_TIMEOUT_SECONDS
			)
		else:
			response = requests.post(url, json=payload, headers=_headers(settings), timeout=_TIMEOUT_SECONDS)
		response.raise_for_status()
		return response.json()
	except Exception as exc:
		frappe.logger("friday.randompack").warning(f"Outbound {method!r} failed: {type(exc).__name__}")
		frappe.log_error(title=f"friday.randompack outbound failed: {method}")
		return None


def enqueue_send(method: str, payload: dict) -> None:
	"""Fire-and-forget with the queue's retry semantics (for must-deliver calls)."""
	frappe.enqueue(
		"frappe.friday_core.integrations.randompack_client.send",
		method=method,
		payload=payload,
		queue="friday",
		timeout=120,
		enqueue_after_commit=True,
	)


# ── The contract calls ──────────────────────────────────────────────────────


def update_task_progress(
	task_ref: str, status: str | None = None, progress: int | None = None, note: str | None = None
) -> dict | None:
	"""Heartbeat-safe per contract: progress alone never touches status."""
	payload: dict = {"task": task_ref}
	if status is not None:
		payload["status"] = status
	if progress is not None:
		payload["progress"] = max(0, min(100, int(progress)))
	if note:
		payload["note"] = note
	return send("update_task_progress", payload)


def signal_pending_review(task_ref: str, issue_name: str, summary: str) -> None:
	"""The locked needs-human signal: Pending Review + a note with the Issue ref."""
	update_task_progress(task_ref, status=PENDING_REVIEW)
	post_project_note(
		project_ref=None,
		note=f"Needs human review on {task_ref}: {summary}\nFriday Issue: {issue_name}",
		task_ref=task_ref,
	)


def attach_deliverable(
	project_ref: str, file_name: str, content: bytes, description: str = ""
) -> dict | None:
	"""Two-step per contract: upload_file (multipart, token auth) → attach by file_url."""
	uploaded = send(
		"upload_file",
		payload={"is_private": 1},
		files={"file": (file_name, content)},
	)
	file_url = ((uploaded or {}).get("message") or {}).get("file_url")
	if not file_url:
		return None
	return send(
		"attach_deliverable",
		{"project": project_ref, "file_url": file_url, "description": description},
	)


def post_project_note(project_ref: str | None, note: str, task_ref: str | None = None) -> dict | None:
	payload: dict = {"note": note}
	if project_ref:
		payload["project"] = project_ref
	if task_ref:
		payload["task"] = task_ref
	return send("post_project_note", payload)


def request_gate_open(project_ref: str, gate: str, summary: str) -> dict | None:
	"""Signal-only (locked): Friday says 'ready'; humans open the gate."""
	return send("request_gate_open", {"project": project_ref, "gate": gate, "summary": summary})


def get_project_state(project_ref: str) -> dict | None:
	"""Read endpoint — rehydration without event replay."""
	return send("get_project", {"project": project_ref})


def get_comments(project_ref: str) -> dict | None:
	return send("get_comments", {"project": project_ref})
