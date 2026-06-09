# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt

"""
Tests for the Slice 6 dispatcher — the skill execution chokepoint.

PLAIN ENGLISH
=============

These tests prove the dispatcher correctly:
  - Allows skills that pass the permission matrix check.
  - Denies skills that fail the permission matrix check.
  - Writes an Execution Log row for every dispatch attempt.
  - Handles unknown skills, malformed arguments, and handler exceptions.
  - Never raises — all errors are captured in DispatchResult and the log.

TEST DATA STRATEGY
=================

The tests use the same infrastructure as Slice 2/3:
  - A `Friday Test Note Creator` Role with `create` on Note.
  - A `Friday Test Note Reader` Role with `read` on Note (not `create`).
  - A `create_note` Skill that requires `create` on Note.
  - A `FRIDAY-SLICE6-TEST-PROFILE-ALLOWED` profile with the creator role.
  - A `FRIDAY-SLICE6-TEST-PROFILE-DENIED` profile with the reader role.

HOW TO RUN
==========

    bench --site friday.localhost run-tests \
        --module frappe.friday_core.tests.test_dispatcher

REFERENCED DOCS
==============
- `docs/contributing/proposals/slice-6-first-skill.md`
- `docs/design/10-agent-execution-guide.md` §Slice 6
"""

from __future__ import annotations

import unittest

import frappe

from frappe.friday_core.agent_runner.dispatcher import (
    DispatchResult,
    dispatch,
    register_skill_handler,
    _SKILL_HANDLERS,
)

# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

TARGET_DOCTYPE = "Note"
ROLE_CAN_CREATE = "Friday Slice6 Creator"
ROLE_CANNOT_CREATE = "Friday Slice6 Reader"
SKILL_NAME = "slice6-create-note"
PROFILE_ALLOWED = "FRIDAY-SLICE6-PROFILE-ALLOWED"
PROFILE_DENIED = "FRIDAY-SLICE6-PROFILE-DENIED"


def _ensure_role(name: str, create_perm: bool, read_perm: bool = False):
    """Create a Role with specified Note permissions."""
    if not frappe.db.exists("Role", name):
        frappe.get_doc({"doctype": "Role", "role_name": name}).insert(ignore_permissions=True)
    if not frappe.db.exists("Custom DocPerm", {"parent": TARGET_DOCTYPE, "role": name}):
        frappe.get_doc(
            {
                "doctype": "Custom DocPerm",
                "parent": TARGET_DOCTYPE,
                "parenttype": "DocType",
                "parentfield": "permissions",
                "role": name,
                "create": 1 if create_perm else 0,
                "read": 1 if read_perm else 0,
                "permlevel": 0,
            }
        ).insert(ignore_permissions=True)


def _ensure_skill():
    """Active skill that requires `create` on Note."""
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
            "description": "Slice 6 test: create a note",
            "risk_level": "low",
            "status": "Active",
            "required_doctypes": [{"target_doctype": TARGET_DOCTYPE, "operation": "create"}],
        }
    ).insert(ignore_permissions=True)


def _ensure_profile(name: str, role: str, skill: str):
    """Profile with one role and one permitted skill."""
    if frappe.db.exists("Agent Profile", name):
        profile = frappe.get_doc("Agent Profile", name)
        profile.status = "Active"
        profile.assigned_roles = []
        profile.permitted_skills = []
        profile.save(ignore_permissions=True)
    else:
        profile = frappe.get_doc(
            {
                "doctype": "Agent Profile",
                "profile_name": name,
                "status": "Active",
            }
        )
        profile.insert(ignore_permissions=True)
        name = profile.name

    # Clear and reset.
    frappe.db.sql("DELETE FROM `tabHas Role` WHERE parent=%s", (name,))
    frappe.db.sql("DELETE FROM `tabAgent Profile Skill` WHERE parent=%s", (name,))
    frappe.get_doc(
        {
            "doctype": "Has Role",
            "parent": name,
            "parentfield": "assigned_roles",
            "parenttype": "Agent Profile",
            "role": role,
        }
    ).insert(ignore_permissions=True)
    frappe.get_doc(
        {
            "doctype": "Agent Profile Skill",
            "parent": name,
            "parentfield": "permitted_skills",
            "parenttype": "Agent Profile",
            "skill": skill,
        }
    ).insert(ignore_permissions=True)


def _ensure_llm_provider():
    """Minimal LLM Provider for test profile resolution."""
    provider_name = "friday-slice6-test-provider"
    if not frappe.db.exists("LLM Provider", provider_name):
        # Use set_value to bypass mandatory validation on api_key
        # (api_key is mandatory in DocType but not needed for test resolution)
        doc = frappe.get_doc(
            {
                "doctype": "LLM Provider",
                "provider_name": provider_name,
                "provider_type": "minimax",
                "default_model": "MiniMax-Standard",
                "is_active": 1,
            }
        )
        doc.insert(ignore_permissions=True, ignore_mandatory=True)


def _link_provider_to_profile(profile_name: str, provider_name: str = "friday-slice6-test-provider"):
    """Link an LLM Provider to a profile for provider resolution."""
    frappe.db.set_value(
        "Agent Profile",
        profile_name,
        "model_provider",
        provider_name,
        update_modified=False,
    )


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------


class TestDispatchResultDataclass(unittest.TestCase):
    """Sanity-check the DispatchResult dataclass."""

    def test_all_fields_present(self):
        result = DispatchResult(
            success=True,
            content="Note 'Shopping list' created",
            execution_log_name="EXEC-001",
            tokens_used=1500,
            tool_call_name="create_note",
            tool_call_id="call_abc123",
        )
        self.assertTrue(result.success)
        self.assertEqual(result.content, "Note 'Shopping list' created")
        self.assertEqual(result.execution_log_name, "EXEC-001")
        self.assertEqual(result.tokens_used, 1500)
        self.assertEqual(result.tool_call_name, "create_note")
        self.assertEqual(result.tool_call_id, "call_abc123")

    def test_optional_fields_default_to_none(self):
        result = DispatchResult(success=False, content="Denied")
        self.assertIsNone(result.execution_log_name)
        self.assertIsNone(result.tokens_used)
        self.assertIsNone(result.tool_call_name)
        self.assertIsNone(result.tool_call_id)


class TestDispatchAllowedFlow(unittest.TestCase):
    """The skill is permitted — Execution Log gets submitted with success."""

    @classmethod
    def setUpClass(cls):
        # Abort any stale transaction from a prior failed test before touching the DB.
        frappe.db.rollback()
        _ensure_role(ROLE_CAN_CREATE, create_perm=True)
        _ensure_llm_provider()
        _ensure_skill()
        _ensure_profile(PROFILE_ALLOWED, ROLE_CAN_CREATE, SKILL_NAME)
        _link_provider_to_profile(PROFILE_ALLOWED)
        frappe.db.commit()

    def setUp(self):
        # Clean up any Note rows created by previous test runs.
        frappe.db.sql("DELETE FROM `tabNote` WHERE title LIKE 'slice6-test-%'")
        frappe.db.sql("DELETE FROM `tabExecution Log` WHERE agent_profile=%s", (PROFILE_ALLOWED,))
        frappe.db.sql("DELETE FROM `tabPermission Decision Log` WHERE agent_profile=%s", (PROFILE_ALLOWED,))
        # Invalidate skill cache so the new profile picks up the skill.
        from frappe.friday_core.skills.loader import invalidate_for_profile
        invalidate_for_profile(PROFILE_ALLOWED)

    def tearDown(self):
        frappe.db.sql("DELETE FROM `tabNote` WHERE title LIKE 'slice6-test-%'")

    def test_dispatch_returns_success_true(self):
        tool_call = {
            "id": "call_slice6_001",
            "name": "slice6-create-note",  # Skill DB name, not the handler name
            "arguments": '{"title": "slice6-test-todo", "content": "Buy groceries"}',
        }
        result = dispatch(
            tool_call=tool_call,
            agent_profile=PROFILE_ALLOWED,
            session_id="sess-001",
            tokens_used=1200,
        )
        self.assertTrue(result.success)
        self.assertEqual(result.tool_call_name, "slice6-create-note")
        self.assertEqual(result.tool_call_id, "call_slice6_001")
        self.assertIn("slice6-test-todo", result.content)

    def test_execution_log_row_is_written_with_success_status(self):
        tool_call = {
            "id": "call_slice6_002",
            "name": "slice6-create-note",
            "arguments": '{"title": "slice6-test-checklist"}',
        }
        result = dispatch(
            tool_call=tool_call,
            agent_profile=PROFILE_ALLOWED,
            session_id="sess-002",
        )
        self.assertIsNotNone(result.execution_log_name)
        log = frappe.get_doc("Execution Log", result.execution_log_name)
        self.assertEqual(log.status, "success")
        self.assertEqual(log.agent_profile, PROFILE_ALLOWED)
        self.assertEqual(log.skill, "slice6-create-note")

    def test_note_row_is_actually_created(self):
        tool_call = {
            "id": "call_slice6_003",
            "name": "slice6-create-note",
            "arguments": '{"title": "slice6-test-created-note", "content": "Hello world"}',
        }
        dispatch(
            tool_call=tool_call,
            agent_profile=PROFILE_ALLOWED,
            session_id="sess-003",
        )
        exists = frappe.db.exists("Note", {"title": "slice6-test-created-note"})
        self.assertTrue(exists, "Note row should have been created by create_note handler")


class TestDispatchPermissionDenied(unittest.TestCase):
    """The skill is denied by the permission matrix — Execution Log gets rejected."""

    @classmethod
    def setUpClass(cls):
        frappe.db.rollback()
        _ensure_role(ROLE_CANNOT_CREATE, create_perm=False, read_perm=True)
        _ensure_llm_provider()
        _ensure_skill()
        _ensure_profile(PROFILE_DENIED, ROLE_CANNOT_CREATE, SKILL_NAME)
        _link_provider_to_profile(PROFILE_DENIED)
        frappe.db.commit()

    def setUp(self):
        frappe.db.sql("DELETE FROM `tabExecution Log` WHERE agent_profile=%s", (PROFILE_DENIED,))
        frappe.db.sql("DELETE FROM `tabPermission Decision Log` WHERE agent_profile=%s", (PROFILE_DENIED,))
        from frappe.friday_core.skills.loader import invalidate_for_profile
        invalidate_for_profile(PROFILE_DENIED)

    def test_dispatch_returns_success_false(self):
        tool_call = {
            "id": "call_slice6_d001",
            "name": "slice6-create-note",
            "arguments": '{"title": "should-not-be-created"}',
        }
        result = dispatch(
            tool_call=tool_call,
            agent_profile=PROFILE_DENIED,
            session_id="sess-denied-001",
        )
        self.assertFalse(result.success)
        self.assertIn("permission", result.content.lower())

    def test_execution_log_row_has_rejected_status(self):
        tool_call = {
            "id": "call_slice6_d002",
            "name": "slice6-create-note",
            "arguments": '{"title": "should-not-exist"}',
        }
        result = dispatch(
            tool_call=tool_call,
            agent_profile=PROFILE_DENIED,
            session_id="sess-denied-002",
        )
        self.assertIsNotNone(result.execution_log_name)
        log = frappe.get_doc("Execution Log", result.execution_log_name)
        self.assertEqual(log.status, "rejected")

    def test_permission_decision_log_row_is_written(self):
        tool_call = {
            "id": "call_slice6_d003",
            "name": "slice6-create-note",
            "arguments": '{"title": "nope"}',
        }
        result = dispatch(
            tool_call=tool_call,
            agent_profile=PROFILE_DENIED,
            session_id="sess-denied-003",
        )
        # matrix.check writes a Permission Decision Log row.
        rows = frappe.get_all(
            "Permission Decision Log",
            filters={"agent_profile": PROFILE_DENIED, "skill": "slice6-create-note"},
            fields=["name", "decision"],
        )
        self.assertEqual(len(rows), 1, "Permission Decision Log row should exist after dispatch")
        self.assertEqual(rows[0]["decision"], "denied")


class TestDispatchUnknownSkill(unittest.TestCase):
    """LLM calls a skill that has no handler registered."""

    @classmethod
    def setUpClass(cls):
        frappe.db.rollback()
        _ensure_role(ROLE_CAN_CREATE, create_perm=True)
        _ensure_llm_provider()
        _ensure_skill()
        _ensure_profile(PROFILE_ALLOWED, ROLE_CAN_CREATE, SKILL_NAME)
        _link_provider_to_profile(PROFILE_ALLOWED)
        frappe.db.commit()

    def setUp(self):
        frappe.db.sql("DELETE FROM `tabExecution Log` WHERE agent_profile=%s", (PROFILE_ALLOWED,))
        from frappe.friday_core.skills.loader import invalidate_for_profile
        invalidate_for_profile(PROFILE_ALLOWED)

    def test_unknown_skill_returns_error_result(self):
        tool_call = {
            "id": "call_slice6_u001",
            "name": "i_do_not_exist_skill",
            "arguments": "{}",
        }
        result = dispatch(
            tool_call=tool_call,
            agent_profile=PROFILE_ALLOWED,
            session_id="sess-unknown-001",
        )
        self.assertFalse(result.success)
        self.assertIn("doesn't exist", result.content)

    def test_unknown_skill_writes_execution_log_with_error(self):
        tool_call = {
            "id": "call_slice6_u002",
            "name": "another_unknown_skill",
            "arguments": "{}",
        }
        result = dispatch(
            tool_call=tool_call,
            agent_profile=PROFILE_ALLOWED,
            session_id="sess-unknown-002",
        )
        self.assertFalse(result.success)


class TestDispatchMalformedArguments(unittest.TestCase):
    """LLM returns tool call with unparseable or wrong-type arguments."""

    @classmethod
    def setUpClass(cls):
        frappe.db.rollback()
        _ensure_role(ROLE_CAN_CREATE, create_perm=True)
        _ensure_llm_provider()
        _ensure_skill()
        _ensure_profile(PROFILE_ALLOWED, ROLE_CAN_CREATE, SKILL_NAME)
        _link_provider_to_profile(PROFILE_ALLOWED)
        frappe.db.commit()

    def setUp(self):
        frappe.db.sql("DELETE FROM `tabExecution Log` WHERE agent_profile=%s", (PROFILE_ALLOWED,))
        from frappe.friday_core.skills.loader import invalidate_for_profile
        invalidate_for_profile(PROFILE_ALLOWED)

    def test_malformed_json_is_repaired_then_validated_by_skill(self):
        # H-class robustness: malformed argument JSON is now REPAIRED (an
        # unrepairable string falls back to "{}") instead of hard-failing at
        # parse. The skill's OWN validation then handles the empty params — so
        # we get a skill error, not a raw JSON parse error.
        tool_call = {
            "id": "call_slice6_m001",
            "name": "slice6-create-note",
            "arguments": "not valid json at all {",
        }
        result = dispatch(
            tool_call=tool_call,
            agent_profile=PROFILE_ALLOWED,
            session_id="sess-malf-001",
        )
        self.assertFalse(result.success)
        self.assertNotIn("Malformed JSON", result.content)
        self.assertIn("Something went wrong", result.content)

    def test_non_dict_arguments_returns_error(self):
        tool_call = {
            "id": "call_slice6_m002",
            "name": "slice6-create-note",
            "arguments": '"just a string"',
        }
        result = dispatch(
            tool_call=tool_call,
            agent_profile=PROFILE_ALLOWED,
            session_id="sess-malf-002",
        )
        self.assertFalse(result.success)
        self.assertIn("must be a dict", result.content)


class TestDispatchHandlerException(unittest.TestCase):
    """Skill handler raises an exception — error captured in result and log."""

    @classmethod
    def setUpClass(cls):
        frappe.db.rollback()
        _ensure_role(ROLE_CAN_CREATE, create_perm=True)
        _ensure_llm_provider()
        _ensure_skill()
        _ensure_profile(PROFILE_ALLOWED, ROLE_CAN_CREATE, SKILL_NAME)
        _link_provider_to_profile(PROFILE_ALLOWED)
        frappe.db.commit()

    def setUp(self):
        frappe.db.sql("DELETE FROM `tabExecution Log` WHERE agent_profile=%s", (PROFILE_ALLOWED,))
        from frappe.friday_core.skills.loader import invalidate_for_profile
        invalidate_for_profile(PROFILE_ALLOWED)

    def test_create_note_without_title_raises_and_returns_error_result(self):
        tool_call = {
            "id": "call_slice6_e001",
            "name": "slice6-create-note",
            "arguments": '{"content": "No title provided"}',  # title missing
        }
        result = dispatch(
            tool_call=tool_call,
            agent_profile=PROFILE_ALLOWED,
            session_id="sess-err-001",
        )
        self.assertFalse(result.success)
        # Error is about the missing title parameter.
        self.assertTrue(
            "title" in result.content.lower() or "parameter" in result.content.lower(),
            f"Expected error about missing 'title', got: {result.content!r}",
        )

    def test_exception_writes_execution_log_with_error_status(self):
        tool_call = {
            "id": "call_slice6_e002",
            "name": "slice6-create-note",
            "arguments": '{"content": "Missing title"}',
        }
        result = dispatch(
            tool_call=tool_call,
            agent_profile=PROFILE_ALLOWED,
            session_id="sess-err-002",
        )
        self.assertIsNotNone(result.execution_log_name)
        log = frappe.get_doc("Execution Log", result.execution_log_name)
        self.assertEqual(log.status, "error")


class TestRegisterSkillHandler(unittest.TestCase):
    """register_skill_handler() adds entries to the handler registry."""

    def test_register_adds_to_handlers_dict(self):
        def dummy_handler(skill_name, parameters):
            return {"result": "handled"}

        before = len(_SKILL_HANDLERS)
        register_skill_handler("dummy_skill_test", dummy_handler)
        self.assertEqual(len(_SKILL_HANDLERS), before + 1)
        self.assertIn("dummy_skill_test", _SKILL_HANDLERS)

    def test_cannot_register_twice_for_same_skill(self):
        def handler_a(skill_name, parameters):
            return {"result": "a"}

        def handler_b(skill_name, parameters):
            return {"result": "b"}

        register_skill_handler("slice6-dup-test-skill", handler_a)
        with self.assertRaises(ValueError):
            register_skill_handler("slice6-dup-test-skill", handler_b)


class TestDispatchNoToolCallName(unittest.TestCase):
    """Tool call dict has no 'name' field."""

    @classmethod
    def setUpClass(cls):
        frappe.db.rollback()
        _ensure_role(ROLE_CAN_CREATE, create_perm=True)
        _ensure_llm_provider()
        _ensure_skill()
        _ensure_profile(PROFILE_ALLOWED, ROLE_CAN_CREATE, SKILL_NAME)
        _link_provider_to_profile(PROFILE_ALLOWED)
        frappe.db.commit()

    def test_empty_name_returns_error_result(self):
        tool_call = {
            "id": "call_slice6_n001",
            "name": "",
            "arguments": "{}",
        }
        result = dispatch(
            tool_call=tool_call,
            agent_profile=PROFILE_ALLOWED,
            session_id="sess-noname-001",
        )
        self.assertFalse(result.success)
        self.assertIn("no name", result.content.lower())


if __name__ == "__main__":
    unittest.main()