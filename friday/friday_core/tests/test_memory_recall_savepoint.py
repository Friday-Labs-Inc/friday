"""recall_block must survive a failing scored query WITHOUT aborting the transaction.

On Postgres a failed statement poisons the transaction until a rollback; the
recency fallback runs in the same transaction, so before the savepoint it died
with InFailedSqlTransaction. First seen on a fresh CI site whose after_migrate
DDL (the memory_search tsvector column) had not run.
"""

import unittest
from unittest.mock import patch

import frappe

from friday.friday_core.llm import memory


def _bad_scored(*args, **kwargs):
	# A real SQL failure, like the missing-column case — not a Python exception.
	frappe.db.sql('select this_column_does_not_exist from "tabAgent Memory" limit 1')


class TestRecallSavepoint(unittest.TestCase):
	def setUp(self):
		if frappe.db.db_type != "postgres":
			self.skipTest("transaction-abort semantics are Postgres-only")

	def test_failed_scored_recall_leaves_transaction_usable(self):
		with patch.object(memory, "_recall_scored", side_effect=_bad_scored):
			memory.recall_block("Friday", 200, query="anything")  # falls back, must not raise
		# The proof: the same transaction still answers a query.
		self.assertEqual(frappe.db.sql("select 1")[0][0], 1)
