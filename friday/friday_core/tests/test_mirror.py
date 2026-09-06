# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt

"""Unit tests for transcript mirroring (gateway/mirror.py).

Mock-based, no DB. Pins the contract: a mirror row is an OUTBOUND, `is_mirror=1`,
processed row whose content carries the source marker; empty input writes nothing;
and any insert failure is swallowed (best-effort — a mirror must never break the
caller that posted out-of-band).
"""

import unittest
from unittest.mock import MagicMock, patch

from friday.friday_core.gateway import mirror

_M = "friday.friday_core.gateway.mirror"


class TestMirror(unittest.TestCase):
	@patch(f"{_M}.frappe")
	def test_writes_marked_outbound_row(self, mock_frappe):
		doc = MagicMock()
		doc.name = "cm-1"
		mock_frappe.get_doc.return_value = doc

		out = mirror.mirror_to_session(
			"CH-1", "Shared 2 file(s): a.pdf, b.pdf", source_label="share-deliverables"
		)

		self.assertEqual(out, "cm-1")
		payload = mock_frappe.get_doc.call_args[0][0]
		self.assertEqual(payload["doctype"], "Chat Message")
		self.assertEqual(payload["session_id"], "CH-1")
		self.assertEqual(payload["direction"], "outbound")  # → assistant in history
		self.assertEqual(payload["is_mirror"], 1)
		self.assertEqual(payload["processed"], 1)
		self.assertIn("share-deliverables", payload["content"])  # source marker
		self.assertIn("Shared 2 file(s)", payload["content"])
		doc.insert.assert_called_once()

	@patch(f"{_M}.frappe")
	def test_empty_input_writes_nothing(self, mock_frappe):
		self.assertIsNone(mirror.mirror_to_session("", "note"))
		self.assertIsNone(mirror.mirror_to_session("CH-1", "   "))
		mock_frappe.get_doc.assert_not_called()

	@patch(f"{_M}.frappe")
	def test_insert_failure_is_swallowed(self, mock_frappe):
		mock_frappe.get_doc.return_value.insert.side_effect = RuntimeError("boom")
		out = mirror.mirror_to_session("CH-1", "note")
		self.assertIsNone(out)  # never raises
		mock_frappe.db.rollback.assert_called_once_with(save_point="friday_mirror")
		mock_frappe.log_error.assert_called_once()


if __name__ == "__main__":
	unittest.main()
