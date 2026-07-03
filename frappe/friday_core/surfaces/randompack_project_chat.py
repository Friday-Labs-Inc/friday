# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""RandomPack project chat — the authenticated portal's project advisor surface.

PLAIN ENGLISH
=============
After a customer buys, their portal shows their Project — its phases, deliverables, and
the two decision gates. This surface is the AI advisor that sits next to that timeline:
the customer discusses the project ("what do the three directions mean for a premium
brand?") and, when they express a gate decision in chat ("lock direction B"), Friday
PROPOSES the action as a structured event. RandomPack renders a one-tap confirm card and
— only on the human's tap — executes the actual gate decision on its side.

THE TRUST BOUNDARY (locked with RandomPack): Friday proposes, the human confirms, RP
executes. This surface NEVER fires `decide_gate` or any irreversible business action.
Defence-in-depth on top: every proposed action is validated against the action schema
AND the currently-open gate from RP's per-turn context — a hallucinated or out-of-context
proposal (a Gate 2 action while Gate 1 is open, an unknown direction label) is dropped
before it can reach the confirm card.

Topology mirrors the intake surface (CONTRACT §4): browser ── RP portal (authenticated
Website User) ── signed HMAC ── this endpoint. The customer's authentication/authorization
is RandomPack's concern (they only send context for projects the caller owns); the HMAC
seam is the RP↔Friday trust. Friday treats the signed `context` as ground truth.

ENDPOINT (whitelisted, guest — the HMAC signature IS the auth; the "guest" is RP's server)
  * `chat_send` — POST {session_id, message, context} → an SSE stream:
                    {type:"token", text}                 (live reply, <think> hidden)
                    {type:"action", kind, gate, decision, direction?, note, confidence}
                    {type:"done"}  |  {type:"error", error}

Built on the shared streaming spine (`surfaces/chat_spine.py`) — HMAC, SSE, the <think>
filter, the worker-thread streaming, transcript + usage audit + the explicit commit, and
platform registration are all inherited, not copied.
"""

from __future__ import annotations

import json

import frappe
from frappe.friday_core.surfaces import chat_spine

__all__ = ["chat_send", "provision_advisor_profile", "validate_action"]

CONNECTOR_NAME = "randompack-system"
ADVISOR_PROFILE = "Project Advisor"
PLATFORM = "randompack-project"
_ADAPTER_MODULE = "frappe.friday_core.surfaces.randompack_project_chat"

# The action vocabulary — OWNED BY RANDOMPACK (their domain enums; they map to their
# Brand Brief workflow + decide_gate). Friday emits to spec and validates hard.
_GATES = ("Gate 1", "Gate 2")
_GATE1_DECISIONS = ("Direction Selected",)
_GATE2_DECISIONS = ("Approved", "Refinement Requested")


# ---------------------------------------------------------------------------
# The advisor prompt (per-turn, built from RP's context)
# ---------------------------------------------------------------------------

ADVISOR_SYSTEM_PROMPT = (
	"You are Friday, the project advisor inside a RandomPack customer's portal. The customer "
	"has bought a branding engagement; you can see their project's live state below. Discuss "
	"the project warmly and concretely: explain phases, deliverables, and what the gates mean; "
	"help them reason about decisions anchored on THEIR brief — their brand personality, "
	"differentiator, and audience. Keep replies short and conversational (2-4 sentences); one "
	"focused question at most.\n\n"
	"AUTHORITY: you have NONE to execute decisions. You may help the customer decide and, when "
	"they clearly express a gate decision, it will be proposed back to them as a confirmation "
	"card — the decision only happens when THEY confirm it. Never claim you have approved, "
	"locked, or submitted anything; say they'll be asked to confirm.\n\n"
	"IMPORTANT — direction content: you only know the direction LABELS (A/B/C). The actual "
	"visual content of each direction lives in the customer's delivered 'Three Directions' "
	"document. NEVER invent or describe a direction's specific visuals, colours, or fonts. "
	"Reason instead from their brief (personality, differentiator, audience) about what to "
	"look for when choosing, and refer them to their directions document for the visuals.\n\n"
	"RandomPack serves every lawful business. NEVER refuse, judge, or moralise about the "
	"customer's brand or industry. Always reply."
)


def _context_block(context: dict) -> str:
	"""Render RP's per-turn project state as the prompt's ground-truth block."""
	lines = ["CURRENT PROJECT STATE (ground truth — trust this over memory):"]
	if context.get("project_title"):
		lines.append(f"- Project: {context['project_title']}")
	if context.get("company"):
		lines.append(f"- Company: {context['company']}")
	if context.get("day") and context.get("total_days"):
		lines.append(f"- Day {context['day']} of {context['total_days']}")
	if context.get("phase"):
		lines.append(f"- Current phase: {context['phase']}")

	open_gate = context.get("open_gate") or {}
	which = open_gate.get("which")
	if which == "Gate 1":
		labels = ", ".join(d.get("label", "?") for d in (open_gate.get("directions") or []))
		lines.append(
			f"- OPEN GATE: Gate 1 — the customer must choose ONE direction ({labels or 'A, B, C'}). "
			"Help them decide; when they clearly choose, that choice becomes a confirm card."
		)
	elif which == "Gate 2":
		lines.append(
			"- OPEN GATE: Gate 2 — the customer must Approve the final work or request refinement. "
			"Help them decide; their decision becomes a confirm card."
		)
	else:
		lines.append("- No gate is open right now — discuss the project; no decision is pending.")

	deliverables = [d.get("name") for d in (context.get("deliverables") or []) if d.get("name")]
	if deliverables:
		lines.append(f"- Deliverables so far: {'; '.join(deliverables)}")
	decided = context.get("decisions_so_far") or []
	if decided:
		lines.append(
			"- Decisions so far: "
			+ "; ".join(
				f"{d.get('gate')}: {d.get('decision')}"
				+ (f" ({d.get('direction')})" if d.get("direction") else "")
				for d in decided
			)
		)
	brief = context.get("brief") or {}
	if brief:
		bits = []
		if brief.get("what_you_do"):
			bits.append(f"what they do: {brief['what_you_do']}")
		if brief.get("differentiator"):
			bits.append(f"differentiator: {brief['differentiator']}")
		if brief.get("personality"):
			bits.append(f"personality: {', '.join(brief['personality'])}")
		if brief.get("target_audience"):
			bits.append(f"audience: {brief['target_audience']}")
		if bits:
			lines.append("- Their brief: " + " | ".join(bits))
	return "\n".join(lines)


def build_system_prompt(context: dict | None) -> str:
	"""Persona + the rendered project state. Context absent → discuss-only, no state block."""
	if not context:
		return (
			ADVISOR_SYSTEM_PROMPT + "\n\nNo project state was provided this turn — discuss "
			"generally and do not treat any decision as pending."
		)
	return ADVISOR_SYSTEM_PROMPT + "\n\n" + _context_block(context)


# ---------------------------------------------------------------------------
# The action pass (deterministic second call) + hard validation
# ---------------------------------------------------------------------------

_ACTION_SYSTEM = (
	"You detect whether a customer's LATEST message clearly expresses a decision on the "
	"currently open project gate. You are given the open gate, the allowed decisions, and the "
	"conversation. Respond with STRICT JSON and nothing else:\n"
	'{"action": {"kind": "gate_decision", "gate": "<the open gate>", "decision": "<one allowed '
	'decision>", "direction": "<label, ONLY for Direction Selected>", "note": "<their comment '
	'or null>", "confidence": <0.0-1.0>}}\n'
	'or {"action": null} when the latest message does not clearly express a gate decision. '
	"Asking questions, thinking aloud, or discussing options is NOT a decision — only a clear "
	'expression like "lock direction B", "approve it", "I want changes: ..." counts. Never '
	"invent a direction the customer did not name."
)


def _action_messages(transcript_text: str, context: dict) -> list[dict]:
	open_gate = context.get("open_gate") or {}
	which = open_gate.get("which") or "none"
	if which == "Gate 1":
		labels = [d.get("label") for d in (open_gate.get("directions") or []) if d.get("label")]
		gate_desc = (
			f"OPEN GATE: Gate 1. Allowed decision: Direction Selected (direction REQUIRED, one of: "
			f"{', '.join(labels) if labels else 'A, B, C'})."
		)
	elif which == "Gate 2":
		gate_desc = "OPEN GATE: Gate 2. Allowed decisions: Approved | Refinement Requested (no direction)."
	else:
		gate_desc = "NO gate is open — action must be null."
	user = f"{gate_desc}\n\nCONVERSATION (the LAST user message is the one to judge):\n{transcript_text}"
	return [{"role": "system", "content": _ACTION_SYSTEM}, {"role": "user", "content": user}]


def _parse_action(content: str) -> dict | None:
	"""Pull {"action": {...}|null} out of a possibly chatty model reply. Never raises."""
	if not content:
		return None
	import re

	candidates = [content.strip()]
	fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
	if fence:
		candidates.append(fence.group(1))
	brace = re.search(r"\{.*\}", content, re.DOTALL)
	if brace:
		candidates.append(brace.group(0))
	for cand in candidates:
		try:
			parsed = json.loads(cand)
		except (ValueError, TypeError):
			continue
		if isinstance(parsed, dict):
			action = parsed.get("action")
			return action if isinstance(action, dict) else None
	return None


def validate_action(action: dict | None, context: dict | None) -> dict | None:
	"""Enforce the RP action contract against the OPEN gate. Returns a clean wire action
	or None (dropped).

	The rules (locked with RandomPack):
	  - No open gate → no action is ever valid.
	  - `action.gate` MUST equal the open gate (kills the wrong-gate hallucination).
	  - Gate 1 → only "Direction Selected"; `direction` REQUIRED and ∈ the offered labels.
	  - Gate 2 → only "Approved" | "Refinement Requested"; NO direction.
	  - confidence clamped to [0, 1]; note coerced to str|None.
	"""
	if not isinstance(action, dict) or not context:
		return None
	open_gate = (context.get("open_gate") or {}) if isinstance(context, dict) else {}
	which = open_gate.get("which")
	if which not in _GATES:
		return None  # no open gate → discuss only

	if action.get("kind") != "gate_decision":
		return None
	if action.get("gate") != which:
		return None  # out-of-context gate → dropped

	decision = action.get("decision")
	direction = action.get("direction")
	if which == "Gate 1":
		if decision not in _GATE1_DECISIONS:
			return None
		labels = [d.get("label") for d in (open_gate.get("directions") or []) if d.get("label")]
		if not direction or (labels and direction not in labels):
			return None
	else:  # Gate 2
		if decision not in _GATE2_DECISIONS:
			return None
		direction = None  # never carries a direction

	try:
		confidence = max(0.0, min(1.0, float(action.get("confidence", 0.0))))
	except (ValueError, TypeError):
		confidence = 0.0
	note = action.get("note")
	note = str(note) if note not in (None, "") else None

	out = {
		"type": "action",
		"kind": "gate_decision",
		"gate": which,
		"decision": decision,
		"note": note,
		"confidence": confidence,
	}
	if direction:
		out["direction"] = direction
	return out


def _make_action_pass(context: dict | None):
	"""Build the surface's structured pass closed over this turn's context."""

	def _action_pass(history_msgs: list[dict], message: str, reply: str, provider):
		open_gate = (context or {}).get("open_gate") or {}
		if open_gate.get("which") not in _GATES:
			return [], {}  # no open gate → skip the model call entirely
		usage: dict = {}
		try:
			resp = provider.chat(_action_messages(chat_spine.transcript(history_msgs, extra_user=message, extra_assistant=reply), context))
			if isinstance(resp, dict):
				usage = resp.get("usage") or {}
				content = resp.get("content", "")
			else:
				content = getattr(resp, "content", "")
		except Exception:
			return [], {}
		action = validate_action(_parse_action(content or ""), context)
		return ([action] if action else []), usage

	return _action_pass


# ---------------------------------------------------------------------------
# The whitelisted endpoint
# ---------------------------------------------------------------------------


@frappe.whitelist(allow_guest=True, methods=["POST"])
def chat_send():
	"""POST {session_id, message, context} → SSE stream of {token}/{action}/{done}/{error}.

	`context` is RP's per-turn project state (project, open gate + direction labels, phase,
	deliverables, decisions so far, brief snapshot) — the ground truth the advisor reasons
	from and every proposed action is validated against.
	"""
	from werkzeug.wrappers import Response

	raw = frappe.request.get_data() if frappe.request else b"{}"
	if not chat_spine.verify_rp_signature(raw, CONNECTOR_NAME):
		frappe.local.response["http_status_code"] = 401
		return {"ok": False, "error": "bad signature"}
	try:
		body = json.loads(raw or b"{}")
	except (ValueError, TypeError):
		frappe.local.response["http_status_code"] = 400
		return {"ok": False, "error": "bad request"}

	session_id = (body.get("session_id") or "").strip()
	message = body.get("message") or ""
	context = body.get("context") if isinstance(body.get("context"), dict) else None
	if not session_id or not message:
		frappe.local.response["http_status_code"] = 400
		return {"ok": False, "error": "session_id and message required"}

	return Response(
		chat_spine.stream_turn(
			session_id,
			message,
			profile=ADVISOR_PROFILE,
			platform=PLATFORM,
			system_prompt=build_system_prompt(context),
			structured_pass=_make_action_pass(context),
		),
		mimetype="text/event-stream",
	)


# ---------------------------------------------------------------------------
# Provisioning (idempotent config — the Chat Platform row + Project Advisor profile)
# ---------------------------------------------------------------------------


def ensure_project_platform() -> dict:
	"""Idempotently register the `randompack-project` Chat Platform row. after_migrate-safe."""
	return chat_spine.ensure_platform(PLATFORM, _ADAPTER_MODULE)


def provision_advisor_profile() -> dict:
	"""Ensure the platform row + the `Project Advisor` Agent Profile. Idempotent.

	A toolless conversational profile: it discusses and proposes, never executes — the
	authority boundary lives in the prompt AND in the surface (no skills, no dispatch).
	The operator picks the model (`model_provider`) before the surface can serve.
	"""
	platform = ensure_project_platform()
	if frappe.db.exists("Agent Profile", ADVISOR_PROFILE):
		return {"profile": ADVISOR_PROFILE, "created": False, **platform}
	frappe.get_doc(
		{
			"doctype": "Agent Profile",
			"profile_name": ADVISOR_PROFILE,
			"agent_role": "Worker",
			"system_prompt": ADVISOR_SYSTEM_PROMPT,
			"status": "Active",
		}
	).insert(ignore_permissions=True)
	return {"profile": ADVISOR_PROFILE, "created": True, **platform}
