# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt

"""
The chat REPL and one-turn handler — thin adapter over the unified gateway.

PLAIN ENGLISH
=============

This module is the CLI surface. It is INTENTIONALLY THIN. The actual
agent work happens in the gateway (`friday_core.gateway.service`).
The CLI's only jobs are:

  1. Read a line from the user.
  2. Write an inbound Chat Message row (this triggers the gateway via
     `doc_events.after_insert`).
  3. Wait for the outbound Chat Message row — Gateway v2 (design 55)
     runs the turn on the DEDICATED friday worker, so the reply lands
     moments later; the CLI polls for it (inline-fallback replies are
     found on the very first poll).
  4. Print it to stdout.
  5. Loop.

The CLI does NOT import `agent_runner`. The CLI does NOT call permission
or skill code. Everything happens through the Chat Message DocType and
the gateway's hook. This is the chokepoint pattern (see
`docs/design/47-gateway-design-decisions.md` §3 and §9).

TWO PUBLIC FUNCTIONS
====================

- `handle_user_message(profile, session_id, content) -> str`
      Process one turn end-to-end: write inbound, read the outbound the
      gateway produced, return the reply text. Tests call this directly
      so they don't need a REPL.

- `run_repl(profile)`
      The interactive loop. Opens a session, reads stdin lines, calls
      `handle_user_message`, prints replies, exits on EOF/Ctrl+D/`exit`.
      The `bench friday chat` command calls this.

WHY WE POLL THE OUTBOUND ROW (not subscribe via publish_realtime)
=================================================================

Gateway v2 (design 55, Q1): the "cli" Chat Platform dispatches to the
dedicated friday worker like every other surface; when no worker is
alive the gateway falls back to inline execution. Either way the reply
IS a Chat Message row — so the CLI polls for that row (commit-per-poll
to refresh the long-lived transaction's read snapshot). Inline replies
appear on the first poll; worker replies a moment later. A socketio
subscription would add a client dependency for zero UX gain here.

The gateway still fires `publish_realtime("chat.outbound", ...)` so
future Telegram/Slack/Raven adapters can subscribe to outbound events.
CLI doesn't subscribe.
"""

from __future__ import annotations

import getpass
import sys
import time
import uuid

import frappe

# The Chat Platform record's primary key for CLI-originated messages.
# Created on first use by `_ensure_cli_platform_record` so a fresh site
# Just Works without manual setup.
CLI_PLATFORM_NAME = "cli"
CLI_ADAPTER_MODULE = "friday.friday_core.cli.chat"

# Gateway v2 (design 55): how long the REPL waits for the worker's reply
# before pointing at the logs, and how often it polls. 180s = an LLM turn
# with the full retry budget; the worker job itself may run up to 600s,
# but a CLI user shouldn't sit past three minutes without feedback.
_REPLY_TIMEOUT_SECONDS = 180
_REPLY_POLL_INTERVAL_SECONDS = 0.5


# ---------------------------------------------------------------------------
# Public turn handler — the thing tests call
# ---------------------------------------------------------------------------


def handle_user_message(profile_name: str, session_id: str, content: str) -> str:
	"""Process one turn: write inbound, let gateway run, read outbound, return.

	This is the single source of truth for "what happens in a CLI turn".
	The REPL is just a loop around this function plus stdin/stdout.

	Returns the outbound reply text so the REPL can print it.

	The actual agent work happens in `friday_core.gateway.service`:
	the after_insert hook routes the row to the dedicated friday worker
	(or runs it inline as the Q1 fallback). Either way the reply arrives
	as an outbound Chat Message row, which we wait for below.
	"""
	_ensure_cli_platform_record()

	inbound = _write_inbound(
		profile_name=profile_name,
		session_id=session_id,
		content=content,
	)

	# Commit: (a) makes the inbound row visible to the friday worker, and
	# (b) fires the gateway's enqueue_after_commit job push. In a long-
	# lived CLI we must commit explicitly (Frappe defers to request
	# boundaries otherwise).
	frappe.db.commit()

	# Wait for THIS turn's outbound row (created after our inbound).
	# Inline-fallback replies exist already and are found on the first
	# poll; worker replies land a moment later.
	outbound_content = _wait_for_outbound(session_id, after_creation=inbound.creation)
	if outbound_content is None:
		# Timed out — the worker may be stuck or dead mid-turn. The
		# recovery sweeper will retry the orphan row; tell the user
		# where to look meanwhile.
		return (
			"(no reply after "
			f"{_REPLY_TIMEOUT_SECONDS}s — the friday worker may be busy or down; "
			"check `bench worker --queue friday` and the Frappe Error Log)"
		)
	return outbound_content


# ---------------------------------------------------------------------------
# Public REPL — the thing `bench friday chat` calls
# ---------------------------------------------------------------------------


def run_repl(profile_name: str) -> None:
	"""Run the interactive chat REPL until EOF, Ctrl+D, or `exit`.

	Each line of input becomes one inbound Chat Message. The gateway
	processes it and writes an outbound row. The REPL reads and prints
	the outbound.

	A session_id is generated at REPL start and reused for the lifetime
	of this REPL invocation. Sessions are ephemeral — closing the CLI
	ends the session. The messages persist in Frappe for audit.

	Errors during a turn (gateway crash, DB failure) are caught and
	printed inline — we don't want a single bad turn to kill the whole
	conversation.
	"""
	# Validate the profile exists upfront so the user gets a clean
	# error before we open a session and prompt them.
	if not frappe.db.exists("Agent Profile", profile_name):
		print(f"error: Agent Profile {profile_name!r} not found", file=sys.stderr)
		sys.exit(1)

	session_id = str(uuid.uuid4())
	print(f"Friday chat — profile {profile_name!r}, session {session_id}")
	print("Type 'exit', 'quit', or press Ctrl+D to leave.\n")

	while True:
		try:
			line = input("> ")
		except (EOFError, KeyboardInterrupt):
			print("\nbye.")
			return

		line = line.strip()
		if line in ("exit", "quit"):
			print("bye.")
			return
		if not line:
			continue

		try:
			reply = handle_user_message(profile_name, session_id, line)
			print(reply)
		except Exception as exc:
			frappe.log_error(title="friday chat turn failure")
			print(f"[error] {exc}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _ensure_cli_platform_record() -> None:
	"""Idempotently create the 'cli' Chat Platform row on first use.

	A fresh `bench new-site` has no Chat Platform records. Rather than
	require an install step, we check-and-create on the first chat
	turn. Subsequent turns find it and skip.

	Gateway v2 (design 55, Q1): the "cli" record dispatches "async" — the
	turn runs on the dedicated friday worker like every other surface,
	with the gateway's automatic inline fallback when no worker is alive.
	("sync" remains available as an explicit operator/test override on
	the Chat Platform row.)
	"""
	if frappe.db.exists("Chat Platform", CLI_PLATFORM_NAME):
		return
	frappe.get_doc(
		{
			"doctype": "Chat Platform",
			"platform_name": CLI_PLATFORM_NAME,
			"adapter_module": CLI_ADAPTER_MODULE,
			"enabled": 1,
			"dispatch_mode": "async",
			# CLI doesn't use the default — `--profile` is always provided.
			"default_agent_profile": None,
			# CLI doesn't batch — flush immediately. (Field unused by the
			# v0.1 batching stub; reserved for when real batching lands.)
			"batch_idle_ms": 0,
		}
	).insert(ignore_permissions=True)


def _write_inbound(profile_name: str, session_id: str, content: str):
	"""Insert one inbound Chat Message row. Returns the inserted doc.

	The gateway's `doc_events.after_insert` hook fires inside this call
	and routes the row (friday worker, or inline fallback). The reply is
	an outbound row that `_wait_for_outbound` picks up.

	`ignore_permissions=True` for the same reason the gateway uses it:
	this is system plumbing recording its own state.
	"""
	doc = frappe.get_doc(
		{
			"doctype": "Chat Message",
			"session_id": session_id,
			"platform": CLI_PLATFORM_NAME,
			"direction": "inbound",
			"sender_id": _current_user_label(),
			"agent_profile": profile_name,
			"content": content,
			"timestamp": frappe.utils.now_datetime(),
			"processed": 0,  # gateway flips to 1 after writing outbound
		}
	)
	doc.insert(ignore_permissions=True)
	return doc


def _wait_for_outbound(
	session_id: str,
	after_creation,
	timeout: float = _REPLY_TIMEOUT_SECONDS,
) -> str | None:
	"""Poll for this turn's outbound row until it appears or `timeout` passes.

	Gateway v2: the reply may be written by the dedicated friday worker in
	a different process/transaction. Each poll COMMITS first — a long-lived
	CLI transaction would otherwise keep reading a stale snapshot and never
	see the worker's row. Inline-fallback replies are found on poll #1
	(zero added latency vs the old sync read).
	"""
	deadline = time.monotonic() + timeout
	while True:
		# Manual commit is required: this is a long-lived CLI process polling
		# for a row written by ANOTHER process (the friday worker) — without a
		# commit, this transaction's read snapshot never sees it.
		frappe.db.commit()  # nosemgrep: frappe-semgrep-rules.rules.frappe-manual-commit
		content = _read_latest_outbound(session_id, after_creation)
		if content is not None:
			return content
		if time.monotonic() >= deadline:
			return None
		time.sleep(_REPLY_POLL_INTERVAL_SECONDS)


def _read_latest_outbound(session_id: str, after_creation) -> str | None:
	"""Read the outbound Chat Message produced for this turn.

	Filters by session + direction=outbound + creation > the inbound's
	creation. Returns the content, or None if no outbound was found
	(which shouldn't happen — the gateway always writes one).
	"""
	rows = frappe.get_all(
		"Chat Message",
		filters={
			"session_id": session_id,
			"direction": "outbound",
			"creation": (">=", after_creation),
		},
		fields=["content"],
		order_by="creation desc",
		limit=1,
	)
	return rows[0]["content"] if rows else None


def _current_user_label() -> str:
	"""Best-effort identifier for who's typing.

	Tries the OS login user; falls back to "cli-user". Used for the
	`sender_id` field on inbound messages so audit logs say *who*,
	not just "some CLI process".
	"""
	try:
		return getpass.getuser() or "cli-user"
	except Exception:
		return "cli-user"
