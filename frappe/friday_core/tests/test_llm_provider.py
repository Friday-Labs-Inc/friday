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
        --module frappe.friday_core.tests.test_llm_provider

SEE ALSO
========
- `frappe/friday_core/llm/provider.py` — the module under test.
- `docs/contributing/proposals/slice-5-llm-integration.md` §4.
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import frappe

from frappe.friday_core.llm.provider import (
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
# MinimaxProvider.chat() — HTTP mocking tests
# ---------------------------------------------------------------------------

class TestMinimaxProviderChat(unittest.TestCase):
    """Test MinimaxProvider.chat() with mocked HTTP responses."""

    def _make_provider(self, api_key: str = "sk-test", model: str = "MiniMax-Standard"):
        return MinimaxProvider(api_key=api_key, default_model=model)

    @patch("frappe.friday_core.llm.provider.requests.post")
    def test_chat_sends_correct_headers(self, mock_post: MagicMock):
        """Authorization header uses Bearer token."""
        mock_post.return_value = MagicMock(status_code=200, json=lambda: {
            "choices": [{"message": {"content": "hello"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        })

        p = self._make_provider(api_key="my-secret-key")
        p.chat(messages=[{"role": "user", "content": "hi"}])

        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args[1]
        self.assertEqual(call_kwargs["headers"]["Authorization"], "Bearer my-secret-key")
        self.assertEqual(call_kwargs["headers"]["Content-Type"], "application/json")

    @patch("frappe.friday_core.llm.provider.requests.post")
    def test_chat_sends_model_and_messages_in_payload(self, mock_post: MagicMock):
        """Payload contains model and messages."""
        mock_post.return_value = MagicMock(status_code=200, json=lambda: {
            "choices": [{"message": {"content": "reply"}, "finish_reason": "stop"}],
            "usage": {},
        })

        p = self._make_provider(model="MiniMax-Standard")
        p.chat(messages=[{"role": "system", "content": "you are helpful"}])

        call_kwargs = mock_post.call_args[1]
        payload = call_kwargs["json"]
        self.assertEqual(payload["model"], "MiniMax-Standard")
        self.assertEqual(payload["messages"], [{"role": "system", "content": "you are helpful"}])

    @patch("frappe.friday_core.llm.provider.requests.post")
    def test_chat_includes_tools_when_provided(self, mock_post: MagicMock):
        """Tools are included in the payload when passed."""
        mock_post.return_value = MagicMock(status_code=200, json=lambda: {
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
            "usage": {},
        })

        tools = [
            {
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "description": "Get weather for a city",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ]
        p = self._make_provider()
        p.chat(messages=[{"role": "user", "content": "weather?"}], tools=tools)

        call_kwargs = mock_post.call_args[1]
        self.assertIn("tools", call_kwargs["json"])
        self.assertEqual(call_kwargs["json"]["tools"], tools)

    @patch("frappe.friday_core.llm.provider.requests.post")
    def test_chat_does_not_include_tools_when_none(self, mock_post: MagicMock):
        """Payload has no 'tools' key when tools=None."""
        mock_post.return_value = MagicMock(status_code=200, json=lambda: {
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
            "usage": {},
        })

        p = self._make_provider()
        p.chat(messages=[{"role": "user", "content": "hello"}], tools=None)

        call_kwargs = mock_post.call_args[1]
        self.assertNotIn("tools", call_kwargs["json"])

    @patch("frappe.friday_core.llm.provider.requests.post")
    def test_chat_model_override_from_argument(self, mock_post: MagicMock):
        """When model argument is passed, it overrides the default."""
        mock_post.return_value = MagicMock(status_code=200, json=lambda: {
            "choices": [{"message": {"content": "hi"}, "finish_reason": "stop"}],
            "usage": {},
        })

        p = self._make_provider(model="MiniMax-Standard")
        p.chat(messages=[{"role": "user", "content": "hi"}], model="MiniMax-Plus")

        call_kwargs = mock_post.call_args[1]
        self.assertEqual(call_kwargs["json"]["model"], "MiniMax-Plus")

    @patch("frappe.friday_core.llm.provider.requests.post")
    def test_chat_parses_response_correctly(self, mock_post: MagicMock):
        """A 200 response with well-formed body returns correct LLMResponse."""
        mock_post.return_value = MagicMock(status_code=200, json=lambda: {
            "choices": [{"message": {"content": "the reply"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 10, "total_tokens": 15},
        })

        p = self._make_provider()
        result = p.chat(messages=[{"role": "user", "content": "hi"}])

        self.assertIsInstance(result, dict)
        self.assertEqual(result["content"], "the reply")
        self.assertEqual(result["finish_reason"], "stop")
        self.assertEqual(result["usage"]["prompt_tokens"], 5)
        self.assertEqual(result["usage"]["completion_tokens"], 10)
        self.assertEqual(result["usage"]["total_tokens"], 15)

    @patch("frappe.friday_core.llm.provider.requests.post")
    def test_chat_empty_content_returns_empty_string(self, mock_post: MagicMock):
        """Minimax can return content: null — we treat that as empty string."""
        mock_post.return_value = MagicMock(status_code=200, json=lambda: {
            "choices": [{"message": {"content": None}, "finish_reason": "stop"}],
            "usage": {},
        })

        p = self._make_provider()
        result = p.chat(messages=[{"role": "user", "content": "hi"}])
        self.assertEqual(result["content"], "")

    @patch("frappe.friday_core.llm.provider.requests.post")
    def test_chat_raises_llm_auth_error_on_401(self, mock_post: MagicMock):
        """401 response raises LLMAuthError, not generic LLMError."""
        mock_response = MagicMock(status_code=401)
        mock_response.reason = "Unauthorized"
        mock_post.return_value = mock_response

        p = self._make_provider()
        with self.assertRaises(LLMAuthError):
            p.chat(messages=[{"role": "user", "content": "hi"}])

    @patch("frappe.friday_core.llm.provider.requests.post")
    def test_chat_retries_on_429(self, mock_post: MagicMock):
        """429 triggers retry with exponential backoff — does not raise immediately."""
        mock_response = MagicMock(status_code=429)
        mock_post.return_value = mock_response

        p = self._make_provider()
        with self.assertRaises(LLMError):
            p.chat(messages=[{"role": "user", "content": "hi"}])

        # 3 attempts for 429
        self.assertEqual(mock_post.call_count, 3)

    @patch("frappe.friday_core.llm.provider.requests.post")
    def test_chat_retries_on_500(self, mock_post: MagicMock):
        """500/502/503 triggers retry up to 3 times before raising."""
        mock_response = MagicMock(status_code=500)
        mock_post.return_value = mock_response

        p = self._make_provider()
        with self.assertRaises(LLMError):
            p.chat(messages=[{"role": "user", "content": "hi"}])

        self.assertEqual(mock_post.call_count, 3)

    @patch("frappe.friday_core.llm.provider.requests.post")
    def test_chat_timeout_raises_llm_error(self, mock_post: MagicMock):
        """requests.exceptions.Timeout is caught and retried, then raises LLMError.

        Per the redaction policy (audit fix H1): the raised LLMError reports
        the exception TYPE only, not the original message — Timeout/Connection
        errors can include URLs with query strings, which we never want in
        the Frappe Error Log.
        """
        import requests

        mock_post.side_effect = requests.exceptions.Timeout("Connection timed out")

        p = self._make_provider()
        with self.assertRaises(LLMError) as ctx:
            p.chat(messages=[{"role": "user", "content": "hi"}])

        # Assert the type name appears, NOT the underlying message text.
        self.assertIn("Timeout", str(ctx.exception))
        # And explicitly verify the underlying message text does NOT leak.
        self.assertNotIn("timed out", str(ctx.exception))
        self.assertEqual(mock_post.call_count, 3)

    @patch("frappe.friday_core.llm.provider.requests.post")
    def test_chat_connection_error_raises_llm_error(self, mock_post: MagicMock):
        """Connection errors are caught and retried, then raise LLMError.

        Same redaction policy — type only, never the underlying message.
        """
        import requests

        mock_post.side_effect = requests.exceptions.ConnectionError("Connection refused")

        p = self._make_provider()
        with self.assertRaises(LLMError) as ctx:
            p.chat(messages=[{"role": "user", "content": "hi"}])

        self.assertIn("ConnectionError", str(ctx.exception))
        self.assertNotIn("refused", str(ctx.exception))
        self.assertEqual(mock_post.call_count, 3)

    @patch("frappe.friday_core.llm.provider.requests.post")
    def test_chat_no_choices_in_response_raises_llm_error(self, mock_post: MagicMock):
        """Minimax returning empty choices is treated as an error."""
        mock_post.return_value = MagicMock(status_code=200, json=lambda: {
            "choices": [],
            "usage": {},
        })

        p = self._make_provider()
        with self.assertRaises(LLMError) as ctx:
            p.chat(messages=[{"role": "user", "content": "hi"}])

        self.assertIn("no choices", str(ctx.exception))

    @patch("frappe.friday_core.llm.provider.requests.post")
    def test_chat_uses_correct_timeout(self, mock_post: MagicMock):
        """requests.post is called with timeout=30."""
        mock_post.return_value = MagicMock(status_code=200, json=lambda: {
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
            "usage": {},
        })

        p = self._make_provider()
        p.chat(messages=[{"role": "user", "content": "hi"}])

        call_kwargs = mock_post.call_args[1]
        self.assertEqual(call_kwargs["timeout"], 30)

    @patch("frappe.friday_core.llm.provider.requests.post")
    def test_chat_404_fails_fast_not_retryable(self, mock_post: MagicMock):
        """Feature F: 404 (model_not_found) is not retryable — fail on first attempt."""
        mock_post.return_value = MagicMock(status_code=404, text="model `x` does not exist")
        p = self._make_provider()
        with self.assertRaises(LLMError):
            p.chat(messages=[{"role": "user", "content": "hi"}])
        self.assertEqual(mock_post.call_count, 1)

    @patch("frappe.friday_core.llm.provider.requests.post")
    def test_chat_400_fails_fast_not_retryable(self, mock_post: MagicMock):
        """Feature F: 400 (format_error) is not retryable — fail on first attempt."""
        mock_post.return_value = MagicMock(status_code=400, text="bad request")
        p = self._make_provider()
        with self.assertRaises(LLMError):
            p.chat(messages=[{"role": "user", "content": "hi"}])
        self.assertEqual(mock_post.call_count, 1)

    @patch("frappe.friday_core.llm.provider.requests.post")
    def test_chat_503_retries_as_overloaded(self, mock_post: MagicMock):
        """Feature F: 503 (overloaded) is retryable — 3 attempts then LLMError."""
        mock_post.return_value = MagicMock(status_code=503, text="service unavailable")
        p = self._make_provider()
        with self.assertRaises(LLMError):
            p.chat(messages=[{"role": "user", "content": "hi"}])
        self.assertEqual(mock_post.call_count, 3)


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