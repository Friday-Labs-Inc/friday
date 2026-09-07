# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt

"""
Agent Profile resolution — which agent handles an inbound message?

PLAIN ENGLISH
=============

The CLI doesn't need this — it always has the profile from `--profile`.
A2A doesn't need this — the sending agent names the recipient directly.

External platform adapters (Telegram, Slack, Raven) call this to translate
their world ("a message in chat 12345 from user 555") to a Friday concept
("Agent Profile 'Support Agent'").

TWO ROUTING RULES TODAY
=======================

1. **Project room -> the project's lead (Design 73, Slice 3).** When the message
   arrives in a chat that maps to a Project (a Raven project channel, or a
   ``task::`` session) and that Project has a `project_lead_profile` that is an
   Active agent, route to it — so a human talking in `proj-fli-001` reaches
   FLI-001's own commander, not a one-size-fits-all default. This is what makes
   each project room feel like talking to *that* project's team.
2. **Fallback -> the platform default.** Anything else — a non-project channel, a
   DM, a project with no lead set, or a lead that's Suspended/Retired — falls
   back to `Chat Platform.default_agent_profile`, exactly as before Slice 3.

WHY THIS IS A SEPARATE PACKAGE
==============================

So that every adapter that ever resolved a profile is already calling THIS
function — not its own ad-hoc logic. The function body grows; no adapter
changes. See the project memory rule `feedback-unified-gateway-service`.
"""

from __future__ import annotations

import frappe
from friday.friday_core.llm.memory import project_for_session


def resolve_profile(
	platform: str,
	sender_id: str | None = None,
	chat_id: str | None = None,
	content: str | None = None,
) -> str | None:
	"""Return the Agent Profile name an inbound message should be routed to.

	Arguments:
	  - `platform`: the `Chat Platform` primary key the message came from
	    (e.g. "cli", "telegram", "slack", "a2a", "raven").
	  - `chat_id`: the surface's conversation id (for Raven, the channel id).
	    Used to find the project room's lead (rule 1 above). `sender_id` and
	    `content` are reserved for future per-user / keyword routing rules.

	Returns the profile name (string), or `None` if no rule matches and the
	platform has no default. Callers are expected to handle `None` (typically:
	write a system-error outbound row and give up).
	"""
	if not frappe.db.exists("Chat Platform", platform):
		# Platform record doesn't exist — adapter setup is incomplete. Returning
		# None lets the caller surface a clean error rather than crashing here.
		return None

	# Rule 1 — a project room is answered by that project's lead.
	lead = _project_lead_for(chat_id)
	if lead:
		return lead

	# Rule 2 — the platform default (pre-Slice-3 behaviour, unchanged).
	default = frappe.db.get_value("Chat Platform", platform, "default_agent_profile")
	return default or None


def _project_lead_for(chat_id: str | None) -> str | None:
	"""The Active project_lead_profile of the project this chat maps to, or None.

	Returns None for a chat that isn't a project room, a project with no lead, or
	a lead that isn't Active — each of which falls through to the platform
	default. We never route to a Suspended/Retired agent: a dead lead must not
	swallow the room's messages.
	"""
	if not chat_id:
		return None
	project = project_for_session(chat_id)
	if not project:
		return None
	lead = frappe.db.get_value("Agent Project", project, "project_lead_profile")
	if not lead:
		return None
	if frappe.db.get_value("Agent Profile", lead, "status") != "Active":
		return None
	return lead
