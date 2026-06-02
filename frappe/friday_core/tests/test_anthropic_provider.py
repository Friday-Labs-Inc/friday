# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""
Unit tests for the Anthropic provider adapter (Feature B2, doc 51 §4.B2).

requests-mocked — no DB, no network — so they run on the dev Mac. Pins the
Messages-API translation in both directions:
  - REQUEST (B2.1): system hoisted to the top-level `system` param; assistant
    tool calls -> `tool_use` blocks; `{role:"tool"}` -> `tool_result` blocks
    (consecutive results merged into one user message); OpenAI tool defs ->
    `input_schema`; `max_tokens` required/defaulted.
  - RESPONSE (B2.2): `text` blocks -> `content`; `tool_use` blocks -> canonical
    flat `{id, name, arguments}` (arguments a JSON string) — the normalisation
    the runner depends on.
  - HEADERS (B2.3): `x-api-key` + pinned `anthropic-version` (not Bearer).
  - shared recovery: 401 -> LLMAuthError, 429 -> retry (Feature F classifier).
"""

import json
import unittest
from unittest.mock import MagicMock, patch

from frappe.friday_core.llm.provider import (
	AnthropicProvider,
	LLMAuthError,
	LLMError,
)

_POST = "frappe.friday_core.llm.provider.requests.post"


def _p(base_url=None, default_max_tokens=None):
	return AnthropicProvider(
		api_key="sk-ant",
		default_model="claude-3-5-sonnet",
		base_url=base_url,
		default_max_tokens=default_max_tokens,
	)


def _ok(blocks=None, stop_reason="end_turn", input_tokens=10, output_tokens=20):
	return MagicMock(
		status_code=200,
		json=lambda: {
			"content": blocks if blocks is not None else [{"type": "text", "text": "hello"}],
			"stop_reason": stop_reason,
			"usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
		},
	)


def _sent(mock_post):
	"""The JSON payload the provider POSTed."""
	return mock_post.call_args[1]["json"]


class TestAnthropicEndpointAndAuth(unittest.TestCase):
	def test_default_base_url(self):
		self.assertEqual(_p().base_url, "https://api.anthropic.com")

	@patch(_POST)
	def test_uses_messages_endpoint(self, mock_post):
		mock_post.return_value = _ok()
		_p().chat(messages=[{"role": "user", "content": "hi"}])
		self.assertEqual(mock_post.call_args[0][0], "https://api.anthropic.com/v1/messages")

	@patch(_POST)
	def test_base_url_override(self, mock_post):
		mock_post.return_value = _ok()
		_p(base_url="https://proxy.internal").chat(messages=[{"role": "user", "content": "hi"}])
		self.assertEqual(mock_post.call_args[0][0], "https://proxy.internal/v1/messages")

	@patch(_POST)
	def test_uses_x_api_key_and_version_not_bearer(self, mock_post):
		mock_post.return_value = _ok()
		_p().chat(messages=[{"role": "user", "content": "hi"}])
		headers = mock_post.call_args[1]["headers"]
		self.assertEqual(headers["x-api-key"], "sk-ant")
		self.assertEqual(headers["anthropic-version"], "2023-06-01")
		self.assertNotIn("Authorization", headers)


class TestAnthropicRequestTranslation(unittest.TestCase):
	@patch(_POST)
	def test_system_message_is_hoisted(self, mock_post):
		mock_post.return_value = _ok()
		_p().chat(messages=[
			{"role": "system", "content": "You are Friday."},
			{"role": "user", "content": "hi"},
		])
		sent = _sent(mock_post)
		self.assertEqual(sent["system"], "You are Friday.")
		# system must NOT remain inside messages
		self.assertEqual([m["role"] for m in sent["messages"]], ["user"])

	@patch(_POST)
	def test_max_tokens_defaulted_when_unset(self, mock_post):
		mock_post.return_value = _ok()
		_p().chat(messages=[{"role": "user", "content": "hi"}])
		self.assertEqual(_sent(mock_post)["max_tokens"], 4096)

	@patch(_POST)
	def test_max_tokens_from_row_wins(self, mock_post):
		mock_post.return_value = _ok()
		_p(default_max_tokens=1000).chat(messages=[{"role": "user", "content": "hi"}])
		self.assertEqual(_sent(mock_post)["max_tokens"], 1000)

	@patch(_POST)
	def test_assistant_tool_calls_become_tool_use_blocks(self, mock_post):
		# The runner re-sends an assistant turn in OpenAI WIRE shape
		# ({id, function:{name, arguments}}); the adapter must accept that.
		mock_post.return_value = _ok()
		_p().chat(messages=[
			{"role": "user", "content": "make a note"},
			{
				"role": "assistant",
				"content": "sure",
				"tool_calls": [
					{
						"id": "call_1",
						"type": "function",
						"function": {"name": "create_note", "arguments": '{"title": "x"}'},
					},
				],
			},
		])
		assistant = _sent(mock_post)["messages"][1]
		self.assertEqual(assistant["role"], "assistant")
		blocks = assistant["content"]
		self.assertEqual(blocks[0], {"type": "text", "text": "sure"})
		self.assertEqual(
			blocks[1],
			{"type": "tool_use", "id": "call_1", "name": "create_note", "input": {"title": "x"}},
		)

	@patch(_POST)
	def test_tool_message_becomes_tool_result_block(self, mock_post):
		mock_post.return_value = _ok()
		_p().chat(messages=[
			{"role": "user", "content": "make a note"},
			{"role": "assistant", "content": "", "tool_calls": [
				{"id": "call_1", "name": "create_note", "arguments": "{}"}]},
			{"role": "tool", "tool_call_id": "call_1", "content": "Note created"},
		])
		last = _sent(mock_post)["messages"][-1]
		self.assertEqual(last["role"], "user")
		self.assertEqual(
			last["content"],
			[{"type": "tool_result", "tool_use_id": "call_1", "content": "Note created"}],
		)

	@patch(_POST)
	def test_consecutive_tool_results_merge_into_one_user_message(self, mock_post):
		mock_post.return_value = _ok()
		_p().chat(messages=[
			{"role": "user", "content": "do two"},
			{"role": "assistant", "content": "", "tool_calls": [
				{"id": "c1", "name": "s", "arguments": "{}"},
				{"id": "c2", "name": "s", "arguments": "{}"}]},
			{"role": "tool", "tool_call_id": "c1", "content": "first"},
			{"role": "tool", "tool_call_id": "c2", "content": "second"},
		])
		last = _sent(mock_post)["messages"][-1]
		self.assertEqual(last["role"], "user")
		self.assertEqual(len(last["content"]), 2)
		self.assertEqual([b["tool_use_id"] for b in last["content"]], ["c1", "c2"])

	@patch(_POST)
	def test_openai_tool_defs_translated_to_input_schema(self, mock_post):
		mock_post.return_value = _ok()
		openai_tools = [{
			"type": "function",
			"function": {
				"name": "create_note",
				"description": "Make a note",
				"parameters": {"type": "object", "properties": {"title": {"type": "string"}}},
			},
		}]
		_p().chat(messages=[{"role": "user", "content": "hi"}], tools=openai_tools)
		self.assertEqual(_sent(mock_post)["tools"], [{
			"name": "create_note",
			"description": "Make a note",
			"input_schema": {"type": "object", "properties": {"title": {"type": "string"}}},
		}])


class TestAnthropicResponseTranslation(unittest.TestCase):
	@patch(_POST)
	def test_plain_text_roundtrip(self, mock_post):
		mock_post.return_value = _ok(blocks=[{"type": "text", "text": "Hi there"}])
		resp = _p().chat(messages=[{"role": "user", "content": "hi"}])
		self.assertEqual(resp["content"], "Hi there")
		self.assertIsNone(resp["tool_calls"])
		self.assertEqual(resp["finish_reason"], "end_turn")
		# input(10) + output(20) mapped onto the OpenAI-shaped usage fields.
		self.assertEqual(resp["usage"]["total_tokens"], 30)
		self.assertEqual(resp["usage"]["prompt_tokens"], 10)
		self.assertEqual(resp["usage"]["completion_tokens"], 20)

	@patch(_POST)
	def test_tool_use_becomes_flat_canonical_tool_call(self, mock_post):
		mock_post.return_value = _ok(
			blocks=[
				{"type": "text", "text": "I'll make it"},
				{"type": "tool_use", "id": "toolu_1", "name": "create_note", "input": {"title": "x"}},
			],
			stop_reason="tool_use",
		)
		resp = _p().chat(messages=[{"role": "user", "content": "make a note"}])
		self.assertEqual(resp["content"], "I'll make it")
		self.assertEqual(
			resp["tool_calls"],
			[{"id": "toolu_1", "name": "create_note", "arguments": '{"title": "x"}'}],
		)
		# arguments must be a JSON *string* (the dispatcher json.loads() it).
		self.assertIsInstance(resp["tool_calls"][0]["arguments"], str)
		self.assertEqual(json.loads(resp["tool_calls"][0]["arguments"]), {"title": "x"})


class TestAnthropicErrorHandling(unittest.TestCase):
	@patch(_POST)
	def test_401_raises_auth_error(self, mock_post):
		mock_post.return_value = MagicMock(status_code=401, text="invalid x-api-key")
		with self.assertRaises(LLMAuthError):
			_p().chat(messages=[{"role": "user", "content": "hi"}])

	@patch(_POST)
	def test_429_retries_then_llm_error(self, mock_post):
		mock_post.return_value = MagicMock(status_code=429, text="overloaded")
		with self.assertRaises(LLMError):
			_p().chat(messages=[{"role": "user", "content": "hi"}])
		self.assertEqual(mock_post.call_count, 3)


if __name__ == "__main__":
	unittest.main()
