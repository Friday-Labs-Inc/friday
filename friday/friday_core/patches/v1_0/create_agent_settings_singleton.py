# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""Create (or heal) the Agent Settings singleton row on existing sites.

The `after_migrate` hook already calls `ensure_agent_settings`, but historically
that helper was broken two ways — it guarded on the false-positive
`exists("Agent Settings", "Agent Settings")` (which short-circuits because
name == doctype) AND inserted under the forbidden name "Agent Settings" — so on
many sites the row was never created and the setup wizard / provider resolution
failed with "Agent Settings not found".

This patch runs the corrected helper once, post model sync, so every existing
site ends with exactly one Agent Settings row named "__default". Idempotent:
a no-op where the row already exists.
"""

from friday.friday_core.doctype.agent_settings.agent_settings import ensure_agent_settings


def execute():
	ensure_agent_settings()
