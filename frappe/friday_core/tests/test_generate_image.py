# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt

"""
Tests for the `generate-image` skill (MiniMax image generation).

The MiniMax HTTP call and file save are mocked — no network, no API cost,
nothing committed. We assert the happy path (correct host/auth/model + saved
file URL returned), and the guarded failure paths (no prompt, no agent context,
non-MiniMax provider, API error code) which must return a helpful message and
never raise.
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import frappe

from frappe.friday_core.skills import handlers_visual as hv


class TestGenerateImage(unittest.TestCase):
	def tearDown(self):
		frappe.flags["friday_dispatch_context"] = None

	def test_requires_prompt(self):
		out = hv.generate_image("generate-image", {})
		self.assertIn("prompt", out["result"])

	def test_requires_agent_context(self):
		frappe.flags["friday_dispatch_context"] = {}
		out = hv.generate_image("generate-image", {"prompt": "a logo"})
		self.assertIn("agent", out["result"].lower())

	@patch("frappe.friday_core.llm.provider._resolve_provider_row")
	def test_non_minimax_provider_rejected(self, m_row):
		m_row.return_value = {"name": "X", "provider_type": "openai", "base_url": ""}
		frappe.flags["friday_dispatch_context"] = {"agent_profile": "Creative Director"}
		out = hv.generate_image("generate-image", {"prompt": "a logo"})
		self.assertIn("MiniMax", out["result"])

	@patch("frappe.utils.file_manager.save_file")
	@patch("frappe.friday_core.skills.handlers_visual.requests")
	@patch("frappe.friday_core.llm.provider._get_api_key")
	@patch("frappe.friday_core.llm.provider._resolve_provider_row")
	def test_success_saves_and_returns_url(self, m_row, m_key, m_req, m_save):
		m_row.return_value = {"name": "Minimax", "provider_type": "minimax", "base_url": "https://api.minimax.io/v1"}
		m_key.return_value = "secret"
		post_resp = MagicMock()
		post_resp.json.return_value = {
			"data": {"image_urls": ["https://img.example/1.png"]},
			"base_resp": {"status_code": 0, "status_msg": "success"},
		}
		get_resp = MagicMock()
		get_resp.content = b"PNGBYTES"
		m_req.post.return_value = post_resp
		m_req.get.return_value = get_resp
		m_save.return_value = MagicMock(file_url="/files/glacial-logo-1.png")
		frappe.flags["friday_dispatch_context"] = {"agent_profile": "Creative Director", "session_id": "chat-uuid"}

		out = hv.generate_image("generate-image", {"prompt": "glacial minimalist logo", "aspect_ratio": "1:1"})

		self.assertEqual(out["image_urls"], ["/files/glacial-logo-1.png"])
		self.assertIn("/files/glacial-logo-1.png", out["result"])
		# correct endpoint, auth, and model
		args, kwargs = m_req.post.call_args
		self.assertIn("api.minimax.io/v1/image_generation", args[0])
		self.assertEqual(kwargs["headers"]["Authorization"], "Bearer secret")
		self.assertEqual(kwargs["json"]["model"], "image-01")
		self.assertEqual(kwargs["json"]["aspect_ratio"], "1:1")

	@patch("frappe.friday_core.skills.handlers_visual.requests")
	@patch("frappe.friday_core.llm.provider._get_api_key")
	@patch("frappe.friday_core.llm.provider._resolve_provider_row")
	def test_api_error_is_reported_not_raised(self, m_row, m_key, m_req):
		m_row.return_value = {"name": "Minimax", "provider_type": "minimax", "base_url": ""}
		m_key.return_value = "secret"
		post_resp = MagicMock()
		post_resp.json.return_value = {"base_resp": {"status_code": 1008, "status_msg": "insufficient balance"}}
		m_req.post.return_value = post_resp
		frappe.flags["friday_dispatch_context"] = {"agent_profile": "Creative Director"}

		out = hv.generate_image("generate-image", {"prompt": "a logo"})
		self.assertIn("1008", out["result"])

	@patch("frappe.friday_core.llm.provider._get_api_key")
	@patch("frappe.friday_core.llm.provider._resolve_provider_row")
	def test_china_host_selected_by_base_url(self, m_row, m_key):
		m_row.return_value = {"name": "Minimax", "provider_type": "minimax", "base_url": "https://api.minimaxi.com/v1"}
		m_key.return_value = "secret"
		with patch("frappe.friday_core.skills.handlers_visual.requests") as m_req:
			post_resp = MagicMock()
			post_resp.json.return_value = {"data": {"image_urls": []}, "base_resp": {"status_code": 0}}
			m_req.post.return_value = post_resp
			frappe.flags["friday_dispatch_context"] = {"agent_profile": "Creative Director"}
			hv.generate_image("generate-image", {"prompt": "a logo"})
			args, _ = m_req.post.call_args
			self.assertIn("api.minimaxi.com", args[0])
