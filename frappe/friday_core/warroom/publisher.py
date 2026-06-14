# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""
War Room publisher — posts Task status updates to the Raven FRIDAY_WAR_ROOM channel.

Graceful degradation
------------------
- If the ``Raven Channel`` DocType does not exist in the site schema,
  the function logs at INFO level and returns silently.
- If the ``FRIDAY_WAR_ROOM`` channel is not found, logs at WARNING and returns.
- If posting the message to Raven raises, logs at ERROR and returns.
- **Never raises an exception. Never blocks the task pipeline.**

Activation
----------
Activate when Raven is installed in v0.2.  Code already exists; the
existence check on ``Raven Channel`` ensures zero-cost passthrough when
Raven is absent.
"""

import logging
from typing import Optional

import frappe

__all__ = ["post_task_update"]

_logger = logging.getLogger("friday.warroom")

CHANNEL_NAME = "FRIDAY_WAR_ROOM"
CHANNEL_DOCTYPE = "Raven Channel"


def post_task_update(
	task_name: str,
	event: str,
	details: dict | None = None,
) -> None:
	"""
	Post a task status update to the Raven War Room channel.

	Args:
		task_name: The ``Task`` document name (e.g. ``AT-000042``).
		event: One of the state-transition event strings:
		       ``assigned``, ``executing``, ``completed``, ``blocked``,
		       ``cancelled``, ``error``, ``oom``, ``timeout``.
		details: Optional extra data to include in the message payload.
	"""
	# Fast path: skip entirely if Raven Channel DocType is not installed.
	if not _is_raven_installed():
		_logger.info(
			"Raven not installed, skipping War Room post for task %s event %s",
			task_name,
			event,
		)
		return

	channel_id = _get_channel_id()
	if not channel_id:
		# Channel exists in schema but somehow wasn't found — degrade gracefully.
		_logger.warning(
			"War Room channel %s not found, skipping post for task %s event %s",
			CHANNEL_NAME,
			task_name,
			event,
		)
		return

	_payload = _build_payload(task_name, event, details)
	# Graceful degradation: network/HTTP failures publishing to Raven must
	# never propagate up — a War Room outage shouldn't crash the agent.
	# Log at ERROR so ops dashboards can alert on it.
	try:
		_post_to_raven(channel_id, _payload)
	except Exception as exc:
		_logger.error(
			"War Room post failed for task %s event %s: %s",
			task_name,
			event,
			exc,
		)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _is_raven_installed() -> bool:
	"""
	Return True only when the ``Raven Channel`` DocType is present in the
	installed apps' schema (i.e. the Raven app is installed on this site).
	"""
	try:
		# Check via the table catalogue (information_schema), NOT by querying
		# the table itself. The old probe issued `SELECT ... FROM "tabRaven
		# Channel"` — when the table is absent that statement FAILS, and on
		# Postgres a failed statement ABORTS the surrounding transaction even
		# though the exception is caught here ("graceful" on MariaDB,
		# transaction-poisoning on Postgres: every later statement dies with
		# InFailedSqlTransaction).
		return frappe.db.table_exists(CHANNEL_DOCTYPE)
	except Exception:
		return False


def _get_channel_id() -> str | None:
	"""
	Return the Raven Channel document name for CHANNEL_NAME, or None if not found.

	Raven lowercases `channel_name` on save (the War Room is stored as
	`friday_war_room`), so we look it up by the lowercased slug — matching how
	`surfaces/bootstrap_raven` seeds it.
	"""
	try:
		channel = frappe.db.get_value(
			CHANNEL_DOCTYPE,
			{"channel_name": CHANNEL_NAME.strip().lower().replace(" ", "-")},
			"name",
			as_dict=True,
		)
		return channel.name if channel else None
	except Exception:
		return None


def _build_payload(task_name: str, event: str, details: dict | None) -> dict:
	"""
	Assemble the message dict posted to Raven.

	Args:
		task_name: Task document name.
		event: Transition event string.
		details: Optional supplementary data.

	Returns:
		Message dict ready for the Raven API.
	"""
	import datetime

	text = _format_message_text(task_name, event, details)
	return {
		"text": text,
		"channel_id": None,  # set by caller after lookup
		"message_type": "Text",
		"hide_in_message_history": False,
		"creation": datetime.datetime.utcnow().isoformat(),
	}


def _format_message_text(task_name: str, event: str, details: dict | None) -> str:
	"""Format a human-readable War Room message.

	Design 62 — the message leads with the AGENT as speaker so the War
	Room shows *who* did the work, not a single faceless voice. The agent
	profile (from ``details['profile']``) headlines the line; the task ref
	and event follow.
	"""
	details = details or {}
	profile = details.get("profile")

	if profile:
		text = f"🤖 **{profile}**\n   `[{task_name}]` {event}"
	else:
		# No known agent (e.g. a system-level transition) — fall back to the
		# task-led format.
		text = f"**[{task_name}]** — *{event}*"

	for k, v in details.items():
		if k == "profile":
			continue  # already the headline
		if k == "error_message" and v:
			text += f"\n  > Error: {v}"
		elif k == "duration_ms" and v:
			text += f"\n  > Duration: {v}ms"
		elif k == "skills" and v:
			text += f"\n  > Skills: {', '.join(v)}"
		elif v:
			text += f"\n  > {k}: {v}"

	return text


def _post_to_raven(channel_id: str, payload: dict) -> None:
	"""
	Post a message to the Raven channel IN-PROCESS.

	Calls ``raven.api.raven_message.send_message`` directly — no HTTP round-trip.
	The previous implementation POSTed to ``/api/method/raven.api.send_message``,
	which is wrong two ways:

	  1. that method does not exist in Raven 2.x — the function lives at
	     ``raven.api.raven_message.send_message`` (Frappe's RPC dispatcher raised
	     "module 'raven.api' has no attribute 'send_message'" on every call), and
	  2. it authenticated with ``Cookie: sid=<session>``, but the War Room post
	     fires from a background worker / the task-transition hook, where there is
	     no HTTP session — so even with the right path it would 403.

	Net effect of the old path: every War Room post silently failed. The
	in-process call inserts a Raven Message in the CURRENT transaction (it does
	no commit of its own), firing Raven's own realtime hooks so the channel
	updates live. ``send_message`` takes ``channel_id`` and ``text`` only;
	``message_type`` is "Text" internally, so the old ``message_type`` /
	``hide_in_message_history`` keys are dropped. Failures propagate to
	``post_task_update``, which logs and degrades gracefully.

	Args:
		channel_id: The ``Raven Channel`` document name.
		payload: The message dict built by _build_payload (only ``text`` is used).
	"""
	from raven.api.raven_message import send_message

	send_message(channel_id=channel_id, text=payload["text"])
