# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""
Unit tests for the USER.md two-store split (design 80).

Memories carry a `memory_type` ('user_profile' vs 'general'); the `remember`
skill stores it; recall labels user-profile facts distinctly so the model treats
them as "about the user". Mock-based — no DB.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from frappe.friday_core.llm import memory as M

_H = "frappe.friday_core.skills.handlers_memory"


class TestMemoryTypeField(unittest.TestCase):
	def test_doctype_field_present_default_general(self):
		p = Path(__file__).resolve().parents[1] / "doctype" / "agent_memory" / "agent_memory.json"
		d = json.loads(p.read_text())
		field = next((f for f in d["fields"] if f.get("fieldname") == "memory_type"), None)
		self.assertIsNotNone(field)
		self.assertEqual(field["default"], "general")
		self.assertIn("user_profile", field["options"])
		self.assertIn("memory_type", d["field_order"])

	def test_skill_schema_has_memory_type(self):
		from frappe.friday_core.skills.bootstrap_memory import _SKILL

		props = _SKILL["parameters_schema"]["properties"]
		self.assertIn("memory_type", props)
		self.assertEqual(set(props["memory_type"]["enum"]), {"general", "user_profile"})


class TestFormatBlockLabels(unittest.TestCase):
	def test_user_profile_row_labelled_about_the_user(self):
		block = M._format_block(
			[{"memory": "prefers sans-serif", "subject": "BB-1", "memory_type": "user_profile"}], 2000
		)
		self.assertIn("[about the user] prefers sans-serif", block)

	def test_general_row_keeps_subject(self):
		block = M._format_block(
			[{"memory": "ships fridays", "subject": "BB-1", "memory_type": "general"}], 2000
		)
		self.assertIn("[BB-1] ships fridays", block)

	def test_general_no_subject_is_plain(self):
		block = M._format_block([{"memory": "ships fridays", "memory_type": "general"}], 2000)
		self.assertIn("- ships fridays", block)


class TestRememberStoresType(unittest.TestCase):
	def _remember(self, params):
		from frappe.friday_core.skills.handlers_memory import remember

		with (
			patch(f"{_H}.frappe") as fr,
			patch("frappe.friday_core.llm.memory.project_for_session", return_value=None),
			patch("frappe.friday_core.llm.embed.enqueue_embed"),
		):
			fr.flags.get.return_value = {"agent_profile": "P", "session_id": "s"}
			doc = MagicMock()
			doc.name = "AM-1"
			fr.get_doc.return_value = doc
			remember("remember", params)
			return fr.get_doc.call_args[0][0]

	def test_defaults_to_general(self):
		row = self._remember({"memory": "a fact"})
		self.assertEqual(row["memory_type"], "general")

	def test_stores_user_profile(self):
		row = self._remember({"memory": "user likes SMS", "memory_type": "user_profile"})
		self.assertEqual(row["memory_type"], "user_profile")

	def test_invalid_type_coerced_to_general(self):
		row = self._remember({"memory": "x", "memory_type": "bogus"})
		self.assertEqual(row["memory_type"], "general")


if __name__ == "__main__":
	unittest.main()
