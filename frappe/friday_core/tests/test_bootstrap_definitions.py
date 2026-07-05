# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""The create-only-provisioner audit (the class behind #179, #18/#190, #19).

DB-free. Pins three properties:
  1. COVERAGE (the class-killer): every ``skills/bootstrap_*.py`` module is
     on the migrate path — either in the registry or individually wired.
     A NEW bootstrap that lands in neither fails this test.
  2. FULL UPSERT: bootstrap_files/_read now force the complete definition
     (including status="Active") on an EXISTING row — the exact create-only
     Draft default that made the file skills invisible in #179.
  3. ISOLATION: one broken ensure is logged and skipped; the rest still run.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from frappe.friday_core.skills import bootstrap_files, bootstrap_read, bootstrap_registry

_SKILLS_DIR = Path(bootstrap_registry.__file__).parent


class TestEveryBootstrapIsOnTheMigratePath(unittest.TestCase):
	def test_no_bootstrap_is_forgotten(self):
		registered = {path.split(".")[-2] for path in bootstrap_registry.DEFINITION_ENSURES}
		covered = registered | bootstrap_registry.INDIVIDUALLY_WIRED
		on_disk = {p.stem for p in _SKILLS_DIR.glob("bootstrap_*.py") if p.stem != "bootstrap_registry"}
		missing = on_disk - covered
		self.assertFalse(
			missing,
			f"Bootstrap(s) {sorted(missing)} are on neither the registry nor an "
			"individual after_migrate entry — their definitions will drift from "
			"code exactly like #179/#19. Add ensure_definitions() + register.",
		)

	def test_registry_paths_resolve(self):
		import importlib

		for path in bootstrap_registry.DEFINITION_ENSURES:
			module_path, func = path.rsplit(".", 1)
			mod = importlib.import_module(module_path)
			self.assertTrue(callable(getattr(mod, func)), f"{path} does not resolve to a callable")


class TestFullUpsertKillsTheDraftDefault(unittest.TestCase):
	"""#179: created rows defaulted to Draft and existing rows were never
	touched on status — the loader hard-excludes Draft, so the skills were
	invisible. Both bootstraps must now force the full definition."""

	def _existing_row_gets_full_definition(self, module, any_skill_name):
		with patch(f"{module.__name__}.frappe") as fr:
			fr.db.exists.return_value = True
			doc = MagicMock()
			fr.get_doc.return_value = doc

			module._ensure_skill_row(any_skill_name)

			self.assertEqual(doc.status, "Active")
			self.assertEqual(doc.risk_level, "low")
			self.assertEqual(doc.requires_approval, 0)
			spec = module._SKILLS[any_skill_name]
			self.assertEqual(json.loads(doc.parameters_schema), spec["parameters_schema"])
			doc.save.assert_called_once()

	def test_files_existing_row_forced_active(self):
		self._existing_row_gets_full_definition(bootstrap_files, next(iter(bootstrap_files._SKILLS)))

	def test_read_existing_row_forced_active(self):
		self._existing_row_gets_full_definition(bootstrap_read, next(iter(bootstrap_read._SKILLS)))


class TestRegistryIsolation(unittest.TestCase):
	@patch("frappe.friday_core.skills.bootstrap_registry.frappe")
	def test_one_failure_does_not_starve_the_rest(self, fr):
		calls: list[str] = []

		def get_attr(path):
			if path == bootstrap_registry.DEFINITION_ENSURES[0]:
				raise RuntimeError("broken bootstrap")
			return lambda: calls.append(path)

		fr.get_attr.side_effect = get_attr

		bootstrap_registry.ensure_all_skill_definitions()

		self.assertEqual(len(calls), len(bootstrap_registry.DEFINITION_ENSURES) - 1)
		fr.log_error.assert_called_once()

	@patch("frappe.friday_core.skills.bootstrap_registry.frappe")
	def test_all_run_when_healthy(self, fr):
		fr.get_attr.return_value = MagicMock()
		bootstrap_registry.ensure_all_skill_definitions()
		resolved = [c[0][0] for c in fr.get_attr.call_args_list]
		self.assertEqual(resolved, list(bootstrap_registry.DEFINITION_ENSURES))


if __name__ == "__main__":
	unittest.main()
