# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""
The generic governed read tools (design 66a).

Why this exists, in plain English
=================================
Until today every Friday skill was a one-directional verb:
``create-brand-direction`` writes a row, ``remember`` writes a row,
``plan-project`` writes rows. None of them read anything back. So when an
operator asked "what brand directions do we have for BB-0001?", the agent
had no tool to fetch them — and the LLM, faced with a missing capability,
**fabricated three brand new ones** and presented them as if they were
the saved work. This is the Legion incident at L5142 of the validation
transcript, and it is the worst possible failure mode for a governance
framework: silent hallucination at the agent's mouth.

The Friday-beats-Hermes insight that fixes this in one move
============================================================
Hermes has to hand-write a read tool per record type. Friday sits on
Frappe — a permissioned database — so **one generic ``read-record`` tool,
scoped by the agent's permissions and audited like every write, gives an
agent read access to every DocType it can already write to**. No per-type
read skill needed. Brand Direction, Task, Project, Issue, Brand Brief —
all readable through the same tool, all gated by the same Frappe
permission machinery the rest of the framework already trusts.

Governance contract
===================
1. Every read calls ``frappe.has_permission(doctype, "read", doc=name)``
   for the AGENT'S User (one-user-per-agent per doc 23). A denial does
   not raise into the agent's turn (the ReAct loop would just retry); it
   returns a structured error the model observes and reports honestly.
2. Password fields (Frappe's encrypted secret type) are stripped from
   the response so the read tool cannot leak credentials it can
   technically "see."
3. Permission-denied and not-found collapse to one error
   (``not_found_or_unreadable``) so the agent cannot probe forbidden
   existence by reading.

The fail-loud system-prompt frame in ``prompt_builder._build_system_prompt``
makes the contract teeth-bearing: the agent is instructed to SAY when it
cannot fetch something, not to invent.
"""

from __future__ import annotations

import frappe
from frappe.friday_core.agent_runner.dispatcher import register_skill_handler

READ_RECORD = "read-record"
LIST_RECORDS = "list-records"

# Cap to keep an over-eager agent from pulling tens of thousands of rows in
# one turn. 100 is enough for human-scale review; pagination is a follow-up.
MAX_LIST_ROWS = 100

# Frappe field types we strip from any read response. Password is the obvious
# one (encrypted secrets); Code can carry raw queries/scripts (skill content,
# print formats); leaving them out keeps the read tool safely non-leaky.
_SCRUBBED_FIELD_TYPES = {"Password", "Code"}

# House-keeping fields Frappe puts on every row that aren't part of the
# DocType's declared schema. We let them through (they're stable, public,
# and useful: an agent often needs the creation/modified time).
_HOUSEKEEPING = {
	"name",
	"creation",
	"modified",
	"owner",
	"modified_by",
	"docstatus",
	"idx",
}


def _calling_profile() -> str:
	ctx = frappe.flags.get("friday_dispatch_context") or {}
	return (ctx.get("agent_profile") or "").strip()


def read_record(skill_name: str, parameters: dict) -> dict:
	"""
	Return one DocType row by name, permission-gated, with sensitive fields
	stripped. Never raises a denial into the ReAct loop — the agent sees a
	structured ``error`` field instead.
	"""
	doctype = (parameters.get("doctype") or "").strip()
	name = (parameters.get("name") or "").strip()
	if not doctype:
		raise ValueError("read-record requires a 'doctype' parameter (e.g. 'Brand Direction')")
	if not name:
		raise ValueError("read-record requires a 'name' parameter (the record's ID)")

	profile = _calling_profile()
	if not profile:
		raise ValueError("read-record could not determine the calling agent profile")

	# Unknown DocType: surface as a discrete error so the agent reports it
	# honestly ("I don't have access to that record type") rather than
	# inventing one.
	try:
		meta = frappe.get_meta(doctype)
	except Exception:
		return {"error": "unknown_doctype", "doctype": doctype}

	# Not-found and permission-denied collapse to the same error shape so
	# an agent cannot probe forbidden existence by reading.
	if not frappe.db.exists(doctype, name):
		return {"error": "not_found_or_unreadable", "doctype": doctype, "name": name}
	if not frappe.has_permission(doctype, "read", doc=name):
		return {"error": "not_found_or_unreadable", "doctype": doctype, "name": name}

	doc = frappe.get_doc(doctype, name)
	full = doc.as_dict()
	scrubbed_field_names = {f.fieldname for f in (meta.fields or []) if f.fieldtype in _SCRUBBED_FIELD_TYPES}
	# Allowed = housekeeping + declared non-scrubbed fields.
	allowed = _HOUSEKEEPING | {
		f.fieldname for f in (meta.fields or []) if f.fieldtype not in _SCRUBBED_FIELD_TYPES
	}
	record = {k: v for k, v in full.items() if k in allowed}

	return {
		"doctype": doctype,
		"name": name,
		"record": record,
		"scrubbed_fields": sorted(scrubbed_field_names),
	}


def list_records(skill_name: str, parameters: dict) -> dict:
	"""
	List rows of a DocType the agent has read access to.

	Filters are passed straight through to ``frappe.db.get_all`` — same
	dict-of-conditions API the Desk uses. The result is capped at
	``MAX_LIST_ROWS``; denial returns ``rows=[]`` with the ``denied`` flag
	rather than raising (the ReAct loop should observe and report, not
	retry blindly).
	"""
	doctype = (parameters.get("doctype") or "").strip()
	if not doctype:
		raise ValueError("list-records requires a 'doctype' parameter (e.g. 'Brand Direction')")

	profile = _calling_profile()
	if not profile:
		raise ValueError("list-records could not determine the calling agent profile")

	if not frappe.has_permission(doctype, "read"):
		return {"doctype": doctype, "rows": [], "denied": True}

	filters = parameters.get("filters") or {}
	limit = int(parameters.get("limit") or MAX_LIST_ROWS)
	limit = max(1, min(MAX_LIST_ROWS, limit))

	try:
		meta = frappe.get_meta(doctype)
	except Exception:
		return {"error": "unknown_doctype", "doctype": doctype}

	# Project the agent only the safe-to-show fields by name. Frappe's
	# ``fields=['*']`` would include Password fields verbatim; we choose
	# explicit names to keep the scrub honest.
	field_names = ["name"]
	for f in meta.fields or []:
		if f.fieldtype in _SCRUBBED_FIELD_TYPES:
			continue
		if f.fieldname:
			field_names.append(f.fieldname)

	rows = frappe.db.get_all(
		doctype,
		filters=filters,
		fields=field_names,
		limit_page_length=limit,
		order_by="modified desc",
	)
	return {"doctype": doctype, "filters": filters, "rows": rows, "row_count": len(rows)}


register_skill_handler(READ_RECORD, read_record)
register_skill_handler(LIST_RECORDS, list_records)
