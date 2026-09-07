# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""
Unit tests for OpenAI Codex OAuth + the Responses-API transport (design 63b-2).
"""

import base64
import datetime
import json
import unittest
from unittest.mock import MagicMock, patch

_FIXED_NOW = datetime.datetime(2026, 6, 13, 12, 0, 0)


class _FakeDoc(dict):
	def __getattr__(self, k):
		return self.get(k)

	def __setattr__(self, k, v):
		self[k] = v

	def save(self, *a, **kw):
		self["__saved"] = True


def _resp(status, payload=None):
	r = MagicMock()
	r.status_code = status
	r.json.return_value = payload or {}
	return r


def _make_jwt(claims: dict) -> str:
	payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
	return f"header.{payload}.sig"


class TestJwtClaims(unittest.TestCase):
	def test_decodes_payload(self):
		from friday.friday_core.llm.oauth import codex

		token = _make_jwt({"exp": 1234567890, "https://api.openai.com/auth": {"chatgpt_account_id": "acc-9"}})
		claims = codex.jwt_claims(token)
		self.assertEqual(claims["exp"], 1234567890)
		self.assertEqual(claims["https://api.openai.com/auth"]["chatgpt_account_id"], "acc-9")

	def test_malformed_returns_empty(self):
		from friday.friday_core.llm.oauth import codex

		self.assertEqual(codex.jwt_claims("not-a-jwt"), {})


class TestStartDevice(unittest.TestCase):
	@patch("friday.friday_core.llm.oauth.codex.requests")
	@patch("friday.friday_core.llm.oauth.codex.frappe")
	def test_persists_device_and_returns_user_code(self, mock_frappe, mock_requests):
		from friday.friday_core.llm.oauth import codex

		doc = _FakeDoc({})
		mock_frappe.get_doc.return_value = doc
		mock_requests.post.return_value = _resp(
			200, {"user_code": "WXYZ", "device_auth_id": "dev-1", "interval": 5}
		)

		out = codex.start_device("Codex")

		self.assertEqual(out["user_code"], "WXYZ")
		self.assertEqual(out["verification_url"], codex.VERIFICATION_URL)
		self.assertEqual(doc["oauth_device_id"], "dev-1")
		self.assertEqual(doc["oauth_state"], "WXYZ")
		self.assertEqual(doc["oauth_flavor"], "openai-codex")
		self.assertTrue(doc["__saved"])


class TestPollDevice(unittest.TestCase):
	@patch("friday.friday_core.llm.oauth.codex.requests")
	@patch("friday.friday_core.llm.oauth.codex.frappe")
	def test_pending_when_not_authorized(self, mock_frappe, mock_requests):
		from friday.friday_core.llm.oauth import codex

		mock_frappe.get_doc.return_value = _FakeDoc({"oauth_device_id": "dev-1", "oauth_state": "WXYZ"})
		mock_requests.post.return_value = _resp(404)
		self.assertEqual(codex.poll_device("Codex"), {"pending": True})

	@patch("friday.friday_core.llm.oauth.codex.now_datetime", return_value=_FIXED_NOW)
	@patch("friday.friday_core.llm.oauth.codex.tokens")
	@patch("friday.friday_core.llm.oauth.codex.requests")
	@patch("friday.friday_core.llm.oauth.codex.frappe")
	def test_success_exchanges_and_stores(self, mock_frappe, mock_requests, mock_tokens, _now):
		from friday.friday_core.llm.oauth import codex

		mock_frappe.get_doc.return_value = _FakeDoc({"oauth_device_id": "dev-1", "oauth_state": "WXYZ"})
		access = _make_jwt(
			{"exp": 9999999999, "https://api.openai.com/auth": {"chatgpt_account_id": "acc-9"}}
		)
		mock_requests.post.side_effect = [
			_resp(200, {"authorization_code": "AC", "code_verifier": "VER"}),  # poll
			_resp(200, {"access_token": access, "refresh_token": "rt"}),  # exchange
		]

		out = codex.poll_device("Codex")
		self.assertTrue(out["logged_in"])
		kw = mock_tokens.store_tokens.call_args.kwargs
		self.assertEqual(kw["access_token"], access)
		self.assertEqual(kw["account_id"], "acc-9")


class TestRefresh(unittest.TestCase):
	@patch("friday.friday_core.llm.oauth.codex.tokens")
	@patch("friday.friday_core.llm.oauth.codex.requests")
	@patch("friday.friday_core.llm.oauth.codex.frappe")
	def test_reused_token_forces_relogin(self, mock_frappe, mock_requests, mock_tokens):
		from friday.friday_core.llm.oauth import codex
		from friday.friday_core.llm.oauth.tokens import OAuthError

		mock_frappe.get_doc.return_value = _FakeDoc({})
		mock_tokens.get_secret.return_value = "old-rt"
		mock_requests.post.return_value = _resp(409)
		with self.assertRaises(OAuthError):
			codex.refresh("Codex")


class TestCodexProviderResponses(unittest.TestCase):
	# The Codex backend only answers SSE ("Stream must be set to true" on a
	# non-streaming request — found live 2026-07-02). The mock now serves the
	# event stream; the final response.completed event carries the same
	# response object the old JSON mock had.
	_SSE = (
		"event: response.created\n"
		'data: {"type":"response.created","response":{"status":"in_progress"}}\n'
		"\n"
		"event: response.completed\n"
		'data: {"type":"response.completed","response":{'
		'"output":[{"type":"message","content":[{"type":"output_text","text":"hello"}]},'
		'{"type":"function_call","call_id":"c1","name":"foo","arguments":"{}"}],'
		'"usage":{"input_tokens":3,"output_tokens":4},"status":"completed"}}\n'
	)

	def _provider(self):
		from friday.friday_core.llm.provider import CodexProvider

		p = CodexProvider(oauth_token="tok", account_id="acc-9", default_model="gpt-5-codex")
		p._post_with_recovery = MagicMock(return_value=self._SSE)
		return p

	def test_request_shape_and_headers(self):
		p = self._provider()
		p.chat(
			messages=[{"role": "system", "content": "be brief"}, {"role": "user", "content": "hi"}],
			tools=[{"type": "function", "function": {"name": "foo", "description": "d", "parameters": {}}}],
		)
		call = p._post_with_recovery.call_args.kwargs
		headers, payload = call["headers"], call["payload"]
		self.assertEqual(headers["authorization"], "Bearer tok")
		self.assertEqual(headers["originator"], "codex_cli_rs")
		self.assertEqual(headers["ChatGPT-Account-ID"], "acc-9")
		self.assertEqual(payload["store"], False)
		self.assertIs(payload["stream"], True)
		self.assertEqual(payload["instructions"], "be brief")
		self.assertTrue(any(i.get("role") == "user" for i in payload["input"]))
		self.assertEqual(payload["tools"][0]["type"], "function")
		self.assertEqual(payload["tools"][0]["name"], "foo")

	def test_parses_text_and_tool_calls(self):
		p = self._provider()
		out = p.chat(messages=[{"role": "user", "content": "hi"}])
		self.assertEqual(out["content"], "hello")
		self.assertEqual(out["tool_calls"][0]["name"], "foo")
		self.assertEqual(out["usage"]["total_tokens"], 7)


if __name__ == "__main__":
	unittest.main()
