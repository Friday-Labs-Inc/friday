# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""The shared streaming-chat spine — one engine, many chat surfaces.

PLAIN ENGLISH
=============
Friday now has more than one live streamed chat surface (the guest intake chat and the
authenticated project chat, both proxied by RandomPack). They differ only in WHO talks,
WHAT the assistant is told, and WHAT structured events ride alongside the reply. All the
hard-won plumbing is identical — so it lives HERE, once:

  * HMAC verification against a Connector's webhook secret (the RP↔Friday trust seam).
  * SSE framing + the tag-split-safe ``<think>`` suppression filter.
  * The worker-thread streaming model: ``provider.chat()`` is Frappe-free, so it runs in
    a thread feeding a queue while the SSE generator (the request thread) owns the
    session lock and ALL Frappe DB work.
  * Transcript persistence + LLM usage audit + the EXPLICIT COMMIT. The SSE generator
    runs *after* the request's auto-commit, so without ``frappe.db.commit()`` every
    write is silently discarded — the governance gap found on the first live loopback
    and fixed twice (#166 → #168). Every surface built on this spine inherits that fix.
  * ``Chat Platform`` registration. ``Chat Message.platform`` is a Link — a surface
    whose platform row is missing fails EVERY transcript insert (#168's root cause).
  * The anti-blank guard: an empty completion becomes a gentle nudge, never a blank turn.

A surface module (a domain app's intake / project chat) keeps only its OWN
meaning: the agent profile, the platform name, the system-prompt builder, and a
``structured_pass`` — the deterministic second model pass that turns the finished turn
into side-channel events (wizard deltas for intake; gate-action proposals for project
chat). Structured events are never parsed from the streamed prose.
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
from frappe.friday_core.llm.reasoning import strip_reasoning
from frappe.friday_core.llm.usage import record_usage

_SESSION_LOCK = "friday:session_lock:{}"
_LOCK_TTL = 300
_LOCK_WAIT = 30
_PERSIST_SAVEPOINT = "friday_chat_persist"

# Never leave the caller with a blank turn (an empty or all-reasoning completion).
EMPTY_FALLBACK = "Sorry — could you tell me a little more about that? I want to capture it right."


# ---------------------------------------------------------------------------
# Auth (the connector HMAC seam)
# ---------------------------------------------------------------------------


def verify_rp_signature(raw_body: bytes, connector_name: str) -> bool:
	"""Verify the caller's HMAC signature against `connector_name`'s webhook secret.

	Fail-closed: a missing/disabled connector, an unset secret, or a bad/missing
	`X-RP-Signature` header all return False.
	"""
	try:
		connector = frappe.get_cached_doc("Connector", connector_name)
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
# Pure stream helpers (SSE framing + the <think> filter)
# ---------------------------------------------------------------------------


def sse(obj: dict) -> str:
	"""Frame one object as a Server-Sent Event line."""
	return f"data: {json.dumps(obj)}\n\n"


class ThinkFilter:
	"""Suppress `<think>…</think>` blocks from a token stream, tag-split-safe.

	Reasoning models (MiniMax-M3) emit chain-of-thought in `<think>` tags; the customer
	must never see it. Tokens arrive in arbitrary chunks, so a tag can split across two
	deltas (`"<thi"` + `"nk>"`). `feed()` returns only the customer-visible text, holding
	back any trailing run that could be the start of a tag until it's resolved; `flush()`
	emits whatever's left at end-of-stream. The FINAL reply is also scrubbed with
	`strip_reasoning` for persistence — this is the live-stream counterpart.
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


def history(session_id: str) -> list[dict]:
	"""The session's prior turns as chat messages, oldest first."""
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


def persist_turn(session_id: str, message: str, reply: str, platform: str) -> None:
	"""Write the turn's inbound + outbound transcript rows."""
	now = frappe.utils.now_datetime()
	for direction, content in (("inbound", message), ("outbound", reply)):
		frappe.get_doc(
			{
				"doctype": "Chat Message",
				"session_id": session_id,
				"direction": direction,
				"platform": platform,
				"content": content,
				"timestamp": now,
				"processed": 1,
			}
		).insert(ignore_permissions=True)


def transcript(history_msgs: list[dict], *, extra_user: str = "", extra_assistant: str = "") -> str:
	"""Render history (+ this turn) as a plain 'role: text' transcript for a second pass."""
	lines = [f"{m.get('role', 'user')}: {m.get('content', '')}" for m in history_msgs]
	if extra_user:
		lines.append(f"user: {extra_user}")
	if extra_assistant:
		lines.append(f"assistant: {extra_assistant}")
	return "\n".join(lines)


def default_model(provider) -> str:
	"""The provider's default model name for the usage log (defensive — never raises)."""
	try:
		return provider.get_default_model() or ""
	except Exception:
		return ""


def record_turn(
	session_id: str,
	message: str,
	reply: str,
	provider,
	*,
	profile: str,
	platform: str,
	usages: list[dict],
) -> None:
	"""Persist the transcript + every model call's usage for one streamed turn, then COMMIT.

	This runs INSIDE the SSE generator, which Frappe iterates AFTER the request's
	auto-commit — so without an explicit commit these writes are silently discarded (the
	#166→#168 governance gap). All the turn's model calls (the streamed reply AND any
	structured pass) are cost-audited. A persistence failure rolls back to a savepoint
	(un-poisoning the tx) and lands a durable Error Log row — never a silent void.
	"""
	frappe.db.savepoint(_PERSIST_SAVEPOINT)
	try:
		persist_turn(session_id, message, reply, platform)
		model = default_model(provider)
		for usage in usages:
			if usage:
				record_usage(
					profile_name=profile,
					session_id=session_id,
					provider=provider,
					model=model,
					usage=usage,
				)
	except Exception:
		frappe.db.rollback(save_point=_PERSIST_SAVEPOINT)
		try:
			frappe.log_error(
				title=f"friday.chat persist failed: {session_id}",
				message=frappe.get_traceback(),
			)
		except Exception:
			pass
	# The explicit commit that makes the audit durable (and the error row, on failure).
	try:
		frappe.db.commit()
	except Exception:
		pass


# ---------------------------------------------------------------------------
# The streaming turn (the SSE generator every surface shares)
# ---------------------------------------------------------------------------


def stream_turn(
	session_id: str,
	message: str,
	*,
	profile: str,
	platform: str,
	system_prompt: str,
	structured_pass=None,
):
	"""Run ONE streamed chat turn as `profile`; yield SSE strings.

	Event order: {token}* → structured events (surface-specific) → {done}. On failure a
	single {error} event ends the stream.

	`structured_pass(history, message, reply, provider) -> (events, usage)` is the
	surface's deterministic second pass — it returns wire-ready event dicts (each gets
	`type` from the surface, e.g. delta/action) and that call's token usage for the
	audit. It runs AFTER the reply finishes and is never parsed from the streamed prose.
	"""
	from frappe.friday_core.llm.provider import get_provider_for_profile

	try:
		provider = get_provider_for_profile(profile)
	except Exception as exc:
		yield sse({"type": "error", "error": f"agent profile unavailable: {type(exc).__name__}"})
		return

	lock = frappe.cache().lock(
		_SESSION_LOCK.format(session_id), timeout=_LOCK_TTL, blocking_timeout=_LOCK_WAIT
	)
	if not lock.acquire(blocking=True):
		yield sse({"type": "error", "error": "session busy"})
		return
	try:
		history_msgs = history(session_id)
		messages = [
			{"role": "system", "content": system_prompt},
			*history_msgs,
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

		think = ThinkFilter()
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
		if not reply.strip():
			# The anti-blank guard: an empty/all-reasoning completion becomes a nudge.
			reply = EMPTY_FALLBACK
			yield sse({"type": "token", "text": reply})

		events: list[dict] = []
		pass_usage: dict = {}
		if structured_pass is not None:
			try:
				events, pass_usage = structured_pass(history_msgs, message, reply, provider)
			except Exception:
				events, pass_usage = [], {}

		record_turn(
			session_id,
			message,
			reply,
			provider,
			profile=profile,
			platform=platform,
			usages=[result.get("usage") or {}, pass_usage],
		)

		for event in events or []:
			yield sse(event)
		yield sse({"type": "done"})
	finally:
		try:
			lock.release()
		except Exception:
			pass


# ---------------------------------------------------------------------------
# Provisioning (every chat surface must register its Chat Platform row)
# ---------------------------------------------------------------------------


def ensure_platform(platform_name: str, adapter_module: str) -> dict:
	"""Idempotently register a surface's `Chat Platform` row. after_migrate-safe.

	`Chat Message.platform` is a Link to Chat Platform, so a surface whose row is
	missing fails EVERY transcript insert with LinkValidationError (#168's root cause).
	`enabled=0`: spine surfaces answer signed HTTP directly — the row exists to satisfy
	the Link + register the platform, not for gateway adapter dispatch.
	"""
	if frappe.db.exists("Chat Platform", platform_name):
		return {"platform": platform_name, "platform_created": False}
	frappe.get_doc(
		{
			"doctype": "Chat Platform",
			"platform_name": platform_name,
			"adapter_module": adapter_module,
			"enabled": 0,
			"dispatch_mode": "sync",
		}
	).insert(ignore_permissions=True)
	return {"platform": platform_name, "platform_created": True}
