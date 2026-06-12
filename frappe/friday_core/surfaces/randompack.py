# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt

"""
The RandomPack webhook surface (design 60a, LOCKED).

PLAIN ENGLISH
=============
RandomPack (the ops backend) POSTs signed events here. We:

  1. Verify the Stripe-style per-attempt signature
     (`X-RP-Signature: t=<unix>,v1=HMAC-SHA256(secret, "{t}.{raw_body}")`):
     constant-time compare on v1 FIRST, then a freshness window on `t`
     (default 300s). Backend replays re-sign with fresh `t`, so replays
     stay valid — and our UUID dedupe keeps them boring.
  2. Persist the envelope as a RandomPack Event row — `event_id` is UNIQUE,
     so a duplicate delivery is a 200 no-op.
  3. Ack 200 immediately; the handler runs on the dedicated `friday` queue.

Handlers live in the registry below. 60a ships the surface + the handlers
that need no command-center machinery (brief ingestion on payment); the
project/task handlers land in 60b — until then their events are recorded and
marked Processed with action "recorded (handler lands in 60b)".

CONTRACT NOTES (agreed with the randompack side, design 60):
  - comment.added never echoes Friday's own notes back — no self-dedupe here.
  - `Pending Review` (not "failed") is the needs-human signal on write-back.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time

import frappe

SIGNATURE_HEADER = "X-RP-Signature"
DEFAULT_TOLERANCE_SECONDS = 300


# ---------------------------------------------------------------------------
# The endpoint
# ---------------------------------------------------------------------------


@frappe.whitelist(allow_guest=True, methods=["POST"])
def receive_event():
	"""POST /api/method/frappe.friday_core.surfaces.randompack.receive_event

	Guest-reachable by design: the HMAC signature IS the authentication.
	Returns fast; processing is queued.
	"""
	settings = frappe.get_cached_doc("RandomPack Settings")
	if not settings.enabled:
		frappe.throw(frappe._("RandomPack integration is disabled."), frappe.PermissionError)

	raw_body = frappe.request.get_data() or b""
	header = frappe.get_request_header(SIGNATURE_HEADER) or ""
	secret = settings.get_password("webhook_secret") or ""
	tolerance = settings.signature_tolerance_seconds or DEFAULT_TOLERANCE_SECONDS

	if not verify_signature(raw_body, header, secret, tolerance):
		frappe.throw(frappe._("Invalid webhook signature."), frappe.AuthenticationError)

	envelope = json.loads(raw_body)
	event_id = envelope.get("id")
	event_type = envelope.get("type")
	if not event_id or not event_type:
		frappe.throw(frappe._("Envelope must carry id and type."), frappe.ValidationError)

	# UUID dedupe (Q1): the unique event_id makes duplicates a clean no-op.
	if frappe.db.exists("RandomPack Event", event_id):
		return {"ok": True, "deduped": True, "event": event_id}

	frappe.get_doc(
		{
			"doctype": "RandomPack Event",
			"event_id": event_id,
			"event_type": event_type,
			"version": str(envelope.get("version") or ""),
			"occurred_at": str(envelope.get("occurred_at") or ""),
			"payload": frappe.as_json(envelope.get("data") or {}),
			"status": "Received",
		}
	).insert(ignore_permissions=True)

	frappe.enqueue(
		"frappe.friday_core.surfaces.randompack.process_event",
		event_id=event_id,
		queue="friday",
		timeout=600,
		enqueue_after_commit=True,
	)
	return {"ok": True, "event": event_id}


def verify_signature(raw_body: bytes, header: str, secret: str, tolerance_seconds: int) -> bool:
	"""Verify the Stripe-style per-attempt signature (locked contract).

	Order matters: constant-time verify v1 FIRST (an attacker learns nothing
	from timing), then enforce the freshness window on `t`.
	"""
	if not secret or not header:
		return False
	parts = dict(
		part.split("=", 1) for part in header.split(",") if "=" in part
	)
	t = parts.get("t")
	v1 = parts.get("v1")
	if not t or not v1:
		return False

	signed = f"{t}.".encode() + raw_body
	expected = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
	if not hmac.compare_digest(expected, v1):
		return False

	try:
		age = abs(time.time() - float(t))
	except (TypeError, ValueError):
		return False
	return age <= tolerance_seconds


# ---------------------------------------------------------------------------
# Processing (runs on the friday queue)
# ---------------------------------------------------------------------------


def process_event(event_id: str) -> None:
	"""Route one persisted event through the handler registry. Idempotent."""
	event = frappe.get_doc("RandomPack Event", event_id)
	if event.status == "Processed":
		return  # replay of a success — skip

	handler = _HANDLERS.get(event.event_type)
	# Frappe's JSON fieldtype returns an already-parsed dict on Postgres
	# reads and a string elsewhere — tolerate both.
	data = event.payload or {}
	if isinstance(data, str):
		data = json.loads(data or "{}")
	try:
		if handler:
			handler(data, event)
			note = ""
		else:
			note = "recorded (handler lands in 60b)"
		event.status = "Processed"
		event.failure_reason = note
		event.processed_at = frappe.utils.now_datetime()
		event.save(ignore_permissions=True)
	except Exception as exc:  # noqa: BLE001 — the event row is the error ledger
		event.status = "Failed"
		event.failure_reason = f"{type(exc).__name__}: {str(exc)[:300]}"
		event.save(ignore_permissions=True)
		frappe.log_error(title=f"friday.randompack handler failed: {event.event_type}")


# ---------------------------------------------------------------------------
# Handlers (60a scope: brief ingestion; the rest land with 60b)
# ---------------------------------------------------------------------------

# Their brief field → our Brand Brief field. Unknown keys fall through to
# `notes` so nothing in the frozen snapshot is ever silently lost.
_BRIEF_FIELD_MAP = {
	"company": "business_name",
	"industry": "industry",
	"audience": "target_audience",
	"differentiator": "what_they_do",
	"personality_attributes": "brand_personality",  # list → comma-joined
	"references": "inspirations",
	"brands_admired": "color_preferences",  # admired/avoid both land in prefs
	"brands_avoid": "competitors",
}


def handle_payment_received(data: dict, event) -> None:
	"""payment.received → ingest the frozen brief_snapshot as a Brand Brief.

	Staging only (locked role map): generation starts at project.created
	(60b). Idempotent: keyed by the backend project/brief reference when
	present, stored in the brief's notes for traceability.
	"""
	snapshot = data.get("brief_snapshot") or {}
	if not snapshot:
		return

	backend_ref = str(data.get("project_id") or data.get("brief_id") or event.event_id)
	existing = frappe.db.get_value(
		"Brand Brief", {"notes": ("like", f"%[rp:{backend_ref}]%")}, "name"
	)
	if existing:
		return  # snapshot is frozen — never overwrite

	doc_fields: dict = {"doctype": "Brand Brief", "status": "Ready"}
	leftovers: dict = {}
	for key, value in snapshot.items():
		target = _BRIEF_FIELD_MAP.get(key)
		if not target:
			leftovers[key] = value
			continue
		if isinstance(value, list):
			value = ", ".join(str(v) for v in value)
		if target in doc_fields and doc_fields[target]:
			doc_fields[target] = f"{doc_fields[target]}\nAvoid: {value}" if key == "brands_avoid" else f"{doc_fields[target]}\n{value}"
		else:
			doc_fields[target] = value

	notes_parts = [f"[rp:{backend_ref}]"]
	if leftovers:
		notes_parts.append("Unmapped brief fields:\n" + frappe.as_json(leftovers))
	doc_fields["notes"] = "\n".join(notes_parts)
	doc_fields.setdefault("business_name", f"RandomPack {backend_ref}")

	frappe.get_doc(doc_fields).insert(ignore_permissions=True)


_HANDLERS = {
	"payment.received": handle_payment_received,
	# 60b: project.created, gate.opened, gate.decided, refinement.requested,
	# phase.changed, comment.added, files.delivered, project.completed,
	# project.cancelled, payment.refunded, gate.reminder.
}
