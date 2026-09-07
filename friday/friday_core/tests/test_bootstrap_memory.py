# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""Finding #19 (design 95 deploy verify): the remember Skill row's schema
silently drifted from the code because provision() is CLI-only and nothing on
the migrate path refreshed it — the deployed tool definition lacked the new
`scope` param. Pins: the migrate-path ensure UPSERTS an existing row (not
create-only), the schema it writes carries scope, and a failure never aborts
the migrate."""

from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock, patch

from friday.friday_core.skills import bootstrap_memory as bm

_M = "friday.friday_core.skills.bootstrap_memory"


class TestEnsureMemorySkill(unittest.TestCase):
	@patch(f"{_M}.frappe")
	def test_existing_row_is_updated_not_skipped(self, fr):
		fr.db.exists.return_value = True
		skill = MagicMock()
		fr.get_doc.return_value = skill

		bm.ensure_memory_skill()

		schema = json.loads(skill.parameters_schema)
		self.assertIn("scope", schema["properties"])  # the #19 drift, pinned
		self.assertEqual(schema["properties"]["scope"]["enum"], ["project", "global"])
		self.assertEqual(skill.status, "Active")
		skill.save.assert_called_once()

	@patch(f"{_M}.frappe")
	def test_missing_row_is_created(self, fr):
		fr.db.exists.return_value = False
		skill = MagicMock()
		fr.new_doc.return_value = skill

		bm.ensure_memory_skill()

		self.assertEqual(skill.skill_name, "remember")
		skill.save.assert_called_once()


class TestEnsureMemoryProvisioned(unittest.TestCase):
	@patch(f"{_M}.ensure_memory_skill")
	@patch(f"{_M}.ensure_memory_role")
	@patch(f"{_M}.frappe")
	def test_runs_role_then_skill(self, fr, m_role, m_skill):
		bm.ensure_memory_provisioned()
		m_role.assert_called_once()
		m_skill.assert_called_once()

	@patch(f"{_M}.ensure_memory_role")
	@patch(f"{_M}.frappe")
	def test_failure_never_aborts_the_migrate(self, fr, m_role):
		m_role.side_effect = RuntimeError("boom")
		bm.ensure_memory_provisioned()  # must not raise
		fr.log_error.assert_called()


if __name__ == "__main__":
	unittest.main()
