# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""Design 95 Slice 4 — grounded research tooling for the Brand Strategist.

DB-free. Pins the slice's contract:
  - The RESEARCH_SKILLS names are in LOCKSTEP with what the MCP sync actually
    mints for a server named "Tavily" advertising tavily-search/tavily-extract
    — a naming drift would make the grant silently no-op forever.
  - The grant is CONDITIONAL: only Skill rows that exist are appended (a site
    without the Tavily registration is a clean no-op, never a broken Link).
  - The strategy prompt carries the grounded-research step, names the exact
    tools, and mandates the honest "ungrounded" fallback when they're absent.
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from frappe.friday_core.domains import randompack_brand as brand
from frappe.friday_core.mcp import sync

_M = "frappe.friday_core.domains.randompack_brand"


class TestSkillNameLockstep(unittest.TestCase):
	def test_research_skills_match_what_sync_mints(self):
		# Server row "Tavily" + the two tools we include on registration.
		slug = sync.sanitize("Tavily")
		expected = {
			sync.skill_name_for(slug, "tavily-search"),
			sync.skill_name_for(slug, "tavily-extract"),
		}
		self.assertEqual(set(brand.RESEARCH_SKILLS), expected)


class TestStrategyPromptResearchStep(unittest.TestCase):
	def _strategy_prompt(self) -> str:
		phase = next(p for p in brand.PHASES if p["phase_key"] == "strategy")
		return phase["prompt"]

	def test_prompt_names_the_research_tools(self):
		prompt = self._strategy_prompt()
		for skill in brand.RESEARCH_SKILLS:
			self.assertIn(skill, prompt)

	def test_prompt_mandates_honest_ungrounded_fallback(self):
		prompt = self._strategy_prompt()
		self.assertIn("ungrounded", prompt)
		self.assertIn("instead of inventing", prompt)

	def test_strategist_owns_the_phase(self):
		phase = next(p for p in brand.PHASES if p["phase_key"] == "strategy")
		self.assertEqual(phase["agent_role"], brand.RESEARCH_PROFILE)


class TestEnsureResearchGrants(unittest.TestCase):
	@patch(f"{_M}.frappe")
	def test_no_skill_rows_is_a_clean_no_op(self, fr):
		# Profile exists, but the Tavily MCP was never registered → no Skill rows.
		fr.db.exists.side_effect = lambda dt, name=None, **k: dt == "Agent Profile"
		brand._ensure_research_grants()
		fr.get_doc.assert_not_called()

	@patch(f"{_M}.frappe")
	def test_missing_profile_is_a_no_op(self, fr):
		fr.db.exists.return_value = False
		brand._ensure_research_grants()
		fr.get_doc.assert_not_called()

	@patch(f"{_M}.frappe")
	def test_existing_skills_are_granted_without_duplicates(self, fr):
		fr.db.exists.return_value = True  # profile + both skills
		profile = MagicMock()
		existing = MagicMock()
		existing.get.side_effect = lambda k, d=None: {"skill": brand.RESEARCH_SKILLS[0]}.get(k, d)
		profile.get.return_value = [existing]  # search already granted
		fr.get_doc.return_value = profile

		brand._ensure_research_grants()

		appended = [c[0][1]["skill"] for c in profile.append.call_args_list]
		self.assertEqual(appended, [brand.RESEARCH_SKILLS[1]])  # only extract added
		profile.save.assert_called_once()


if __name__ == "__main__":
	unittest.main()
