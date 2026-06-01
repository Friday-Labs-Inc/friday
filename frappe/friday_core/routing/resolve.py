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
("Agent Profile 'Support Agent'"). In v0.1 the only routing rule is the
`Chat Platform.default_agent_profile` fallback. Richer routing (per-chat
mappings, per-user mappings, keyword routing) lands as a separate
DocType when the first webhook adapter has concrete needs.

WHY THIS IS A SEPARATE PACKAGE EVEN THOUGH IT'S A ONE-LINER TODAY
=================================================================

So that when richer routing lands, every adapter that ever resolved a
profile is already calling THIS function — not its own ad-hoc logic.
The function body grows; no adapter changes. See the project memory
rule `feedback-unified-gateway-service`.
"""

from __future__ import annotations

import frappe


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
	  - `sender_id`, `chat_id`, `content`: platform-specific identifiers
	    that more sophisticated routing rules will consult. Today they
	    are accepted in the signature but unused — reserved for the
	    future rules engine.

	Returns the profile name (string) if resolution succeeds, or `None`
	if no rule matches and the platform has no default. Callers are
	expected to handle `None` (typically: write a system-error outbound
	row and give up).

	Today's only rule: read `Chat Platform.default_agent_profile`.
	"""
	if not frappe.db.exists("Chat Platform", platform):
		# Platform record doesn't exist — adapter setup is incomplete.
		# Returning None lets the caller surface a clean error rather than
		# crashing here.
		return None

	default = frappe.db.get_value("Chat Platform", platform, "default_agent_profile")
	return default or None
