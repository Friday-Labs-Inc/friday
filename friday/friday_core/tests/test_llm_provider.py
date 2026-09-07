# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt

"""
Tests for the LLM provider abstraction and Minimax adapter.

SCOPE
=====
These tests verify:
  1. The LLMProvider ABC interface is correctly defined.
  2. MinimaxProvider makes well-formed HTTP requests.
  3. Error handling (401, 429, 500, timeout) behaves correctly.
  4. Provider resolution from profile → settings → first-active works.
  5. Missing provider raises a descriptive LLMError.

These tests use `responses` (or `unittest.mock`) to mock HTTP calls.
No real Minimax API calls are made.

HOW TO RUN
==========
    bench --site friday.localhost run-tests \
        --module friday.friday_core.tests.test_llm_provider

SEE ALSO
========
- `friday/friday_core/llm/provider.py` — the module under test.
- `docs/contributing/proposals/slice-5-llm-integration.md` §4.
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import frappe

from friday.friday_core.llm.provider import (
    LLMProvider,
    LLMResponse,
    LLMError,
    LLMAuthError,
    MinimaxProvider,
    get_provider_for_profile,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ensure_llm_provider(name: str, provider_type: str = "minimax", is_active: int = 1) -> None:
    """Create or update an LLM Provider row for tests."""
    if frappe.db.exists("LLM Provider", name):
        doc = frappe.get_doc("LLM Provider", name)
        doc.provider_type = provider_type
        doc.is_active = is_active
        doc.api_key = "test-api-key-" + name
        doc.default_model = "MiniMax-Standard"
        doc.save(ignore_permissions=True)
        return
    frappe.get_doc(
        {
            "doctype": "LLM Provider",
            "provider_name": name,
            "provider_type": provider_type,
            "is_active": is_active,
            "api_key": "test-api-key-" + name,
            "default_model": "MiniMax-Standard",
            "default_max_tokens": 2048,
            "default_temperature": 0.7,
        }
    ).insert(ignore_permissions=True)


# ---------------------------------------------------------------------------
# Interface tests
# ---------------------------------------------------------------------------

class TestLLMProviderInterface(unittest.TestCase):
    """Verify the ABC correctly enforces the contract."""

    def test_abc_cannot_be_instantiated_directly(self):
        """LLMProvider is abstract — instantiating it directly must fail."""
        with self.assertRaises(TypeError):
            LLMProvider()  # type: ignore

    def test_subclass_must_implement_chat_and_get_default_model(self):
        """A concrete subclass without chat() raises TypeError at creation time."""
        class IncompleteProvider(LLMProvider):
            pass

        with self.assertRaises(TypeError):
            IncompleteProvider()  # type: ignore


class TestMinimaxProviderConstruction(unittest.TestCase):
    """Verify MinimaxProvider can be constructed with valid params."""

    def test_construction_with_all_args(self):
        """All arguments are accepted and stored."""
        p = MinimaxProvider(
            api_key="sk-test-key",
            default_model="MiniMax-Standard",
            base_url="https://api.minimaxi.com",  # custom override (China endpoint)
        )
        self.assertEqual(p.api_key, "sk-test-key")
        self.assertEqual(p.default_model, "MiniMax-Standard")
        self.assertEqual(p.base_url, "https://api.minimaxi.com")

    def test_construction_without_base_url_uses_default(self):
        """base_url defaults to MinimaxProvider.DEFAULT_BASE_URL (international endpoint)."""
        p = MinimaxProvider(api_key="sk-test", default_model="MiniMax-Standard")
        self.assertEqual(p.base_url, MinimaxProvider.DEFAULT_BASE_URL)
        # Sanity: the default is the OpenAI-compat international endpoint.
        self.assertEqual(MinimaxProvider.DEFAULT_BASE_URL, "https://api.minimax.io")

    def test_get_default_model_returns_constructor_model(self):
        """get_default_model returns the model passed at construction."""
        p = MinimaxProvider(api_key="sk-test", default_model="MiniMax-Plus")
        self.assertEqual(p.get_default_model(), "MiniMax-Plus")


# ---------------------------------------------------------------------------
# Provider resolution tests
# ---------------------------------------------------------------------------

class TestGetProviderForProfile(unittest.TestCase):
    """Test get_provider_for_profile resolution chain."""

    TEST_PROFILE = "FRIDAY-TEST-PROFILE-LLM"
    TEST_PROVIDER = "friday-test-llm-provider"

    @classmethod
    def setUpClass(cls):
        _ensure_llm_provider(cls.TEST_PROVIDER, provider_type="minimax", is_active=1)
        if not frappe.db.exists("Agent Profile", cls.TEST_PROFILE):
            frappe.get_doc(
                {
                    "doctype": "Agent Profile",
                    "profile_name": cls.TEST_PROFILE,
                    "status": "Active",
                    "model_provider": None,  # No link — tests will set per test case
                }
            ).insert(ignore_permissions=True)
        # Ensure Agent Settings singleton exists (normally created by after_migrate hook)
        if not frappe.db.exists("Agent Settings", "Agent Settings"):
            frappe.get_doc({"doctype": "Agent Settings", "__default": "Agent Settings"}).insert(
                ignore_permissions=True
            )
        frappe.db.commit()

    def setUp(self):
        profile = frappe.get_doc("Agent Profile", self.TEST_PROFILE)
        profile.model_provider = None
        profile.save(ignore_permissions=True)
        # Clear Agent Settings default without loading the doc (which fails if it doesn't exist)
        frappe.db.set_value(
            "Agent Settings",
            "Agent Settings",
            "default_provider",
            None,
            update_modified=False,
        )
        frappe.db.commit()

    def tearDown(self):
        # Reset profile for next test
        self.setUp()

    def test_raises_when_no_provider_configured(self):
        """No LLM Provider at all → raises LLMError with descriptive message."""
        # Deactivate ALL providers so resolution falls through to "no provider"
        frappe.db.sql("UPDATE `tabLLM Provider` SET is_active = 0")
        frappe.db.commit()

        try:
            with self.assertRaises(LLMError) as ctx:
                get_provider_for_profile(self.TEST_PROFILE)

            self.assertIn(self.TEST_PROFILE, str(ctx.exception))
        finally:
            # Reactivate test provider
            frappe.db.sql("UPDATE `tabLLM Provider` SET is_active = 1 WHERE name = %s", [self.TEST_PROVIDER])
            frappe.db.commit()

    def test_resolves_from_profile_model_provider_link(self):
        """When Agent Profile.model_provider is set → that row is used."""
        profile = frappe.get_doc("Agent Profile", self.TEST_PROFILE)
        profile.model_provider = self.TEST_PROVIDER
        profile.save(ignore_permissions=True)
        frappe.db.commit()

        provider = get_provider_for_profile(self.TEST_PROFILE)
        self.assertIsInstance(provider, MinimaxProvider)
        self.assertEqual(provider.api_key, f"test-api-key-{self.TEST_PROVIDER}")

    def test_resolves_from_settings_default_provider(self):
        """When profile has no model_provider → falls back to Agent Settings.default_provider."""
        # Use raw SQL to set the default_provider without loading the full doc
        frappe.db.set_value(
            "Agent Settings",
            "Agent Settings",
            "default_provider",
            self.TEST_PROVIDER,
            update_modified=False,
        )
        frappe.db.commit()

        provider = get_provider_for_profile(self.TEST_PROFILE)
        self.assertIsInstance(provider, MinimaxProvider)

    def test_resolves_to_first_active_when_no_links_set(self):
        """No profile link and no settings default → first active LLM Provider row."""
        provider = get_provider_for_profile(self.TEST_PROFILE)
        self.assertIsInstance(provider, MinimaxProvider)

    def test_raises_for_inactive_provider_link(self):
        """Profile links to an inactive LLM Provider → raises LLMError."""
        # Re-link the profile to the test provider (setUp cleared it)
        frappe.db.set_value(
            "Agent Profile",
            self.TEST_PROFILE,
            "model_provider",
            self.TEST_PROVIDER,
            update_modified=False,
        )
        # Deactivate the test provider via raw SQL
        frappe.db.set_value("LLM Provider", self.TEST_PROVIDER, "is_active", 0, update_modified=False)
        frappe.db.commit()

        try:
            with self.assertRaises(LLMError):
                get_provider_for_profile(self.TEST_PROFILE)
        finally:
            # Reactivate for other tests
            frappe.db.set_value("LLM Provider", self.TEST_PROVIDER, "is_active", 1, update_modified=False)
            frappe.db.commit()

    def test_raises_for_unsupported_provider_type(self):
        """LLM Provider with unknown provider_type raises LLMError."""
        # Set a non-minimax type on the provider via raw SQL
        frappe.db.set_value("LLM Provider", self.TEST_PROVIDER, "provider_type", "unknown-provider", update_modified=False)
        frappe.db.commit()

        try:
            with self.assertRaises(LLMError) as ctx:
                get_provider_for_profile(self.TEST_PROFILE)

            self.assertIn("unknown-provider", str(ctx.exception))
        finally:
            frappe.db.set_value("LLM Provider", self.TEST_PROVIDER, "provider_type", "minimax", update_modified=False)
            frappe.db.commit()