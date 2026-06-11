# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""
War Room publisher — posts Task status updates to the Raven FRIDAY_WAR_ROOM channel.

Graceful degradation
------------------
- If the ``Raven Channel`` DocType does not exist in the site schema,
  the function logs at INFO level and returns silently.
- If the ``FRIDAY_WAR_ROOM`` channel is not found, logs at WARNING and returns.
- If a network error occurs during the HTTP call, logs at ERROR and returns.
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
	details: Optional[dict] = None,
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


def _get_channel_id() -> Optional[str]:
	"""
	Return the Raven Channel document name for CHANNEL_NAME, or None if not found.
	"""
	try:
		channel = frappe.db.get_value(
			CHANNEL_DOCTYPE,
			{"channel_name": CHANNEL_NAME},
			"name",
			as_dict=True,
		)
		return channel.name if channel else None
	except Exception:
		return None


def _build_payload(task_name: str, event: str, details: Optional[dict]) -> dict:
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


def _format_message_text(task_name: str, event: str, details: Optional[dict]) -> str:
	"""Format a human-readable War Room message."""
	import frappe

	text = f"**[{task_name}]** — *{event}*"

	if details:
		text += "\n"
		for k, v in details.items():
			if k == "error_message" and v:
				text += f"\n  > Error: {v}"
			elif k == "duration_ms" and v:
				text += f"\n  > Duration: {v}ms"
			elif k == "profile" and v:
				text += f"\n  > Profile: {v}"
			elif k == "skills" and v:
				text += f"\n  > Skills: {', '.join(v)}"
			else:
				text += f"\n  > {k}: {v}"

	return text


def _post_to_raven(channel_id: str, payload: dict) -> None:
	"""
	POST a message to the Raven channel via the Frappe RPC API.

	The standard Raven endpoint is::

	    /api/method/raven.api.send_message

	which accepts ``channel_id``, ``text``, ``message_type``, etc.

	Args:
		channel_id: The ``Raven Channel`` document name.
		payload: The message dict built by _build_payload.
	"""
	import requests

	endpoint = (
		frappe.utils.get_url()
		+ "/api/method/raven.api.send_message"
	)

	headers = {
		"Content-Type": "application/json",
		# Use the current session cookie if available; otherwise fall back to
		# the API key header that the Frappe Realtime worker sets.
		"Cookie": f"sid={frappe.session.sid}" if hasattr(frappe, "session") else "",
	}

	data = {
		"channel_id": channel_id,
		"text": payload["text"],
		"message_type": payload["message_type"],
		"hide_in_message_history": payload["hide_in_message_history"],
	}

	try:
		requests.post(
			endpoint,
			json=data,
			headers=headers,
			timeout=5,
		)
	except requests.exceptions.Timeout:
		_logger.error(
			"War Room post timed out for task %s event %s",
			_extract_task_name(payload.get("text", "")),
			"timeout",
		)
	except requests.exceptions.RequestException as exc:
		_logger.error(
			"War Room post failed for task %s: %s",
			_extract_task_name(payload.get("text", "")),
			exc,
		)


def _extract_task_name(text: str) -> str:
	"""Pull the task name out of the formatted message text for logging."""
	# Message format: **[{task_name}]** — *{event}*
	if text and "][" in text:
		return text.split("][")[1].split("]")[0]
	return "?"