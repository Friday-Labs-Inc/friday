# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""
Unit tests for the `friday setup` provisioning logic (cli/setup.py).

Mock-based — no DB. Verifies the two records get created/updated correctly, the
API key lands on the (encrypted) `api_key` field, and the returned summary never
carries the secret. The live end-to-end (a real provider + a real chat turn)
runs on a bench.
"""

import unittest
from unittest.mock import MagicMock, patch

from frappe.friday_core.cli.setup import (
	provision_profile,
	provision_provider,
	run_setup,
)

_S = "frappe.friday_core.cli.setup"


class TestProvisionProvider(unittest.TestCase):
	@patch(f"{_S}.frappe")
	def test_creates_with_key_on_encrypted_field(self, mock_frappe):
		mock_frappe.db.exists.return_value = False
		doc = MagicMock()
		doc.name = "Minimax"
		mock_frappe.new_doc.return_value = doc

		name = provision_provider(
			provider_name="Minimax", provider_type="minimax",
			api_key="sk-secret", default_model="MiniMax-M2",
		)

		self.assertEqual(name, "Minimax")
		self.assertEqual(doc.provider_type, "minimax")
		self.assertEqual(doc.default_model, "MiniMax-M2")
		self.assertEqual(doc.is_active, 1)
		self.assertEqual(doc.api_key, "sk-secret")  # the Password field
		doc.save.assert_called_once()

	@patch(f"{_S}.frappe")
	def test_updates_existing_without_new_doc(self, mock_frappe):
		mock_frappe.db.exists.return_value = True
		doc = MagicMock()
		doc.name = "Minimax"
		mock_frappe.get_doc.return_value = doc

		provision_provider(
			provider_name="Minimax", provider_type="minimax",
			api_key="sk-new", default_model="MiniMax-M2",
		)

		mock_frappe.new_doc.assert_not_called()
		self.assertEqual(doc.api_key, "sk-new")


class TestProvisionProfile(unittest.TestCase):
	@patch(f"{_S}.frappe")
	def test_creates_active_profile_linked_to_provider(self, mock_frappe):
		mock_frappe.db.exists.return_value = False
		doc = MagicMock()
		doc.name = "Friday"
		mock_frappe.new_doc.return_value = doc

		name = provision_profile(profile_name="Friday", provider_name="Minimax", system_prompt="hi")

		self.assertEqual(name, "Friday")
		self.assertEqual(doc.model_provider, "Minimax")
		self.assertEqual(doc.system_prompt, "hi")
		self.assertEqual(doc.status, "Active")
		doc.save.assert_called_once()


class TestRunSetup(unittest.TestCase):
	@patch(f"{_S}.frappe")
	def test_provisions_both_and_commits(self, mock_frappe):
		mock_frappe.db.exists.return_value = False
		prov = MagicMock(); prov.name = "Minimax"
		prof = MagicMock(); prof.name = "Friday"
		mock_frappe.new_doc.side_effect = [prov, prof]

		result = run_setup(
			provider_name="Minimax", provider_type="minimax", api_key="sk-x",
			default_model="MiniMax-M2", profile_name="Friday",
		)

		self.assertEqual(result, {"provider": "Minimax", "profile": "Friday", "model": "MiniMax-M2"})
		self.assertEqual(prof.model_provider, "Minimax")
		self.assertEqual(prof.status, "Active")
		mock_frappe.db.commit.assert_called_once()

	@patch(f"{_S}.frappe")
	def test_summary_never_leaks_the_key(self, mock_frappe):
		mock_frappe.db.exists.return_value = False
		prov = MagicMock(); prov.name = "P"
		prof = MagicMock(); prof.name = "A"
		mock_frappe.new_doc.side_effect = [prov, prof]

		result = run_setup(
			provider_name="P", provider_type="minimax", api_key="sk-SENSITIVE",
			default_model="m", profile_name="A",
		)

		self.assertNotIn("sk-SENSITIVE", str(result))
		self.assertNotIn("api_key", result)


if __name__ == "__main__":
	unittest.main()
