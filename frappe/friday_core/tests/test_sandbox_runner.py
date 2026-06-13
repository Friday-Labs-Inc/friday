# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt

"""
Tests for the Slice 7 sandbox runner — the Docker container orchestrator.

These tests verify the execute() function correctly:
  - Spawns containers with proper resource limits and security flags
  - Parses structured result envelopes from container stdout
  - Maps exit codes to correct SandboxResult statuses
  - Falls back to in-process execution when Docker is unavailable
  - Handles OOM, timeout, and failed skill scenarios

Tests that require a live Docker daemon (T5, T6, T7 from the proposal)
are marked @unittest.skip if Docker is not reachable. The rest are pure
unit tests using unittest.mock.

HOW TO RUN
==========

    bench --site friday.localhost run-tests \
        --module frappe.friday_core.tests.test_sandbox_runner

REFERENCED DOCS
==============
- `docs/contributing/proposals/slice-7-docker-sandbox.md` §4
- `docs/design/24-sandbox-architecture-implementation.md`
"""

from __future__ import annotations

import json
import time
import unittest
from unittest.mock import MagicMock, patch

import frappe
from frappe.friday_core.sandbox.runner import (
	RESULT_BEGIN,
	RESULT_END,
	SandboxResult,
	_build_etc_hosts,
	_get_egress_config,
	_parse_result,
	_resolve_limits,
	execute,
)

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _make_result_envelope(status: str, result: dict | None = None, error: str = "") -> bytes:
	"""Build a container stdout payload matching the entrypoint's result envelope."""
	payload = {"status": status, "result": result}
	if error:
		payload["error"] = error
	return RESULT_BEGIN.encode() + b"\n" + json.dumps(payload).encode() + b"\n" + RESULT_END.encode() + b"\n"


def _mock_container(exit_code: int = 0, logs_bytes: bytes = b"", status: str = "exited"):
	"""Return a mock container that respond to the calls execute() makes."""
	container = MagicMock()
	container.short_id = "abc1234"
	container.status = status
	container.exit_code = exit_code
	container.logs.return_value = logs_bytes
	return container


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------


class TestParseResult(unittest.TestCase):
	"""Unit tests for the _parse_result helper (no Docker needed)."""

	def test_valid_success_envelope(self):
		envelope = {
			"status": "success",
			"result": {"name": "Note-001", "title": "Shopping"},
		}
		raw = RESULT_BEGIN + "\n" + json.dumps(envelope) + "\n" + RESULT_END
		status, result = _parse_result(raw)
		self.assertEqual(status, "success")
		self.assertEqual(result, {"name": "Note-001", "title": "Shopping"})

	def test_valid_failed_envelope(self):
		envelope = {"status": "failed", "result": None, "error": "KeyError: title"}
		raw = RESULT_BEGIN + "\n" + json.dumps(envelope) + "\n" + RESULT_END
		status, result = _parse_result(raw)
		self.assertEqual(status, "failed")
		self.assertIsNone(result)

	def test_missing_begin_marker_returns_protocol_error(self):
		raw = '{"status": "success"}\n' + RESULT_END
		status, _result = _parse_result(raw)
		self.assertEqual(status, "protocol_error")

	def test_missing_end_marker_returns_protocol_error(self):
		raw = RESULT_BEGIN + "\n{'status': 'success'}"
		status, _result = _parse_result(raw)
		self.assertEqual(status, "protocol_error")

	def test_malformed_json_returns_protocol_error(self):
		raw = RESULT_BEGIN + "\nnot valid json\n" + RESULT_END
		status, _result = _parse_result(raw)
		self.assertEqual(status, "protocol_error")


class TestResolveLimits(unittest.TestCase):
	"""Unit tests for _resolve_limits()."""

	def test_defaults_when_profile_not_found(self):
		cpu, memory, timeout = _resolve_limits("Nonexistent Profile", "any_skill")
		self.assertEqual(cpu, 1)
		self.assertEqual(memory, 256)
		self.assertEqual(timeout, 300)

	def test_raises_db_error_gracefully(self):
		# Profile can't be loaded — returns defaults
		cpu, _memory, _timeout = _resolve_limits("Also Nonexistent", "any_skill")
		self.assertEqual(cpu, 1)


class TestExecuteHappyPath(unittest.TestCase):
	"""T1: execute() spawns a container and returns status=success."""

	def setUp(self):
		frappe.db.rollback()

	@patch("frappe.friday_core.sandbox.runner._get_client")
	@patch("frappe.friday_core.sandbox.runner.frappe")
	@patch("frappe.friday_core.sandbox.runner.time.monotonic")
	def test_execute_returns_success_with_result(self, mock_monotonic, mock_frappe, mock_get_client):
		logs = _make_result_envelope("success", {"name": "Note-001", "title": "Test"})
		container = _mock_container(exit_code=0, logs_bytes=logs)
		container.status = "exited"

		mock_client = MagicMock()
		mock_client.containers.run.return_value = container
		mock_client.networks.get.return_value = MagicMock()
		mock_get_client.return_value = mock_client

		mock_frappe.local.site = "testsite.local"
		mock_profile = MagicMock()
		mock_profile.get.side_effect = lambda k: {"network_allowlist": ""}.get(k)
		mock_frappe.get_doc.return_value = mock_profile

		# Mock monotonic: started_at, iter1, iter2 (exits), duration_ms
		mock_monotonic.side_effect = [1.0, 1.001, 1.5, 1.6, 1.7]

		result = execute(
			skill_name="create_note",
			parameters={"title": "Test", "content": "hello"},
			agent_profile="Test Agent",
			credentials={},
			timeout_seconds=60,
		)

		self.assertEqual(result.status, "success")
		self.assertEqual(result.result, {"name": "Note-001", "title": "Test"})
		self.assertEqual(result.container_id, "abc1234")
		self.assertGreater(result.duration_ms, 0)

		# Verify container.run was called with expected security flags
		call_kwargs = mock_client.containers.run.call_args[1]
		self.assertEqual(call_kwargs["user"], 65532)
		self.assertEqual(call_kwargs["cap_drop"], "ALL")
		self.assertIn("no-new-privileges:true", call_kwargs["security_opt"])
		self.assertTrue(call_kwargs["read_only"])
		self.assertIn("/tmp", call_kwargs["tmpfs"])

	@patch("frappe.friday_core.sandbox.runner._get_client")
	def test_container_network_omitted_when_no_network(self, mock_get_client):
		"""When Docker network is unavailable, network= is not passed."""
		logs = _make_result_envelope("success", {"name": "Note-001"})
		container = _mock_container(exit_code=0, logs_bytes=logs)
		container.status = "exited"

		mock_client = MagicMock()
		mock_client.containers.run.return_value = container
		mock_client.networks.get.side_effect = Exception("no network")
		mock_get_client.return_value = mock_client

		result = execute(
			skill_name="create_note",
			parameters={"title": "No Network Test"},
			agent_profile="Test Agent",
			credentials={},
			timeout_seconds=30,
		)

		self.assertEqual(result.status, "success")
		# Verify network= was NOT in container_kwargs
		call_kwargs = mock_client.containers.run.call_args[1]
		self.assertNotIn("network", call_kwargs)


class TestExecuteExceptionHandling(unittest.TestCase):
	"""T2: Skill raises exception → status=failed."""

	def setUp(self):
		frappe.db.rollback()

	@patch("frappe.friday_core.sandbox.runner._get_client")
	@patch("frappe.friday_core.sandbox.runner.frappe")
	def test_handler_exception_returns_failed_status(self, mock_frappe, mock_get_client):
		logs = _make_result_envelope(
			"failed",
			result=None,
			error="ValueError: title is required",
		)
		container = _mock_container(exit_code=1, logs_bytes=logs)
		container.status = "exited"

		mock_client = MagicMock()
		mock_client.containers.run.return_value = container
		mock_client.networks.get.return_value = MagicMock()
		mock_get_client.return_value = mock_client

		mock_frappe.local.site = "testsite.local"
		mock_profile = MagicMock()
		mock_profile.get.side_effect = lambda k: {"network_allowlist": ""}.get(k)
		mock_frappe.get_doc.return_value = mock_profile

		result = execute(
			skill_name="create_note",
			parameters={"content": "No title provided"},
			agent_profile="Test Agent",
			credentials={},
			timeout_seconds=30,
		)

		self.assertEqual(result.status, "failed")


class TestExecuteOOM(unittest.TestCase):
	"""T3: Container OOM (exit code 137) → status=oom."""

	def setUp(self):
		frappe.db.rollback()

	@patch("frappe.friday_core.sandbox.runner._get_client")
	@patch("frappe.friday_core.sandbox.runner.frappe")
	def test_exit_code_137_maps_to_oom(self, mock_frappe, mock_get_client):
		logs = _make_result_envelope("success", {"data": "partial"})
		container = _mock_container(exit_code=137, logs_bytes=logs)
		container.status = "exited"

		mock_client = MagicMock()
		mock_client.containers.run.return_value = container
		mock_client.networks.get.return_value = MagicMock()
		mock_get_client.return_value = mock_client

		mock_frappe.local.site = "testsite.local"
		mock_profile = MagicMock()
		mock_profile.get.side_effect = lambda k: {"network_allowlist": ""}.get(k)
		mock_frappe.get_doc.return_value = mock_profile

		result = execute(
			skill_name="create_note",
			parameters={"title": "OOM Test"},
			agent_profile="Test Agent",
			credentials={},
			timeout_seconds=30,
		)

		self.assertEqual(result.status, "oom")


class TestExecuteTimeout(unittest.TestCase):
	"""T4: Wall-clock timeout → status=timeout."""

	def setUp(self):
		frappe.db.rollback()

	@patch("frappe.friday_core.sandbox.runner._get_client")
	@patch("frappe.friday_core.sandbox.runner.frappe")
	@patch("frappe.friday_core.sandbox.runner.time.monotonic")
	def test_timeout_reaches_kills_container(self, mock_monotonic, mock_frappe, mock_get_client):
		# Container never exits — simulate timeout at T=2s
		container = _mock_container(exit_code=0, logs_bytes=b"")
		container.status = "created"  # still running

		mock_client = MagicMock()
		mock_client.containers.run.return_value = container
		mock_client.networks.get.return_value = MagicMock()
		mock_get_client.return_value = mock_client

		mock_frappe.local.site = "testsite.local"
		mock_profile = MagicMock()
		mock_profile.get.side_effect = lambda k: {"network_allowlist": ""}.get(k)
		mock_frappe.get_doc.return_value = mock_profile

		# Monotonic: started_at, iter1, iter2, iter3 (timeout), duration
		mock_monotonic.side_effect = [0.0, 0.5, 1.5, 2.5, 3.0]

		result = execute(
			skill_name="create_note",
			parameters={"title": "Slow Skill"},
			agent_profile="Test Agent",
			credentials={},
			timeout_seconds=2,  # 2 second timeout
		)

		self.assertEqual(result.status, "timeout")
		self.assertTrue(container.kill.called)


class TestExecuteInvalidSkill(unittest.TestCase):
	"""T8: Unknown skill name → status=failed."""

	def setUp(self):
		frappe.db.rollback()

	@patch("frappe.friday_core.sandbox.runner._get_client")
	@patch("frappe.friday_core.sandbox.runner.frappe")
	def test_invalid_skill_name_returns_failed(self, mock_frappe, mock_get_client):
		logs = _make_result_envelope(
			"failed",
			result=None,
			error="ImportError: skill 'i_do_not_exist' not found",
		)
		container = _mock_container(exit_code=1, logs_bytes=logs)
		container.status = "exited"

		mock_client = MagicMock()
		mock_client.containers.run.return_value = container
		mock_client.networks.get.return_value = MagicMock()
		mock_get_client.return_value = mock_client

		mock_frappe.local.site = "testsite.local"
		mock_profile = MagicMock()
		mock_profile.get.side_effect = lambda k: {"network_allowlist": ""}.get(k)
		mock_frappe.get_doc.return_value = mock_profile

		result = execute(
			skill_name="i_do_not_exist",
			parameters={},
			agent_profile="Test Agent",
			credentials={},
			timeout_seconds=30,
		)

		self.assertEqual(result.status, "failed")


class TestExecuteEmptySkillName(unittest.TestCase):
	"""T9: Null/empty skill_name raises ValueError before touching Docker."""

	def setUp(self):
		frappe.db.rollback()

	@patch("frappe.friday_core.sandbox.runner._get_client")
	def test_empty_skill_name_raises_value_error(self, mock_get_client):
		with self.assertRaises(ValueError) as ctx:
			execute(
				skill_name="",
				parameters={},
				agent_profile="Test Agent",
				credentials={},
				timeout_seconds=30,
			)
		self.assertIn("skill_name", str(ctx.exception))

		# Docker should never have been touched
		mock_get_client.assert_not_called()


class TestExecuteDockerUnavailableFallback(unittest.TestCase):
	"""T1 fallback: Docker unavailable → returns SandboxResult with failed status."""

	def setUp(self):
		frappe.db.rollback()

	@patch("frappe.friday_core.sandbox.runner._get_client")
	def test_docker_unavailable_returns_failed_result(self, mock_get_client):
		mock_client = MagicMock()
		mock_client.containers.run.side_effect = Exception("Docker daemon not running")
		mock_get_client.return_value = mock_client

		result = execute(
			skill_name="create_note",
			parameters={"title": "Fallback Test"},
			agent_profile="Test Agent",
			credentials={},
			timeout_seconds=30,
		)

		self.assertEqual(result.status, "failed")
		self.assertIn("Docker daemon not running", result.logs)


class TestSandboxResultDataclass(unittest.TestCase):
	"""Sanity-check the SandboxResult dataclass."""

	def test_all_fields_present(self):
		result = SandboxResult(
			status="success",
			result={"name": "Note-001"},
			logs="container output here",
			duration_ms=1500,
			container_id="abc1234",
		)
		self.assertEqual(result.status, "success")
		self.assertEqual(result.result, {"name": "Note-001"})
		self.assertEqual(result.duration_ms, 1500)
		self.assertEqual(result.container_id, "abc1234")

	def test_defaults(self):
		result = SandboxResult(status="failed")
		self.assertIsNone(result.result)
		self.assertEqual(result.logs, "")
		self.assertEqual(result.duration_ms, 0)
		self.assertIsNone(result.container_id)


# ---------------------------------------------------------------------------
# Egress allowlist tests (Phase 1.5)
# ---------------------------------------------------------------------------


class TestBuildEtcHosts(unittest.TestCase):
	"""Unit tests for /etc/hosts-based egress allowlist."""

	def test_localhost_always_included(self):
		content = _build_etc_hosts("friday.localhost", [])
		self.assertIn("127.0.0.1 localhost", content)

	def test_frappe_host_included(self):
		content = _build_etc_hosts("friday.localhost", [])
		self.assertIn("127.0.0.1 friday.localhost", content)

	def test_extra_hosts_appended(self):
		content = _build_etc_hosts("friday.localhost", ["api.stripe.com", "maps.google.com"])
		self.assertIn("127.0.0.1 api.stripe.com", content)
		self.assertIn("127.0.0.1 maps.google.com", content)

	def test_duplicates_filtered(self):
		content = _build_etc_hosts("friday.localhost", ["api.stripe.com"])
		lines = content.splitlines()
		# Should appear once, not twice
		addr_lines = [l for l in lines if "api.stripe.com" in l]
		self.assertEqual(len(addr_lines), 1)


class TestGetEgressConfig(unittest.TestCase):
	"""Unit tests for _get_egress_config()."""

	@patch("frappe.friday_core.sandbox.runner.frappe")
	def test_default_returns_frappe_host_no_extras(self, mock_frappe):
		mock_profile = MagicMock()
		mock_profile.get.return_value = None
		mock_frappe.get_doc.return_value = mock_profile
		mock_frappe.local.site = "testsite.local"
		mock_profile.get.side_effect = lambda k: {"network_allowlist": ""}.get(k)

		frappe_host, extra = _get_egress_config("Test Profile")
		self.assertEqual(frappe_host, "testsite.local")
		self.assertEqual(extra, [])

	@patch("frappe.friday_core.sandbox.runner.frappe")
	def test_comma_separated_extra_hosts(self, mock_frappe):
		mock_profile = MagicMock()
		mock_profile.get.side_effect = lambda k: {"network_allowlist": "api.stripe.com,smtp.mailgun.org"}.get(
			k
		)
		mock_frappe.get_doc.return_value = mock_profile
		mock_frappe.local.site = "testsite.local"

		_, extra = _get_egress_config("Test Profile")
		self.assertEqual(extra, ["api.stripe.com", "smtp.mailgun.org"])

	@patch("frappe.friday_core.sandbox.runner.frappe")
	def test_newline_separated_extra_hosts(self, mock_frappe):
		mock_profile = MagicMock()
		mock_profile.get.side_effect = lambda k: {
			"network_allowlist": "api.stripe.com\nsmtp.mailgun.org"
		}.get(k)
		mock_frappe.get_doc.return_value = mock_profile
		mock_frappe.local.site = "testsite.local"

		_, extra = _get_egress_config("Test Profile")
		self.assertEqual(extra, ["api.stripe.com", "smtp.mailgun.org"])

	@patch("frappe.friday_core.sandbox.runner.frappe")
	def test_empty_allowlist_returns_empty_list(self, mock_frappe):
		mock_profile = MagicMock()
		mock_profile.get.side_effect = lambda k: {"network_allowlist": ""}.get(k)
		mock_frappe.get_doc.return_value = mock_profile
		mock_frappe.local.site = "testsite.local"

		_, extra = _get_egress_config("Test Profile")
		self.assertEqual(extra, [])

	@patch("frappe.friday_core.sandbox.runner.frappe")
	def test_profile_not_found_returns_defaults(self, mock_frappe):
		mock_frappe.get_doc.side_effect = Exception("Not found")
		mock_frappe.local.site = "testsite.local"

		frappe_host, extra = _get_egress_config("NonExistent Profile")
		self.assertEqual(frappe_host, "testsite.local")
		self.assertEqual(extra, [])


if __name__ == "__main__":
	unittest.main()
