# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""RandomPack chat-intake surface — the wire for Friday's streaming front-door.

Topology (CONTRACT.md §4): browser ──SSE── RandomPack `chat_*` ──signed SSE── these
endpoints. The browser never talks to Friday directly; RandomPack proxies, signing each
call with the SAME HMAC seam as connector events (`X-RP-Signature`, the
`randompack-system` Connector's secret). This module turns one customer message into a
live streamed reply + structured wizard deltas, on top of `conversation/intake.py`.

ENDPOINTS (whitelisted, guest — the HMAC signature IS the auth)
  * `chat_send`     — POST {session_id, message} → an SSE stream:
                        {type:"token", text}        (live reply, <think> blocks hidden)
                        {type:"delta", step, field, value, confidence}  (wizard pre-fill)
                        {type:"done"}  |  {type:"error", error}
  * `chat_finalize` — POST {session_id} → a final full-transcript extraction pass,
                        returns {session_id, deltas:[...]} as JSON (RandomPack writes the
                        draft brief + owns the account step — provisional, not here).

DELIBERATELY NOT HERE (CONTRACT.md §4.6): no `patch_brief` callback (deltas return
in-band), no `chat.*` outbox events (chat is live request/response, not the async fact
outbox). The 3 never-touch fields (password / gate_commitment / terms_accepted) are not
in the extraction vocabulary at all, so they can never be emitted as deltas.

STREAMING MODEL: `provider.chat()` is Frappe-free, so the streamed completion runs in a
worker thread feeding a queue; the SSE generator (the request thread) owns all Frappe
work (history load, persistence, the session lock) and relays tokens through a
`_ThinkFilter` that suppresses `<think>…</think>` before they reach the browser.
"""

from __future__ import annotations

import json
import queue
import threading

import frappe
from frappe.friday_core.connectors.core import (
	DEFAULT_TOLERANCE_SECONDS,
	SIGNATURE_HEADER,
	verify_signature,
)
from frappe.friday_core.conversation.intake import extract_deltas
from frappe.friday_core.llm.reasoning import strip_reasoning
from frappe.friday_core.llm.usage import record_usage

CONNECTOR_NAME = "randompack-system"
INTAKE_PROFILE = "Customer Intake"
PLATFORM = "randompack-intake"
# Chat Message.platform is a Link to Chat Platform — this surface's row must exist or
# every transcript insert fails LinkValidationError. Registered like every other surface.
_ADAPTER_MODULE = "frappe.friday_core.surfaces.randompack_chat"
_PERSIST_SAVEPOINT = "friday_intake_persist"
_SESSION_LOCK = "friday:session_lock:{}"
_LOCK_TTL = 300
_LOCK_WAIT = 30

# The extraction vocabulary — RandomPack's `Onboarding Brief` field names exactly
# (CONTRACT.md §4.5). The 3 never-touch fields are simply absent. Select fields name
# their exact allowed options so the extractor emits a verbatim string or nothing.
_FIELDS: list[dict] = [
	# identity
	{"name": "full_name", "step": "identity", "description": "the customer's full name"},
	{"name": "email", "step": "identity", "description": "the customer's email address"},
	{"name": "company_name", "step": "identity", "description": "the company / brand name"},
	{"name": "website_or_social", "step": "identity", "description": "their website or a social handle/URL"},
	{"name": "country", "step": "identity", "description": "their country (full country name)"},
	{
		"name": "lead_source",
		"step": "identity",
		"description": "how they found RandomPack — EXACTLY one of: Search | YouTube | Instagram | LinkedIn | Twitter / X | Referral | Other",
	},
	# business
	{"name": "what_you_do", "step": "business", "description": "what the business does, in their words"},
	{
		"name": "category",
		"step": "business",
		"description": "business category — EXACTLY one of: SaaS | Fintech | D2C | Skincare | Media | Agency | Other",
	},
	{
		"name": "stage",
		"step": "business",
		"description": "stage — EXACTLY one of: Idea | Pre-launch | Launched | Rebranding",
	},
	# audience
	{"name": "target_audience", "step": "audience", "description": "who the brand is for (target customers)"},
	{"name": "competitors", "step": "audience", "description": "competitors they named"},
	{"name": "differentiator", "step": "audience", "description": "what makes them different / their edge"},
	# naming
	{
		"name": "naming_status",
		"step": "naming",
		"description": "naming status — EXACTLY one of: Name is locked | Open to exploring | Need a name",
	},
	{"name": "current_name", "step": "naming", "description": "their current/working name, if any"},
	{"name": "name_meaning", "step": "naming", "description": "the meaning/story behind the name, if given"},
	# taste
	{
		"name": "personality",
		"step": "taste",
		"description": 'the brand personality — a JSON ARRAY of up to 3 short attribute words the customer expressed or implied, e.g. ["rugged", "heritage", "honest"]',
	},
	{
		"name": "brands_admired",
		"step": "taste",
		"description": "brands they admire or want to feel adjacent to",
	},
	{"name": "avoid", "step": "taste", "description": "looks/feels/brands they want to AVOID"},
	{
		"name": "references",
		"step": "taste",
		"description": 'visual references — a JSON array (max 10) of {"type":"URL","url":"<link>"} the customer shared',
	},
	# logistics
	{
		"name": "preferred_start",
		"step": "logistics",
		"description": "preferred start date, normalised to ISO YYYY-MM-DD",
	},
	{"name": "notes", "step": "logistics", "description": "any other notes the customer added"},
]
_FIELD_STEP = {f["name"]: f["step"] for f in _FIELDS}
# What the extraction pass sees (no `step` — that's wire metadata we add back on the way out).
_EXTRACTION_FIELDS = [{"name": f["name"], "description": f["description"]} for f in _FIELDS]

INTAKE_SYSTEM_PROMPT = (
	"You are Friday's warm, sharp brand-intake assistant for RandomPack. You are having a "
	"live chat with a customer to scope a branding project. Each turn: in 1-2 warm sentences "
	"acknowledge what they just told you, then ask the SINGLE most useful next question — "
	"never more than one question at a time, never a wall of text. Naturally steer the "
	"conversation to cover these essentials before suggesting they move to the review step: "
	"their name, email, company name, what the business does, and what makes it different. "
	"Be genuinely helpful and concise; do not ask for payment details, passwords, or legal "
	"consent — those are handled later in the review wizard."
)


# ---------------------------------------------------------------------------
# Auth (reuse the connector HMAC seam)
# ---------------------------------------------------------------------------


def _verify(raw_body: bytes) -> bool:
	"""Verify the RandomPack HMAC signature using the connector's outbound secret."""
	try:
		connector = frappe.get_cached_doc("Connector", CONNECTOR_NAME)
	except Exception:
		return False
	if not connector.enabled:
		return False
	header = frappe.get_request_header(SIGNATURE_HEADER) or ""
	try:
		secret = connector.get_password("webhook_secret") or ""
	except Exception:
		secret = ""
	tolerance = connector.signature_tolerance_seconds or DEFAULT_TOLERANCE_SECONDS
	return verify_signature(raw_body, header, secret, tolerance)


# ---------------------------------------------------------------------------
# Pure helpers (SSE framing, the <think> filter, the wire delta shape)
# ---------------------------------------------------------------------------


def sse(obj: dict) -> str:
	"""Frame one object as a Server-Sent Event line."""
	return f"data: {json.dumps(obj)}\n\n"


def wire_deltas(deltas: list[dict]) -> list[dict]:
	"""Tag each `{field,value,confidence}` delta with its advisory wizard `step`.

	Drops any field not in the vocabulary (defence in depth — the 3 never-touch fields
	aren't here anyway, but a stray field name can't leak onto the wire).
	"""
	out = []
	for d in deltas:
		step = _FIELD_STEP.get(d.get("field"))
		if step is None:
			continue
		out.append({"step": step, "field": d["field"], "value": d["value"], "confidence": d["confidence"]})
	return out


class _ThinkFilter:
	"""Suppress `<think>…</think>` blocks from a token stream, tag-split-safe.

	Reasoning models (MiniMax-M3) emit chain-of-thought in `<think>` tags; the customer
	must never see it. Tokens arrive in arbitrary chunks, so a tag can split across two
	deltas (`"<thi"` + `"nk>"`). `feed()` returns only the customer-visible text, holding
	back any trailing run that could be the start of a tag until it's resolved; `flush()`
	emits whatever's left at end-of-stream. The FINAL reply is also scrubbed with
	`strip_reasoning` for persistence/extraction — this is the live-stream counterpart.
	"""

	_OPEN = "<think>"
	_CLOSE = "</think>"

	def __init__(self):
		self.buf = ""
		self.inside = False

	def feed(self, text: str) -> str:
		self.buf += text
		out: list[str] = []
		while True:
			if not self.inside:
				i = self.buf.find(self._OPEN)
				if i == -1:
					hold = _partial_tail(self.buf, self._OPEN)
					emit = self.buf[: len(self.buf) - hold]
					self.buf = self.buf[len(self.buf) - hold :]
					if emit:
						out.append(emit)
					break
				if i > 0:
					out.append(self.buf[:i])
				self.buf = self.buf[i + len(self._OPEN) :]
				self.inside = True
			else:
				j = self.buf.find(self._CLOSE)
				if j == -1:
					hold = _partial_tail(self.buf, self._CLOSE)
					self.buf = self.buf[len(self.buf) - hold :]
					break
				self.buf = self.buf[j + len(self._CLOSE) :]
				self.inside = False
		return "".join(out)

	def flush(self) -> str:
		out = self.buf if not self.inside else ""
		self.buf = ""
		return out


def _partial_tail(s: str, tag: str) -> int:
	"""Length of the longest suffix of `s` that is a (proper) prefix of `tag`."""
	for k in range(min(len(s), len(tag) - 1), 0, -1):
		if tag.startswith(s[-k:]):
			return k
	return 0


# ---------------------------------------------------------------------------
# Session transcript (Chat Message rows — continuity that survives a refresh)
# ---------------------------------------------------------------------------


def _history(session_id: str) -> list[dict]:
	rows = frappe.get_all(
		"Chat Message",
		filters={"session_id": session_id, "direction": ("in", ["inbound", "outbound"]), "compacted": 0},
		fields=["direction", "content"],
		order_by="creation asc",
		limit=40,
	)
	return [
		{"role": "user" if r["direction"] == "inbound" else "assistant", "content": r["content"] or ""}
		for r in rows
	]


def _persist(session_id: str, message: str, reply: str) -> None:
	now = frappe.utils.now_datetime()
	for direction, content in (("inbound", message), ("outbound", reply)):
		frappe.get_doc(
			{
				"doctype": "Chat Message",
				"session_id": session_id,
				"direction": direction,
				"platform": PLATFORM,
				"content": content,
				"timestamp": now,
				"processed": 1,
			}
		).insert(ignore_permissions=True)


def _default_model(provider) -> str:
	"""The provider's default model name for the usage log (defensive — never raises)."""
	try:
		return provider.get_default_model() or ""
	except Exception:
		return ""


def _record_turn(session_id: str, message: str, reply: str, provider, conv_usage, extraction_usage) -> None:
	"""Persist the transcript + per-call LLM usage for one streamed turn, then COMMIT.

	This runs INSIDE the SSE generator, which Frappe iterates AFTER the request's
	auto-commit — so without an explicit commit these writes are silently discarded (the
	governance gap caught on the live loopback: a clean stream that left 0 Chat Message and
	0 LLM Usage Log rows). Both model calls of the turn — the streamed reply AND the
	extraction pass — are cost-audited. Guarded + logged: a persistence failure must never
	corrupt the reply already streamed, but it is no longer SILENT.
	"""
	frappe.db.savepoint(_PERSIST_SAVEPOINT)
	try:
		_persist(session_id, message, reply)
		model = _default_model(provider)
		record_usage(
			profile_name=INTAKE_PROFILE,
			session_id=session_id,
			provider=provider,
			model=model,
			usage=conv_usage or {},
		)
		if extraction_usage:
			record_usage(
				profile_name=INTAKE_PROFILE,
				session_id=session_id,
				provider=provider,
				model=model,
				usage=extraction_usage,
			)
	except Exception:
		# Undo the partial/poisoned writes so the tx is usable again, then record the
		# failure in the Error Log — a plain logger.warning here went to a 0-byte void on
		# the box, so the failure stayed SILENT (exactly the bug we're closing). log_error
		# lands a durable, operator-visible row.
		frappe.db.rollback(save_point=_PERSIST_SAVEPOINT)
		try:
			frappe.log_error(
				title=f"friday.intake persist failed: {session_id}",
				message=frappe.get_traceback(),
			)
		except Exception:
			pass
	# The SSE generator runs PAST the request's auto-commit, so commit explicitly or BOTH
	# the turn's writes AND any error-log row are silently discarded.
	try:
		frappe.db.commit()
	except Exception:
		pass


def _transcript(history: list[dict], *, extra_user: str = "", extra_assistant: str = "") -> str:
	lines = [f"{m.get('role', 'user')}: {m.get('content', '')}" for m in history]
	if extra_user:
		lines.append(f"user: {extra_user}")
	if extra_assistant:
		lines.append(f"assistant: {extra_assistant}")
	return "\n".join(lines)


# ---------------------------------------------------------------------------
# The whitelisted endpoints
# ---------------------------------------------------------------------------


@frappe.whitelist(allow_guest=True, methods=["POST"])
def chat_send():
	"""POST {session_id, message} → SSE stream of {token}/{delta}/{done}/{error}."""
	from werkzeug.wrappers import Response

	raw = frappe.request.get_data() if frappe.request else b"{}"
	if not _verify(raw):
		frappe.local.response["http_status_code"] = 401
		return {"ok": False, "error": "bad signature"}
	try:
		body = json.loads(raw or b"{}")
	except ValueError, TypeError:
		frappe.local.response["http_status_code"] = 400
		return {"ok": False, "error": "bad request"}

	session_id = (body.get("session_id") or "").strip()
	message = body.get("message") or ""
	if not session_id or not message:
		frappe.local.response["http_status_code"] = 400
		return {"ok": False, "error": "session_id and message required"}

	return Response(_stream(session_id, message), mimetype="text/event-stream")


@frappe.whitelist(allow_guest=True, methods=["POST"])
def chat_finalize():
	"""POST {session_id} → a final full-transcript extraction pass, returns the deltas.

	(RandomPack writes the draft brief from these and owns the account/Customer step —
	provisional per CONTRACT.md, not built here.)
	"""
	from frappe.friday_core.llm.provider import get_provider_for_profile

	raw = frappe.request.get_data() if frappe.request else b"{}"
	if not _verify(raw):
		frappe.local.response["http_status_code"] = 401
		return {"ok": False, "error": "bad signature"}
	try:
		session_id = (json.loads(raw or b"{}").get("session_id") or "").strip()
	except ValueError, TypeError:
		session_id = ""
	if not session_id:
		frappe.local.response["http_status_code"] = 400
		return {"ok": False, "error": "session_id required"}

	provider = get_provider_for_profile(INTAKE_PROFILE)
	# The finalize extraction is a real model call too — cost-audit it. This runs in a
	# normal request (not the SSE generator), so Frappe auto-commits the usage row.
	deltas = extract_deltas(
		_transcript(_history(session_id)),
		_EXTRACTION_FIELDS,
		provider,
		on_usage=lambda u: record_usage(
			profile_name=INTAKE_PROFILE,
			session_id=session_id,
			provider=provider,
			model=_default_model(provider),
			usage=u,
		),
	)
	return {"ok": True, "session_id": session_id, "deltas": wire_deltas(deltas)}


def _stream(session_id: str, message: str):
	"""The SSE generator: stream the reply (think-filtered), then the wizard deltas.

	`provider.chat()` runs in a worker thread (it is Frappe-free); this generator — the
	request thread — owns the session lock + all Frappe DB work and relays tokens.
	"""
	from frappe.friday_core.llm.provider import get_provider_for_profile

	try:
		provider = get_provider_for_profile(INTAKE_PROFILE)
	except Exception as exc:
		yield sse({"type": "error", "error": f"intake profile unavailable: {type(exc).__name__}"})
		return

	lock = frappe.cache().lock(
		_SESSION_LOCK.format(session_id), timeout=_LOCK_TTL, blocking_timeout=_LOCK_WAIT
	)
	if not lock.acquire(blocking=True):
		yield sse({"type": "error", "error": "session busy"})
		return
	try:
		history = _history(session_id)
		messages = [
			{"role": "system", "content": INTAKE_SYSTEM_PROMPT},
			*history,
			{"role": "user", "content": message},
		]

		q: queue.Queue = queue.Queue()
		result: dict = {}

		def _worker():
			try:
				resp = provider.chat(messages, on_token=lambda t: q.put(("tok", t)))
				if isinstance(resp, dict):
					result["reply"] = resp.get("content", "")
					result["usage"] = resp.get("usage") or {}  # logged from the request thread
				else:
					result["reply"] = getattr(resp, "content", "")
			except Exception as exc:
				result["error"] = type(exc).__name__
			finally:
				q.put(("end", None))

		th = threading.Thread(target=_worker, daemon=True)
		th.start()

		think = _ThinkFilter()
		while True:
			kind, val = q.get()
			if kind == "end":
				break
			visible = think.feed(val)
			if visible:
				yield sse({"type": "token", "text": visible})
		tail = think.flush()
		if tail:
			yield sse({"type": "token", "text": tail})
		th.join(timeout=1)

		if result.get("error"):
			yield sse({"type": "error", "error": result["error"]})
			return

		reply = strip_reasoning(result.get("reply", "") or "")

		# Extract wizard deltas (a SECOND model call) and capture its token usage too.
		extraction_usage: dict = {}
		deltas = extract_deltas(
			_transcript(history, extra_user=message, extra_assistant=reply),
			_EXTRACTION_FIELDS,
			provider,
			on_usage=extraction_usage.update,
		)

		# Persist the transcript + BOTH calls' usage, then COMMIT — the SSE generator runs
		# past the request's auto-commit, so this is what actually makes the audit durable.
		_record_turn(session_id, message, reply, provider, result.get("usage"), extraction_usage)

		for d in wire_deltas(deltas):
			yield sse({"type": "delta", **d})
		yield sse({"type": "done"})
	finally:
		try:
			lock.release()
		except Exception:
			pass


# ---------------------------------------------------------------------------
# Provisioning (idempotent config — the Chat Platform row + Customer Intake profile)
# ---------------------------------------------------------------------------


def ensure_intake_platform() -> dict:
	"""Idempotently register the `randompack-intake` Chat Platform row. after_migrate-safe.

	`Chat Message.platform` is a Link to Chat Platform, so the transcript writes in
	`_persist` raise LinkValidationError unless this row exists — which on the box left
	every chat turn with NO transcript and NO usage audit (caught on the live loopback).
	Every other surface (cli/raven/slack) registers its platform the same way.

	`enabled=0`: this surface handles `chat_send`/`chat_finalize` directly over HMAC, NOT
	via the gateway's adapter dispatch — the row exists to satisfy the Link + register the
	platform, not for worker pickup (intake rows are written `processed=1`).
	"""
	if frappe.db.exists("Chat Platform", PLATFORM):
		return {"platform": PLATFORM, "platform_created": False}
	frappe.get_doc(
		{
			"doctype": "Chat Platform",
			"platform_name": PLATFORM,
			"adapter_module": _ADAPTER_MODULE,
			"enabled": 0,
			"dispatch_mode": "sync",
		}
	).insert(ignore_permissions=True)
	return {"platform": PLATFORM, "platform_created": True}


def provision_intake_profile() -> dict:
	"""Ensure the `randompack-intake` Chat Platform row + the `Customer Intake` Agent
	Profile. Idempotent; safe in after_migrate.

	A near-toolless conversational profile (intake takes no gated actions). The field
	vocabulary lives in THIS module (injected into the extraction pass), not the profile;
	the profile carries the conversational system prompt + the model.
	"""
	# Always ensure the platform first — the profile may already exist (early return below)
	# while the platform row is still missing, which is exactly the box state that broke
	# persistence.
	platform = ensure_intake_platform()

	if frappe.db.exists("Agent Profile", INTAKE_PROFILE):
		return {"profile": INTAKE_PROFILE, "created": False, **platform}
	frappe.get_doc(
		{
			"doctype": "Agent Profile",
			"profile_name": INTAKE_PROFILE,
			"agent_role": "Worker",
			"system_prompt": INTAKE_SYSTEM_PROMPT,
			"status": "Active",
		}
	).insert(ignore_permissions=True)
	return {"profile": INTAKE_PROFILE, "created": True, **platform}


def run_demo(
	message: str = "Hey! I'm Mara Lindqvist, mara@northwind.co. We're Northwind Tools — premium hand tools for woodworkers, and we want a rugged heritage feel. Found you via a YouTube review.",
) -> dict:
	"""Sandbox showcase of the FULL surface logic (minus the HTTP/SSE/HMAC layer, which
	needs the web stack): provision the intake profile, stream a real turn through the
	<think> filter, and run the RandomPack 20-field extraction + step tagging.

	    bench --site <sandbox> execute frappe.friday_core.surfaces.randompack_chat.run_demo
	"""
	from frappe.friday_core.llm.provider import get_provider_by_name

	provision_intake_profile()
	# The live surface resolves the provider from the intake profile (operator-configured);
	# the dev profile has none set, so the demo points at the known-good provider row.
	provider = get_provider_by_name("Minimax")
	messages = [{"role": "system", "content": INTAKE_SYSTEM_PROMPT}, {"role": "user", "content": message}]

	print(
		f"\n=== RandomPack chat-intake surface demo ===\ncustomer> {message}\nfriday>   ", end="", flush=True
	)
	think = _ThinkFilter()
	resp = provider.chat(messages, on_token=lambda t: print(think.feed(t), end="", flush=True))
	print(think.flush(), end="", flush=True)
	reply = strip_reasoning(resp["content"] if isinstance(resp, dict) else getattr(resp, "content", ""))

	transcript = _transcript([], extra_user=message, extra_assistant=reply)
	deltas = wire_deltas(extract_deltas(transcript, _EXTRACTION_FIELDS, provider))
	print("\n\nwizard deltas (over RandomPack's real field vocabulary):")
	for d in deltas:
		print(f"  [{d['step']}] {d['field']} = {d['value']!r}  (conf {d['confidence']})")
	return {"deltas": deltas}
