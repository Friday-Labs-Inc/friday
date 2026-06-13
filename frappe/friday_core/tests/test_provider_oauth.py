# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""
Unit tests for OAuth at the provider layer (design 63b-OAuth).

Covers the AnthropicProvider auth-header switch (Bearer + Claude-Code betas for
OAuth vs x-api-key for API key) and the _build_provider OAuth branch.
"""

import unittest
from unittest.mock import MagicMock, patch

_ANTHROPIC_OK = {
	"content": [{"type": "text", "text": "hi"}],
	"usage": {"input_tokens": 1, "output_tokens": 1},
	"stop_reason": "end_turn",
}


class TestAnthropicAuthHeaders(unittest.TestCase):
	def _capture_headers(self, **provider_kwargs):
		from frappe.friday_core.llm.provider import AnthropicProvider

		p = AnthropicProvider(default_model="claude-x", **provider_kwargs)
		p._post_with_recovery = MagicMock(return_value=_ANTHROPIC_OK)
		p.chat(messages=[{"role": "user", "content": "hi"}])
		return p._post_with_recovery.call_args.kwargs["headers"]

	def test_oauth_uses_bearer_and_betas(self):
		headers = self._capture_headers(api_key="", oauth_token="tok-123")
		self.assertEqual(headers["authorization"], "Bearer tok-123")
		self.assertIn("oauth-2025-04-20", headers["anthropic-beta"])
		self.assertIn("claude-code-20250219", headers["anthropic-beta"])
		self.assertTrue(headers["user-agent"].startswith("claude-cli/"))
		self.assertEqual(headers["x-app"], "cli")
		# OAuth must NOT send the API-key header
		self.assertNotIn("x-api-key", headers)

	def test_api_key_uses_x_api_key(self):
		headers = self._capture_headers(api_key="sk-ant-api-xyz")
		self.assertEqual(headers["x-api-key"], "sk-ant-api-xyz")
		self.assertNotIn("authorization", headers)
		self.assertNotIn("anthropic-beta", headers)


class TestBuildProviderOAuthBranch(unittest.TestCase):
	@patch("frappe.friday_core.llm.oauth.tokens.get_fresh_access_token", return_value="fresh-tok")
	def test_anthropic_oauth_builds_provider_with_token(self, _tok):
		from frappe.friday_core.llm.provider import AnthropicProvider, _build_provider

		row = {
			"name": "Claude Max",
			"provider_type": "anthropic",
			"auth_mode": "oauth",
			"oauth_flavor": "anthropic-claude",
			"default_model": "claude-sonnet-4",
		}
		provider = _build_provider(row)
		self.assertIsInstance(provider, AnthropicProvider)
		self.assertEqual(provider.oauth_token, "fresh-tok")

	@patch("frappe.friday_core.llm.oauth.tokens.get_fresh_access_token", return_value="fresh-tok")
	def test_codex_oauth_builds_codex_provider(self, _tok):
		from frappe.friday_core.llm.provider import CodexProvider, _build_provider

		row = {
			"name": "Codex",
			"provider_type": "openai",
			"auth_mode": "oauth",
			"oauth_flavor": "openai-codex",
			"oauth_account_id": "acc-123",
			"default_model": "gpt-5-codex",
		}
		provider = _build_provider(row)
		self.assertIsInstance(provider, CodexProvider)
		self.assertEqual(provider.oauth_token, "fresh-tok")
		self.assertEqual(provider.account_id, "acc-123")


if __name__ == "__main__":
	unittest.main()
