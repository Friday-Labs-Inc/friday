# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""
Unit tests for the LLM error classifier (Feature F, doc 51 §4.F).

Pure logic — no DB, no HTTP. Pins the trimmed v0.1 taxonomy (F.1), the
result + hint fields (F.2), and the hint semantics (F.3): one case per
`FailoverReason` mapping (status code / message -> reason + hints).
"""

import unittest

from frappe.friday_core.llm.error_classifier import (
	ClassifiedError,
	FailoverReason,
	classify_api_error,
)


class TestStatusCodeMapping(unittest.TestCase):
	"""Status code -> FailoverReason (the primary signal)."""

	def _reason(self, status_code, message=None):
		return classify_api_error(status_code=status_code, message=message).reason

	def test_401_is_auth(self):
		self.assertEqual(self._reason(401), FailoverReason.auth)

	def test_403_is_auth(self):
		self.assertEqual(self._reason(403), FailoverReason.auth)

	def test_402_is_billing(self):
		self.assertEqual(self._reason(402), FailoverReason.billing)

	def test_429_is_rate_limit(self):
		self.assertEqual(self._reason(429), FailoverReason.rate_limit)

	def test_429_with_billing_message_is_billing(self):
		# A 429 that's really credit exhaustion (not transient throttling).
		self.assertEqual(
			self._reason(429, "You have insufficient credits to complete this request"),
			FailoverReason.billing,
		)

	def test_500_is_server_error(self):
		self.assertEqual(self._reason(500), FailoverReason.server_error)

	def test_502_is_server_error(self):
		self.assertEqual(self._reason(502), FailoverReason.server_error)

	def test_503_is_overloaded(self):
		self.assertEqual(self._reason(503), FailoverReason.overloaded)

	def test_529_is_overloaded(self):
		self.assertEqual(self._reason(529), FailoverReason.overloaded)

	def test_404_is_model_not_found(self):
		self.assertEqual(self._reason(404), FailoverReason.model_not_found)

	def test_413_is_context_overflow(self):
		self.assertEqual(self._reason(413), FailoverReason.context_overflow)

	def test_400_is_format_error(self):
		self.assertEqual(self._reason(400), FailoverReason.format_error)

	def test_400_with_context_message_is_context_overflow(self):
		self.assertEqual(
			self._reason(400, "This model's maximum context length is 8192 tokens"),
			FailoverReason.context_overflow,
		)

	def test_unknown_status_is_unknown(self):
		self.assertEqual(self._reason(418), FailoverReason.unknown)


class TestMessageAndExceptionMapping(unittest.TestCase):
	"""When there's no decisive status code, fall back to message/type."""

	def test_timeout_exception_is_timeout(self):
		class ReadTimeout(Exception):
			pass

		self.assertEqual(classify_api_error(ReadTimeout("read timed out")).reason, FailoverReason.timeout)

	def test_timeout_message_is_timeout(self):
		self.assertEqual(classify_api_error(message="Connection timed out").reason, FailoverReason.timeout)

	def test_context_message_is_context_overflow(self):
		self.assertEqual(
			classify_api_error(message="context_length_exceeded").reason,
			FailoverReason.context_overflow,
		)

	def test_model_not_found_message(self):
		self.assertEqual(
			classify_api_error(message="The model `gpt-9` does not exist").reason,
			FailoverReason.model_not_found,
		)

	def test_rate_limit_message(self):
		self.assertEqual(
			classify_api_error(message="Too Many Requests, please retry after 2s").reason,
			FailoverReason.rate_limit,
		)

	def test_no_info_is_unknown(self):
		self.assertEqual(classify_api_error().reason, FailoverReason.unknown)


class TestHints(unittest.TestCase):
	"""F.3 — hint semantics per reason (retryable / should_compress / should_fallback)."""

	def test_retryable_reasons_backoff(self):
		# rate_limit, overloaded, server_error, timeout, unknown -> retry with backoff.
		for sc in (429, 503, 500):
			self.assertTrue(classify_api_error(status_code=sc).retryable)
		self.assertTrue(classify_api_error(message="timed out").retryable)
		self.assertTrue(classify_api_error().retryable)  # unknown

	def test_auth_billing_model_format_surface_clean_error(self):
		# Not retryable; should_fallback (which in v0.1 = surface a clean error).
		for sc in (401, 402, 404, 400):
			c = classify_api_error(status_code=sc)
			self.assertFalse(c.retryable)
			self.assertTrue(c.should_fallback)
			self.assertFalse(c.should_compress)

	def test_context_overflow_compresses_not_retries(self):
		c = classify_api_error(status_code=413)
		self.assertFalse(c.retryable)
		self.assertTrue(c.should_compress)
		self.assertFalse(c.should_fallback)

	def test_result_carries_context(self):
		c = classify_api_error(status_code=429, provider="minimax", model="MiniMax-Standard", message="slow down")
		self.assertIsInstance(c, ClassifiedError)
		self.assertEqual(c.status_code, 429)
		self.assertEqual(c.provider, "minimax")
		self.assertEqual(c.model, "MiniMax-Standard")
		self.assertIn("slow down", c.message)


if __name__ == "__main__":
	unittest.main()
