# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt

"""
Unit tests for the Phase 1.5 scoped credentials module.

Tests cover:
- generate_scoped_token() returns a non-empty hex string
- generate_scoped_token() returns different values for different execution_ids
- resolve_credentials() returns {} when no Skill Credential rows exist
- resolve_credentials() returns env dict with FRIDAY_CREDS_ prefix when rows exist
- redact_credentials_from_logs() replaces credential values with [REDACTED:name]
- redact_credentials_from_logs() passes through when no credentials
- redact_credentials_from_logs() handles empty logs
"""

from __future__ import annotations

import unittest
from unittest.mock import patch


class TestGenerateScopedToken(unittest.TestCase):
	"""generate_scoped_token() produces a non-empty hex token."""

	def test_returns_non_empty_string(self):
		from frappe.friday_core.sandbox.credentials import generate_scoped_token

		result = generate_scoped_token("Note Taker Agent", "exec-123")
		self.assertIsInstance(result, str)
		self.assertGreater(len(result), 0)

	def test_is_hex_string(self):
		from frappe.friday_core.sandbox.credentials import generate_scoped_token

		result = generate_scoped_token("Note Taker Agent", "exec-123")
		# Should be valid hexadecimal (frappe.generate_hash returns hex)
		int(result, 16)
		self.assertEqual(len(result), len(result))  # no exception = valid hex

	def test_different_execution_ids_produce_different_tokens_same_agent(self):
		from frappe.friday_core.sandbox.credentials import generate_scoped_token

		t1 = generate_scoped_token("Note Taker Agent", "exec-aaa")
		t2 = generate_scoped_token("Note Taker Agent", "exec-bbb")
		self.assertNotEqual(t1, t2)


class TestResolveCredentialsEmpty(unittest.TestCase):
	"""resolve_credentials() returns {} when no rows exist in DB."""

	def test_returns_empty_dict_when_no_rows(self):
		from frappe.friday_core.sandbox.credentials import resolve_credentials

		with patch("frappe.friday_core.sandbox.credentials.frappe") as mock_frappe:
			mock_frappe.db.sql.return_value = []
			result = resolve_credentials("Note Taker Agent", "create_note")
			self.assertEqual(result, {})


class TestResolveCredentialsWithRows(unittest.TestCase):
	"""resolve_credentials() returns prefixed env vars for each row."""

	def test_returns_env_dict_with_friday_creds_prefix(self):
		from frappe.friday_core.sandbox.credentials import resolve_credentials

		fake_rows = [
			{
				"name": "email-service-key",
				"api_key": "ak-test-key",
				"api_token": "at-secret-token",
				"username": "agent_user",
			}
		]
		with patch("frappe.friday_core.sandbox.credentials.frappe") as mock_frappe:
			mock_frappe.db.sql.return_value = fake_rows
			result = resolve_credentials("Note Taker Agent", "create_note")

		self.assertIn("FRIDAY_CREDS_email-service-key", result)
		self.assertEqual(result["FRIDAY_CREDS_email-service-key"], "at-secret-token")
		self.assertIn("FRIDAY_CREDS_email-service-key_KEY", result)
		self.assertEqual(result["FRIDAY_CREDS_email-service-key_KEY"], "ak-test-key")
		self.assertIn("FRIDAY_CREDS_email-service-key_USER", result)
		self.assertEqual(result["FRIDAY_CREDS_email-service-key_USER"], "agent_user")

	def test_multiple_rows_all_prefixed(self):
		from frappe.friday_core.sandbox.credentials import resolve_credentials

		fake_rows = [
			{"name": "email-creds", "api_token": "tok1", "api_key": "", "username": ""},
			{"name": "sms-creds", "api_token": "tok2", "api_key": "", "username": ""},
		]
		with patch("frappe.friday_core.sandbox.credentials.frappe") as mock_frappe:
			mock_frappe.db.sql.return_value = fake_rows
			result = resolve_credentials("Note Taker Agent", "create_note")

		self.assertIn("FRIDAY_CREDS_email-creds", result)
		self.assertIn("FRIDAY_CREDS_sms-creds", result)

	def test_db_error_returns_empty_dict(self):
		from frappe.friday_core.sandbox.credentials import resolve_credentials

		with patch("frappe.friday_core.sandbox.credentials.frappe") as mock_frappe:
			mock_frappe.db.sql.side_effect = Exception("db connection lost")
			result = resolve_credentials("Note Taker Agent", "create_note")
			self.assertEqual(result, {})


class TestRedactCredentialsFromLogs(unittest.TestCase):
	"""redact_credentials_from_logs() replaces value with [REDACTED:name]."""

	def test_replaces_credential_value(self):
		from frappe.friday_core.sandbox.credentials import redact_credentials_from_logs

		logs = "Connecting with token secret123 and api key xyz"
		creds = {"api_token": "secret123", "api_key": "xyz"}

		result = redact_credentials_from_logs(logs, creds)
		self.assertNotIn("secret123", result)
		self.assertIn("[REDACTED:api_token]", result)
		self.assertNotIn("xyz", result)
		self.assertIn("[REDACTED:api_key]", result)

	def test_no_credentials_returns_logs_unchanged(self):
		from frappe.friday_core.sandbox.credentials import redact_credentials_from_logs

		logs = "Task completed successfully"
		result = redact_credentials_from_logs(logs, {})
		self.assertEqual(result, logs)

	def test_empty_logs_returns_empty(self):
		from frappe.friday_core.sandbox.credentials import redact_credentials_from_logs

		creds = {"api_token": "secret123"}
		result = redact_credentials_from_logs("", creds)
		self.assertEqual(result, "")

	def test_none_credentials_returns_logs_unchanged(self):
		from frappe.friday_core.sandbox.credentials import redact_credentials_from_logs

		logs = "Connecting using api_token=secret123"
		result = redact_credentials_from_logs(logs, None)
		self.assertEqual(result, logs)


if __name__ == "__main__":
	unittest.main()
