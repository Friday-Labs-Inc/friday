# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt

"""
Tests for the prompt builder — the pure function that assembles the LLM prompt.

SCOPE
=====
These tests verify that `build()` (from `frappe.friday_core.llm.prompt_builder`)
produces correct output given controlled inputs:

  1. System prompt is correctly assembled with the framing + operator text.
  2. History loading: correct role alternation, oldest-first ordering.
  3. History truncation when turns exceed max_history_turns.
  4. Tools None when agent has no permitted skills.
  5. Tools list when skills are passed in.
  6. Model field: profile override vs. None.
  7. max_history_turns=0 returns empty history (no rows fetched).

HOW TO RUN
==========
    bench --site friday.localhost run-tests \
        --module frappe.friday_core.tests.test_prompt_builder

SEE ALSO
========
- `frappe/friday_core/llm/prompt_builder.py` — the module under test.
- `docs/contributing/proposals/slice-5-llm-integration.md` §4.
"""

from __future__ import annotations

import unittest
import uuid

import frappe
from frappe.friday_core.llm.prompt_builder import _build_system_prompt, _load_history, build
from frappe.friday_core.skills.loader import SkillDefinition

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TARGET_DOCTYPE = "Note"
TEST_ROLE = "Friday PB Test Reader"
SKILL_NAME = "slice5-test-skill"
PROFILE_WITH_TOOLS = "FRIDAY-SLICE5-PROFILE-TOOLS"
PROFILE_NO_TOOLS = "FRIDAY-SLICE5-PROFILE-NO-TOOLS"
PLATFORM_NAME = "slice5-test-platform"


def _ensure_role():
	"""Role with read on Note (low-risk setup for tool tests)."""
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
	"""Active skill with read on Note."""
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
			"description": "Slice 5 test skill",
			"risk_level": "low",
			"status": "Active",
			"required_doctypes": [{"target_doctype": TARGET_DOCTYPE, "operation": "read"}],
		}
	).insert(ignore_permissions=True)


def _ensure_profile(name: str, with_skill: bool):
	"""Profile with the test role and optionally the test skill."""
	skills = [SKILL_NAME] if with_skill else []
	if frappe.db.exists("Agent Profile", name):
		profile = frappe.get_doc("Agent Profile", name)
		profile.status = "Active"
		profile.system_prompt = "You are a test assistant."
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
			"system_prompt": "You are a test assistant.",
			"assigned_roles": [{"role": TEST_ROLE}],
			"permitted_skills": [{"skill": s} for s in skills],
		}
	).insert(ignore_permissions=True)


def _ensure_platform():
	"""A test platform for Chat Message rows."""
	if frappe.db.exists("Chat Platform", PLATFORM_NAME):
		return
	frappe.get_doc(
		{
			"doctype": "Chat Platform",
			"platform_name": PLATFORM_NAME,
			"adapter_module": "test.adapter",
			"enabled": 1,
			"dispatch_mode": "sync",
		}
	).insert(ignore_permissions=True)


def _write_chat_message(session_id: str, direction: str, content: str, sender_id: str = "user"):
	"""Helper to write a Chat Message row directly."""
	frappe.get_doc(
		{
			"doctype": "Chat Message",
			"session_id": session_id,
			"platform": PLATFORM_NAME,
			"direction": direction,
			"sender_id": sender_id,
			"agent_profile": PROFILE_WITH_TOOLS,
			"content": content,
			"timestamp": frappe.utils.now_datetime(),
			"processed": 1,
		}
	).insert(ignore_permissions=True)
	frappe.db.commit()


def _make_tool_definition(skill_name: str) -> SkillDefinition:
	"""Build a minimal SkillDefinition for testing."""
	return SkillDefinition(
		name=skill_name,
		description="Test skill",
		when_to_use="Use for testing",
		parameters_schema={},
		risk_level="low",
		requires_approval=False,
	)


# ---------------------------------------------------------------------------
# _build_system_prompt tests
# ---------------------------------------------------------------------------


class TestBuildSystemPrompt(unittest.TestCase):
	"""Unit tests for the internal _build_system_prompt helper."""

	@classmethod
	def setUpClass(cls):
		_ensure_role()
		_ensure_skill()
		_ensure_profile(PROFILE_WITH_TOOLS, with_skill=True)
		frappe.db.commit()

	def test_contains_friday_frame(self):
		"""Output starts with the Friday framing."""
		profile = frappe.get_doc("Agent Profile", PROFILE_WITH_TOOLS)
		result = _build_system_prompt(profile)
		self.assertTrue(result.startswith("You are a Friday AI Agent."))

	def test_operator_text_appended_after_frame(self):
		"""Operator's system_prompt appears verbatim after the frame."""
		profile = frappe.get_doc("Agent Profile", PROFILE_WITH_TOOLS)
		profile.system_prompt = "Always cite your sources."
		profile.save(ignore_permissions=True)
		frappe.db.commit()

		result = _build_system_prompt(profile)
		self.assertIn("Always cite your sources.", result)

	def test_empty_operator_prompt_still_has_frame(self):
		"""system_prompt is empty string → output has only the frame."""
		profile = frappe.get_doc("Agent Profile", PROFILE_WITH_TOOLS)
		profile.system_prompt = ""
		profile.save(ignore_permissions=True)
		frappe.db.commit()

		result = _build_system_prompt(profile)
		self.assertTrue(result.startswith("You are a Friday AI Agent."))

	def test_includes_date_line_and_tool_discipline(self):
		"""Design 80 — the frame carries today's date + the tool-use discipline."""
		profile = frappe.get_doc("Agent Profile", PROFILE_WITH_TOOLS)
		result = _build_system_prompt(profile)
		self.assertIn("Today's date is", result)
		self.assertIn(frappe.utils.today(), result)
		self.assertIn("Call each tool at most once", result)


# ---------------------------------------------------------------------------
# _load_history tests
# ---------------------------------------------------------------------------


class TestLoadHistory(unittest.TestCase):
	"""Unit tests for the internal _load_history helper."""

	@classmethod
	def setUpClass(cls):
		_ensure_role()
		_ensure_skill()
		_ensure_profile(PROFILE_WITH_TOOLS, with_skill=True)
		_ensure_platform()
		frappe.cache().delete_keys("friday:skills:")
		frappe.cache().delete_keys("friday:perm_matrix:")
		frappe.db.commit()

	def setUp(self):
		# Always start with fresh state
		frappe.cache().delete_keys("friday:skills:")
		frappe.cache().delete_keys("friday:perm_matrix:")

	def test_max_history_turns_zero_returns_empty_list(self):
		"""max_history_turns=0 means no history rows fetched."""
		session_id = str(uuid.uuid4())
		result = _load_history(session_id, max_history_turns=0)
		self.assertEqual(result, [])

	def test_no_history_returns_empty_list(self):
		"""Session with no prior messages returns []."""
		result = _load_history(str(uuid.uuid4()), max_history_turns=10)
		self.assertEqual(result, [])

	def test_single_inbound_becomes_user_role(self):
		"""A single inbound row maps to role=user."""
		session_id = str(uuid.uuid4())
		_write_chat_message(session_id, "inbound", "hello", sender_id="user")

		result = _load_history(session_id, max_history_turns=10)
		self.assertEqual(len(result), 1)
		self.assertEqual(result[0]["role"], "user")
		self.assertEqual(result[0]["content"], "hello")

	def test_single_outbound_becomes_assistant_role(self):
		"""A single outbound row maps to role=assistant."""
		session_id = str(uuid.uuid4())
		_write_chat_message(session_id, "outbound", "how can I help", sender_id=PROFILE_WITH_TOOLS)

		result = _load_history(session_id, max_history_turns=10)
		self.assertEqual(len(result), 1)
		self.assertEqual(result[0]["role"], "assistant")
		self.assertEqual(result[0]["content"], "how can I help")

	def test_alternating_inbound_outbound_in_order(self):
		"""History returns messages in chronological order (creation asc)."""
		session_id = str(uuid.uuid4())
		_write_chat_message(session_id, "inbound", "first", sender_id="user")
		_write_chat_message(session_id, "outbound", "second", sender_id=PROFILE_WITH_TOOLS)
		_write_chat_message(session_id, "inbound", "third", sender_id="user")

		result = _load_history(session_id, max_history_turns=10)
		self.assertEqual(len(result), 3)
		self.assertEqual(result[0]["content"], "first")
		self.assertEqual(result[1]["content"], "second")
		self.assertEqual(result[2]["content"], "third")
		self.assertEqual(result[0]["role"], "user")
		self.assertEqual(result[1]["role"], "assistant")
		self.assertEqual(result[2]["role"], "user")

	def test_truncation_respects_max_history_turns(self):
		"""More than max_history_turns are available → oldest are dropped.

		With 15 inbound/outbound pairs (30 rows) and max_history_turns=4,
		the query uses ORDER BY creation ASC with limit=8, so it returns
		the FIRST 8 rows (oldest 4 pairs): turn-0 through reply-3.
		"""
		session_id = str(uuid.uuid4())
		for i in range(15):
			_write_chat_message(session_id, "inbound", f"turn-{i}", sender_id="user")
			_write_chat_message(session_id, "outbound", f"reply-{i}", sender_id=PROFILE_WITH_TOOLS)

		# max_history_turns=4 → limit=8 (ASC) → first 8 rows = oldest 4 pairs
		result = _load_history(session_id, max_history_turns=4)
		self.assertEqual(len(result), 8)
		self.assertEqual(result[0]["content"], "turn-0")
		self.assertEqual(result[-1]["content"], "reply-3")

	def test_empty_content_is_skipped(self):
		"""Chat Message row with empty content does not appear in history."""
		session_id = str(uuid.uuid4())
		_write_chat_message(session_id, "inbound", "hello", sender_id="user")
		_write_chat_message(session_id, "outbound", "", sender_id=PROFILE_WITH_TOOLS)  # empty
		_write_chat_message(session_id, "inbound", "world", sender_id="user")

		result = _load_history(session_id, max_history_turns=10)
		# Empty outbound should be skipped, but other 2 included
		self.assertEqual(len(result), 2)


# ---------------------------------------------------------------------------
# build() integration tests
# ---------------------------------------------------------------------------


class TestPromptBuilderBuild(unittest.TestCase):
	"""Full integration tests for the public `build()` function."""

	@classmethod
	def setUpClass(cls):
		_ensure_role()
		_ensure_skill()
		_ensure_profile(PROFILE_WITH_TOOLS, with_skill=True)
		_ensure_profile(PROFILE_NO_TOOLS, with_skill=False)
		_ensure_platform()
		frappe.cache().delete_keys("friday:skills:")
		frappe.cache().delete_keys("friday:perm_matrix:")
		frappe.db.commit()

	def setUp(self):
		frappe.cache().delete_keys("friday:skills:")
		frappe.cache().delete_keys("friday:perm_matrix:")

	def test_build_returns_dict_with_messages_tools_model(self):
		"""Return value has exactly the three expected keys."""
		session_id = str(uuid.uuid4())
		result = build(PROFILE_WITH_TOOLS, session_id, "hello", tools=None)

		self.assertIn("messages", result)
		self.assertIn("tools", result)
		self.assertIn("model", result)

	def test_system_prompt_is_first_message(self):
		"""The first message in the list has role=system and contains the frame."""
		session_id = str(uuid.uuid4())
		result = build(PROFILE_WITH_TOOLS, session_id, "hello", tools=None)

		self.assertEqual(result["messages"][0]["role"], "system")
		self.assertIn("Friday AI Agent", result["messages"][0]["content"])

	def test_current_message_is_last(self):
		"""The last message in the list is the inbound_content with role=user."""
		session_id = str(uuid.uuid4())
		result = build(PROFILE_WITH_TOOLS, session_id, "my question here", tools=None)

		self.assertEqual(result["messages"][-1]["role"], "user")
		self.assertEqual(result["messages"][-1]["content"], "my question here")

	def test_tools_none_when_no_skills_passed(self):
		"""build(tools=None) → tools key is None."""
		session_id = str(uuid.uuid4())
		result = build(PROFILE_WITH_TOOLS, session_id, "hello", tools=None)

		self.assertIsNone(result["tools"])

	def test_tools_list_when_skills_passed(self):
		"""build(tools=[...]) → tools key is a list of tool defs."""
		session_id = str(uuid.uuid4())
		skill_defs = [_make_tool_definition("test-skill-1"), _make_tool_definition("test-skill-2")]
		result = build(PROFILE_WITH_TOOLS, session_id, "hello", tools=skill_defs)

		self.assertIsNotNone(result["tools"])
		self.assertEqual(len(result["tools"]), 2)
		self.assertEqual(result["tools"][0]["type"], "function")

	def test_history_appended_between_system_and_current(self):
		"""Prior Chat Message rows appear between the system prompt and the user's message."""
		session_id = str(uuid.uuid4())
		_write_chat_message(session_id, "inbound", "prior user message", sender_id="user")
		_write_chat_message(session_id, "outbound", "prior agent reply", sender_id=PROFILE_WITH_TOOLS)

		result = build(PROFILE_WITH_TOOLS, session_id, "new message", tools=None)

		# messages[0] = system, messages[1] = prior user, messages[2] = prior agent,
		# messages[3] = current user
		self.assertEqual(result["messages"][0]["role"], "system")
		self.assertEqual(result["messages"][1]["content"], "prior user message")
		self.assertEqual(result["messages"][1]["role"], "user")
		self.assertEqual(result["messages"][2]["content"], "prior agent reply")
		self.assertEqual(result["messages"][2]["role"], "assistant")
		self.assertEqual(result["messages"][-1]["content"], "new message")

	def test_max_history_turns_zero_omits_history(self):
		"""max_history_turns=0 → no prior messages loaded."""
		session_id = str(uuid.uuid4())
		_write_chat_message(session_id, "inbound", "old message", sender_id="user")
		_write_chat_message(session_id, "outbound", "old reply", sender_id=PROFILE_WITH_TOOLS)

		result = build(
			PROFILE_WITH_TOOLS,
			session_id,
			"new message",
			tools=None,
			max_history_turns=0,
		)

		# Should only have system + current message (2 messages total)
		self.assertEqual(len(result["messages"]), 2)
		self.assertEqual(result["messages"][0]["role"], "system")
		self.assertEqual(result["messages"][-1]["role"], "user")
		self.assertEqual(result["messages"][-1]["content"], "new message")

	def test_model_from_profile_model_name(self):
		"""When Agent Profile has model_name set, model field reflects it."""
		profile = frappe.get_doc("Agent Profile", PROFILE_WITH_TOOLS)
		profile.model_name = "MiniMax-Pro-1"
		profile.save(ignore_permissions=True)
		frappe.db.commit()

		session_id = str(uuid.uuid4())
		result = build(PROFILE_WITH_TOOLS, session_id, "hello", tools=None)

		self.assertEqual(result["model"], "MiniMax-Pro-1")

	def test_model_none_when_profile_has_no_model_name(self):
		"""When Agent Profile.model_name is empty, model field is None."""
		profile = frappe.get_doc("Agent Profile", PROFILE_WITH_TOOLS)
		profile.model_name = None
		profile.save(ignore_permissions=True)
		frappe.db.commit()

		session_id = str(uuid.uuid4())
		result = build(PROFILE_WITH_TOOLS, session_id, "hello", tools=None)

		self.assertIsNone(result["model"])

	def test_nonexistent_profile_raises_does_not_exist(self):
		"""Non-existent profile name raises frappe.DoesNotExistError."""
		with self.assertRaises(frappe.DoesNotExistError):
			build("definitely-does-not-exist-12345", str(uuid.uuid4()), "hello", tools=None)
