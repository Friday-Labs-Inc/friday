# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""
Unit tests for provider model discovery (design 63).

Ports Hermes' models.py pattern: live ``/v1/models`` per provider with a
curated catalog fallback. Tests mock the HTTP layer so they run headless.
"""

import unittest
from unittest.mock import MagicMock, patch

_M = "frappe.friday_core.llm.model_discovery"


def _resp(status=200, payload=None):
	r = MagicMock()
	r.status_code = status
	r.json.return_value = payload or {}
	return r


class TestFetchModelsLive(unittest.TestCase):
	"""A reachable /v1/models endpoint is the authoritative source."""

	@patch(f"{_M}.requests")
	def test_openai_compat_uses_bearer_and_parses_data_ids(self, mock_requests):
		from frappe.friday_core.llm.model_discovery import fetch_models

		mock_requests.get.return_value = _resp(200, {"data": [{"id": "gpt-4o"}, {"id": "gpt-4o-mini"}]})

		out = fetch_models("openai", "sk-key", "https://api.openai.com")

		self.assertEqual(out["source"], "live")
		self.assertEqual(out["models"], ["gpt-4o", "gpt-4o-mini"])
		# Bearer auth + the /v1/models path.
		call = mock_requests.get.call_args
		self.assertIn("/v1/models", call.args[0])
		self.assertEqual(call.kwargs["headers"]["Authorization"], "Bearer sk-key")

	@patch(f"{_M}.requests")
	def test_minimax_uses_bearer(self, mock_requests):
		from frappe.friday_core.llm.model_discovery import fetch_models

		mock_requests.get.return_value = _resp(200, {"data": [{"id": "MiniMax-M2"}]})

		out = fetch_models("minimax", "key", "https://api.minimax.io")

		self.assertEqual(out["models"], ["MiniMax-M2"])
		self.assertEqual(mock_requests.get.call_args.kwargs["headers"]["Authorization"], "Bearer key")

	@patch(f"{_M}.requests")
	def test_anthropic_uses_x_api_key_header(self, mock_requests):
		from frappe.friday_core.llm.model_discovery import fetch_models

		mock_requests.get.return_value = _resp(200, {"data": [{"id": "claude-3-5-sonnet-20241022"}]})

		out = fetch_models("anthropic", "sk-ant-key", "https://api.anthropic.com")

		self.assertEqual(out["source"], "live")
		self.assertIn("claude-3-5-sonnet-20241022", out["models"])
		headers = mock_requests.get.call_args.kwargs["headers"]
		# Anthropic uses x-api-key + a version header, NOT Bearer.
		self.assertEqual(headers["x-api-key"], "sk-ant-key")
		self.assertIn("anthropic-version", headers)
		self.assertNotIn("Authorization", headers)


class TestFetchModelsFallback(unittest.TestCase):
	"""When live fetch can't run, the curated catalog keeps the picker full."""

	def test_no_api_key_returns_catalog(self):
		from frappe.friday_core.llm.model_discovery import fetch_models

		out = fetch_models("anthropic", "", "https://api.anthropic.com")

		self.assertEqual(out["source"], "catalog")
		self.assertTrue(out["models"])  # non-empty
		self.assertIsNotNone(out["error"])

	@patch(f"{_M}.requests")
	def test_network_error_falls_back_to_catalog(self, mock_requests):
		from frappe.friday_core.llm.model_discovery import fetch_models

		mock_requests.get.side_effect = Exception("connection refused")

		out = fetch_models("openai", "sk-key", "https://api.openai.com")

		self.assertEqual(out["source"], "catalog")
		self.assertIn("gpt-4o", out["models"])
		self.assertIn("connection refused", out["error"])

	@patch(f"{_M}.requests")
	def test_non_200_falls_back_to_catalog(self, mock_requests):
		from frappe.friday_core.llm.model_discovery import fetch_models

		mock_requests.get.return_value = _resp(401, {"error": "unauthorized"})

		out = fetch_models("minimax", "bad-key", "https://api.minimax.io")

		self.assertEqual(out["source"], "catalog")
		self.assertTrue(out["models"])
		self.assertIn("401", out["error"])

	def test_unknown_provider_type_returns_empty_with_error(self):
		from frappe.friday_core.llm.model_discovery import fetch_models

		out = fetch_models("imaginary", "key", "https://x")

		self.assertEqual(out["models"], [])
		self.assertIn("unknown", out["error"].lower())


class TestListModelsEndpoint(unittest.TestCase):
	"""The whitelisted endpoint resolves the provider row and its key."""

	@patch(f"{_M}.fetch_models")
	@patch(f"{_M}.frappe")
	def test_loads_provider_row_and_calls_fetch(self, mock_frappe, mock_fetch):
		from frappe.friday_core.llm.model_discovery import list_models

		doc = MagicMock()
		doc.provider_type = "minimax"
		doc.base_url = "https://api.minimax.io"
		doc.get_password.return_value = "secret-key"
		mock_frappe.get_doc.return_value = doc
		mock_fetch.return_value = {"models": ["MiniMax-M2"], "source": "live", "error": None}

		out = list_models("Minimax")

		mock_fetch.assert_called_once_with("minimax", "secret-key", "https://api.minimax.io")
		self.assertEqual(out["provider"], "Minimax")
		self.assertEqual(out["models"], ["MiniMax-M2"])

	@patch(f"{_M}.fetch_models")
	@patch(f"{_M}.frappe")
	def test_missing_key_still_returns_catalog(self, mock_frappe, mock_fetch):
		"""get_password raises when the field was never set — treat as no key."""
		from frappe.friday_core.llm.model_discovery import list_models

		doc = MagicMock()
		doc.provider_type = "anthropic"
		doc.base_url = None
		doc.get_password.side_effect = Exception("no password")
		mock_frappe.get_doc.return_value = doc
		mock_fetch.return_value = {
			"models": ["claude-3-5-sonnet-20241022"],
			"source": "catalog",
			"error": "no key",
		}

		out = list_models("Anthropic")

		# Empty key passed through; base_url falls back to provider default (None → "").
		args = mock_fetch.call_args.args
		self.assertEqual(args[0], "anthropic")
		self.assertEqual(args[1], "")
		self.assertEqual(out["source"], "catalog")


if __name__ == "__main__":
	unittest.main()
