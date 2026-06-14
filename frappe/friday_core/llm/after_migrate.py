# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt

"""
Migration helper — seeded defaults for the Friday LLM stack.

Called on every `bench --site <site> migrate` via the `after_migrate` hook
in `frappe/hooks.py`.

What it does
============

Ensures the `Agent Settings` singleton row exists. This row holds global
defaults (e.g. `default_provider`, delegation limits). If it already exists,
this is a no-op.

The actual create/identity logic lives in the Agent Settings controller
(`doctype/agent_settings/agent_settings.py`) as the single source of truth —
the row is named `"__default"`, NOT "Agent Settings" (Frappe forbids a record
named the same as its DocType). This module just wires that helper into the
`after_migrate` hook so the singleton is always present when the site boots,
without operators creating it by hand.
"""

from __future__ import annotations

from frappe.friday_core.doctype.agent_settings.agent_settings import (
	ensure_agent_settings,
)

__all__ = ["ensure_agent_settings"]
