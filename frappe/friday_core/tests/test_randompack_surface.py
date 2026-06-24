# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""
Unit tests for the RandomPack DOMAIN surface (Design 81b — connector #1).

Mock-based — no DB, no network. The generic spine (signature, dispatch,
transport) is tested in test_connector_core.py; this file pins the RandomPack
*meaning* + thin-adapter behaviour that stays in domain:randompack:
  - brief ingestion: field mapping, list joining, unmapped keys preserved in
    notes, frozen-snapshot idempotency (never overwrite)
  - outbound contract calls: endpoint-path resolution, heartbeat-safety
    (progress alone carries no status), the upload_file → attach_deliverable
    chaining, Pending Review signalling
"""

import json
import unittest
from unittest.mock import MagicMock, patch

from frappe.friday_core.integrations import randompack_client
from frappe.friday_core.surfaces import randompack

_S = "frappe.friday_core.surfaces.randompack"
_C = "frappe.friday_core.integrations.randompack_client"


class TestBriefIngestion(unittest.TestCase):
	_SNAPSHOT = {
		"company": "Loop Coffee",
		"audience": "Urban pros 25-40",
		"differentiator": "Single-origin subscription",
		"personality_attributes": ["warm", "crafted", "honest"],
		"references": "Aesop, Monocle",
		"brands_avoid": "Generic franchise look",
		"custom_field": "kept verbatim",
	}

	@patch(f"{_S}.frappe")
	def test_maps_fields_joins_lists_keeps_leftovers(self, mock_frappe):
		mock_frappe.db.get_value.return_value = None  # no existing brief
		mock_frappe.as_json.side_effect = json.dumps
		event = MagicMock()
		event.event_id = "evt-9"
		randompack.handle_payment_received({"brief": "RP-BRIEF-7", "brief_snapshot": self._SNAPSHOT}, event)
		payload = mock_frappe.get_doc.call_args[0][0]
		self.assertEqual(payload["business_name"], "Loop Coffee")
		self.assertEqual(payload["brand_personality"], "warm, crafted, honest")
		self.assertEqual(payload["status"], "Ready")
		self.assertIn("[rp:RP-BRIEF-7]", payload["notes"])
		self.assertIn("custom_field", payload["notes"])  # nothing silently lost

	@patch(f"{_S}.frappe")
	def test_frozen_snapshot_never_overwrites(self, mock_frappe):
		mock_frappe.db.get_value.return_value = "BB-0042"  # already ingested
		event = MagicMock()
		randompack.handle_payment_received({"brief": "RP-BRIEF-7", "brief_snapshot": self._SNAPSHOT}, event)
		mock_frappe.get_doc.assert_not_called()

	@patch(f"{_S}.frappe")
	def test_empty_snapshot_is_a_noop(self, mock_frappe):
		# Real payment.received carries no snapshot → staging no-op.
		randompack.handle_payment_received({"brief": "RP-BRIEF-7"}, MagicMock())
		mock_frappe.get_doc.assert_not_called()


class TestOutboundContractCalls(unittest.TestCase):
	@patch(f"{_C}.connector_client")
	def test_send_resolves_v1_path_and_connector(self, mock_cc):
		# bare contract names resolve under the backend's locked v1 module, and
		# every send goes through the randompack-system connector.
		randompack_client.send("update_task_progress", {"task": "T-1"})
		mock_cc.send.assert_called_once()
		args = mock_cc.send.call_args[0]
		self.assertEqual(args[0], "randompack-system")
		self.assertEqual(args[1], "randompack.api.v1.update_task_progress")

	@patch(f"{_C}.connector_client")
	def test_send_passes_dotted_path_through(self, mock_cc):
		randompack_client.send("x.y.z", {"a": 1})
		self.assertEqual(mock_cc.send.call_args[0][1], "x.y.z")

	@patch(f"{_C}.send")
	def test_heartbeat_progress_never_carries_status(self, mock_send):
		randompack_client.update_task_progress("T-1", progress=40)
		payload = mock_send.call_args[0][1]
		self.assertEqual(payload["progress"], 40)
		self.assertNotIn("status", payload)  # heartbeat-safe per contract

	@patch(f"{_C}.send")
	def test_attach_deliverable_chains_upload_file_url(self, mock_send):
		mock_send.side_effect = [
			{"message": {"file_url": "/private/files/spec.pdf"}},  # upload_file
			{"message": "attached"},  # attach_deliverable
		]
		out = randompack_client.attach_deliverable("PRJ-7", "spec.pdf", b"%PDF", "Guidelines")
		self.assertEqual(out, {"message": "attached"})
		attach_payload = mock_send.call_args_list[1][0][1]
		self.assertEqual(attach_payload["file_url"], "/private/files/spec.pdf")

	@patch(f"{_C}.send")
	def test_attach_deliverable_stops_when_upload_fails(self, mock_send):
		mock_send.side_effect = [None]
		self.assertIsNone(randompack_client.attach_deliverable("PRJ-7", "x.pdf", b""))
		self.assertEqual(mock_send.call_count, 1)

	@patch(f"{_C}.post_project_note")
	@patch(f"{_C}.update_task_progress")
	def test_pending_review_signal_shape(self, mock_update, mock_note):
		randompack_client.signal_pending_review("T-1", "ISS-7", "palette conflict")
		mock_update.assert_called_once_with("T-1", status="Pending Review")
		self.assertIn("ISS-7", mock_note.call_args.kwargs["note"])


if __name__ == "__main__":
	unittest.main()
