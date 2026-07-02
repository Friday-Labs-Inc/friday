# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""
Turn Event — one diary line of one agent turn (Design 93).

This table is the durable turn journal: while the ReAct loop runs, every step
(prompt built, LLM answered, tool returned, reply delivered) is appended here
the moment it happens, so a crashed turn resumes from its last line instead
of re-running from scratch.

UNLIKE Dispatcher Event (observability, purged at 30 days), this table is
load-bearing REPLAY STATE — the agent_runner reads it back. It is not the
audit trail either; that stays in Execution Log / LLM Usage Log / Chat
Message. Rows are purged after 7 days (design 93, Q6) — by then every turn
is long since finished or given up on.

All writes go through `agent_runner/journal.py:TurnJournal.record`. Direct
inserts are not expected anywhere else.
"""

import frappe
from frappe.model.document import Document


class TurnEvent(Document):
	"""Append-only journal row. No mutation; not user-editable."""

	pass


def on_doctype_update():
	"""(turn_id, seq) is unique — two racing resumers of the same turn cannot
	both append line N; the loser's write fails and is swallowed by the
	journal's savepoint guard (belt-and-braces on top of the session lock /
	task claim token that already serialize turns)."""
	frappe.db.add_unique("Turn Event", ["turn_id", "seq"], constraint_name="unique_turn_seq")
