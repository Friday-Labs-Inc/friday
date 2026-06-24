# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt

"""
The gateway command surface — one shared dispatcher for slash commands.

PLAIN ENGLISH
=============

When someone types `/approve` or `/status` into a chat, that is a *command*,
not a message for the agent. Commands are caught at the surface-adapter edge
(Raven, CLI) BEFORE a conversational `Chat Message` row is written (Design 82,
decision D1), and routed here.

This module is the single place all surfaces share (Design 82, Q1): an adapter's
only job is to (1) notice a leading "/", (2) call `dispatch_command(...)`, and
(3) deliver the returned reply through its own send path. The logic of *what a
command does* lives here, once, so Raven and CLI never drift.

v1 commands (Design 82, Q2; `/stop` by Design 83, `/steer` by Design 84):
  /approve [id]        — approve a paused, human-gated action
  /deny [reason]       — reject it (records the reason)
  /stop                — interrupt the running turn for this session
  /steer <text>        — nudge the running turn without stopping it
  /status              — show this session's state (read-only)
  /help                — list the commands

Permissions (Design 82, Q4): `/approve` and `/deny` are *operator-tier* — they
require the `Friday Operator` Frappe role. `/status` and `/help` are open to
anyone already allowed to talk in the channel.

Why `/approve` matters: Friday's human-approval gate already exists — a risky
skill pauses and writes a Pending `Workflow Request` (`approvals/workflow.py`).
Until now the only way to approve was Desk. This command makes the gate usable
from Raven, where the operator actually lives.
"""

from __future__ import annotations

from dataclasses import dataclass

import frappe
from frappe.friday_core.approvals.workflow import approve, reject

# The Frappe role that may run operator-tier commands (Design 82, Q4).
_OPERATOR_ROLE = "Friday Operator"


@dataclass(frozen=True)
class CommandResult:
	"""The outcome of one command, handed back to the calling adapter.

	- `handled` — True means the gateway dealt with this input; the adapter must
	  NOT pass it on to `run_turn`. (Always True here: by the time we're called,
	  the text was already a command.)
	- `ok` — True on success, False on refusal / not-found / error.
	- `reply` — the text the adapter posts back to the user.
	"""

	handled: bool
	ok: bool
	reply: str


# ---------------------------------------------------------------------------
# Detection + parsing (called by adapters)
# ---------------------------------------------------------------------------


def is_command(text: str) -> bool:
	"""True when `text` is a slash command (leading "/", whitespace tolerated).

	This is the D1 fork: a leading "/" is control traffic and never becomes a
	conversational row; anything else flows to the agent unchanged.
	"""
	return bool(text) and text.strip().startswith("/")


def parse_command(text: str) -> tuple[str, list[str]]:
	"""Split `/name arg1 arg2` into `("name", ["arg1", "arg2"])`.

	The name is lower-cased so `/Approve` and `/approve` are the same command.
	Returns `("", [])` for a bare "/" with nothing after it.
	"""
	parts = text.strip().lstrip("/").split()
	if not parts:
		return "", []
	return parts[0].lower(), parts[1:]


# ---------------------------------------------------------------------------
# The shared dispatcher (Design 82, Q1)
# ---------------------------------------------------------------------------


def dispatch_command(platform: str, session_id: str, user: str, raw: str) -> CommandResult:
	"""Resolve `raw` to a command, check the caller's role, run it.

	`platform`/`session_id` locate the channel; `user` is the Frappe user who
	issued the command (the adapter supplies it). The permission check (Q4)
	happens here, before the handler runs, so a refused command never touches
	the thing it would have changed.
	"""
	name, args = parse_command(raw)
	spec = _COMMANDS.get(name)
	if spec is None:
		return CommandResult(
			handled=True,
			ok=False,
			reply=f"Unknown command /{name or ''}. Try /help.",
		)

	handler, required_role = spec
	if required_role and required_role not in frappe.get_roles(user):
		return CommandResult(
			handled=True,
			ok=False,
			reply=f"/{name} requires the {required_role} role.",
		)

	return handler(session_id, user, args)


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


def _cmd_help(session_id: str, user: str, args: list[str]) -> CommandResult:
	"""List the v1 commands."""
	lines = [
		"Commands:",
		"  /approve [id]   — approve the paused action (oldest in this channel, or a named request)",
		"  /deny [reason]  — reject the paused action (reason recorded)",
		"  /stop           — interrupt the running turn for this session",
		"  /steer <text>   — nudge the running turn without stopping it",
		"  /status         — show this session's state",
		"  /help           — show this list",
	]
	return CommandResult(handled=True, ok=True, reply="\n".join(lines))


def _cmd_status(session_id: str, user: str, args: list[str]) -> CommandResult:
	"""Read-only snapshot of the session. Must NOT mutate anything."""
	try:
		pending = frappe.get_all(
			"Workflow Request",
			filters={"session_id": session_id, "status": "Pending"},
			pluck="name",
		)
		n_pending = len(pending)
	except Exception:
		# Defensive: a read failure must not make /status itself fail.
		n_pending = 0
	return CommandResult(
		handled=True,
		ok=True,
		reply=f"Session {session_id} — {n_pending} pending approval(s).",
	)


def _cmd_approve(session_id: str, user: str, args: list[str]) -> CommandResult:
	"""Approve a Pending Workflow Request (Design 82, Q5).

	Bare `/approve` targets the channel's OLDEST Pending request; an explicit id
	as the first arg overrides that.
	"""
	explicit_id = args[0] if args else None
	request_name = _resolve_pending_request(session_id, explicit_id)
	if not request_name:
		return CommandResult(
			handled=True, ok=False, reply="No pending approval in this channel."
		)
	try:
		approve(request_name, approved_by=user)
	except Exception as exc:
		return CommandResult(
			handled=True, ok=False, reply=f"Could not approve {request_name}: {exc}"
		)
	return CommandResult(handled=True, ok=True, reply=f"✅ Approved {request_name}.")


def _cmd_stop(session_id: str, user: str, args: list[str]) -> CommandResult:
	"""Interrupt the running turn for this session (Design 83).

	Sets the interrupt flag; the worker running the turn checks it at its next
	ReAct boundary and stops cleanly. A no-op when nothing is running — the flag
	self-expires (TTL) and the next turn clears it at entry.
	"""
	from frappe.friday_core.gateway.interrupt import request_interrupt

	request_interrupt(session_id)
	return CommandResult(handled=True, ok=True, reply="🛑 Stopping the current turn.")


def _cmd_steer(session_id: str, user: str, args: list[str]) -> CommandResult:
	"""Nudge the running turn for this session without stopping it (Design 84).

	Pushes the guidance into the steer slot; the worker running the turn drains
	it at its next ReAct boundary and the model sees it on the next call. A
	no-op when nothing is running — the slot self-expires (TTL) and the next
	turn clears it at entry.
	"""
	from frappe.friday_core.gateway.steer import push_steer

	text = " ".join(args).strip()
	if not text:
		return CommandResult(handled=True, ok=False, reply="usage: /steer <guidance>")
	push_steer(session_id, text)
	return CommandResult(handled=True, ok=True, reply="↪ Steering the current turn.")


def _cmd_deny(session_id: str, user: str, args: list[str]) -> CommandResult:
	"""Reject the channel's oldest Pending Workflow Request, recording a reason.

	v1 is reason-first (`/deny too risky`); explicit-id deny is deferred to the
	interrupt/steer PR, where richer command parsing lands.
	"""
	reason = " ".join(args).strip()
	request_name = _resolve_pending_request(session_id, None)
	if not request_name:
		return CommandResult(
			handled=True, ok=False, reply="No pending approval in this channel."
		)
	try:
		reject(request_name, approved_by=user, reason=reason)
	except Exception as exc:
		return CommandResult(
			handled=True, ok=False, reply=f"Could not deny {request_name}: {exc}"
		)
	tail = f" ({reason})" if reason else ""
	return CommandResult(handled=True, ok=True, reply=f"🚫 Denied {request_name}.{tail}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_pending_request(session_id: str, explicit_id: str | None) -> str | None:
	"""Pick the Workflow Request a command should act on (Design 82, Q5).

	An explicit id wins outright. Otherwise return the OLDEST Pending request in
	this channel (creation ascending, limit 1) — "approve the thing you just
	asked me about". Returns None when nothing is pending.
	"""
	if explicit_id:
		return explicit_id
	rows = frappe.get_all(
		"Workflow Request",
		filters={"session_id": session_id, "status": "Pending"},
		fields=["name"],
		order_by="creation asc",
		limit=1,
	)
	return rows[0]["name"] if rows else None


# The command table (Design 82, Q1 + Q4). name -> (handler, required_role|None).
# Defined after the handlers so the references resolve.
_COMMANDS: dict[str, tuple] = {
	"approve": (_cmd_approve, _OPERATOR_ROLE),
	"deny": (_cmd_deny, _OPERATOR_ROLE),
	"stop": (_cmd_stop, _OPERATOR_ROLE),
	"steer": (_cmd_steer, _OPERATOR_ROLE),
	"status": (_cmd_status, None),
	"help": (_cmd_help, None),
}
