# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""
Tests for project-aware profile resolution (Design 73, Slice 3).

Mock-based — no DB, no Raven needed (mirrors test_raven_adapter's style). Pins
the locked routing contract:
  - a message in a project's room routes to that Project's project_lead_profile
    when it's an Active Agent Profile,
  - everything else falls back to Chat Platform.default_agent_profile, byte-for-
    byte the pre-Slice-3 behaviour: non-project channel, DM, no lead set, or a
    Suspended/Retired lead,
  - an unknown platform still returns None.
"""

import unittest
from unittest.mock import patch

from frappe.friday_core.routing.resolve import resolve_profile

_R = "frappe.friday_core.routing.resolve"


def _get_value_router(mapping):
	"""A frappe.db.get_value side_effect that answers by (doctype, field)."""

	def _gv(doctype, name, field=None, *args, **kwargs):
		return mapping.get((doctype, field))

	return _gv


class TestProjectAwareRouting(unittest.TestCase):
	@patch(f"{_R}.project_for_session", return_value="FLI-001")
	@patch(f"{_R}.frappe")
	def test_project_room_routes_to_active_lead(self, mock_frappe, _pfs):
		mock_frappe.db.exists.return_value = True
		mock_frappe.db.get_value.side_effect = _get_value_router(
			{
				("Project", "project_lead_profile"): "Commander",
				("Agent Profile", "status"): "Active",
				("Chat Platform", "default_agent_profile"): "PlatformDefault",
			}
		)
		self.assertEqual(resolve_profile("raven", chat_id="proj-fli-001"), "Commander")

	@patch(f"{_R}.project_for_session", return_value=None)
	@patch(f"{_R}.frappe")
	def test_non_project_channel_falls_back_to_default(self, mock_frappe, _pfs):
		mock_frappe.db.exists.return_value = True
		mock_frappe.db.get_value.side_effect = _get_value_router(
			{("Chat Platform", "default_agent_profile"): "PlatformDefault"}
		)
		self.assertEqual(resolve_profile("raven", chat_id="some-dm-channel"), "PlatformDefault")

	@patch(f"{_R}.project_for_session", return_value="FLI-001")
	@patch(f"{_R}.frappe")
	def test_project_without_lead_falls_back_to_default(self, mock_frappe, _pfs):
		mock_frappe.db.exists.return_value = True
		mock_frappe.db.get_value.side_effect = _get_value_router(
			{
				("Project", "project_lead_profile"): None,  # no lead set
				("Chat Platform", "default_agent_profile"): "PlatformDefault",
			}
		)
		self.assertEqual(resolve_profile("raven", chat_id="proj-no-lead"), "PlatformDefault")

	@patch(f"{_R}.project_for_session", return_value="FLI-001")
	@patch(f"{_R}.frappe")
	def test_inactive_lead_falls_back_to_default(self, mock_frappe, _pfs):
		mock_frappe.db.exists.return_value = True
		mock_frappe.db.get_value.side_effect = _get_value_router(
			{
				("Project", "project_lead_profile"): "OldLead",
				("Agent Profile", "status"): "Retired",  # not Active
				("Chat Platform", "default_agent_profile"): "PlatformDefault",
			}
		)
		self.assertEqual(resolve_profile("raven", chat_id="proj-retired-lead"), "PlatformDefault")

	@patch(f"{_R}.project_for_session")
	@patch(f"{_R}.frappe")
	def test_no_chat_id_is_plain_default_lookup(self, mock_frappe, mock_pfs):
		"""chat_id=None short-circuits — project resolution isn't even attempted."""
		mock_frappe.db.exists.return_value = True
		mock_frappe.db.get_value.side_effect = _get_value_router(
			{("Chat Platform", "default_agent_profile"): "PlatformDefault"}
		)
		self.assertEqual(resolve_profile("raven"), "PlatformDefault")
		mock_pfs.assert_not_called()

	@patch(f"{_R}.project_for_session")
	@patch(f"{_R}.frappe")
	def test_unknown_platform_returns_none(self, mock_frappe, mock_pfs):
		mock_frappe.db.exists.return_value = False
		self.assertIsNone(resolve_profile("not-a-platform", chat_id="whatever"))


if __name__ == "__main__":
	unittest.main()
