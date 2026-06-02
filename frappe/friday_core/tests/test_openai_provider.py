# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""
Unit tests for the OpenAI provider adapter (Feature B1, doc 51 §4.B1).

requests-mocked — no DB, no network — so they run on the Mac. Pins:
  - the canonical endpoint (`/v1/chat/completions`) + Bearer auth, base_url
    overridable (Azure / OpenRouter / proxy);
  - the unchanged `LLMResponse` contract (plain-text + tool-call round-trips);
  - shared error handling (401 -> LLMAuthError, 429 -> retry) via the Feature F
    classifier.
"""

import unittest
from unittest.mock import MagicMock, patch

from frappe.friday_core.llm.provider import (
	LLMAuthError,
	LLMError,
	OpenAIProvider,
)

_POST = "frappe.friday_core.llm.provider.requests.post"


def _p(base_url=None):
	return OpenAIProvider(api_key="sk-test", default_model="gpt-4o", base_url=base_url)


def _ok(content="hello", tool_calls=None):
	return MagicMock(
		status_code=200,
		json=lambda: {
			"choices": [
				{
					"message": {"content": content, "tool_calls": tool_calls},
					"finish_reason": "tool_calls" if tool_calls else "stop",
				}
			],
			"usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
		},
	)


class TestOpenAIProvider(unittest.TestCase):
	def test_default_base_url_is_openai(self):
		self.assertEqual(_p().base_url, "https://api.openai.com")

	@patch(_POST)
	def test_uses_chat_completions_endpoint(self, mock_post):
		mock_post.return_value = _ok()
		_p().chat(messages=[{"role": "user", "content": "hi"}])
		self.assertEqual(mock_post.call_args[0][0], "https://api.openai.com/v1/chat/completions")

	@patch(_POST)
	def test_base_url_override(self, mock_post):
		mock_post.return_value = _ok()
		_p(base_url="https://openrouter.ai/api").chat(messages=[{"role": "user", "content": "hi"}])
		self.assertEqual(mock_post.call_args[0][0], "https://openrouter.ai/api/v1/chat/completions")

	@patch(_POST)
	def test_bearer_auth_header(self, mock_post):
		mock_post.return_value = _ok()
		_p().chat(messages=[{"role": "user", "content": "hi"}])
		self.assertEqual(mock_post.call_args[1]["headers"]["Authorization"], "Bearer sk-test")

	@patch(_POST)
	def test_plain_text_roundtrip(self, mock_post):
		mock_post.return_value = _ok(content="Hi there")
		resp = _p().chat(messages=[{"role": "user", "content": "hi"}])
		self.assertEqual(resp["content"], "Hi there")
		self.assertIsNone(resp["tool_calls"])
		self.assertEqual(resp["usage"]["total_tokens"], 3)

	@patch(_POST)
	def test_tool_call_normalized_to_flat_canonical(self, mock_post):
		# OpenAI returns tool calls NESTED under `function`; the provider must
		# flatten to the canonical {id, name, arguments} the dispatcher + runner
		# read (doc 51 §4.B2.2). Left nested, dispatch would see no name.
		nested = [
			{
				"id": "call_1",
				"type": "function",
				"function": {"name": "create_note", "arguments": '{"title": "x"}'},
			}
		]
		mock_post.return_value = _ok(content="", tool_calls=nested)
		resp = _p().chat(messages=[{"role": "user", "content": "make a note"}])
		self.assertEqual(
			resp["tool_calls"],
			[{"id": "call_1", "name": "create_note", "arguments": '{"title": "x"}'}],
		)

	@patch(_POST)
	def test_401_raises_auth_error(self, mock_post):
		mock_post.return_value = MagicMock(status_code=401, text="invalid api key")
		with self.assertRaises(LLMAuthError):
			_p().chat(messages=[{"role": "user", "content": "hi"}])

	@patch(_POST)
	def test_429_retries_then_llm_error(self, mock_post):
		mock_post.return_value = MagicMock(status_code=429, text="rate limited")
		with self.assertRaises(LLMError):
			_p().chat(messages=[{"role": "user", "content": "hi"}])
		self.assertEqual(mock_post.call_count, 3)


if __name__ == "__main__":
	unittest.main()
