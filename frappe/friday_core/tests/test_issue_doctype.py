# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""
End-to-end DocType contract for `Issue` — runs on a bench (needs a site/DB),
so it is part of the Legion e2e, not the Mac unit run. Verifies the migrated
DocType carries the doc-53 field + option contract.

    bench --site friday.localhost run-tests \\
        --module frappe.friday_core.tests.test_issue_doctype
"""

import unittest

import frappe


class TestIssueDocTypeContract(unittest.TestCase):
	"""The migrated `Issue` DocType matches doc 53 §3.3."""

	def test_doctype_exists_with_doc53_fields(self):
		have = {df.fieldname for df in frappe.get_meta("Issue").fields}
		expected = {
			"subject", "source", "reason", "status", "priority",
			"raised_by", "assigned_to", "project", "related_task",
			"waiting_on", "description", "resolution_details", "execution_log",
		}
		self.assertEqual(expected - have, set(), f"Issue is missing fields: {expected - have}")

	def test_source_status_reason_options(self):
		opts = {df.fieldname: (df.options or "") for df in frappe.get_meta("Issue").fields}
		self.assertIn("Agent-raised", opts["source"])
		self.assertIn("Human-raised", opts["source"])
		for s in ("Open", "In Progress", "Resolved", "Closed", "Reopened"):
			self.assertIn(s, opts["status"])
		for r in ("Failure", "Dependency-Wait"):
			self.assertIn(r, opts["reason"])


if __name__ == "__main__":
	unittest.main()
