# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt

"""
Bench integration tests for the runner's ReAct loop (Feature A, doc 48 §1)
against the real dispatcher / permission engine / Note DocType.

They verify the runner correctly:
  1. Returns plain text directly when there are no tool calls.
  2. Dispatches tool calls through the real dispatcher (creating a Note),
     feeds results back, and returns the model's final plain-text reply.
  3. Dispatches multiple tool calls sequentially, in order.
  4. Breaks the loop and surfaces the denial on a permission-denied call.
  5. Feeds a tool error back to the model and continues the loop.

The LLM provider is mocked with scripted responses (a tool-call turn, then a
plain-text turn so the loop ends); everything below it is real, so these run
on a bench. The pure-logic loop tests live in test_react_loop.py.
"""

import unittest
from unittest.mock import patch, MagicMock

import frappe
from frappe.friday_core.agent_runner.runner import run_turn
from frappe.friday_core.agent_runner.dispatcher import DispatchResult

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TEST_ROLE = "Friday Slice6 Runner Test Role"
SKILL_NAME = "slice6-create-note"
PROFILE_NAME = "FRIDAY-SLICE6-RUNNER-TEST-PROFILE"
LLM_PROVIDER_NAME = "friday-slice6-runner-test-provider"
TARGET_DOCTYPE = "Note"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _ensure_role():
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
                "create": 1,
                "permlevel": 0,
            }
        ).insert(ignore_permissions=True)


def _ensure_skill():
    if frappe.db.exists("Skill", SKILL_NAME):
        skill = frappe.get_doc("Skill", SKILL_NAME)
        skill.status = "Active"
        skill.risk_level = "low"
        skill.required_doctypes = []
        skill.append("required_doctypes", {"target_doctype": TARGET_DOCTYPE, "operation": "create"})
        skill.save(ignore_permissions=True)
        return
    frappe.get_doc(
        {
            "doctype": "Skill",
            "skill_name": SKILL_NAME,
            "description": "Slice 6 runner test skill",
            "risk_level": "low",
            "status": "Active",
            "required_doctypes": [{"target_doctype": TARGET_DOCTYPE, "operation": "create"}],
        }
    ).insert(ignore_permissions=True)


def _ensure_profile():
    if frappe.db.exists("Agent Profile", PROFILE_NAME):
        profile = frappe.get_doc("Agent Profile", PROFILE_NAME)
        profile.status = "Active"
        profile.assigned_roles = []
        profile.permitted_skills = []
        profile.append("assigned_roles", {"role": TEST_ROLE})
        profile.append("permitted_skills", {"skill": SKILL_NAME})
        profile.save(ignore_permissions=True)
        return
    frappe.get_doc(
        {
            "doctype": "Agent Profile",
            "profile_name": PROFILE_NAME,
            "status": "Active",
            "requires_approval_above_risk": "high",
            "assigned_roles": [{"role": TEST_ROLE}],
            "permitted_skills": [{"skill": SKILL_NAME}],
        }
    ).insert(ignore_permissions=True)


def _ensure_llm_provider():
    if frappe.db.exists("LLM Provider", LLM_PROVIDER_NAME):
        return
    frappe.get_doc(
        {
            "doctype": "LLM Provider",
            "provider_name": LLM_PROVIDER_NAME,
            "provider_type": "minimax",
            "is_active": 1,
            "api_key": "test-runner-key",
        }
    ).insert(ignore_permissions=True, ignore_mandatory=True)


def _link_provider_to_profile():
    profile = frappe.get_doc("Agent Profile", PROFILE_NAME)
    profile.llm_provider = LLM_PROVIDER_NAME
    profile.save(ignore_permissions=True)


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

class TestRunnerToolCallDetection(unittest.TestCase):
    """runner.py correctly detects tool_calls and dispatches to dispatcher."""

    @classmethod
    def setUpClass(cls):
        frappe.db.rollback()
        _ensure_role()
        _ensure_llm_provider()
        _ensure_skill()
        _ensure_profile()
        _link_provider_to_profile()
        frappe.db.commit()

    def setUp(self):
        frappe.db.sql("DELETE FROM `tabExecution Log` WHERE agent_profile=%s", (PROFILE_NAME,))
        frappe.db.sql("DELETE FROM `tabNote` WHERE title LIKE 'slice6-runner-%'")
        # Don't invalidate the loader cache here — we want the profile's
        # cached matrix to persist so the permission check finds our role.
        # frappe.db.commit()

    @classmethod
    def tearDownClass(cls):
        from frappe.friday_core.skills.loader import invalidate_for_profile
        invalidate_for_profile(PROFILE_NAME)
        frappe.db.sql("DELETE FROM `tabExecution Log` WHERE agent_profile=%s", (PROFILE_NAME,))
        frappe.db.sql("DELETE FROM `tabNote` WHERE title LIKE 'slice6-runner-%'")
        frappe.db.commit()

    def test_no_tool_calls_returns_content_directly(self):
        """When LLM response has no tool_calls, runner returns content as-is."""
        fake_response = {
            "content": "Hello! How can I help you today?",
            "finish_reason": "stop",
            "usage": {"prompt_tokens": 10, "completion_tokens": 8, "total_tokens": 18},
            "tool_calls": None,
        }

        mock_provider = MagicMock()
        mock_provider.chat.return_value = fake_response

        with patch(
            "frappe.friday_core.agent_runner.runner.get_provider_for_profile",
            return_value=mock_provider,
        ):
            result = run_turn(
                profile_name=PROFILE_NAME,
                session_id="sess-runner-001",
                inbound_content="Hello there",
            )

        self.assertEqual(result, "Hello! How can I help you today?")

    def test_tool_call_triggers_dispatch_and_returns_result(self):
        """When LLM returns tool_calls, runner dispatches first one and returns result."""
        fake_response = {
            "content": "",
            "finish_reason": "tool_calls",
            "usage": {"prompt_tokens": 50, "completion_tokens": 20, "total_tokens": 70},
            "tool_calls": [
                {
                    "id": "call_abc123",
                    "name": SKILL_NAME,
                    "arguments": '{"title": "slice6-runner-note", "content": "Dispatched via runner"}',
                }
            ],
        }

        mock_provider = MagicMock()
        # ReAct loop: a tool-call turn, then a plain-text turn so the loop ends.
        mock_provider.chat.side_effect = [
            fake_response,
            {"content": "I created the note.", "finish_reason": "stop", "usage": {}, "tool_calls": None},
        ]

        with patch(
            "frappe.friday_core.agent_runner.runner.get_provider_for_profile",
            return_value=mock_provider,
        ):
            result = run_turn(
                profile_name=PROFILE_NAME,
                session_id="sess-runner-002",
                inbound_content="Create a note about the meeting",
            )

        # The loop dispatches the tool, feeds the result back, then returns the
        # model's final plain-text reply.
        self.assertEqual(result, "I created the note.")
        # Verify the Note was actually created in DB by the dispatched tool.
        exists = frappe.db.exists("Note", {"title": "slice6-runner-note"})
        self.assertTrue(exists, "Note should have been created by the create_note handler")

    def test_dispatch_success_returns_note_title(self):
        """When dispatch succeeds, runner returns the result content."""
        tool_call = {
            "id": "call_xyz",
            "name": SKILL_NAME,
            "arguments": '{"title": "slice6-runner-my-note", "content": "Test"}',
        }

        fake_response = {
            "content": "",
            "finish_reason": "tool_calls",
            "usage": {"total_tokens": 50},
            "tool_calls": [tool_call],
        }

        mock_provider = MagicMock()
        mock_provider.chat.side_effect = [
            fake_response,
            {"content": "Created it.", "finish_reason": "stop", "usage": {}, "tool_calls": None},
        ]

        with patch(
            "frappe.friday_core.agent_runner.runner.get_provider_for_profile",
            return_value=mock_provider,
        ):
            result = run_turn(
                profile_name=PROFILE_NAME,
                session_id="sess-runner-003",
                inbound_content="Create a note",
            )

        # The dispatched tool created the note; the loop returns the final reply.
        self.assertEqual(result, "Created it.")
        exists = frappe.db.exists("Note", {"title": "slice6-runner-my-note"})
        self.assertTrue(exists)

    def test_permission_denied_returns_denial_message(self):
        """When permission is denied, runner returns the denial message."""
        fake_response = {
            "content": "",
            "finish_reason": "tool_calls",
            "usage": {"prompt_tokens": 50, "completion_tokens": 10, "total_tokens": 60},
            "tool_calls": [
                {
                    "id": "call_denied_001",
                    "name": SKILL_NAME,
                    "arguments": '{"title": "should-not-be-created"}',
                }
            ],
        }

        mock_provider = MagicMock()
        mock_provider.chat.return_value = fake_response

        # Revoke the role from the profile so permission is denied.
        profile = frappe.get_doc("Agent Profile", PROFILE_NAME)
        profile.assigned_roles = []
        profile.save(ignore_permissions=True)
        from frappe.friday_core.skills.loader import invalidate_for_profile
        invalidate_for_profile(PROFILE_NAME)

        try:
            with patch(
                "frappe.friday_core.agent_runner.runner.get_provider_for_profile",
                return_value=mock_provider,
            ):
                result = run_turn(
                    profile_name=PROFILE_NAME,
                    session_id="sess-runner-004",
                    inbound_content="Create a note",
                )

            self.assertIn("permission", result.lower())
            # Note should NOT have been created.
            exists = frappe.db.exists("Note", {"title": "should-not-be-created"})
            self.assertFalse(exists)
        finally:
            # Restore the role so subsequent tests still have permissions.
            profile.reload()
            profile.append("assigned_roles", {"role": TEST_ROLE})
            profile.save(ignore_permissions=True)
            invalidate_for_profile(PROFILE_NAME)

    def test_multiple_tool_calls_dispatched_sequentially(self):
        """Feature A: all tool calls in a response are dispatched, in order."""
        call_log = []

        fake_response = {
            "content": "",
            "finish_reason": "tool_calls",
            "usage": {"prompt_tokens": 50, "completion_tokens": 20, "total_tokens": 70},
            "tool_calls": [
                {
                    "id": "call_first",
                    "name": SKILL_NAME,
                    "arguments": '{"title": "slice6-runner-first-note"}',
                },
                {
                    "id": "call_second",
                    "name": SKILL_NAME,
                    "arguments": '{"title": "slice6-runner-second-note"}',
                },
            ],
        }
        plain_response = {"content": "Both done.", "finish_reason": "stop", "usage": {}, "tool_calls": None}

        mock_provider = MagicMock()
        mock_provider.chat.side_effect = [fake_response, plain_response]

        def track_dispatch(**kwargs):
            call_log.append(kwargs)
            return DispatchResult(
                success=True,
                content="OK",
                execution_log_name="log-multi",
                tool_call_name=kwargs["tool_call"]["name"],
                tool_call_id=kwargs["tool_call"]["id"],
            )

        with patch(
            "frappe.friday_core.agent_runner.runner.get_provider_for_profile",
            return_value=mock_provider,
        ):
            with patch(
                "frappe.friday_core.agent_runner.runner.dispatch",
                side_effect=track_dispatch,
            ):
                result = run_turn(
                    profile_name=PROFILE_NAME,
                    session_id="sess-runner-005",
                    inbound_content="Create two notes",
                )

        # Both tool calls dispatched, in order.
        self.assertEqual(len(call_log), 2)
        self.assertEqual([c["tool_call"]["id"] for c in call_log], ["call_first", "call_second"])
        self.assertEqual(result, "Both done.")

    def test_dispatch_error_is_fed_back_and_loop_continues(self):
        """Feature A (A.3): a tool error is fed back to the model; the loop continues."""
        fake_response = {
            "content": "",
            "finish_reason": "tool_calls",
            "usage": {"prompt_tokens": 50, "completion_tokens": 15, "total_tokens": 65},
            "tool_calls": [
                {
                    "id": "call_err",
                    "name": "nonexistent-skill-xyz",
                    "arguments": "{}",
                }
            ],
        }
        plain_response = {"content": "Sorry, I couldn't do that.", "finish_reason": "stop", "usage": {}, "tool_calls": None}

        mock_provider = MagicMock()
        mock_provider.chat.side_effect = [fake_response, plain_response]

        with patch(
            "frappe.friday_core.agent_runner.runner.get_provider_for_profile",
            return_value=mock_provider,
        ):
            result = run_turn(
                profile_name=PROFILE_NAME,
                session_id="sess-runner-006",
                inbound_content="Do something impossible",
            )

        # The loop re-prompted after feeding the error back; returns the final reply.
        self.assertEqual(result, "Sorry, I couldn't do that.")
        self.assertEqual(mock_provider.chat.call_count, 2)
        # The error text was fed back to the model as a tool message.
        second_call_messages = mock_provider.chat.call_args_list[1].kwargs["messages"]
        tool_msgs = [m for m in second_call_messages if m.get("role") == "tool"]
        self.assertTrue(any("doesn't exist" in m["content"] for m in tool_msgs))


if __name__ == "__main__":
    unittest.main()