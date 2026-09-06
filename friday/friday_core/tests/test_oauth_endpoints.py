# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""
Unit tests for the OAuth Desk endpoints + the refresh cron (design 63b-OAuth).
"""

import unittest
from unittest.mock import patch


class _FakeDoc(dict):
	def __getattr__(self, k):
		return self.get(k)

	def __setattr__(self, k, v):
		self[k] = v

	def save(self, *a, **kw):
		self["__saved"] = True


class TestStartClaudeLogin(unittest.TestCase):
	@patch(
		"friday.friday_core.llm.oauth.anthropic.build_authorize_url",
		return_value="https://claude.ai/oauth/authorize?x=1",
	)
	@patch("friday.friday_core.llm.oauth.endpoints.frappe")
	def test_flips_to_oauth_and_returns_url(self, mock_frappe, mock_build):
		from friday.friday_core.llm.oauth import endpoints

		doc = _FakeDoc({"provider_type": "minimax"})
		mock_frappe.get_doc.return_value = doc

		out = endpoints.start_claude_login("Claude")

		mock_frappe.only_for.assert_called_with("System Manager")
		self.assertEqual(doc["auth_mode"], "oauth")
		self.assertEqual(doc["oauth_flavor"], "anthropic-claude")
		self.assertEqual(doc["provider_type"], "anthropic")
		self.assertTrue(doc["__saved"])
		self.assertEqual(out["authorize_url"], "https://claude.ai/oauth/authorize?x=1")


class TestCompleteClaudeLogin(unittest.TestCase):
	@patch("friday.friday_core.llm.oauth.endpoints.tokens")
	@patch("friday.friday_core.llm.oauth.anthropic.exchange_code")
	@patch("friday.friday_core.llm.oauth.endpoints.frappe")
	def test_delegates_to_exchange(self, mock_frappe, mock_exchange, mock_tokens):
		from friday.friday_core.llm.oauth import endpoints

		mock_frappe.get_doc.return_value = _FakeDoc(
			{"auth_mode": "oauth", "oauth_flavor": "anthropic-claude"}
		)
		mock_tokens.get_secret.return_value = "tok"

		out = endpoints.complete_claude_login("Claude", "CODE#STATE")

		mock_exchange.assert_called_once_with("Claude", "CODE#STATE")
		self.assertTrue(out["logged_in"])


class TestRefreshCron(unittest.TestCase):
	@patch("friday.friday_core.llm.oauth_token_refresh.tokens")
	@patch("friday.friday_core.llm.oauth_token_refresh.frappe")
	def test_refreshes_expiring_only(self, mock_frappe, mock_tokens):
		from friday.friday_core.llm import oauth_token_refresh

		mock_frappe.get_all.return_value = ["Claude", "Fresh"]
		docs = {
			"Claude": _FakeDoc({"name": "Claude", "oauth_expires_at": "soon"}),
			"Fresh": _FakeDoc({"name": "Fresh", "oauth_expires_at": "later"}),
		}
		mock_frappe.get_doc.side_effect = lambda dt, n: docs[n]
		# only Claude is expiring
		mock_tokens.is_expiring.side_effect = lambda exp: exp == "soon"

		summary = oauth_token_refresh.tick()

		self.assertEqual(summary["refreshed"], 1)
		self.assertEqual(summary["failed"], [])
		mock_tokens._refresh_for_flavor.assert_called_once()

	@patch("friday.friday_core.llm.oauth_token_refresh.tokens")
	@patch("friday.friday_core.llm.oauth_token_refresh.frappe")
	def test_failure_isolated(self, mock_frappe, mock_tokens):
		from friday.friday_core.llm import oauth_token_refresh

		mock_frappe.get_all.return_value = ["Bad"]
		mock_frappe.get_doc.return_value = _FakeDoc({"name": "Bad", "oauth_expires_at": "soon"})
		mock_tokens.is_expiring.return_value = True
		mock_tokens._refresh_for_flavor.side_effect = RuntimeError("boom")

		summary = oauth_token_refresh.tick()

		self.assertEqual(summary["failed"], ["Bad"])
		self.assertTrue(mock_frappe.log_error.called)


if __name__ == "__main__":
	unittest.main()
