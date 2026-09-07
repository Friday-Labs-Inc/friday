# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""
Unit tests for the Anthropic Claude OAuth flow (design 63b-OAuth).
"""

import base64
import datetime
import hashlib
import unittest
from unittest.mock import MagicMock, patch

_FIXED_NOW = datetime.datetime(2026, 6, 13, 12, 0, 0)


class _FakeDoc(dict):
	def __getattr__(self, k):
		return self.get(k)

	def __setattr__(self, k, v):
		self[k] = v

	def get_password(self, field, raise_exception=True):
		return self.get(f"__pw_{field}")

	def save(self, *a, **kw):
		self["__saved"] = True


def _resp(status, payload=None):
	r = MagicMock()
	r.status_code = status
	r.json.return_value = payload or {}
	return r


class TestCodeChallenge(unittest.TestCase):
	def test_s256_b64url_no_pad(self):
		from friday.friday_core.llm.oauth import anthropic

		verifier = "test-verifier-123"
		expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
		self.assertEqual(anthropic.code_challenge(verifier), expected)
		self.assertNotIn("=", anthropic.code_challenge(verifier))


class TestBuildAuthorizeUrl(unittest.TestCase):
	@patch("friday.friday_core.llm.oauth.anthropic.frappe")
	def test_persists_pkce_and_returns_url(self, mock_frappe):
		from friday.friday_core.llm.oauth import anthropic

		doc = _FakeDoc({})
		mock_frappe.get_doc.return_value = doc

		url = anthropic.build_authorize_url("Claude")

		self.assertTrue(url.startswith(anthropic.AUTHORIZE_URL))
		self.assertIn(f"client_id={anthropic.CLIENT_ID}", url)
		self.assertIn("code_challenge_method=S256", url)
		# verifier + state were persisted and the URL's challenge matches the verifier
		self.assertTrue(doc["oauth_pkce_verifier"])
		self.assertTrue(doc["oauth_state"])
		self.assertIn(anthropic.code_challenge(doc["oauth_pkce_verifier"]), url)
		self.assertTrue(doc["__saved"])


class TestExchangeCode(unittest.TestCase):
	@patch("friday.friday_core.llm.oauth.anthropic.now_datetime", return_value=_FIXED_NOW)
	@patch("friday.friday_core.llm.oauth.anthropic.tokens")
	@patch("friday.friday_core.llm.oauth.anthropic.requests")
	@patch("friday.friday_core.llm.oauth.anthropic.frappe")
	def test_happy_path_stores_tokens(self, mock_frappe, mock_requests, mock_tokens, _now):
		from friday.friday_core.llm.oauth import anthropic

		mock_tokens.get_secret.return_value = "the-verifier"
		mock_frappe.get_doc.return_value = _FakeDoc({"oauth_state": "ST"})
		mock_requests.post.return_value = _resp(
			200, {"access_token": "at", "refresh_token": "rt", "expires_in": 3600}
		)

		out = anthropic.exchange_code("Claude", "AUTHCODE#ST")

		self.assertTrue(out["ok"])
		mock_tokens.store_tokens.assert_called_once()
		kw = mock_tokens.store_tokens.call_args.kwargs
		self.assertEqual(kw["access_token"], "at")
		self.assertEqual(kw["refresh_token"], "rt")
		self.assertIsNotNone(kw["expires_at"])

	@patch("friday.friday_core.llm.oauth.anthropic.tokens")
	@patch("friday.friday_core.llm.oauth.anthropic.frappe")
	def test_state_mismatch_raises(self, mock_frappe, mock_tokens):
		from friday.friday_core.llm.oauth import anthropic
		from friday.friday_core.llm.oauth.tokens import OAuthError

		mock_tokens.get_secret.return_value = "v"
		mock_frappe.get_doc.return_value = _FakeDoc({"oauth_state": "EXPECTED"})
		with self.assertRaises(OAuthError):
			anthropic.exchange_code("Claude", "CODE#WRONGSTATE")

	@patch("friday.friday_core.llm.oauth.anthropic.tokens")
	@patch("friday.friday_core.llm.oauth.anthropic.frappe")
	def test_no_code_raises(self, mock_frappe, mock_tokens):
		from friday.friday_core.llm.oauth import anthropic
		from friday.friday_core.llm.oauth.tokens import OAuthError

		mock_tokens.get_secret.return_value = "v"
		mock_frappe.get_doc.return_value = _FakeDoc({"oauth_state": "ST"})
		with self.assertRaises(OAuthError):
			anthropic.exchange_code("Claude", "")


class TestRefresh(unittest.TestCase):
	@patch("friday.friday_core.llm.oauth.anthropic.now_datetime", return_value=_FIXED_NOW)
	@patch("friday.friday_core.llm.oauth.anthropic.tokens")
	@patch("friday.friday_core.llm.oauth.anthropic.requests")
	@patch("friday.friday_core.llm.oauth.anthropic.frappe")
	def test_refresh_posts_and_stores(self, mock_frappe, mock_requests, mock_tokens, _now):
		from friday.friday_core.llm.oauth import anthropic

		mock_tokens.get_secret.return_value = "old-refresh"
		mock_frappe.get_doc.return_value = _FakeDoc({})
		mock_requests.post.return_value = _resp(200, {"access_token": "at2", "expires_in": 3600})

		anthropic.refresh("Claude")
		mock_tokens.store_tokens.assert_called_once()
		# form-encoded refresh grant uses data=, not json=
		self.assertIn("data", mock_requests.post.call_args.kwargs)

	@patch("friday.friday_core.llm.oauth.anthropic.tokens")
	@patch("friday.friday_core.llm.oauth.anthropic.frappe")
	def test_refresh_without_token_raises(self, mock_frappe, mock_tokens):
		from friday.friday_core.llm.oauth import anthropic
		from friday.friday_core.llm.oauth.tokens import OAuthError

		mock_tokens.get_secret.return_value = ""
		mock_frappe.get_doc.return_value = _FakeDoc({})
		with self.assertRaises(OAuthError):
			anthropic.refresh("Claude")


class TestPostTokenFallback(unittest.TestCase):
	@patch("friday.friday_core.llm.oauth.anthropic.now_datetime", return_value=_FIXED_NOW)
	@patch("friday.friday_core.llm.oauth.anthropic.tokens")
	@patch("friday.friday_core.llm.oauth.anthropic.requests")
	@patch("friday.friday_core.llm.oauth.anthropic.frappe")
	def test_falls_back_to_second_host(self, mock_frappe, mock_requests, mock_tokens, _now):
		from friday.friday_core.llm.oauth import anthropic

		mock_tokens.get_secret.return_value = "v"
		mock_frappe.get_doc.return_value = _FakeDoc({"oauth_state": "ST"})
		# primary 500, fallback 200
		mock_requests.post.side_effect = [_resp(500), _resp(200, {"access_token": "at", "expires_in": 60})]

		anthropic.exchange_code("Claude", "CODE#ST")
		self.assertEqual(mock_requests.post.call_count, 2)
		mock_tokens.store_tokens.assert_called_once()

	@patch("friday.friday_core.llm.oauth.anthropic.tokens")
	@patch("friday.friday_core.llm.oauth.anthropic.requests")
	@patch("friday.friday_core.llm.oauth.anthropic.frappe")
	def test_both_hosts_fail_raises(self, mock_frappe, mock_requests, mock_tokens):
		from friday.friday_core.llm.oauth import anthropic
		from friday.friday_core.llm.oauth.tokens import OAuthError

		mock_tokens.get_secret.return_value = "v"
		mock_frappe.get_doc.return_value = _FakeDoc({"oauth_state": "ST"})
		mock_requests.post.side_effect = [_resp(500), _resp(403)]
		with self.assertRaises(OAuthError):
			anthropic.exchange_code("Claude", "CODE#ST")


if __name__ == "__main__":
	unittest.main()
