# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""
Tests for the session_search skill + its Chat Message FTS schema (Design 89).
Mock-based.

Pins: the FTS query is scoped to the CALLING agent (governance); empty results
are handled; non-Postgres falls back to a recency LIKE scan; the after_migrate
DDL rolls back to its savepoint on failure (Postgres-only no-op otherwise).
"""

import unittest
from unittest.mock import patch

_SS = "friday.friday_core.skills.handlers_session_search"
_M = "friday.friday_core.llm.after_migrate"


class TestSessionSearch(unittest.TestCase):
	@patch(f"{_SS}.frappe")
	def test_requires_query(self, fr):
		from friday.friday_core.skills import handlers_session_search as h

		fr.flags.get.return_value = {"agent_profile": "Friday"}
		with self.assertRaises(ValueError):
			h.session_search("session_search", {})

	@patch(f"{_SS}.frappe")
	def test_postgres_fts_scoped_to_caller(self, fr):
		from friday.friday_core.skills import handlers_session_search as h

		fr.flags.get.return_value = {"agent_profile": "Friday", "session_id": "S"}
		fr.db.db_type = "postgres"
		fr.db.sql.return_value = [
			{"content": "we decided X", "session_id": "CH-1", "timestamp": "T", "direction": "inbound"}
		]
		res = h.session_search("session_search", {"query": "decided", "limit": 5})

		# Scoped to the caller's own messages; query + limit passed through.
		params = fr.db.sql.call_args[0][1]
		self.assertEqual(params["profile"], "Friday")
		self.assertEqual(params["q"], "decided")
		self.assertEqual(params["limit"], 5)
		# The SQL must filter to the caller (no cross-agent transcript reads).
		sql = fr.db.sql.call_args[0][0]
		self.assertIn("m.agent_profile = %(profile)s", sql)
		self.assertIn("content_search @@", sql)  # actual FTS match, not recall
		self.assertEqual(len(res["matches"]), 1)
		self.assertIn("we decided X", res["result"])

	@patch(f"{_SS}.frappe")
	def test_empty_result(self, fr):
		from friday.friday_core.skills import handlers_session_search as h

		fr.flags.get.return_value = {"agent_profile": "Friday"}
		fr.db.db_type = "postgres"
		fr.db.sql.return_value = []
		res = h.session_search("session_search", {"query": "nope"})
		self.assertEqual(res["matches"], [])
		self.assertIn("No past messages", res["result"])

	@patch(f"{_SS}.frappe")
	def test_non_postgres_falls_back_to_like(self, fr):
		from friday.friday_core.skills import handlers_session_search as h

		fr.flags.get.return_value = {"agent_profile": "Friday"}
		fr.db.db_type = "mariadb"
		fr.db.get_all.return_value = [
			{"content": "x", "session_id": "S", "timestamp": "T", "direction": "outbound"}
		]
		res = h.session_search("session_search", {"query": "x"})
		gkw = fr.db.get_all.call_args.kwargs
		self.assertEqual(gkw["filters"]["agent_profile"], "Friday")
		self.assertEqual(gkw["filters"]["content"], ("like", "%x%"))
		self.assertEqual(len(res["matches"]), 1)


class TestChatSearchSchema(unittest.TestCase):
	@patch(f"{_M}.frappe")
	def test_ddl_rolls_back_to_savepoint_on_failure(self, fr):
		from friday.friday_core.llm import after_migrate

		fr.db.db_type = "postgres"
		fr.db.sql_ddl.side_effect = Exception("vector/tsvector DDL failed")
		after_migrate.ensure_chatmessage_search_schema()  # must not raise
		fr.db.rollback.assert_called_once()
		self.assertIn("save_point", fr.db.rollback.call_args.kwargs)

	@patch(f"{_M}.frappe")
	def test_noop_on_non_postgres(self, fr):
		from friday.friday_core.llm import after_migrate

		fr.db.db_type = "mariadb"
		after_migrate.ensure_chatmessage_search_schema()
		fr.db.sql_ddl.assert_not_called()


class TestSkillIsLoadable(unittest.TestCase):
	def test_no_doctype_gate(self):
		# REGRESSION GUARD (AWS-found): a `required_doctypes=[Chat Message: read]`
		# gate drops session_search from every agent's menu unless a role grants
		# Chat Message read — and that grant is doctype-level, so it would ALSO
		# leak cross-agent reads via generic read-record/list-records. The handler
		# hard-scopes to the caller's own agent_profile, so NO doctype gate is
		# needed. Keep this empty.
		from friday.friday_core.skills import bootstrap_session_search as b

		self.assertEqual(b._SKILL["docs"], [])


if __name__ == "__main__":
	unittest.main()
