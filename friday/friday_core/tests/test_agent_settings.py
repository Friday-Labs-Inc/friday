# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""
Real-DB tests for the Agent Settings singleton identity.

These are deliberately **not** mocked. The whole class of bug they guard against
(the singleton silently failing to exist, and reads as "Agent Settings" raising
DoesNotExistError) only shows up against real Frappe naming rules:

  * Frappe forbids a record named the same as its DocType, so the row CANNOT be
    "Agent Settings" — it is named "__default".
  * ``frappe.db.exists("Agent Settings", "Agent Settings")`` false-positives via
    the ``dt == dn`` single short-circuit, so any guard using it lies.

Mocks reproduce neither, which is exactly how the setup wizard shipped broken.
Run with ``bench --site <site> run-tests --module
friday.friday_core.tests.test_agent_settings``.
"""

import unittest

import frappe
from friday.friday_core.doctype.agent_settings.agent_settings import (
	SETTINGS_DOCTYPE,
	SETTINGS_NAME,
	ensure_agent_settings,
	get_agent_settings,
)


def _delete_all_settings() -> None:
	for nm in frappe.get_all(SETTINGS_DOCTYPE, pluck="name"):
		frappe.delete_doc(SETTINGS_DOCTYPE, nm, force=1, ignore_permissions=True)
	frappe.clear_document_cache(SETTINGS_DOCTYPE, SETTINGS_NAME)


class TestAgentSettingsSingleton(unittest.TestCase):
	def setUp(self):
		_delete_all_settings()
		frappe.db.commit()  # nosemgrep: frappe-semgrep-rules.rules.frappe-manual-commit

	def tearDown(self):
		# Leave the DB with the canonical singleton present for other suites.
		_delete_all_settings()
		ensure_agent_settings()
		frappe.db.commit()  # nosemgrep: frappe-semgrep-rules.rules.frappe-manual-commit

	def test_canonical_name_is_default(self):
		self.assertEqual(SETTINGS_NAME, "__default")
		self.assertEqual(SETTINGS_DOCTYPE, "Agent Settings")

	def test_ensure_creates_one_row_named_default(self):
		ensure_agent_settings()
		self.assertEqual(frappe.get_all(SETTINGS_DOCTYPE, pluck="name"), [SETTINGS_NAME])

	def test_ensure_is_idempotent(self):
		ensure_agent_settings()
		ensure_agent_settings()
		self.assertEqual(frappe.db.count(SETTINGS_DOCTYPE), 1)

	def test_get_agent_settings_self_heals_and_returns_singleton(self):
		# nothing exists yet (setUp cleared it); the accessor must create + return
		doc = get_agent_settings()
		self.assertEqual(doc.name, SETTINGS_NAME)

	def test_canonical_name_resolves_doctype_name_raises(self):
		ensure_agent_settings()
		# the right way works
		self.assertTrue(frappe.get_doc(SETTINGS_DOCTYPE, SETTINGS_NAME))
		# the trap (reading it as "Agent Settings") raises — pins the bug we fixed
		with self.assertRaises(frappe.DoesNotExistError):
			frappe.get_doc(SETTINGS_DOCTYPE, SETTINGS_DOCTYPE)
