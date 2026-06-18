# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt

import frappe
from frappe.locale import get_date_format, get_locale_value
from frappe.tests import IntegrationTestCase


class TestLocale(IntegrationTestCase):
	def test_get_locale_value_with_falsy_lang(self):
		"""Regression: ``get_locale_value`` raised ``UnboundLocalError`` when
		``frappe.local.lang`` was falsy — e.g. a freshly created site whose
		System Settings ``language`` is unset. ``value`` must be initialised
		before the ``if lang:`` guard so the final ``return value or ...`` is
		always safe. This path is hit by every ``render_template`` call (via
		``get_safe_globals`` -> ``get_date_format``), so the bug broke ALL
		Jinja rendering on such sites, not just locale lookups.
		"""
		original = frappe.local.lang
		try:
			frappe.local.lang = None
			# Must NOT raise UnboundLocalError; falls back to the system default.
			get_locale_value("date_format")
			# get_date_format wraps it and must always return a usable format.
			self.assertTrue(get_date_format())
		finally:
			frappe.local.lang = original
