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
	try:
		secret = settings.get_password("webhook_secret") or ""
	except Exception:
		secret = ""  # unset secret → verify_signature fails closed (401)
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
	parts = dict(part.split("=", 1) for part in header.split(",") if "=" in part)
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
	except Exception as exc:
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


def _ingest_brief(rp_brief: str, snapshot: dict) -> str:
	"""Create a Brand Brief from a frozen brief_snapshot (idempotent by rp_brief).
	Returns the brief name (existing or newly created). Shared by both handlers —
	whichever event arrives carrying the snapshot creates the brief. Correlation
	key is the RandomPack Onboarding Brief docname (`brief`)."""
	existing = frappe.db.get_value("Brand Brief", {"rp_brief": rp_brief}, "name") if rp_brief else None
	if existing:
		return existing

	# RandomPack's brief_snapshot is a JSON field → arrives as a JSON string.
	if isinstance(snapshot, str):
		try:
			snapshot = json.loads(snapshot)
		except (ValueError, TypeError):
			snapshot = {}

	doc_fields: dict = {"doctype": "Brand Brief", "status": "Ready", "rp_brief": rp_brief}
	leftovers: dict = {}
	for key, value in (snapshot or {}).items():
		target = _BRIEF_FIELD_MAP.get(key)
		if not target:
			leftovers[key] = value
			continue
		if isinstance(value, list):
			value = ", ".join(str(v) for v in value)
		if doc_fields.get(target):
			doc_fields[target] = (
				f"{doc_fields[target]}\nAvoid: {value}"
				if key == "brands_avoid"
				else f"{doc_fields[target]}\n{value}"
			)
		else:
			doc_fields[target] = value

	notes_parts = [f"[rp:{rp_brief}]"]
	if leftovers:
		notes_parts.append("Unmapped brief fields:\n" + frappe.as_json(leftovers))
	doc_fields["notes"] = "\n".join(notes_parts)
	doc_fields.setdefault("business_name", f"RandomPack {rp_brief}")
	return frappe.get_doc(doc_fields).insert(ignore_permissions=True).name


def handle_payment_received(data: dict, event) -> None:
	"""payment.received → stage the Brand Brief IF a snapshot is present.

	RandomPack's payment.received carries only {brief, sales_order} (no
	snapshot), so this is normally a no-op — the brief is created at
	project.created, which carries the frozen snapshot. Kept for the case where
	a snapshot is delivered early.
	"""
	snapshot = data.get("brief_snapshot") or {}
	rp_brief = str(data.get("brief") or "")
	if snapshot and rp_brief:
		_ingest_brief(rp_brief, snapshot)


# ---------------------------------------------------------------------------
# 60b handlers — the command center reacts to the pipeline's business moments
# ---------------------------------------------------------------------------


def _backend_ref(data: dict, event) -> str:
	return str(data.get("project_id") or data.get("brief_id") or event.event_id)


def _find_brief(backend_ref: str) -> str | None:
	return frappe.db.get_value("Brand Brief", {"notes": ("like", f"%[rp:{backend_ref}]%")}, "name")


def _find_project(backend_ref: str) -> str | None:
	return frappe.db.get_value("Project", {"backend_ref": backend_ref}, "name")


def _warroom(text: str) -> None:
	"""Best-effort War Room post (reuses the task publisher's transport)."""
	try:
		from frappe.friday_core.warroom.publisher import _get_channel_id, _post_to_raven

		channel = _get_channel_id()
		if channel:
			_post_to_raven(channel, {"text": text, "message_type": "Text", "hide_in_message_history": False})
	except Exception:
		pass


def handle_project_created(data: dict, event) -> None:
	"""project.created → start the Brand Brief metadata engine (Design 75).

	Correlate the ingested Brand Brief by the RandomPack brief docname, record
	the RandomPack project ref on it (for write-back), then kick the Design-75
	engine by moving the brief into its initial workflow state. The engine's
	on_update hook dispatches the first phase. Idempotent: a replay that finds
	the brief already started is an observable no-op.
	"""
	from frappe.friday_core.domains.randompack_brand import INITIAL_STATE

	rp_brief = str(data.get("brief") or "")
	rp_project = str(data.get("project") or "")
	snapshot = data.get("brief_snapshot") or {}
	brief = frappe.db.get_value("Brand Brief", {"rp_brief": rp_brief}, "name") if rp_brief else None
	# payment.received carries no snapshot, so the brief usually doesn't exist
	# yet — create it now from project.created's frozen snapshot.
	if not brief and snapshot and rp_brief:
		brief = _ingest_brief(rp_brief, snapshot)
	if not brief:
		brief = _find_brief(_backend_ref(data, event))
	if not brief:
		raise ValueError(
			f"no Brand Brief for RandomPack brief {rp_brief!r} / project {rp_project!r} and no "
			"snapshot to create one"
		)

	doc = frappe.get_doc("Brand Brief", brief)
	# Persist rp_project NOW (apply_workflow doesn't reliably carry an unsaved
	# field), so the engine + write-back see it from the first phase on.
	if rp_project and doc.rp_project != rp_project:
		doc.db_set("rp_project", rp_project, update_modified=False)
		doc.reload()

	# After payment the brief idles at INITIAL_STATE ("Intake") — no agentic phase
	# there, so nothing has run yet. Starting the pipeline = firing the Start
	# Pipeline transition (Intake → Strategy), which lets the engine dispatch the
	# first phase WITH the project ref set. A brief already past Intake is a replay.
	if doc.workflow_state and doc.workflow_state != INITIAL_STATE:
		_warroom(f"**[{rp_project or rp_brief}]** project.created replay — pipeline already running ({doc.workflow_state}); no-op.")
		return

	from frappe.friday_core.engine.governance import acting_as
	from frappe.model.workflow import apply_workflow

	if doc.workflow_state != INITIAL_STATE:
		doc.workflow_state = INITIAL_STATE  # ensure at Intake for the transition
	# The webhook worker runs as Guest; Start Pipeline is a System-Manager-gated
	# SYSTEM transition (not an agent/gate action), so fire it as Administrator.
	with acting_as("Administrator"):
		apply_workflow(doc, "Start Pipeline")  # Intake → Strategy; fires the engine
	_warroom(f"**[{rp_project or rp_brief}]** brand pipeline started (brief {brief} → Strategy).")

	from frappe.friday_core.integrations.randompack_client import post_project_note

	if rp_project:
		post_project_note(rp_project, note="Friday started the brand pipeline (strategy → directions → gates → delivery).")


def handle_gate_decided(data: dict, event) -> None:
	"""gate.decided → fire the Brand Brief's gate transition as the gateway user.

	The brief's CURRENT workflow_state tells us which gate this is (Gate 1
	Review → Approve Direction; Gate 2 Review → Final Approval), so we don't
	depend on the backend's gate naming. 'Refinement Requested' does NOT advance
	— it's noted for a human. The transition fires as the gateway system user
	(holds only the client-reviewer role) per the Design 75 §3 governance guard;
	the engine then dispatches the next phase.
	"""
	from frappe.friday_core.domains.randompack_brand import GATEWAY_USER
	from frappe.friday_core.engine.governance import acting_as
	from frappe.friday_core.integrations.randompack_client import post_project_note
	from frappe.model.workflow import apply_workflow

	rp_project = str(data.get("project") or "")
	brief = (frappe.db.get_value("Brand Brief", {"rp_project": rp_project}, "name") if rp_project else None) or \
		_find_brief(_backend_ref(data, event))
	if not brief:
		raise ValueError(f"no Brand Brief for RandomPack project {rp_project!r}")

	decision = str(data.get("decision") or "")
	chosen = str(data.get("chosen_direction") or "")
	if decision == "Refinement Requested":
		_warroom(f"**[{rp_project}]** refinement requested: {str(data.get('client_comments') or '')}")
		post_project_note(rp_project, note="Friday noted the refinement request; awaiting the updated direction.")
		return

	doc = frappe.get_doc("Brand Brief", brief)
	state = doc.workflow_state or ""
	if "Gate 1" in state:
		action = "Approve Direction"
		if chosen:
			doc.db_set("chosen_direction", chosen, update_modified=False)
			doc.reload()
	elif "Gate 2" in state:
		action = "Final Approval"
	else:
		_warroom(f"**[{rp_project}]** gate.decided but brief is at {state!r} — no matching gate transition; ignored.")
		return

	with acting_as(GATEWAY_USER):
		apply_workflow(doc, action)

	_remember(
		f"RandomPack project {rp_project}: {state} approved — {chosen or decision or 'approved'}",
		subject=rp_project or brief,
	)
	_warroom(f"**[{rp_project}]** {state} approved ({chosen or decision or 'approved'}) — pipeline advanced.")


def handle_refinement_requested(data: dict, event) -> None:
	"""refinement.requested → an agentic task now; advisory scope-guard at round ≥ 3 (Q6)."""
	ref = _backend_ref(data, event)
	project = _find_project(ref)
	if not project:
		raise ValueError(f"no Friday project for backend ref {ref!r}")
	round_n = int(data.get("round") or 1)
	request = str(data.get("request") or data.get("notes") or "See backend comments.")
	brief = _find_brief(ref) or ""

	frappe.get_doc(
		{
			"doctype": "Task",
			"title": f"Refinement round {round_n}",
			"description": (
				f"Client refinement request (round {round_n}) for Brand Brief {brief}:\n"
				f"{request}\n\nProduce the revised draft(s); reply with a concise summary."
			),
			"project": project,
			"workflow_state": "Pending",
			"execution_mode": "agentic",
			"backend_ref": f"refinement_r{round_n}",
			"required_skills": [{"skill": "get-brand-brief"}],
		}
	).insert(ignore_permissions=True)

	if round_n >= 3:
		_remember(
			f"Backend project {ref} reached refinement round {round_n} (+2 delivery days each).", subject=ref
		)
		_warroom(
			f"⚠️ **[PRJ {ref}]** refinement round {round_n} — scope check: each round adds 2 delivery days."
		)


def handle_kill_switch(data: dict, event) -> None:
	"""project.cancelled / payment.refunded → cancel all open tasks NOW (Q7)."""
	ref = _backend_ref(data, event)
	project = _find_project(ref)
	if not project:
		return  # nothing planned — nothing to kill
	open_tasks = frappe.get_all(
		"Task",
		filters={"project": project, "workflow_state": ("not in", ["Completed", "Cancelled"])},
		pluck="name",
	)
	for name in open_tasks:
		task = frappe.get_doc("Task", name)
		task.workflow_state = "Cancelled"
		task.save(ignore_permissions=True)
	frappe.db.set_value("Project", project, "status", "Cancelled", update_modified=False)
	_warroom(f"🛑 **[PRJ {ref}]** {event.event_type} — {len(open_tasks)} open tasks cancelled.")


def handle_gate_reminder(data: dict, event) -> None:
	ref = _backend_ref(data, event)
	_warroom(f"⏰ **[PRJ {ref}]** gate reminder: {data.get('gate') or 'a gate'} is awaiting the client.")


def handle_comment_added(data: dict, event) -> None:
	"""Relay client/team comments to the War Room (Friday's own notes are
	already filtered out by the backend — locked contract, no self-dedupe)."""
	ref = _backend_ref(data, event)
	comment = str(data.get("comment") or data.get("text") or "")[:500]
	if comment:
		_warroom(f"💬 **[PRJ {ref}]** comment: {comment}")


def handle_project_completed(data: dict, event) -> None:
	ref = _backend_ref(data, event)
	project = _find_project(ref)
	if project:
		frappe.db.set_value("Project", project, "status", "Completed", update_modified=False)
	_remember(f"Backend project {ref} completed and delivered.", subject=ref)
	_warroom(f"✅ **[PRJ {ref}]** project completed.")


def _remember(memory: str, subject: str) -> None:
	"""Direct memory write for event context (no agent turn to attribute)."""
	profile = (
		frappe.db.get_value("Chat Platform", "raven", "default_agent_profile")
		or frappe.db.get_value("Chat Platform", "cli", "default_agent_profile")
		or "Friday"
	)
	if not frappe.db.exists("Agent Profile", profile):
		return
	# Design 73 — scope the memory to its project. The subject is the backend_ref
	# (e.g. FLI-001), so resolve the Project from it; recall in that project's
	# room then sees this fact, and other rooms don't.
	project = frappe.db.get_value("Project", {"backend_ref": subject}, "name") if subject else None
	frappe.get_doc(
		{
			"doctype": "Agent Memory",
			"memory": memory[:490],
			"agent_profile": profile,
			"project": project,
			"subject": subject,
			"source_session": "randompack-events",
			"status": "Active",
		}
	).insert(ignore_permissions=True)


_HANDLERS = {
	"payment.received": handle_payment_received,
	"project.created": handle_project_created,
	"gate.decided": handle_gate_decided,
	"refinement.requested": handle_refinement_requested,
	"project.cancelled": handle_kill_switch,
	"payment.refunded": handle_kill_switch,
	"gate.reminder": handle_gate_reminder,
	"comment.added": handle_comment_added,
	"project.completed": handle_project_completed,
	# gate.opened / phase.changed / files.delivered: recorded (no action needed
	# v0.1 — the ledger keeps them for audit and later use).
}
