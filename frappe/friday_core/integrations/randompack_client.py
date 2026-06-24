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
"Friday Integration" API user. Transport + secrets now come from the generic
connector client (Design 81); the secret lives encrypted on the
`randompack-system` Connector row. This module is the thin domain adapter: it
keeps the five locked contract calls and resolves their endpoint paths.
"""

from __future__ import annotations

from frappe.friday_core.connectors import client as connector_client

# The randompack-system Connector row carries the base URL + token auth secret.
CONNECTOR_NAME = "randompack-system"
PENDING_REVIEW = "Pending Review"  # the locked needs-human status


def _resolve_path(method: str) -> str:
	"""Map a contract method name to the backend's dotted endpoint path.

	A dotted name (e.g. "x.y.z") is used as-is; `upload_file` is the
	Frappe-native multipart endpoint; bare names resolve under the backend's
	locked v1 API module.
	"""
	if "." in method:
		return method
	if method == "upload_file":
		return "upload_file"
	return f"randompack.api.v1.{method}"


def send(method: str, payload: dict, files: dict | None = None) -> dict | None:
	"""POST one backend API call through the randompack-system connector.

	NEVER raises — returns the JSON or None (the reliability contract is now
	enforced by the generic connector client). `method` is a contract method
	name resolved to a dotted endpoint by `_resolve_path`.
	"""
	return connector_client.send(CONNECTOR_NAME, _resolve_path(method), payload, files=files)


def enqueue_send(method: str, payload: dict) -> None:
	"""Fire-and-forget with the queue's retry semantics (for must-deliver calls)."""
	connector_client.enqueue_send(CONNECTOR_NAME, _resolve_path(method), payload)


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
	# v1 contract: attach_deliverable(project, file_url, title).
	return send(
		"attach_deliverable",
		{"project": project_ref, "file_url": file_url, "title": description or file_name},
	)


def post_project_note(project_ref: str | None, note: str, task_ref: str | None = None) -> dict | None:
	# v1 contract: post_project_note(project, content) — project is required and
	# there is no task param. task_ref is accepted for call-site compatibility
	# but not sent.
	if not project_ref:
		return None
	return send("post_project_note", {"project": project_ref, "content": note})


def request_gate_open(project_ref: str, gate: str, summary: str) -> dict | None:
	"""Signal-only (locked): Friday says 'ready'; humans open the gate.
	v1 contract: request_gate_open(project, gate, note)."""
	return send("request_gate_open", {"project": project_ref, "gate": gate, "note": summary})


def get_project_state(project_ref: str) -> dict | None:
	"""Read endpoint — rehydration without event replay."""
	return send("get_project", {"project": project_ref})


def get_comments(project_ref: str) -> dict | None:
	return send("get_comments", {"project": project_ref})
