# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt

"""
The permission engine — does this agent have permission to use this skill?

PLAIN ENGLISH
=============

Friday lets AI agents do real work inside a business (create records,
send emails, run queries). Before any of that work runs, we have to
answer one question:

    "Is this agent allowed to call this skill?"

This file answers that question. Three steps:

  1. **Look up the agent** — read the Agent Profile DocType, see which
     Frappe roles it has (a "role" is just a named bundle of permissions,
     like 'Note Writer' or 'Knowledge User'; same idea as a job role).
  2. **Add up what those roles can do** — every role has rows in
     Frappe's DocPerm table that say "this role can read/write/create/
     delete this DocType". We collect all of those into one big map
     called the "permission matrix": `{doctype: {operations the agent
     can do on it}}`.
  3. **Compare with what the skill needs** — every Skill DocType lists
     `required_doctypes` (rows like "I need to *read* the Note doctype"
     and "I need to *create* the ToDo doctype"). If every required
     (doctype, operation) is in the matrix → ALLOW. If even one is
     missing → DENY, with a reason that names what's missing.

We also reject in two more cases, before looking at the matrix at all:

  - The Agent Profile is not "Active" (e.g. Suspended, Retired). A
    paused worker doesn't get to act, even if their permissions would
    have allowed it.
  - The Skill is not "Active" (Draft, Experimental, Retired, Archived).
    Skills that haven't been promoted to Active are not safe to run in
    production, regardless of who's asking.

PUBLIC FUNCTIONS (what other code calls)
========================================

- `build_matrix(profile_name)` — get the permission matrix for an agent,
  using the Redis cache when warm. Use this if you want to inspect what
  an agent can do without actually checking a specific skill.

- `evaluate(matrix, skill_name)` — pure decision logic. Given a matrix
  and a skill, return `Decision(allowed, reason)`. No side effects, no
  database writes. This is what tests aim at for branch coverage.

- `check(profile_name, skill_name)` — the **gateway entry point**. The
  agent execution loop calls this just before queueing any skill work.
  It builds the matrix (cache-aware), evaluates it, and writes an
  immutable Permission Decision Log row with the outcome. Returns the
  same `Decision` object `evaluate` does.

NON-OBVIOUS DECISIONS
=====================

- **Why two functions, `check` and `evaluate`?** Because the design doc
  says the deliverable command is `check(profile, skill)` (two strings),
  but also lists the internal signature as `check(matrix, skill)`. Those
  are different functions doing different jobs, so we gave them
  different names: `evaluate` is the pure version (no I/O — easy to test),
  `check` is the orchestrator (builds matrix + logs decision — the
  one real callers use).

- **Why is the matrix cached at all?** The check has to run *before* every
  skill invocation. If even one agent makes 100 calls per minute and each
  build_matrix hits the database 3 times, that's 300 round-trips/min of
  pure permission overhead. Caching the matrix for 60 seconds drops that
  to ~1 round-trip/min/agent.

- **Why 60 seconds and not longer?** Two reasons. (1) Permission changes
  must take effect quickly — a manager suspends an agent at 12:00:00,
  they should not be running at 12:01:00. (2) We also invalidate on
  Agent Profile and Role updates, so 60s is the worst case, not the
  norm.

- **Why is `ignore_permissions=True` used when writing the log?** Because
  the system is recording its own audit trail. This is not a user-driven
  write that should be permission-checked — denying the log write would
  hide the very thing it's trying to record.

REFERENCED DESIGN DOCS
======================
- `docs/design/04-security-model.md` §Layer 2 (Gateway pre-check) — the
  intent, why this matters.
- `docs/design/10-agent-execution-guide.md` §Slice 2 — the spec, what
  functions and tests must exist.
- `docs/design/05-module-design.md` — the DocType fields this code reads.
"""

from __future__ import annotations

from dataclasses import dataclass

import frappe

# ---------------------------------------------------------------------------
# Operation mapping.
#
# Skill Required DocType.operation is one of these six string values.
# Frappe's DocPerm row stores them as boolean columns with the same names.
# So "read" → check the `read` column on the DocPerm row, "write" → the
# `write` column, and so on. The dict is mostly here so future readers can
# see the mapping in one place if Frappe ever adds a new operation.
# ---------------------------------------------------------------------------
_OP_TO_PERM_FIELD = {
	"read": "read",
	"write": "write",
	"create": "create",
	"submit": "submit",
	"cancel": "cancel",
	"delete": "delete",
}


@dataclass(frozen=True)
class Decision:
	"""The result of a permission check.

	`allowed` is a yes/no. `reason` is a short human-readable string that
	either says "Allowed" or explains exactly what was missing — e.g.
	"Profile lacks 'write' on 'Note' (roles=['Note Writer'])".

	`reason` is meant to be read by humans (in audit logs, in War Room
	UIs), not parsed by code. If you need machine-readable detail later,
	add structured fields here instead of regex-parsing the string.

	`frozen=True` means once a Decision is created, you can't change its
	fields. This makes Decisions safe to share across threads and to
	cache without worrying about someone mutating them.
	"""

	allowed: bool
	reason: str

	def to_dict(self) -> dict:
		"""Plain dict form, for JSON snapshots and tests."""
		return {"allowed": self.allowed, "reason": self.reason}

	def __json__(self) -> dict:
		"""Frappe's response serializer looks for this method.

		Without it, `bench execute …matrix.check …` blows up trying to
		JSON-encode a dataclass. With it, the CLI prints
		`{"allowed": true, "reason": "Allowed"}` cleanly.
		"""
		return self.to_dict()


@dataclass(frozen=True)
class PermissionMatrix:
	"""The 'what can this agent do' snapshot.

	Fields:

	- `profile_name` — the Agent Profile DocType's name (its primary key
	  in Frappe). E.g. "Research Agent 01".
	- `profile_status` — "Active" | "Suspended" | "Retired". A
	  non-Active profile can never run anything, period.
	- `roles` — tuple of Frappe role names assigned to this agent (e.g.
	  `("Knowledge User", "Note Writer")`). Sorted for deterministic
	  snapshots.
	- `permitted_ops` — the precomputed answer to "what DocType
	  operations can this agent do?", as `{doctype_name: frozenset of
	  operation names}`. Example::

	      {
	          "Note":          frozenset({"read", "write", "create"}),
	          "ToDo":          frozenset({"read"}),
	          "Contact": frozenset(),  # explicitly nothing
	      }

	The matrix is the **expensive thing** to compute (joins across
	DocPerm + Custom DocPerm for every assigned role). The cache stores
	exactly this object.

	`frozen=True` keeps it immutable so caching is safe. `frozenset`
	rather than `set` so the inner collections are also immutable and
	hashable.
	"""

	profile_name: str
	profile_status: str
	roles: tuple[str, ...]
	permitted_ops: dict[str, frozenset[str]]

	def ops_for(self, doctype: str) -> frozenset[str]:
		"""Operations this matrix allows on the given DocType.

		Returns an empty frozenset (not None, not KeyError) if the agent
		has no permissions for that DocType — that's the common case for
		"deny" decisions, so we want callers to be able to write
		`if op not in matrix.ops_for(dt):` without worrying about None.
		"""
		return self.permitted_ops.get(doctype, frozenset())

	def to_dict(self) -> dict:
		"""Plain dict form for caching and audit snapshots.

		Sorts the operation lists so the JSON output is deterministic —
		two matrices with the same content always serialize identically,
		which makes cache hits work and tests easier to write.
		"""
		return {
			"profile_name": self.profile_name,
			"profile_status": self.profile_status,
			"roles": list(self.roles),
			"permitted_ops": {dt: sorted(ops) for dt, ops in self.permitted_ops.items()},
		}

	def __json__(self) -> dict:
		"""Honored by Frappe's response serializer (see Decision.__json__)."""
		return self.to_dict()

	@classmethod
	def from_dict(cls, data: dict) -> PermissionMatrix:
		"""Reverse of `to_dict`. Used when reading back from the cache."""
		return cls(
			profile_name=data["profile_name"],
			profile_status=data["profile_status"],
			roles=tuple(data["roles"]),
			permitted_ops={dt: frozenset(ops) for dt, ops in data["permitted_ops"].items()},
		)


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


def build_matrix(profile_name: str) -> PermissionMatrix:
	"""Return the PermissionMatrix for an Agent Profile, using the cache.

	Flow:

	  1. Ask the Redis cache "do we already have this matrix?" → if yes,
	     return it. This is the hot path; >99% of calls hit cache.
	  2. If no, load the profile + roles + DocPerms from PostgreSQL,
	     build the matrix, store it in the cache (60s TTL), return it.

	The cache is automatically invalidated when the Agent Profile or any
	Role is updated (see `cache.py` and the `doc_events` wiring in
	`frappe/hooks.py`), so 60 seconds is the worst-case staleness.

	Raises `frappe.DoesNotExistError` if `profile_name` doesn't exist —
	we deliberately don't swallow that; an unknown profile is a bug, not
	a "deny silently" case.
	"""
	# Lazy import to break the circular dependency between matrix.py and
	# cache.py (cache imports PermissionMatrix; matrix needs the cache
	# functions). Importing inside the function defers the resolution
	# until both modules are fully loaded.
	from frappe.friday_core.permissions import cache

	cached = cache.get(profile_name)
	if cached is not None:
		return cached

	matrix = _build_matrix_uncached(profile_name)
	cache.set(profile_name, matrix)
	return matrix


def evaluate(matrix: PermissionMatrix, skill_name: str) -> Decision:
	"""Pure permission decision — no cache writes, no log writes.

	Order of checks matters: cheapest first so we fail fast.

	  1. Profile status must be "Active". (Field read on already-loaded
	     matrix — zero I/O.)
	  2. Skill status must be "Active". (One DocType load.)
	  3. Every (target_doctype, operation) listed in
	     skill.required_doctypes must be present in the matrix's
	     permitted_ops. The first miss short-circuits with a reason that
	     names what's missing.

	If we reach the end → ALLOW.

	Why is this function separate from `check`? Because `check` writes
	an audit log row, which is the wrong thing to do inside unit tests.
	Tests call `evaluate` directly on a matrix they constructed
	in-memory and assert on the Decision. The real production caller
	uses `check`.
	"""
	if matrix.profile_status != "Active":
		return Decision(False, f"Agent Profile is {matrix.profile_status!r}, not Active")

	skill = frappe.get_doc("Skill", skill_name)
	if skill.status != "Active":
		return Decision(False, f"Skill is {skill.status!r}, not Active")

	for req in skill.required_doctypes or []:
		op = req.operation
		permitted = matrix.ops_for(req.target_doctype)
		if op not in permitted:
			return Decision(
				False,
				f"Profile lacks {op!r} on {req.target_doctype!r} (roles={list(matrix.roles)})",
			)

	return Decision(True, "Allowed")


def check(profile_name: str, skill_name: str) -> Decision:
	"""The gateway pre-check — builds matrix, evaluates, logs.

	This is the function the agent execution loop will call *before*
	queueing any skill invocation. It is the single chokepoint that
	produces an immutable Permission Decision Log row for every
	permission decision in the system — every allow and every deny.

	Why log every decision (including allows)? Audit. A regulator asking
	"did Agent X have permission to do Y on date Z" needs to see "yes
	because of role A" as much as they need to see "no because of B".
	The log row also includes a snapshot of the matrix that was used,
	so the decision is reproducible even after roles or skills change
	later.

	Deliverable command:

	    bench --site friday.localhost execute \\
	        frappe.friday_core.permissions.matrix.check \\
	        --args "['FRIDAY-TEST-PROFILE-A', 'friday-test-skill-active']"

	Returns the same `Decision` `evaluate` returns. The audit log
	persistence is a side effect — callers should not need to think
	about it.
	"""
	# Lazy import — see the note in `build_matrix` for why.
	from frappe.friday_core.permissions import decisions

	matrix = build_matrix(profile_name)
	decision = evaluate(matrix, skill_name)
	decisions.record(profile_name, skill_name, decision, matrix)
	return decision


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _build_matrix_uncached(profile_name: str) -> PermissionMatrix:
	"""The slow path of `build_matrix`. Always hits the database."""
	profile = frappe.get_doc("Agent Profile", profile_name)

	# `assigned_roles` is a child table on Agent Profile; each row has a
	# `role` field. We dedupe (via set) and sort so the tuple is
	# deterministic — which makes cached snapshots stable and tests
	# easier to write.
	roles = tuple(sorted({row.role for row in (profile.assigned_roles or []) if row.role}))

	return PermissionMatrix(
		profile_name=profile.name,
		profile_status=profile.status,
		roles=roles,
		permitted_ops=_resolve_permitted_ops(roles),
	)


def _resolve_permitted_ops(roles: tuple[str, ...]) -> dict[str, frozenset[str]]:
	"""For a set of roles, return {doctype: {operations}} they can do.

	We read from BOTH `DocPerm` (the standard, built-in permissions
	defined in DocType JSON) AND `Custom DocPerm` (overrides the admin
	added at runtime via the Role Permissions Manager). Frappe layers
	these the same way at runtime, so our matrix should too.

	The query is `WHERE role IN (...)` rather than one query per role,
	because a profile with 5 roles would otherwise do 10 round-trips
	instead of 2.
	"""
	if not roles:
		# Short-circuit: an agent with no roles has no permissions, full
		# stop. Skipping the queries saves two DB round-trips per build.
		return {}

	per_doctype: dict[str, set[str]] = {}
	for table in ("DocPerm", "Custom DocPerm"):
		rows = frappe.get_all(
			table,
			filters={"role": ("in", roles)},
			# `parent` on a DocPerm row is the DocType the permission
			# applies to. The other six fields are the booleans for each
			# operation.
			fields=["parent", *_OP_TO_PERM_FIELD.values()],
		)
		for row in rows:
			doctype = row["parent"]
			ops = per_doctype.setdefault(doctype, set())
			for op_name, perm_field in _OP_TO_PERM_FIELD.items():
				if row.get(perm_field):
					ops.add(op_name)

	# Convert inner sets to frozensets so PermissionMatrix can stay
	# immutable.
	return {dt: frozenset(ops) for dt, ops in per_doctype.items()}
