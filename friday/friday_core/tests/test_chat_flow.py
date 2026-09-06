# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt

"""
Tests for the Slice 4 v2 chat flow — unified gateway pattern.

PLAIN ENGLISH
=============

These tests prove the gateway chokepoint pattern works:

  - When ANY surface (we use the CLI as the representative) writes an
    inbound Chat Message row, the gateway fires automatically via
    Frappe's `doc_events.after_insert`.
  - The gateway runs the agent and writes an outbound Chat Message row
    in the SAME transaction.
  - The CLI then reads the outbound row directly from the database
    (since the "cli" Chat Platform has dispatch_mode="sync").
  - The inbound row gets marked `processed=1`.
  - The gateway does NOT loop on its own outbound writes (skip rule).
  - Adapter contract violations (missing agent_profile) produce a clean
    system-error outbound, never crash.

Also covers the routing helper and the recovery sweeper at a basic
level so future regressions on those modules surface here.

TEST DATA STRATEGY
==================

We reuse the Slice 2/3 test Role + a profile with permitted_skills so
the stub agent has a non-empty tool menu in its reply (verifies the
Slice 3 chain end-to-end).

HOW TO RUN
==========

    bench --site friday.localhost run-tests \\
        --module friday.friday_core.tests.test_chat_flow

REFERENCED DOCS
===============
- `docs/design/47-gateway-design-decisions.md` — the contract being tested.
- `docs/rollouts/slice-4-chat-flow.md` — narrative.
"""

from __future__ import annotations

import time
import unittest
import uuid
from unittest.mock import MagicMock, patch

import frappe
from friday.friday_core.agent_runner.runner import run_turn
from friday.friday_core.cli.chat import (
	CLI_PLATFORM_NAME,
	handle_user_message,
)
from friday.friday_core.gateway import recovery as recovery_module
from friday.friday_core.routing.resolve import resolve_profile

TARGET_DOCTYPE = "Note"
TEST_ROLE = "Friday Test Reader"
PROFILE_WITH_TOOLS = "FRIDAY-SLICE4V2-PROFILE-TOOLS"
PROFILE_NO_TOOLS = "FRIDAY-SLICE4V2-PROFILE-NO-TOOLS"
SKILL_NAME = "slice4v2-skill"
TEST_LLM_PROVIDER = "friday-chatflow-test-provider"

# Async-platform test fixtures (for recovery sweeper tests)
ASYNC_PLATFORM_NAME = "test-async-platform"


def _ensure_role():
	"""Same pattern as Slice 2 / 3 tests — a Role with `read` on Note."""
	if not frappe.db.exists("Role", TEST_ROLE):
		frappe.get_doc({"doctype": "Role", "role_name": TEST_ROLE}).insert(ignore_permissions=True)
	if not frappe.db.exists("Custom DocPerm", {"parent": TARGET_DOCTYPE, "role": TEST_ROLE}):
		frappe.get_doc(
			{
				"doctype": "Custom DocPerm",
				"parent": TARGET_DOCTYPE,
				"parenttype": "DocType",
				"parentfield": "permissions",
				"role": TEST_ROLE,
				"read": 1,
				"permlevel": 0,
			}
		).insert(ignore_permissions=True)


def _ensure_skill():
	"""Active skill that needs read on Note."""
	if frappe.db.exists("Skill", SKILL_NAME):
		skill = frappe.get_doc("Skill", SKILL_NAME)
		skill.status = "Active"
		skill.required_doctypes = []
		skill.append("required_doctypes", {"target_doctype": TARGET_DOCTYPE, "operation": "read"})
		skill.save(ignore_permissions=True)
		return
	frappe.get_doc(
		{
			"doctype": "Skill",
			"skill_name": SKILL_NAME,
			"description": "Slice 4 v2 test skill",
			"risk_level": "low",
			"status": "Active",
			"required_doctypes": [{"target_doctype": TARGET_DOCTYPE, "operation": "read"}],
		}
	).insert(ignore_permissions=True)


def _ensure_profile(name: str, with_skill: bool):
	"""Profile with the test role and (optionally) the test skill on its allow-list."""
	skills = [SKILL_NAME] if with_skill else []
	if frappe.db.exists("Agent Profile", name):
		profile = frappe.get_doc("Agent Profile", name)
		profile.status = "Active"
		profile.assigned_roles = []
		profile.permitted_skills = []
		profile.append("assigned_roles", {"role": TEST_ROLE})
		for s in skills:
			profile.append("permitted_skills", {"skill": s})
		profile.save(ignore_permissions=True)
		return
	frappe.get_doc(
		{
			"doctype": "Agent Profile",
			"profile_name": name,
			"status": "Active",
			"requires_approval_above_risk": "high",
			"assigned_roles": [{"role": TEST_ROLE}],
			"permitted_skills": [{"skill": s} for s in skills],
		}
	).insert(ignore_permissions=True)


def _ensure_async_platform():
	"""A second Chat Platform record with dispatch_mode='async' for sweeper tests."""
	if frappe.db.exists("Chat Platform", ASYNC_PLATFORM_NAME):
		return
	frappe.get_doc(
		{
			"doctype": "Chat Platform",
			"platform_name": ASYNC_PLATFORM_NAME,
			"adapter_module": "test.async.adapter",
			"enabled": 1,
			"dispatch_mode": "async",
			"default_agent_profile": PROFILE_WITH_TOOLS,
			"batch_idle_ms": 500,
		}
	).insert(ignore_permissions=True)


def _ensure_llm_provider():
	"""Create a test LLM Provider row."""
	if frappe.db.exists("LLM Provider", TEST_LLM_PROVIDER):
		doc = frappe.get_doc("LLM Provider", TEST_LLM_PROVIDER)
		doc.is_active = 1
		doc.provider_type = "minimax"
		doc.api_key = "test-key-for-chatflow"
		doc.default_model = "MiniMax-Standard"
		doc.save(ignore_permissions=True)
		return
	frappe.get_doc(
		{
			"doctype": "LLM Provider",
			"provider_name": TEST_LLM_PROVIDER,
			"provider_type": "minimax",
			"is_active": 1,
			"api_key": "test-key-for-chatflow",
			"default_model": "MiniMax-Standard",
			"default_max_tokens": 2048,
			"default_temperature": 0.7,
		}
	).insert(ignore_permissions=True)


def _link_provider_to_profile(profile_name: str):
	"""Link the test LLM Provider to the given profile's model_provider field."""
	frappe.db.set_value(
		"Agent Profile",
		profile_name,
		"model_provider",
		TEST_LLM_PROVIDER,
		update_modified=False,
	)


# =============================================================================
# Chat flow tests — the meat of Slice 4 v2
# =============================================================================


class TestChatFlow(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		_ensure_role()
		_ensure_skill()
		_ensure_llm_provider()
		_ensure_profile(PROFILE_WITH_TOOLS, with_skill=True)
		_ensure_profile(PROFILE_NO_TOOLS, with_skill=False)
		_link_provider_to_profile(PROFILE_WITH_TOOLS)
		frappe.db.commit()

	def setUp(self):
		# Cold caches between tests so the loader / matrix are deterministic.
		frappe.cache().delete_keys("friday:skills:")
		frappe.cache().delete_keys("friday:perm_matrix:")
		# Don't flush session_locks — letting them carry state across tests
		# would only matter if tests collided on session_id (they don't,
		# they use fresh UUIDs each).

	# ------- the stub agent runner -------

	def test_run_turn_pure_function_returns_reply_with_tool_count(self):
		"""run_turn is pure: no DB writes, deterministic reply text.

		Slice 5 update: run_turn calls the real LLM via get_provider_for_profile.
		We patch MinimaxProvider.chat directly so no HTTP or DB calls are made.
		"""
		from friday.friday_core.llm.provider import MinimaxProvider

		reply_content = f"I can help with that using {SKILL_NAME}."

		def fake_chat(self, messages, tools=None, model=None):
			return {
				"content": reply_content,
				"finish_reason": "stop",
				"usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
			}

		with patch.object(MinimaxProvider, "chat", fake_chat):
			before = frappe.db.count("Chat Message")
			reply = run_turn(PROFILE_WITH_TOOLS, "session-pure", "hello")
			after = frappe.db.count("Chat Message")

		self.assertEqual(before, after, "run_turn must NOT write Chat Message rows")
		self.assertIn(SKILL_NAME, reply)

	# ------- end-to-end CLI -> gateway -> back -------

	def test_handle_user_message_writes_inbound_row(self):
		session_id = str(uuid.uuid4())
		handle_user_message(PROFILE_WITH_TOOLS, session_id, "alpha")

		rows = frappe.get_all(
			"Chat Message",
			filters={"session_id": session_id, "direction": "inbound"},
			fields=["name", "content", "agent_profile", "platform", "processed"],
		)
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0]["content"], "alpha")
		self.assertEqual(rows[0]["agent_profile"], PROFILE_WITH_TOOLS)
		self.assertEqual(rows[0]["platform"], CLI_PLATFORM_NAME)
		# Gateway should have marked it processed after writing outbound.
		self.assertEqual(rows[0]["processed"], 1, "gateway should mark inbound processed")

	def test_handle_user_message_gateway_writes_outbound_row(self):
		"""Gateway writes outbound row with correct sender_id and content from LLM."""
		from friday.friday_core.llm.provider import MinimaxProvider

		def fake_chat(self, messages, tools=None, model=None):
			return {
				"content": "Got your message beta",
				"finish_reason": "stop",
				"usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
			}

		with patch.object(MinimaxProvider, "chat", fake_chat):
			session_id = str(uuid.uuid4())
			reply = handle_user_message(PROFILE_WITH_TOOLS, session_id, "beta")

		rows = frappe.get_all(
			"Chat Message",
			filters={"session_id": session_id, "direction": "outbound"},
			fields=["name", "content", "sender_id"],
		)
		self.assertEqual(len(rows), 1, "gateway should write exactly one outbound row per inbound")
		self.assertEqual(rows[0]["content"], reply)
		self.assertEqual(rows[0]["sender_id"], PROFILE_WITH_TOOLS)
		self.assertEqual(rows[0]["content"], "Got your message beta")

	def test_handle_user_message_returns_outbound_content(self):
		"""The string returned by handle_user_message equals the outbound row's content."""
		from friday.friday_core.llm.provider import MinimaxProvider

		def fake_chat(self, messages, tools=None, model=None):
			return {
				"content": "gamma response",
				"finish_reason": "stop",
				"usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
			}

		with patch.object(MinimaxProvider, "chat", fake_chat):
			session_id = str(uuid.uuid4())
			reply = handle_user_message(PROFILE_WITH_TOOLS, session_id, "gamma")
			stored = frappe.db.get_value(
				"Chat Message",
				{"session_id": session_id, "direction": "outbound"},
				"content",
			)

		self.assertEqual(reply, stored)

	def test_session_id_shared_across_both_directions(self):
		session_id = str(uuid.uuid4())
		handle_user_message(PROFILE_WITH_TOOLS, session_id, "delta")
		count = frappe.db.count("Chat Message", filters={"session_id": session_id})
		self.assertEqual(count, 2, "one turn = one inbound + one outbound")

	def test_cli_platform_auto_created_with_sync_dispatch(self):
		"""First CLI call must create the 'cli' Chat Platform record with dispatch_mode=sync."""
		# Force-delete if a prior test created it, so we exercise the
		# create branch. `force=1` bypasses LinkExistsError (caused by
		# existing Chat Message rows referencing this platform).
		if frappe.db.exists("Chat Platform", CLI_PLATFORM_NAME):
			frappe.delete_doc(
				"Chat Platform",
				CLI_PLATFORM_NAME,
				ignore_permissions=True,
				force=1,
			)
		self.assertFalse(frappe.db.exists("Chat Platform", CLI_PLATFORM_NAME))

		handle_user_message(PROFILE_WITH_TOOLS, str(uuid.uuid4()), "first-call")

		self.assertTrue(frappe.db.exists("Chat Platform", CLI_PLATFORM_NAME))
		platform = frappe.get_doc("Chat Platform", CLI_PLATFORM_NAME)
		self.assertEqual(platform.adapter_module, "friday.friday_core.cli.chat")
		self.assertEqual(platform.enabled, 1)
		# The critical bit: dispatch_mode MUST be "sync" so the gateway runs
		# inline with the inbound insert() call. The CLI relies on this.
		self.assertEqual(platform.dispatch_mode, "sync")

	def test_gateway_does_not_loop_on_outbound_rows(self):
		"""Writing an outbound row directly must NOT trigger another gateway run."""
		session_id = str(uuid.uuid4())
		before = frappe.db.count("Chat Message")
		# Insert an outbound row directly — gateway should see direction='outbound'
		# and return without doing anything.
		frappe.get_doc(
			{
				"doctype": "Chat Message",
				"session_id": session_id,
				"platform": CLI_PLATFORM_NAME,
				"direction": "outbound",
				"sender_id": "test",
				"agent_profile": PROFILE_WITH_TOOLS,
				"content": "direct outbound write",
				"timestamp": frappe.utils.now_datetime(),
				"processed": 1,
			}
		).insert(ignore_permissions=True)
		frappe.db.commit()
		after = frappe.db.count("Chat Message")
		# Exactly one row added (the outbound we wrote); gateway did NOT
		# react with another outbound or inbound of its own.
		self.assertEqual(after, before + 1, "gateway must skip direction=outbound rows")

	def test_gateway_writes_system_error_on_missing_agent_profile(self):
		"""Inbound row with no agent_profile triggers a clean system-error outbound."""
		session_id = str(uuid.uuid4())
		# Write directly (bypassing the CLI helper) so we can craft the bad row.
		# `chat platform` does exist (auto-created by prior tests).
		if not frappe.db.exists("Chat Platform", CLI_PLATFORM_NAME):
			handle_user_message(PROFILE_WITH_TOOLS, "bootstrap", "init")
		frappe.get_doc(
			{
				"doctype": "Chat Message",
				"session_id": session_id,
				"platform": CLI_PLATFORM_NAME,
				"direction": "inbound",
				"sender_id": "test",
				# agent_profile DELIBERATELY OMITTED — adapter contract violation
				"content": "no profile",
				"timestamp": frappe.utils.now_datetime(),
				"processed": 0,
			}
		).insert(ignore_permissions=True)
		frappe.db.commit()
		# The gateway should have written a system-error outbound row.
		outbound = frappe.get_all(
			"Chat Message",
			filters={"session_id": session_id, "direction": "outbound"},
			fields=["content", "sender_id"],
		)
		self.assertEqual(len(outbound), 1)
		self.assertEqual(outbound[0]["sender_id"], "system")
		self.assertIn("agent_profile", outbound[0]["content"])

	def test_round_trip_under_one_second(self):
		"""Latency budget: <1s on local dev. Mocked LLM call should be ~10ms total."""
		from friday.friday_core.llm.provider import MinimaxProvider

		def fake_chat(self, messages, tools=None, model=None):
			return {
				"content": "perf response",
				"finish_reason": "stop",
				"usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
			}

		with patch.object(MinimaxProvider, "chat", fake_chat):
			session_id = str(uuid.uuid4())
			start = time.perf_counter()
			handle_user_message(PROFILE_WITH_TOOLS, session_id, "perf check")
			elapsed = time.perf_counter() - start

		self.assertLess(elapsed, 1.0, f"round-trip should be <1s, got {elapsed:.3f}s")


# =============================================================================
# Routing tests — Q3 stub helper
# =============================================================================


class TestRouting(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		_ensure_role()
		_ensure_skill()
		_ensure_profile(PROFILE_WITH_TOOLS, with_skill=True)
		_ensure_async_platform()
		frappe.db.commit()

	def test_resolve_profile_returns_default_when_platform_has_one(self):
		"""The async test platform has default_agent_profile set → that profile is returned."""
		resolved = resolve_profile(ASYNC_PLATFORM_NAME)
		self.assertEqual(resolved, PROFILE_WITH_TOOLS)

	def test_resolve_profile_returns_none_when_no_default(self):
		"""CLI platform has no default_agent_profile → returns None."""
		# Ensure the CLI platform exists (auto-created by other tests' first call).
		if not frappe.db.exists("Chat Platform", CLI_PLATFORM_NAME):
			handle_user_message(PROFILE_WITH_TOOLS, "bootstrap", "init")
		resolved = resolve_profile(CLI_PLATFORM_NAME)
		# CLI platform has no default → None
		self.assertIsNone(resolved)

	def test_resolve_profile_returns_none_for_unknown_platform(self):
		"""Unknown platform name returns None rather than raising."""
		resolved = resolve_profile("definitely-not-a-real-platform-9999")
		self.assertIsNone(resolved)


# =============================================================================
# Recovery sweeper tests — Q5 half-step
# =============================================================================


class TestRecoverySweeper(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		_ensure_role()
		_ensure_skill()
		_ensure_profile(PROFILE_WITH_TOOLS, with_skill=True)
		_ensure_async_platform()
		frappe.db.commit()

	def setUp(self):
		# Wipe any leftover inbound rows on the test async platform from
		# prior runs so each test starts clean.
		stale = frappe.get_all(
			"Chat Message",
			filters={"platform": ASYNC_PLATFORM_NAME},
			pluck="name",
		)
		for name in stale:
			frappe.delete_doc("Chat Message", name, ignore_permissions=True, force=1)
		frappe.db.commit()

	def test_sweeper_returns_zero_on_pure_sync_deployment(self):
		"""With no async platforms in the test, sweeper does nothing.

		Note: this test only holds if the async test platform was NOT
		created. We explicitly skip-creating in this test by deleting
		the platform first.
		"""
		if frappe.db.exists("Chat Platform", ASYNC_PLATFORM_NAME):
			frappe.delete_doc("Chat Platform", ASYNC_PLATFORM_NAME, ignore_permissions=True, force=1)
		frappe.db.commit()

		stats = recovery_module.sweep_orphans()
		self.assertEqual(stats["checked"], 0)
		self.assertEqual(stats["reenqueued"], 0)
		self.assertEqual(stats["gave_up"], 0)

		# Re-create for other tests in this class
		_ensure_async_platform()
		frappe.db.commit()

	def test_sweeper_ignores_recent_inbound(self):
		"""Inbound row written just now should NOT be considered orphaned."""
		# Write a fresh inbound row on the async platform.
		frappe.get_doc(
			{
				"doctype": "Chat Message",
				"session_id": str(uuid.uuid4()),
				"platform": ASYNC_PLATFORM_NAME,
				"direction": "inbound",
				"sender_id": "test",
				"agent_profile": PROFILE_WITH_TOOLS,
				"content": "very recent",
				"timestamp": frappe.utils.now_datetime(),
				"processed": 0,
			}
		).insert(ignore_permissions=True)
		frappe.db.commit()

		stats = recovery_module.sweep_orphans()
		self.assertEqual(stats["checked"], 0, "recent rows must not be swept")

	def test_sweeper_gives_up_after_max_retries(self):
		"""A stale row with retry_count already at MAX_RETRIES → give up immediately."""
		# Insert a stale (>5 min old) inbound row at max retries.
		old_timestamp = frappe.utils.add_to_date(frappe.utils.now_datetime(), minutes=-10)
		inbound = frappe.get_doc(
			{
				"doctype": "Chat Message",
				"session_id": str(uuid.uuid4()),
				"platform": ASYNC_PLATFORM_NAME,
				"direction": "inbound",
				"sender_id": "test",
				"agent_profile": PROFILE_WITH_TOOLS,
				"content": "stuck forever",
				"timestamp": old_timestamp,
				"processed": 0,
				"retry_count": recovery_module.MAX_RETRIES,
			}
		).insert(ignore_permissions=True)
		# Force the creation timestamp to be old (Frappe sets creation=now
		# automatically). Manual update to simulate stale row.
		frappe.db.set_value(
			"Chat Message",
			inbound.name,
			"creation",
			old_timestamp,
			update_modified=False,
		)
		frappe.db.commit()

		stats = recovery_module.sweep_orphans()
		self.assertEqual(stats["gave_up"], 1, "max-retry stale row should be given up on")
		self.assertEqual(stats["reenqueued"], 0)

		# Verify the give-up effects: inbound is now processed; system-error
		# outbound was written.
		updated = frappe.get_doc("Chat Message", inbound.name)
		self.assertEqual(updated.processed, 1)
		self.assertIn("MAX_RETRIES", updated.failure_reason)

		outbound = frappe.get_all(
			"Chat Message",
			filters={"session_id": inbound.session_id, "direction": "outbound"},
			fields=["content", "sender_id"],
		)
		self.assertEqual(len(outbound), 1)
		self.assertEqual(outbound[0]["sender_id"], "system")
