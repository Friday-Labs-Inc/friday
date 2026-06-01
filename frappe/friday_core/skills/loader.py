# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt

"""
The skill loader — what tools can this agent see right now?

PLAIN ENGLISH
=============

Before the LLM running an agent can use any tool, it needs to be
*given* the list of tools — names, descriptions, parameter schemas.
That list is different per agent (a Research Agent and a Support
Agent should not see each other's tools) and different over time (a
suspended skill should silently disappear). This module produces it.

The flow when `load_for_profile("Research Agent")` is called:

  1. **Cache check.** Is the list already in Redis? If yes, return it.
  2. **Otherwise**, read the Agent Profile's `permitted_skills` child
     table — this is the "allow-list" the agent operator set.
  3. **Filter that list** through three checks (cheapest first so we
     fail fast):

       a. `skill.status == "Active"` — skip Draft, Experimental,
          Retired, Archived.
       b. The Slice 2 permission matrix must allow this skill — the
          agent's roles must permit every (DocType, operation) the
          skill declares it needs. We call `permissions.matrix.evaluate`
          here, NOT `permissions.matrix.check`, because:
              - `check` writes one audit-log row per call.
              - Loading the menu would write N rows on every call.
              - The audit-log moment is when the agent actually *uses*
                a skill (handled later by the gateway), not when it
                merely *sees* the menu.

       c. (Future hook for v0.2: per-skill rate limits, time-of-day
          restrictions, etc. Not in v0.1.)

  4. **Build SkillDefinition objects** for the survivors. These are
     the immutable, JSON-safe summaries — same idea as Slice 2's
     `Decision` and `PermissionMatrix`.
  5. **Store in Redis** with a 300-second TTL, return.

THE CACHE
=========

Key shape:    `friday:skills:{profile_name}`
TTL:          300 seconds
Why 300 not 60? Skill lists change much less often than permission
matrices (Skills get promoted/retired rarely; profile-permitted_skills
rarely changes mid-day). The 300s ceiling is still well under
"changed-this-week" granularity, and we eagerly invalidate on the
events that matter, below.

Invalidation hooks wired in `frappe/hooks.py`:

  - **Skill.on_update → invalidate_for_skill** — only flushes the
    profiles that have this skill in their permitted_skills. Cheaper
    than flushing every profile.
  - **Agent Profile.on_update → invalidate_for_profile** — flushes
    just that profile. Triggered when permitted_skills, status, or
    assigned_roles change.
  - **Role.on_update → invalidate_all** — flushes every profile
    because we can't cheaply know which profiles depend on this role,
    and a Role change can flip which skills pass the matrix check.

These hooks are listed alongside Slice 2's hooks on the same
DocTypes — Frappe accepts a list of handlers for one event.

TOOL DEFINITION FORMAT
======================

`to_tool_definition(skill)` returns the OpenAI / Anthropic
"function-calling" tool format:

    {
      "type": "function",
      "function": {
        "name":        skill.skill_name,
        "description": skill.description or skill.when_to_use,
        "parameters":  <parsed JSON schema from skill.parameters_schema>
      }
    }

OpenAI and Anthropic accept the same outer shape; minor field
differences are handled at the provider-adapter layer (Slice 5), not
here. This keeps the loader portable across LLM vendors.

WHAT THIS MODULE DOES NOT DO
============================

- Doesn't execute skills. That's the gateway / agent worker (Slice 4+).
- Doesn't decide whether a *specific* invocation is allowed — that's
  Slice 2's `check()`. The loader filters at *menu build* time;
  `check()` filters at *call* time. Both layers exist on purpose
  (defence in depth — if the menu cache is stale, `check()` still
  catches it before the action runs).
- Doesn't talk to any LLM provider. It just produces the tool list.

REFERENCED DESIGN DOCS
======================
- `docs/design/10-agent-execution-guide.md` §Slice 3 — the spec.
- `docs/design/05-module-design.md` — Skill + Agent Profile schemas.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import frappe

from frappe.friday_core.permissions.matrix import build_matrix, evaluate

# ---------------------------------------------------------------------------
# Cache configuration
# ---------------------------------------------------------------------------

# Every cached skill-list key starts with this prefix. Used both for
# per-profile keys and for the pattern-match flush in `invalidate_all`.
SKILLS_CACHE_KEY_PREFIX = "friday:skills:"

# 300 seconds — five minutes. Skill lists are less volatile than the
# permission matrix (which uses 60s). Eager invalidation hooks below
# keep the worst-case staleness small in practice.
SKILLS_CACHE_TTL_SECONDS = 300


# ---------------------------------------------------------------------------
# Public data types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SkillDefinition:
	"""One row of the agent's "tools available" menu.

	A trimmed, JSON-safe view of the Skill DocType — just the fields the
	LLM (and the cache) need. Mutable Skill rows are not safe to pass
	around or cache directly; this dataclass is the stable form.

	Fields:

	- `name` — the Skill's name (primary key in Frappe). The LLM
	  references this string when calling a tool.
	- `description` — what the skill does, one-liner aimed at humans
	  but read by the LLM during tool selection.
	- `when_to_use` — longer guidance for the LLM on which scenarios
	  this skill is the right answer to. Optional.
	- `parameters_schema` — JSON Schema dict for the skill's
	  parameters. The LLM uses this to generate valid argument JSON.
	- `risk_level` — "low" | "medium" | "high" | "critical". Surfaced
	  in audit and approval flows; the LLM does not read it directly.
	- `requires_approval` — if True, an invocation triggers a Workflow
	  Request before execution (Phase-2 wiring; recorded here so the
	  gateway knows what to do).

	`frozen=True` makes these immutable so we can safely cache them.
	"""

	name: str
	description: str
	when_to_use: str
	parameters_schema: dict
	risk_level: str
	requires_approval: bool

	def to_dict(self) -> dict:
		"""Plain dict for caching and audit snapshots."""
		return {
			"name": self.name,
			"description": self.description,
			"when_to_use": self.when_to_use,
			"parameters_schema": self.parameters_schema,
			"risk_level": self.risk_level,
			"requires_approval": self.requires_approval,
		}

	def __json__(self) -> dict:
		"""Honored by Frappe's response serializer (see Decision.__json__)."""
		return self.to_dict()

	@classmethod
	def from_dict(cls, data: dict) -> SkillDefinition:
		"""Reverse of `to_dict` — used when reading back from the cache."""
		return cls(
			name=data["name"],
			description=data.get("description") or "",
			when_to_use=data.get("when_to_use") or "",
			parameters_schema=data.get("parameters_schema") or {},
			risk_level=data.get("risk_level") or "low",
			requires_approval=bool(data.get("requires_approval", False)),
		)

	@classmethod
	def from_skill_doc(cls, skill) -> SkillDefinition:
		"""Build from a Frappe Skill DocType document.

		`skill.parameters_schema` is stored as a JSON string in the DB
		(the field type is JSON). We parse it here so callers always
		get a dict — if the stored value is empty or malformed, we
		fall back to an empty object schema rather than crashing.
		"""
		return cls(
			name=skill.name,
			description=skill.description or "",
			when_to_use=skill.when_to_use or "",
			parameters_schema=_parse_parameters_schema(skill.parameters_schema),
			risk_level=skill.risk_level or "low",
			requires_approval=bool(skill.requires_approval),
		)


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


def load_for_profile(profile_name: str) -> list[SkillDefinition]:
	"""Return the list of tools the agent currently has access to.

	Cache-aware: a warm cache returns in well under a millisecond.
	A cold cache does one Agent Profile read + N Skill reads + one
	matrix build, then warms.

	The returned list is in the order the agent operator chose in
	`permitted_skills` — preserving that order is intentional, so a
	"primary" tool listed first stays first in the LLM's menu.

	Returns an empty list (never None) for a profile with no
	permitted_skills or all-filtered-out skills.
	"""
	cached = _cache_get(profile_name)
	if cached is not None:
		return cached

	skills = _load_uncached(profile_name)
	_cache_set(profile_name, skills)
	return skills


def to_tool_definition(skill: SkillDefinition | Any) -> dict:
	"""Turn a SkillDefinition (or raw Skill doc) into an LLM tool schema.

	Both inputs accepted because callers in different places hold
	different things — the gateway will hold SkillDefinitions read from
	the loader cache, while admin tools may hold Skill docs directly.
	A single function handles both rather than forcing conversion.

	Returns the OpenAI / Anthropic function-calling tool format. See
	the module docstring for the exact shape.
	"""
	if hasattr(skill, "doctype") and skill.doctype == "Skill":
		# A Frappe Skill document was passed directly.
		name = skill.name
		description = (skill.description or skill.when_to_use or "").strip()
		parameters = _parse_parameters_schema(skill.parameters_schema)
	else:
		# A SkillDefinition (or anything with the same attribute shape).
		name = skill.name
		description = (skill.description or skill.when_to_use or "").strip()
		parameters = skill.parameters_schema or {"type": "object", "properties": {}}

	return {
		"type": "function",
		"function": {
			"name": name,
			"description": description,
			"parameters": parameters,
		},
	}


# ---------------------------------------------------------------------------
# Hook targets — invalidation
# ---------------------------------------------------------------------------


def invalidate_for_profile(doc, method=None) -> None:
	"""Flush one profile's skill cache. Wired to Agent Profile.on_update.

	Triggered whenever the Agent Profile changes — could be a
	permitted_skills edit, a status flip, a role change, anything. We
	don't try to be clever about which change happened; flushing the
	one cache entry is cheap.
	"""
	profile_name = getattr(doc, "name", None) or str(doc)
	frappe.cache().delete_value(_skills_key(profile_name))


def invalidate_for_skill(doc, method=None) -> None:
	"""Flush skill caches for every profile that permits this skill.

	Wired to Skill.on_update. A Skill row change (status, description,
	parameters_schema) can affect any profile that has this skill in
	its permitted_skills. We look up those profiles via the Agent
	Profile Skill child table and flush each one's cache.

	More surgical than flushing every cached profile, and skill edits
	are rare so the extra query is fine.
	"""
	skill_name = getattr(doc, "name", None) or str(doc)
	# Agent Profile Skill is a child table; rows live with the parent
	# Agent Profile name in the `parent` column. We just need the unique
	# set of parent names.
	parent_names = frappe.get_all(
		"Agent Profile Skill",
		filters={"skill": skill_name},
		pluck="parent",
	)
	for profile_name in set(parent_names):
		frappe.cache().delete_value(_skills_key(profile_name))


def invalidate_all(doc=None, method=None) -> None:
	"""Flush every profile's skill cache. Wired to Role.on_update.

	A Role change can flip which skills pass the Slice 2 matrix
	check for any number of profiles, and we don't cheaply know which.
	The broad flush is the safe choice for an event that's rare
	(admin-driven, not hot-path).
	"""
	frappe.cache().delete_keys(SKILLS_CACHE_KEY_PREFIX)


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _load_uncached(profile_name: str) -> list[SkillDefinition]:
	"""The slow path of load_for_profile. Always hits the database."""
	profile = frappe.get_doc("Agent Profile", profile_name)

	# Step 1: the explicit allow-list (preserves the operator's chosen order).
	permitted_skill_names = [row.skill for row in (profile.permitted_skills or []) if row.skill]
	if not permitted_skill_names:
		return []

	# Step 2: cache-aware matrix for the agent (reused for every skill below).
	matrix = build_matrix(profile_name)

	# Step 3: filter skill-by-skill and build SkillDefinitions.
	result: list[SkillDefinition] = []
	for skill_name in permitted_skill_names:
		# A name in permitted_skills that no longer points at a real Skill
		# row (e.g. the skill was deleted) is silently skipped rather than
		# crashing. Logged for visibility.
		if not frappe.db.exists("Skill", skill_name):
			frappe.logger().warning(
				f"friday.skills.loader: profile {profile_name!r} references "
				f"missing skill {skill_name!r} — skipped"
			)
			continue

		skill = frappe.get_doc("Skill", skill_name)

		# Filter 1: status must be Active.
		if skill.status != "Active":
			continue

		# Filter 2: the matrix must allow the skill's required (doctype, op)
		# combinations. We use `evaluate` (pure) not `check` (writes a log
		# row) — see module docstring.
		decision = evaluate(matrix, skill_name)
		if not decision.allowed:
			continue

		result.append(SkillDefinition.from_skill_doc(skill))

	return result


def _skills_key(profile_name: str) -> str:
	"""Build the Redis key for a profile's skill list."""
	return f"{SKILLS_CACHE_KEY_PREFIX}{profile_name}"


def _cache_get(profile_name: str) -> list[SkillDefinition] | None:
	"""Read the skill list from cache. None on miss, also None on corrupt entry."""
	raw = frappe.cache().get_value(_skills_key(profile_name))
	if raw is None:
		return None
	try:
		data = json.loads(raw) if isinstance(raw, str | bytes | bytearray) else raw
		return [SkillDefinition.from_dict(item) for item in data]
	except (json.JSONDecodeError, KeyError, TypeError) as exc:
		# Corrupt entry: drop and treat as miss so the next call rebuilds.
		frappe.logger().warning(
			f"friday.skills.loader: dropping corrupt cache for {profile_name!r}: {exc}"
		)
		frappe.cache().delete_value(_skills_key(profile_name))
		return None


def _cache_set(profile_name: str, skills: list[SkillDefinition]) -> None:
	"""Store the skill list in cache with the standard TTL."""
	payload = json.dumps([s.to_dict() for s in skills])
	frappe.cache().set_value(
		_skills_key(profile_name),
		payload,
		expires_in_sec=SKILLS_CACHE_TTL_SECONDS,
	)


def _parse_parameters_schema(raw) -> dict:
	"""Parse the Skill.parameters_schema field into a dict.

	The DocType field type is JSON, which Frappe stores as a JSON
	string in PostgreSQL. We need a dict at runtime. Handles three
	shapes a caller might hand us:

	- already a dict (Frappe sometimes deserializes automatically)
	- a JSON string ("{}", or a real schema)
	- empty / None / malformed → fall back to an empty object schema
	  so the LLM gets *something* parseable rather than a crash.
	"""
	if isinstance(raw, dict):
		return raw
	if not raw:
		return {"type": "object", "properties": {}}
	try:
		parsed = json.loads(raw)
		return parsed if isinstance(parsed, dict) else {"type": "object", "properties": {}}
	except (json.JSONDecodeError, TypeError):
		return {"type": "object", "properties": {}}
