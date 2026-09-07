# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt

"""
The Friday routing package — how inbound messages get their target Agent Profile.

PLAIN ENGLISH
=============

When a message arrives at any surface (CLI, Telegram, Slack, Raven, A2A),
*somebody* has to decide "which Friday agent should handle this?" That
decision lives here.

The contract (per `docs/design/47-gateway-design-decisions.md` §4 Q3):
  - Adapters MUST set `Chat Message.agent_profile` BEFORE inserting the row.
  - The gateway VALIDATES that the field is set; rejects if empty.
  - Adapters that don't have an obvious resolution (e.g. Telegram, where
    the message doesn't name an agent) call `resolve.resolve_profile(...)`
    as a helper. The CLI does NOT use the helper — it has the profile
    from the `--profile` flag.

In v0.1, `resolve.resolve_profile` reads `Chat Platform.default_agent_profile`.
That's the full sophistication today. When more complex routing arrives
(per-chat, per-user, per-keyword), this helper grows. The contract — that
adapters set the field before insert — does NOT change.

MODULES
=======

- `resolve.py` — the `resolve_profile(platform, sender_id=None, chat_id=None,
  content=None)` helper. Returns a profile name or None.
- `dedup.py` — DEFERRED. The API shape is documented in the design doc
  (§4 Q4-D). Lands when the first webhook adapter ships.
"""
