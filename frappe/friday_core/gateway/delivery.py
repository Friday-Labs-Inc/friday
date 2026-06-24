# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt

"""
Delivery target DSL + router (Design 86) — a faithful port of Hermes
`gateway/delivery.py`, adapted to Frappe's row-based gateway.

PLAIN ENGLISH
=============

"I have some output — where does it go?" A *target string* answers it:

    "origin"              → back to the session that triggered this
    "local"               → a private file (output with no channel — e.g. cron)
    "raven:CH-123"        → a specific channel
    "raven:CH-123:T9"     → a specific channel + thread (thread ignored on Raven)
    "raven"               → the platform's home channel (chat_id resolved later)

`DeliveryRouter.deliver()` fans one piece of content out to many targets, with
per-target isolation (one failing target never aborts the others), oversized-
output truncation, and a private-File sink.

FRAPPE ADAPTATION (vs Hermes)
=============================
- Platform delivery is **one outbound `Chat Message` row** (Design 86, Q1), not
  an adapter `.send()` — so it rides the exact path Raven posting already uses
  and stays on the audit trail.
- The "local" sink is a **private Frappe `File`** (Q3), not a disk path.
- `parse()` is pure (no DB); an unconfigured platform falls back to `local` at
  *deliver* time (Q2), faithful to Hermes' "unknown platform → LOCAL".
- `thread_id` is parsed (the DSL round-trips) but ignored on delivery — Friday's
  `Chat Message` has no thread concept (Q5). The Telegram private-topic logic in
  Hermes is not ported.

GOVERNANCE
==========
The router is a low-level primitive: it can address any channel. *Which skills
may name a free target* is gated at the skill / permission layer, not here
(`share-deliverables` chooses origin-only for its own use case). See
docs/design/86.
"""

from __future__ import annotations

from dataclasses import dataclass

import frappe

# Reserved target keyword for the file sink.
LOCAL = "local"

# Faithful to Hermes (`delivery.py:21-22`): cap a single platform delivery, and
# how much of the original stays visible when we truncate.
MAX_PLATFORM_OUTPUT = 4000
TRUNCATED_VISIBLE = 3800


@dataclass(frozen=True)
class DeliveryOrigin:
	"""Where a delivery came from — Friday's stand-in for Hermes `SessionSource`.

	Just enough to resolve an `"origin"` target: the platform + the session id
	(a Raven channel id, a CLI session, …).
	"""

	platform: str
	session_id: str


@dataclass(frozen=True)
class DeliveryTarget:
	"""A single place to deliver to. Build via `parse()`, never by hand."""

	platform: str
	chat_id: str | None = None
	thread_id: str | None = None
	is_origin: bool = False
	is_explicit: bool = False  # True when chat_id was given explicitly

	@classmethod
	def parse(cls, target: str, origin: DeliveryOrigin | None = None) -> "DeliveryTarget":
		"""Parse a target string. Pure — no DB; unknown platforms resolve later.

		Faithful to Hermes `DeliveryTarget.parse` (`delivery.py:84`): `origin`
		resolves from the supplied source (or falls back to local when there is
		none); `local` is the file sink; `platform:chat[:thread]` is explicit; a
		bare `platform` uses its home channel (chat_id left None).
		"""
		stripped = target.strip()
		lower = stripped.lower()

		if lower == "origin":
			if origin:
				return cls(
					platform=origin.platform,
					chat_id=origin.session_id,
					is_origin=True,
				)
			# No origin to resolve — save it locally instead of dropping it.
			return cls(platform=LOCAL, is_origin=True)

		if lower == LOCAL:
			return cls(platform=LOCAL)

		# platform:chat_id[:thread_id] — keep original case for the ids (they can
		# be case-sensitive), lower-case only the platform token.
		if ":" in stripped:
			parts = stripped.split(":", 2)
			return cls(
				platform=parts[0].lower(),
				chat_id=parts[1] if len(parts) > 1 else None,
				thread_id=parts[2] if len(parts) > 2 else None,
				is_explicit=True,
			)

		# Bare platform name — home channel (chat_id resolved at delivery, if ever).
		return cls(platform=lower)

	def to_string(self) -> str:
		"""Round-trip back to the DSL string (used as the results-dict key)."""
		if self.is_origin:
			return "origin"
		if self.platform == LOCAL:
			return LOCAL
		if self.chat_id:
			base = f"{self.platform}:{self.chat_id}"
			return f"{base}:{self.thread_id}" if self.thread_id else base
		return self.platform


class DeliveryRouter:
	"""Fan content out to a list of targets. Stateless — safe to construct freely."""

	def deliver(
		self,
		content: str,
		targets: list[DeliveryTarget],
		job_id: str | None = None,
		job_name: str | None = None,
		metadata: dict | None = None,
	) -> dict:
		"""Deliver `content` to every target. Returns one result per target.

		Per-target `try/except` (faithful to Hermes `deliver`, `delivery.py:167`):
		a target that fails is recorded as `{success: False, error}` and the rest
		still go out. Keyed by each target's `to_string()`.
		"""
		results: dict = {}
		for target in targets:
			key = target.to_string()
			try:
				if target.platform == LOCAL or not self._platform_known(target.platform):
					result = self._deliver_local(content, job_id, job_name, metadata)
				else:
					result = self._deliver_to_session(target, content)
				results[key] = {"success": True, "result": result}
			except Exception as exc:
				results[key] = {"success": False, "error": str(exc)}
		return results

	# -- sinks ---------------------------------------------------------------

	def _deliver_to_session(self, target: DeliveryTarget, content: str) -> dict:
		"""Deliver to a channel by inserting one outbound `Chat Message` row (Q1).

		Oversized content is truncated and the full text saved to a private File
		(Q4). `thread_id` is intentionally ignored — Friday has no threads (Q5).
		"""
		if not target.chat_id:
			raise ValueError(f"no chat_id for {target.platform!r} delivery")

		body = content
		if len(body) > MAX_PLATFORM_OUTPUT:
			saved = self._save_full_output(content, target.chat_id)
			body = (
				content[:TRUNCATED_VISIBLE]
				+ f"\n\n... [truncated, full output saved to {saved}]"
			)

		doc = frappe.get_doc(
			{
				"doctype": "Chat Message",
				"session_id": target.chat_id,
				"platform": target.platform,
				"direction": "outbound",
				"sender_id": "system",
				"content": body,
				"timestamp": frappe.utils.now_datetime(),
				"processed": 1,
			}
		)
		doc.insert(ignore_permissions=True)
		return {"chat_message": doc.name}

	def _deliver_local(
		self,
		content: str,
		job_id: str | None,
		job_name: str | None,
		metadata: dict | None,
	) -> dict:
		"""Save content as a private Markdown `File` (Q3), header + body.

		Faithful to Hermes `_deliver_local` (`delivery.py:209`): a title, a
		timestamp, the job id, any metadata, then the content.
		"""
		now = frappe.utils.now_datetime()
		lines = [f"# {job_name}" if job_name else "# Delivery Output", ""]
		lines.append(f"**Timestamp:** {now}")
		if job_id:
			lines.append(f"**Job ID:** {job_id}")
		for key, value in (metadata or {}).items():
			lines.append(f"**{key}:** {value}")
		lines += ["", "---", "", content]

		file_doc = self._write_private_file(
			file_name=f"delivery_{job_id or 'misc'}_{frappe.utils.now()}.md",
			content="\n".join(lines),
		)
		return {"file": file_doc.file_url, "name": file_doc.name}

	def _save_full_output(self, content: str, key: str) -> str:
		"""Save the untruncated content to a private File; return its URL (Q4)."""
		file_doc = self._write_private_file(
			file_name=f"delivery_full_{key}_{frappe.utils.now()}.txt",
			content=content,
		)
		return file_doc.file_url

	def _write_private_file(self, file_name: str, content: str):
		"""Insert one private `File` row holding `content`. Returns the doc."""
		doc = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": file_name,
				"is_private": 1,
				"content": content,
			}
		)
		doc.insert(ignore_permissions=True)
		return doc

	# -- helpers -------------------------------------------------------------

	def _platform_known(self, platform: str) -> bool:
		"""True when `platform` is a configured `Chat Platform` (else → local)."""
		try:
			return bool(frappe.db.exists("Chat Platform", platform))
		except Exception:
			return False
