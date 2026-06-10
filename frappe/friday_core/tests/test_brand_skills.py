# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""
Unit tests for the brand skills (design 56, LOCKED) — handlers + bootstrap.

Mock-based — no DB — so they run on the dev Mac and in CI. They pin:
  - validation contract: missing/unknown params raise ValueError with
    model-actionable messages (the dispatcher feeds these back, loop A.3)
  - persistence shape: Brand Direction insert fields, palette list → JSON
    string, brief status flip, ignore_permissions (gate already decided)
  - registration: both skills land in the dispatcher registry on import
  - bootstrap specs: schemas are valid JSON-serialisable tool schemas and
    required_doctypes match what each handler actually touches

The DB-backed end-to-end (real Skill rows + matrix + dispatch) runs on the
bench; the live proof is in the PR.
"""

import json
import unittest
from unittest.mock import MagicMock, patch

from frappe.friday_core.skills import handlers_brand

_H = "frappe.friday_core.skills.handlers_brand"


def _brief_doc(**overrides):
	doc = MagicMock()
	values = {
		"business_name": "Loop Coffee",
		"industry": "Specialty coffee",
		"what_they_do": "Single-origin roastery",
		"target_audience": "Urban 25-40",
		"brand_personality": "warm, crafted, honest",
		"competitors": "Blue Tokai",
		"color_preferences": "earth tones, no neon",
		"inspirations": "Aesop",
		"notes": "",
		"status": "Ready",
	}
	values.update(overrides)
	doc.get.side_effect = lambda f: values.get(f)
	doc.business_name = values["business_name"]
	return doc


class TestGetBrandBrief(unittest.TestCase):
	def test_missing_brief_param_raises_actionable_error(self):
		with self.assertRaises(ValueError) as ctx:
			handlers_brand.get_brand_brief("get-brand-brief", {})
		self.assertIn("brief", str(ctx.exception))

	@patch(f"{_H}.frappe")
	def test_unknown_brief_raises(self, mock_frappe):
		mock_frappe.db.exists.return_value = False
		with self.assertRaises(ValueError) as ctx:
			handlers_brand.get_brand_brief("get-brand-brief", {"brief": "BB-9999"})
		self.assertIn("BB-9999", str(ctx.exception))

	@patch(f"{_H}.frappe")
	def test_returns_content_fields(self, mock_frappe):
		mock_frappe.db.exists.return_value = True
		mock_frappe.get_doc.return_value = _brief_doc()
		out = handlers_brand.get_brand_brief("get-brand-brief", {"brief": "BB-0001"})
		self.assertEqual(out["brief"], "BB-0001")
		self.assertEqual(out["business_name"], "Loop Coffee")
		self.assertEqual(out["brand_personality"], "warm, crafted, honest")
		self.assertIn("Loop Coffee", out["result"])


class TestCreateBrandDirection(unittest.TestCase):
	def _params(self, **overrides):
		params = {
			"brief": "BB-0001",
			"direction_name": "Midnight Atelier",
			"concept_story": "A quiet, premium direction built on craft.",
			"personality_keywords": "calm, premium, crafted",
			"color_palette": [{"hex": "#1A1A2E", "name": "Ink Navy", "role": "primary"}],
			"typography": "Fraunces for headings, Inter for body.",
			"logo_concept": "A roundel monogram with a coffee-leaf negative space.",
			"tagline_options": "Brewed deliberate.\nCraft in every cup.",
		}
		params.update(overrides)
		return params

	def test_missing_required_params_raise(self):
		for missing in ("brief", "direction_name", "concept_story"):
			params = self._params()
			params[missing] = ""
			with self.assertRaises(ValueError) as ctx:
				handlers_brand.create_brand_direction("create-brand-direction", params)
			self.assertIn(missing, str(ctx.exception))

	@patch(f"{_H}.frappe")
	def test_unknown_brief_raises(self, mock_frappe):
		mock_frappe.db.exists.return_value = False
		with self.assertRaises(ValueError):
			handlers_brand.create_brand_direction("create-brand-direction", self._params())

	@patch(f"{_H}.frappe")
	def test_inserts_direction_and_flips_brief_status(self, mock_frappe):
		mock_frappe.db.exists.return_value = True
		doc = MagicMock()
		doc.name = "BD-0001"
		mock_frappe.get_doc.return_value = doc

		out = handlers_brand.create_brand_direction("create-brand-direction", self._params())

		payload = mock_frappe.get_doc.call_args[0][0]
		self.assertEqual(payload["doctype"], "Brand Direction")
		self.assertEqual(payload["brief"], "BB-0001")
		self.assertEqual(payload["direction_name"], "Midnight Atelier")
		self.assertEqual(payload["status"], "Proposed")
		# palette list arrives as a JSON STRING in the field
		self.assertIsInstance(payload["color_palette"], str)
		self.assertEqual(json.loads(payload["color_palette"])[0]["hex"], "#1A1A2E")
		doc.insert.assert_called_once_with(ignore_permissions=True)
		# brief status flips so the team sees progress in list view
		mock_frappe.db.set_value.assert_called_once_with(
			"Brand Brief", "BB-0001", "status", "Directions Generated", update_modified=False
		)
		self.assertEqual(out["record_name"], "BD-0001")

	@patch(f"{_H}.frappe")
	def test_palette_json_string_passes_through(self, mock_frappe):
		mock_frappe.db.exists.return_value = True
		mock_frappe.get_doc.return_value = MagicMock(name="BD-0002")
		raw = '[{"hex": "#FFFFFF", "name": "White", "role": "background"}]'
		handlers_brand.create_brand_direction(
			"create-brand-direction", self._params(color_palette=raw)
		)
		self.assertEqual(mock_frappe.get_doc.call_args[0][0]["color_palette"], raw)


class TestRegistration(unittest.TestCase):
	def test_both_skills_registered_with_dispatcher(self):
		from frappe.friday_core.agent_runner import dispatcher

		self.assertIs(
			dispatcher._SKILL_HANDLERS.get("get-brand-brief"), handlers_brand.get_brand_brief
		)
		self.assertIs(
			dispatcher._SKILL_HANDLERS.get("create-brand-direction"),
			handlers_brand.create_brand_direction,
		)


class TestBootstrapSpecs(unittest.TestCase):
	def test_schemas_are_valid_tool_schemas(self):
		from frappe.friday_core.skills.bootstrap_brand import _SKILLS

		for name, spec in _SKILLS.items():
			schema = spec["parameters_schema"]
			json.dumps(schema)  # serialisable
			self.assertEqual(schema["type"], "object", name)
			self.assertIn("required", schema, name)
			for required_field in schema["required"]:
				self.assertIn(required_field, schema["properties"], name)

	def test_required_doctypes_match_what_handlers_touch(self):
		from frappe.friday_core.skills.bootstrap_brand import _SKILLS

		self.assertEqual(
			_SKILLS["get-brand-brief"]["required_doctypes"],
			[{"target_doctype": "Brand Brief", "operation": "read"}],
		)
		self.assertEqual(
			_SKILLS["create-brand-direction"]["required_doctypes"],
			[{"target_doctype": "Brand Direction", "operation": "create"}],
		)


if __name__ == "__main__":
	unittest.main()
