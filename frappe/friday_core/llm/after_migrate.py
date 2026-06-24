# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt

"""
Migration helper — seeded defaults for the Friday LLM stack.

Called on every `bench --site <site> migrate` via the `after_migrate` hook
in `frappe/hooks.py`.

What it does
============

Ensures the `Agent Settings` singleton row exists. This row holds global
defaults (e.g. `default_provider`, delegation limits). If it already exists,
this is a no-op.

The actual create/identity logic lives in the Agent Settings controller
(`doctype/agent_settings/agent_settings.py`) as the single source of truth —
the row is named `"__default"`, NOT "Agent Settings" (Frappe forbids a record
named the same as its DocType). This module just wires that helper into the
`after_migrate` hook so the singleton is always present when the site boots,
without operators creating it by hand.
"""

from __future__ import annotations

import frappe
from frappe.friday_core.doctype.agent_settings.agent_settings import (
	ensure_agent_settings,
)


def ensure_memory_search_schema() -> None:
	"""Add the Postgres full-text index that scored memory recall uses (design 80 step 2a).

	Adds a generated ``memory_search`` tsvector column on ``tabAgent Memory``
	(subject weighted above the memory body) plus a GIN index, so
	``llm.memory._recall_scored`` can rank memories by relevance to the current
	message. Frappe's ORM has no ``tsvector`` field type, so this lives as a DDL
	side-channel here rather than in the DocType JSON — Frappe's schema sync
	leaves the column untouched.

	Postgres-only, idempotent (``IF NOT EXISTS``), and best-effort: any failure is
	logged and never breaks ``bench migrate``. On non-Postgres (or if this fails),
	recall simply falls back to recency-only.

	NOTE: the generated column references the ``memory`` and ``subject`` fields by
	name — do not rename those Agent Memory fields without updating this DDL.
	"""
	if frappe.db.db_type != "postgres":
		return
	try:
		frappe.db.sql_ddl(
			'ALTER TABLE "tabAgent Memory" ADD COLUMN IF NOT EXISTS memory_search tsvector '
			"GENERATED ALWAYS AS ("
			"setweight(to_tsvector('english', coalesce(subject, '')), 'A') || "
			"setweight(to_tsvector('english', coalesce(memory, '')), 'B')"
			") STORED"
		)
		frappe.db.sql_ddl(
			'CREATE INDEX IF NOT EXISTS "tabAgent Memory_fts_gin" '
			'ON "tabAgent Memory" USING GIN (memory_search)'
		)
	except Exception:
		frappe.logger("friday.memory").warning(
			"ensure_memory_search_schema failed; scored recall will fall back to recency",
			exc_info=True,
		)


def ensure_memory_embedding_schema() -> None:
	"""Create the pgvector shadow table for semantic memory recall (design 80 step 2b-2).

	A side-channel table ``tabAgent Memory Embedding`` (Frappe's ORM has no
	``vector`` type) holds one embedding per ``Agent Memory`` row, keyed by name
	with ``ON DELETE CASCADE``. The column is sized to the ACTIVE embedding
	backend's dimension (local 384 / minimax 1536). An HNSW cosine index makes
	nearest-neighbour recall fast.

	Dimension-aware: if the table already exists at a DIFFERENT dimension (the
	operator switched backend), it is dropped and recreated — stored vectors are
	lost but re-backfilled, and the memory rows themselves are never touched.

	Postgres-only, idempotent, best-effort: any failure is logged and never breaks
	``bench migrate``. With no vectors stored (e.g. local model not installed),
	recall simply runs the keyword+recency path (step 2a) — no regression.
	"""
	if frappe.db.db_type != "postgres":
		return
	try:
		from frappe.friday_core.llm.embed import embedding_dim

		dim = embedding_dim()
		# pgvector must be present; this is a no-op if the extension is missing
		# (the CREATE TABLE then fails and is caught).
		existing = frappe.db.sql(
			"SELECT a.atttypmod FROM pg_attribute a "
			"WHERE a.attrelid = to_regclass('\"tabAgent Memory Embedding\"') "
			"AND a.attname = 'embedding' AND a.attnum > 0"
		)
		if existing and existing[0][0] not in (None, -1) and int(existing[0][0]) != dim:
			# Backend dimension changed — drop and recreate (vectors re-backfilled).
			frappe.db.sql_ddl('DROP TABLE IF EXISTS "tabAgent Memory Embedding"')

		frappe.db.sql_ddl(
			'CREATE TABLE IF NOT EXISTS "tabAgent Memory Embedding" ('
			"name varchar(140) PRIMARY KEY "
			'REFERENCES "tabAgent Memory"(name) ON DELETE CASCADE, '
			f"embedding vector({dim}), "
			"model varchar(100), "
			"embedded_at timestamp DEFAULT NOW()"
			")"
		)
		frappe.db.sql_ddl(
			'CREATE INDEX IF NOT EXISTS "tabAgent Memory Embedding_hnsw" '
			'ON "tabAgent Memory Embedding" USING hnsw (embedding vector_cosine_ops)'
		)
	except Exception:
		frappe.logger("friday.memory").warning(
			"ensure_memory_embedding_schema failed; semantic recall stays off "
			"(recall falls back to keyword+recency)",
			exc_info=True,
		)


__all__ = [
	"ensure_agent_settings",
	"ensure_memory_search_schema",
	"ensure_memory_embedding_schema",
]
