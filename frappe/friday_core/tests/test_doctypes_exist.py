# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt

import unittest

import frappe

EXPECTED_DOCTYPES = {
	"Agent Profile": {"profile_name", "status"},
	"Agent Profile Skill": {"skill"},
	"Skill": {"skill_name", "description", "risk_level", "status"},
	"Skill Required DocType": {"target_doctype", "operation"},
	"Project": {"project_name", "status"},
	"Task": {"title", "priority"},
	"Task Skill": {"skill"},
	"Chat Message": {"session_id", "direction", "timestamp"},
	"Chat Platform": {"platform_name", "adapter_module"},
	"Execution Log": {"agent_profile", "skill", "status"},
	"Permission Decision Log": {"agent_profile", "skill", "decision", "decided_at"},
}


class TestDocTypesExist(unittest.TestCase):
	def test_each_doctype_exists_with_required_fields(self):
		for doctype, required_fieldnames in EXPECTED_DOCTYPES.items():
			with self.subTest(doctype=doctype):
				self.assertTrue(frappe.db.exists("DocType", doctype), f"DocType {doctype!r} missing")
				meta = frappe.get_meta(doctype)
				actual = {field.fieldname for field in meta.fields}
				missing = required_fieldnames - actual
				self.assertFalse(missing, f"DocType {doctype!r} missing required fields: {missing}")

	def test_submittable_doctypes_are_submittable(self):
		for doctype in ("Execution Log", "Permission Decision Log"):
			with self.subTest(doctype=doctype):
				meta = frappe.get_meta(doctype)
				self.assertEqual(
					meta.is_submittable,
					1,
					f"{doctype!r} must be submittable for audit-trail integrity",
				)
