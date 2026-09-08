# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""
Unit tests for the Friday Setup wizard controller (design 64).

The wizard is an *actor*: each whitelisted endpoint reads/writes live state by
delegating to the existing ``cli/setup`` functions and bootstraps — no logic
duplication. These tests assert the delegation, the idempotent/guarded
behaviour, and the verify-before-complete contract (a provider is only
"verified" on a LIVE discovery probe, not the curated catalog fallback).

Every endpoint is System-Manager-gated. Pure unit tests with ``frappe`` mocked.
"""

import unittest
from unittest.mock import patch


class TestSaveProvider(unittest.TestCase):
	@patch("frappe.friday_core.setup.wizard.cli_setup")
	@patch("frappe.friday_core.setup.wizard.frappe")
	def test_delegates_sets_costs_and_default(self, mock_frappe, mock_cli):
		from frappe.friday_core.setup import wizard

		mock_cli.provision_provider.return_value = "Minimax"
		mock_frappe.utils.flt.side_effect = lambda x: float(x)

		out = wizard.save_provider(
			provider_name="Minimax",
			provider_type="minimax",
			api_key="sk-x",
			default_model="MiniMax-M2",
			input_cost_per_million=0.2,
			output_cost_per_million=1.1,
			make_default=1,
		)

		mock_frappe.only_for.assert_called_with("System Manager")
		mock_cli.provision_provider.assert_called_once()
		# cost rates written onto the provider row
		mock_frappe.db.set_value.assert_called_once()
		args = mock_frappe.db.set_value.call_args[0]
		self.assertEqual(args[0], "LLM Provider")
		self.assertEqual(args[1], "Minimax")
		self.assertEqual(args[2]["input_cost_per_million"], 0.2)
		self.assertEqual(args[2]["output_cost_per_million"], 1.1)
		mock_cli.set_default_provider.assert_called_once_with("Minimax")
		self.assertEqual(out["provider"], "Minimax")

	@patch("frappe.friday_core.setup.wizard.cli_setup")
	@patch("frappe.friday_core.setup.wizard.frappe")
	def test_falls_back_to_default_model_when_blank(self, mock_frappe, mock_cli):
		from frappe.friday_core.setup import wizard

		mock_cli.DEFAULT_MODELS = {"minimax": "MiniMax-M2"}
		mock_cli.provision_provider.return_value = "Minimax"

		wizard.save_provider(provider_name="Minimax", provider_type="minimax", api_key="sk-x")

		# provision_provider must have received a non-empty default_model.
		kwargs = mock_cli.provision_provider.call_args.kwargs
		self.assertEqual(kwargs["default_model"], "MiniMax-M2")

	@patch("frappe.friday_core.setup.wizard.cli_setup")
	@patch("frappe.friday_core.setup.wizard.frappe")
	def test_no_cost_write_when_rates_blank(self, mock_frappe, mock_cli):
		from frappe.friday_core.setup import wizard

		mock_cli.provision_provider.return_value = "Minimax"
		wizard.save_provider(provider_name="Minimax", provider_type="minimax", api_key="sk-x", make_default=0)
		mock_frappe.db.set_value.assert_not_called()
		mock_cli.set_default_provider.assert_not_called()


class TestSaveAgent(unittest.TestCase):
	@patch("frappe.friday_core.setup.wizard.cli_setup")
	@patch("frappe.friday_core.setup.wizard.frappe")
	def test_delegates_to_provision_profile(self, mock_frappe, mock_cli):
		from frappe.friday_core.setup import wizard

		mock_cli.provision_profile.return_value = "Friday"
		out = wizard.save_agent(provider_name="Minimax", profile_name="Friday")

		mock_frappe.only_for.assert_called_with("System Manager")
		mock_cli.provision_profile.assert_called_once()
		kwargs = mock_cli.provision_profile.call_args.kwargs
		self.assertEqual(kwargs["profile_name"], "Friday")
		self.assertEqual(kwargs["provider_name"], "Minimax")
		# blank system_prompt is passed as None so provision_profile seeds the default
		self.assertIsNone(kwargs["system_prompt"])
		self.assertEqual(out["profile"], "Friday")


class TestProvisionSurfaces(unittest.TestCase):
	@patch("frappe.friday_core.setup.wizard.frappe")
	def test_throws_when_raven_absent(self, mock_frappe):
		"""Raven is REQUIRED (design 58): it is Friday's chat front door. A missing
		Raven must fail loudly with the install command, not return a tidy
		"skipped" that reads like setup succeeded."""
		from frappe.friday_core.setup import wizard

		mock_frappe.db.table_exists.return_value = False
		mock_frappe.throw.side_effect = RuntimeError("raven required")

		with self.assertRaises(RuntimeError):
			wizard.provision_surfaces()

		mock_frappe.throw.assert_called_once()

	@patch("frappe.friday_core.surfaces.bootstrap_raven.provision")
	@patch("frappe.friday_core.setup.wizard.frappe")
	def test_provisions_when_raven_present(self, mock_frappe, mock_provision):
		from frappe.friday_core.setup import wizard

		mock_frappe.db.table_exists.return_value = True
		out = wizard.provision_surfaces(profile_name="Friday")
		mock_provision.assert_called_once_with(profile_name="Friday")
		self.assertEqual(out["status"], "provisioned")


class TestProvisionTools(unittest.TestCase):
	@patch("frappe.friday_core.skills.bootstrap_files.provision")
	@patch("frappe.friday_core.skills.bootstrap_read.provision")
	@patch("frappe.friday_core.setup.wizard.frappe")
	def test_calls_both_bootstraps(self, mock_frappe, mock_read, mock_files):
		from frappe.friday_core.setup import wizard

		out = wizard.provision_tools(profile_name="Friday")
		mock_read.assert_called_once_with(profile_name="Friday")
		mock_files.assert_called_once_with(profile_name="Friday")
		self.assertTrue(out["read"] and out["files"])


class TestVerifyAndComplete(unittest.TestCase):
	@patch("frappe.friday_core.health.pipeline_health.pipeline_health")
	@patch("frappe.friday_core.llm.model_discovery.list_models")
	@patch("frappe.friday_core.setup.wizard.frappe")
	def test_ready_when_live_and_health_ok(self, mock_frappe, mock_list, mock_health):
		from frappe.friday_core.setup import wizard

		mock_list.return_value = {"source": "live", "models": ["MiniMax-M2"]}
		mock_health.return_value = {"verdict": "ok"}
		out = wizard.verify_and_complete(provider_name="Minimax")

		self.assertTrue(out["ready"])
		# setup_complete flag was set to 1 via the cached doc's db_set
		mock_frappe.get_cached_doc.return_value.db_set.assert_called_with("setup_complete", 1)

	@patch("frappe.friday_core.health.pipeline_health.pipeline_health")
	@patch("frappe.friday_core.llm.model_discovery.list_models")
	@patch("frappe.friday_core.setup.wizard.frappe")
	def test_not_ready_on_catalog_fallback(self, mock_frappe, mock_list, mock_health):
		from frappe.friday_core.setup import wizard

		# Catalog fallback means the live probe did NOT succeed (bad/absent key).
		mock_list.return_value = {"source": "catalog", "models": ["x"], "error": "no key"}
		mock_health.return_value = {"verdict": "ok"}
		out = wizard.verify_and_complete(provider_name="Minimax")

		self.assertFalse(out["ready"])
		self.assertFalse(out["provider_ok"])
		mock_frappe.get_cached_doc.return_value.db_set.assert_not_called()

	@patch("frappe.friday_core.health.pipeline_health.pipeline_health")
	@patch("frappe.friday_core.llm.model_discovery.list_models")
	@patch("frappe.friday_core.setup.wizard.frappe")
	def test_not_ready_when_health_down(self, mock_frappe, mock_list, mock_health):
		from frappe.friday_core.setup import wizard

		mock_list.return_value = {"source": "live", "models": ["MiniMax-M2"]}
		mock_health.return_value = {"verdict": "down", "error": "no friday worker"}
		out = wizard.verify_and_complete(provider_name="Minimax")

		self.assertFalse(out["ready"])
		mock_frappe.get_cached_doc.return_value.db_set.assert_not_called()


class TestSetupStatus(unittest.TestCase):
	@patch("frappe.friday_core.health.pipeline_health.pipeline_health")
	@patch("frappe.friday_core.setup.wizard.frappe")
	def test_status_shape(self, mock_frappe, mock_health):
		from frappe.friday_core.setup import wizard

		def _get_value(doctype, name, field=None, as_dict=False):
			if as_dict:
				return {
					"name": "Friday",
					"system_prompt": "x",
					"status": "Active",
					"model_provider": "Minimax",
				}
			if field == "setup_complete":
				return 0
			return "Minimax"

		mock_frappe.get_all.return_value = ["Minimax"]
		mock_frappe.db.get_value.side_effect = _get_value
		# Agent Settings is read via get_cached_doc (regular single-row DocType).
		mock_frappe.get_cached_doc.return_value = {"default_provider": "Minimax", "setup_complete": 0}
		mock_frappe.db.exists.return_value = True
		mock_frappe.db.table_exists.return_value = True
		mock_health.return_value = {"verdict": "ok", "workers": {"friday": {"present": True}}}

		out = wizard.setup_status()
		mock_frappe.only_for.assert_called_with("System Manager")
		for key in ("provider", "agent", "surfaces", "tools", "health", "setup_complete"):
			self.assertIn(key, out)


if __name__ == "__main__":
	unittest.main()
