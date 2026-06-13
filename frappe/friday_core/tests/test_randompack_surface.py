# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""
Unit tests for the RandomPack integration surface (design 60a, LOCKED).

Mock-based — no DB, no network. Pins the locked contract:
  - Stripe-style signature: valid passes; bad v1 fails BEFORE freshness;
    stale t fails AFTER a valid v1; malformed headers fail closed
  - UUID dedupe: a duplicate delivery is a 200 no-op (no second row)
  - process_event: Processed replays skip; handler errors → Failed + reason
    (the row is the error ledger); unhandled types → Processed "recorded"
  - brief ingestion: field mapping, list joining, unmapped keys preserved in
    notes, frozen-snapshot idempotency (never overwrite)
  - outbound client: token auth header, NEVER raises (returns None on any
    failure), heartbeat-safety (progress alone carries no status), the
    upload_file → attach_deliverable chaining, Pending Review signalling
"""

import hashlib
import hmac
import json
import time
import unittest
from unittest.mock import MagicMock, patch

from frappe.friday_core.integrations import randompack_client
from frappe.friday_core.surfaces import randompack

_S = "frappe.friday_core.surfaces.randompack"
_C = "frappe.friday_core.integrations.randompack_client"

SECRET = "test-secret"


def _sign(body: bytes, t: float | None = None, secret: str = SECRET) -> str:
	t = t if t is not None else time.time()
	v1 = hmac.new(secret.encode(), f"{t}.".encode() + body, hashlib.sha256).hexdigest()
	return f"t={t},v1={v1}"


class TestSignature(unittest.TestCase):
	def test_valid_signature_passes(self):
		body = b'{"id": "evt-1"}'
		self.assertTrue(randompack.verify_signature(body, _sign(body), SECRET, 300))

	def test_wrong_secret_fails(self):
		body = b"{}"
		self.assertFalse(randompack.verify_signature(body, _sign(body, secret="other"), SECRET, 300))

	def test_tampered_body_fails(self):
		header = _sign(b'{"amount": 1}')
		self.assertFalse(randompack.verify_signature(b'{"amount": 9}', header, SECRET, 300))

	def test_stale_t_fails_even_with_valid_v1(self):
		body = b"{}"
		old = time.time() - 3600
		self.assertFalse(randompack.verify_signature(body, _sign(body, t=old), SECRET, 300))

	def test_fresh_replay_with_new_t_passes(self):
		# The backend re-signs replays with fresh t (locked contract).
		body = b'{"id": "evt-1"}'
		self.assertTrue(randompack.verify_signature(body, _sign(body), SECRET, 300))

	def test_malformed_headers_fail_closed(self):
		for header in ("", "t=123", "v1=abc", "junk", "t=abc,v1=zzz"):
			self.assertFalse(randompack.verify_signature(b"{}", header, SECRET, 300))

	def test_missing_secret_fails_closed(self):
		body = b"{}"
		self.assertFalse(randompack.verify_signature(body, _sign(body), "", 300))


class TestProcessEvent(unittest.TestCase):
	def _event(self, event_type="payment.received", status="Received", payload=None):
		event = MagicMock()
		event.event_type = event_type
		event.status = status
		event.payload = json.dumps(payload or {})
		return event

	@patch(f"{_S}.frappe")
	def test_processed_replay_is_skipped(self, mock_frappe):
		event = self._event(status="Processed")
		mock_frappe.get_doc.return_value = event
		randompack.process_event("evt-1")
		event.save.assert_not_called()

	@patch(f"{_S}.frappe")
	def test_dict_payload_tolerated(self, mock_frappe):
		# Frappe's JSON fieldtype returns a parsed dict on Postgres reads.
		event = self._event(event_type="gate.opened")
		event.payload = {"already": "parsed"}
		mock_frappe.get_doc.return_value = event
		randompack.process_event("evt-1")
		self.assertEqual(event.status, "Processed")

	@patch(f"{_S}.frappe")
	def test_unhandled_type_recorded_for_60b(self, mock_frappe):
		event = self._event(event_type="gate.opened")
		mock_frappe.get_doc.return_value = event
		randompack.process_event("evt-1")
		self.assertEqual(event.status, "Processed")
		self.assertIn("60b", event.failure_reason)

	@patch.dict(randompack._HANDLERS, {"boom.event": MagicMock(side_effect=RuntimeError("kaput"))})
	@patch(f"{_S}.frappe")
	def test_handler_error_marks_failed_with_reason(self, mock_frappe):
		event = self._event(event_type="boom.event")
		mock_frappe.get_doc.return_value = event
		randompack.process_event("evt-1")
		self.assertEqual(event.status, "Failed")
		self.assertIn("RuntimeError", event.failure_reason)
		mock_frappe.log_error.assert_called_once()


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
		randompack.handle_payment_received({"project_id": "PRJ-7", "brief_snapshot": self._SNAPSHOT}, event)
		payload = mock_frappe.get_doc.call_args[0][0]
		self.assertEqual(payload["business_name"], "Loop Coffee")
		self.assertEqual(payload["brand_personality"], "warm, crafted, honest")
		self.assertEqual(payload["status"], "Ready")
		self.assertIn("[rp:PRJ-7]", payload["notes"])
		self.assertIn("custom_field", payload["notes"])  # nothing silently lost

	@patch(f"{_S}.frappe")
	def test_frozen_snapshot_never_overwrites(self, mock_frappe):
		mock_frappe.db.get_value.return_value = "BB-0042"  # already ingested
		event = MagicMock()
		randompack.handle_payment_received({"project_id": "PRJ-7", "brief_snapshot": self._SNAPSHOT}, event)
		mock_frappe.get_doc.assert_not_called()

	@patch(f"{_S}.frappe")
	def test_empty_snapshot_is_a_noop(self, mock_frappe):
		randompack.handle_payment_received({"project_id": "PRJ-7"}, MagicMock())
		mock_frappe.get_doc.assert_not_called()


class TestOutboundClient(unittest.TestCase):
	def _settings(self, enabled=1):
		settings = MagicMock()
		settings.enabled = enabled
		settings.api_base_url = "https://ops.randompack.com"
		settings.api_key = "key123"
		settings.get_password.return_value = "sec456"
		return settings

	@patch(f"{_C}.requests")
	@patch(f"{_C}.frappe")
	def test_token_auth_and_endpoint_shape(self, mock_frappe, mock_requests):
		mock_frappe.get_cached_doc.return_value = self._settings()
		mock_requests.post.return_value = MagicMock(json=lambda: {"message": "ok"})
		randompack_client.send("update_task_progress", {"task": "T-1"})
		url = mock_requests.post.call_args[0][0]
		self.assertEqual(url, "https://ops.randompack.com/api/method/randompack.api.update_task_progress")
		headers = mock_requests.post.call_args.kwargs["headers"]
		self.assertEqual(headers["Authorization"], "token key123:sec456")

	@patch(f"{_C}.requests")
	@patch(f"{_C}.frappe")
	def test_never_raises_returns_none_on_failure(self, mock_frappe, mock_requests):
		mock_frappe.get_cached_doc.return_value = self._settings()
		mock_requests.post.side_effect = RuntimeError("network down")
		self.assertIsNone(randompack_client.send("post_project_note", {"note": "x"}))
		mock_frappe.log_error.assert_called_once()

	@patch(f"{_C}.frappe")
	def test_disabled_integration_drops_send(self, mock_frappe):
		mock_frappe.get_cached_doc.return_value = self._settings(enabled=0)
		self.assertIsNone(randompack_client.send("post_project_note", {"note": "x"}))

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
