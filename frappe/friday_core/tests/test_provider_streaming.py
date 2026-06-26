# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""The provider `on_token` streaming primitive (streaming front-door enabler).

DB-free: drives `_consume_stream` with a hand-built fake OpenAI-SDK stream and asserts
the callback fires per text delta while the full content is still assembled. No network.
"""

from __future__ import annotations

import types
import unittest

from frappe.friday_core.llm.provider import MinimaxProvider


def _text_chunk(content, finish=None):
	delta = types.SimpleNamespace(content=content, tool_calls=None)
	choice = types.SimpleNamespace(delta=delta, finish_reason=finish)
	return types.SimpleNamespace(choices=[choice], usage=None)


def _usage_chunk():
	usage = types.SimpleNamespace(prompt_tokens=1, completion_tokens=2, total_tokens=3)
	return types.SimpleNamespace(choices=[], usage=usage)


def _stream():
	return iter([_text_chunk("Hel"), _text_chunk("lo"), _text_chunk(" world", finish="stop"), _usage_chunk()])


class TestOnTokenStreaming(unittest.TestCase):
	def _provider(self):
		return MinimaxProvider(api_key="x", default_model="m")

	def test_on_token_fires_per_delta_and_full_content_assembled(self):
		tokens = []
		data = self._provider()._consume_stream(_stream(), model="m", on_token=tokens.append)
		# Each text delta relayed live...
		self.assertEqual(tokens, ["Hel", "lo", " world"])
		# ...AND the full content still assembled exactly as before.
		self.assertEqual(data["choices"][0]["message"]["content"], "Hello world")
		self.assertEqual(data["usage"]["total_tokens"], 3)

	def test_no_callback_is_unchanged_behaviour(self):
		data = self._provider()._consume_stream(_stream(), model="m")
		self.assertEqual(data["choices"][0]["message"]["content"], "Hello world")

	def test_raising_callback_is_swallowed(self):
		# A UI relay hiccup must NOT abort a healthy generation.
		def boom(_):
			raise RuntimeError("client disconnected")

		data = self._provider()._consume_stream(_stream(), model="m", on_token=boom)
		self.assertEqual(data["choices"][0]["message"]["content"], "Hello world")


if __name__ == "__main__":
	unittest.main()
