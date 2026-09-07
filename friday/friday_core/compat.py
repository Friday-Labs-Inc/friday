"""Upstream Frappe fixes Friday still carries, and why.

PLAIN ENGLISH
=============
When Friday was a fork it could edit Frappe directly. As an app it cannot — so
anything it genuinely needs from the framework is either (a) already fixed
upstream, (b) a small runtime patch applied here with a PR pending, or (c) an
operator step. Keeping the list SHORT and visible is the point: an app that
monkeypatches its framework freely is a fork wearing a disguise.

Audited against frappe/frappe@version-16 on 2026-09-06:

  frappe/desk/doctype/number_card/number_card.py — DROPPED. The fork passed
    `order_by=None` so Postgres would not reject `ORDER BY` on a non-grouped
    column in an aggregate query. Upstream v16 now does exactly this. Nothing
    to carry.

  frappe/api/__init__.py — DROPPED. The fork changed `ApiVersion(str, Enum)` to
    `StrEnum`. Cosmetic; upstream still uses the former and works.

  frappe/locale.py — CARRIED (see `patch_locale_unbound_value` below).

  frappe/app.py — NOT PATCHABLE from an app, and deliberately not monkeypatched.
    The fork special-cased `/.well-known/agent.json` to serve the A2A Agent Card
    before Frappe's generic well-known handler (which raises NotFound for
    anything it does not recognise, so an app cannot claim the path through
    website routing either).

    The card is a guest-readable endpoint regardless:

        /api/method/friday.friday_core.a2a.server.agent_card

    For spec-compliant discovery, alias it at the reverse proxy, e.g. nginx:

        location = /.well-known/agent.json {
            rewrite ^ /api/method/friday.friday_core.a2a.server.agent_card last;
        }

    The clean upstream fix is a `wellknown_handlers` hook in Frappe so apps can
    register their own paths. Until then this is an operator step, not a patch.
"""

from __future__ import annotations

import frappe


def patch_locale_unbound_value() -> None:
	"""frappe.locale.get_locale_value raises UnboundLocalError when lang is falsy.

	Upstream (version-16) reads::

	    lang = language or frappe.local.lang
	    if lang:
	        value = frappe.client_cache.get_doc("Language", lang).get(key)
	    return value or frappe.db.get_default(key)

	`value` is only bound inside the `if`, so any call made without a language —
	a background job before the session sets one, a guest request on a site with
	no default — raises UnboundLocalError instead of falling back to the system
	default. Friday hits this from scheduler jobs, which run before a lang is set.

	The fix is one line upstream (`value = None` before the branch). Until that
	lands, wrap the function so the fallback works. Idempotent, and a no-op the
	moment upstream fixes it.
	"""
	import frappe.locale as locale_module

	if getattr(locale_module.get_locale_value, "_friday_patched", False):
		return

	original = locale_module.get_locale_value

	def get_locale_value(key: str, language: str | None = None) -> str | None:
		try:
			return original(key, language)
		except UnboundLocalError:
			# The upstream bug, exactly: no language in scope. The intended
			# behaviour is the system default.
			return frappe.db.get_default(key)

	get_locale_value._friday_patched = True  # type: ignore[attr-defined]
	locale_module.get_locale_value = get_locale_value


def apply() -> None:
	"""Apply every carried fix. Called once from friday/hooks.py at import."""
	try:
		patch_locale_unbound_value()
	except Exception:
		# A compat shim must never take the site down; if it fails, the
		# underlying upstream behaviour simply stands.
		frappe.logger("friday.compat").warning("compat patch failed", exc_info=True)
