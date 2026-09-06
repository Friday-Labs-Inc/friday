# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""
Unit tests for the shared OAuth token store + freshness (design 63b-OAuth).
"""

import datetime
import unittest
from unittest.mock import MagicMock, patch


class _FakeDoc(dict):
	def __getattr__(self, k):
		return self.get(k)

	def __setattr__(self, k, v):
		self[k] = v

	def get_password(self, field, raise_exception=True):
		return self.get(f"__pw_{field}")

	def save(self, *a, **kw):
		self["__saved"] = True


class TestIsExpiring(unittest.TestCase):
	@patch("friday.friday_core.llm.oauth.tokens.now_datetime")
	def test_unset_is_expiring(self, mock_now):
		from friday.friday_core.llm.oauth import tokens

		mock_now.return_value = datetime.datetime(2026, 6, 13, 12, 0, 0)
		self.assertTrue(tokens.is_expiring(None))

	@patch("friday.friday_core.llm.oauth.tokens.now_datetime")
	def test_far_future_not_expiring(self, mock_now):
		from friday.friday_core.llm.oauth import tokens

		mock_now.return_value = datetime.datetime(2026, 6, 13, 12, 0, 0)
		self.assertFalse(tokens.is_expiring(datetime.datetime(2030, 1, 1, 0, 0, 0)))

	@patch("friday.friday_core.llm.oauth.tokens.now_datetime")
	def test_within_skew_is_expiring(self, mock_now):
		from friday.friday_core.llm.oauth import tokens

		mock_now.return_value = datetime.datetime(2026, 6, 13, 12, 0, 0)
		# 60s ahead < 120s skew -> expiring
		self.assertTrue(tokens.is_expiring(datetime.datetime(2026, 6, 13, 12, 1, 0)))


class TestStoreTokens(unittest.TestCase):
	@patch("friday.friday_core.llm.oauth.tokens.frappe")
	def test_stores_and_clears_transient(self, mock_frappe):
		from friday.friday_core.llm.oauth import tokens

		doc = _FakeDoc({"oauth_pkce_verifier": "v", "oauth_state": "s", "oauth_device_id": "d"})
		mock_frappe.get_doc.return_value = doc

		tokens.store_tokens(
			"Claude",
			access_token="at",
			refresh_token="rt",
			expires_at="2026-06-13 13:00:00",
			account_id="acc",
		)

		self.assertEqual(doc["oauth_access_token"], "at")
		self.assertEqual(doc["oauth_refresh_token"], "rt")
		self.assertEqual(doc["oauth_expires_at"], "2026-06-13 13:00:00")
		self.assertEqual(doc["oauth_account_id"], "acc")
		# transient cleared
		self.assertIsNone(doc["oauth_pkce_verifier"])
		self.assertIsNone(doc["oauth_state"])
		self.assertIsNone(doc["oauth_device_id"])
		self.assertTrue(doc["__saved"])


class TestGetFreshAccessToken(unittest.TestCase):
	@patch("friday.friday_core.llm.oauth.tokens.is_expiring", return_value=False)
	@patch("friday.friday_core.llm.oauth.tokens.frappe")
	def test_returns_token_without_refresh_when_fresh(self, mock_frappe, _exp):
		from friday.friday_core.llm.oauth import tokens

		doc = _FakeDoc({"__pw_oauth_access_token": "live-token"})
		mock_frappe.get_doc.return_value = doc
		self.assertEqual(tokens.get_fresh_access_token("Claude"), "live-token")

	@patch("friday.friday_core.llm.oauth.tokens._refresh_for_flavor")
	@patch("friday.friday_core.llm.oauth.tokens.is_expiring", return_value=True)
	@patch("friday.friday_core.llm.oauth.tokens.frappe")
	def test_refreshes_when_expiring(self, mock_frappe, _exp, mock_refresh):
		from friday.friday_core.llm.oauth import tokens

		doc = _FakeDoc({"__pw_oauth_access_token": "new-token"})
		mock_frappe.get_doc.return_value = doc
		out = tokens.get_fresh_access_token("Claude")
		mock_refresh.assert_called_once()
		self.assertEqual(out, "new-token")

	@patch("friday.friday_core.llm.oauth.tokens.is_expiring", return_value=False)
	@patch("friday.friday_core.llm.oauth.tokens.frappe")
	def test_raises_when_no_token(self, mock_frappe, _exp):
		from friday.friday_core.llm.oauth import tokens

		mock_frappe.get_doc.return_value = _FakeDoc({})
		with self.assertRaises(tokens.OAuthError):
			tokens.get_fresh_access_token("Claude")

	@patch("friday.friday_core.llm.oauth.tokens.frappe")
	def test_refresh_for_flavor_unknown_raises(self, mock_frappe):
		from friday.friday_core.llm.oauth import tokens

		with self.assertRaises(tokens.OAuthError):
			tokens._refresh_for_flavor(_FakeDoc({"name": "X", "oauth_flavor": "bogus"}))


if __name__ == "__main__":
	unittest.main()
