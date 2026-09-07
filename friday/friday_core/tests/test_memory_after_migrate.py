# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""
Regression tests for the memory schema after_migrate hooks.

Caught on a fresh AWS Postgres deploy WITHOUT pgvector: a failed DDL
(`CREATE TABLE ... vector(N)` when the extension is missing, or the tsvector
column DDL) aborts the surrounding transaction. The old `except` logged but did
NOT roll back, so every LATER after_migrate hook died with
`InFailedSqlTransaction` — the "best-effort, never breaks migrate" docstring was
false. These pin the fix: on Postgres the DDL runs inside a savepoint and a
failure rolls back to it, so a missing extension is genuinely non-fatal.
"""

import unittest
from unittest.mock import patch

_M = "friday.friday_core.llm.after_migrate"


class TestMemorySchemaRollback(unittest.TestCase):
	@patch(f"{_M}.frappe")
	def test_search_schema_rolls_back_to_savepoint_on_failure(self, fr):
		from friday.friday_core.llm import after_migrate

		fr.db.db_type = "postgres"
		fr.db.sql_ddl.side_effect = Exception("tsvector DDL failed")

		# Must not raise — and must roll back to its savepoint so the txn survives.
		after_migrate.ensure_memory_search_schema()

		fr.db.rollback.assert_called_once()
		self.assertIn("save_point", fr.db.rollback.call_args.kwargs)

	@patch("friday.friday_core.llm.embed.embedding_dim", return_value=384)
	@patch(f"{_M}.frappe")
	def test_embedding_schema_rolls_back_to_savepoint_on_failure(self, fr, _dim):
		from friday.friday_core.llm import after_migrate

		fr.db.db_type = "postgres"
		fr.db.sql.return_value = []  # the atttypmod probe
		fr.db.sql_ddl.side_effect = Exception('extension "vector" does not exist')

		after_migrate.ensure_memory_embedding_schema()  # must not raise

		fr.db.rollback.assert_called_once()
		self.assertIn("save_point", fr.db.rollback.call_args.kwargs)

	@patch(f"{_M}.frappe")
	def test_non_postgres_is_a_noop(self, fr):
		from friday.friday_core.llm import after_migrate

		fr.db.db_type = "mariadb"
		after_migrate.ensure_memory_search_schema()
		after_migrate.ensure_memory_embedding_schema()
		fr.db.savepoint.assert_not_called()
		fr.db.rollback.assert_not_called()
		fr.db.sql_ddl.assert_not_called()


if __name__ == "__main__":
	unittest.main()
