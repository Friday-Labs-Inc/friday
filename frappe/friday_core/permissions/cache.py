# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt

"""
The Redis cache for permission matrices — making the check fast.

PLAIN ENGLISH
=============

`matrix.py` answers the question "what can this agent do?" by reading
several DocTypes from PostgreSQL and joining them. That's accurate but
slow — too slow to run before *every* skill invocation when an agent
might do hundreds per minute.

So we cache the result. The flow is:

  1. `build_matrix(profile)` checks "do I have this in Redis?"
  2. If yes (a "cache hit"), we return that and skip the database.
  3. If no (a "cache miss"), we do the slow build, then store the
     result in Redis with a 60-second timer.

After 60 seconds the entry expires and the next call rebuilds. We also
expire it earlier when things change — see "Invalidation" below.

WHY REDIS
=========

Frappe already ships with Redis for its own caching. `frappe.cache()`
returns a wrapper around the same Redis instance, so we get a tested,
shared cache without standing up new infrastructure. Same Redis, just
keys prefixed `friday:perm_matrix:` so we don't collide with anything.

KEY SHAPE
=========

    friday:perm_matrix:{profile_name}

One key per Agent Profile. So invalidating a single profile is a single
DELETE, and invalidating everything is one `DELETE WHERE key LIKE
'friday:perm_matrix:*'` (Frappe's `delete_keys` does that pattern match
for us).

INVALIDATION
============

The cache TTL is 60 seconds, but we also flush eagerly when something
that could change permissions actually changes. Two hooks wired in
`frappe/hooks.py`:

  - **Agent Profile.on_update → `invalidate_for_profile`** — when a
    specific profile is edited (role added, status changed, etc.), drop
    only that profile's cached matrix. Other profiles keep their hot
    cache entries.

  - **Role.on_update → `invalidate_all`** — when a Role itself changes
    (e.g. an admin uses Role Permissions Manager to give the role a
    new DocType permission), we don't know which profiles are
    affected, so we drop every `friday:perm_matrix:*` key. Heavier,
    but Role updates are rare in normal operation.

WHY TWO INVALIDATION FUNCTIONS, NOT ONE
=======================================

Frappe's `doc_events` hooks call your function with the doc that
changed plus the method name. The Agent Profile hook gets an Agent
Profile doc (so we know which profile to flush). The Role hook gets a
Role doc (which doesn't tell us which profiles have that role without
another query). The simplest correct answer for Role updates is "flush
everything" — so we have two functions with different scopes.

WHAT THIS MODULE DOES NOT DO
============================

- Doesn't write to or read from PostgreSQL. Pure Redis.
- Doesn't make permission decisions. That's `matrix.evaluate` /
  `matrix.check`.
- Doesn't write audit logs. That's `decisions.record`.

Single responsibility on purpose: makes testing easy and means a Redis
outage degrades to "permission checks get slower" rather than "wrong
decisions get cached".
"""

from __future__ import annotations

import json

import frappe
from frappe.friday_core.permissions.matrix import PermissionMatrix

# Every cache key starts with this prefix. Used both for naming individual
# keys AND for the `delete_keys` pattern-match flush in `invalidate_all`.
CACHE_KEY_PREFIX = "friday:perm_matrix:"

# 60 seconds — matches docs/design/04-security-model.md §Layer 2 which
# states "<10ms with Redis cache". 60s is the worst-case staleness; in
# practice the eager invalidation hooks below mean stale data rarely
# survives more than a single request.
CACHE_TTL_SECONDS = 60


def _key(profile_name: str) -> str:
	"""Build the Redis key for a profile.

	Trivial, but kept as a function so the key shape is defined in
	exactly one place. If we ever need to namespace per site or per
	environment, this is the only line that changes.
	"""
	return f"{CACHE_KEY_PREFIX}{profile_name}"


def get(profile_name: str) -> PermissionMatrix | None:
	"""Read a matrix from the cache. `None` means "not cached" (a miss).

	If the stored value is corrupted somehow (Redis ate a byte, manual
	editing, JSON format drift after a deploy), we log a warning, drop
	the bad entry, and return None. The caller will then do a fresh
	build and store a clean value — self-healing.

	We don't crash on corrupt cache entries because that would block
	every agent action until somebody manually flushed Redis. Returning
	None is safe: the worst that happens is one extra DB round-trip.
	"""
	raw = frappe.cache().get_value(_key(profile_name))
	if raw is None:
		return None
	try:
		# `frappe.cache().get_value` may return the value already
		# deserialized by Frappe's caching layer, or a raw string/bytes.
		# Handle both shapes — saves us from depending on internal
		# Frappe behavior that could change.
		data = json.loads(raw) if isinstance(raw, str | bytes | bytearray) else raw
		return PermissionMatrix.from_dict(data)
	except (json.JSONDecodeError, KeyError, TypeError) as exc:
		frappe.logger().warning(
			f"friday.permissions.cache: dropping corrupt entry for {profile_name!r}: {exc}"
		)
		frappe.cache().delete_value(_key(profile_name))
		return None


def set(profile_name: str, matrix: PermissionMatrix) -> None:
	"""Store a matrix in the cache with the standard TTL.

	We serialize with the matrix's own `to_dict()` (which sorts the
	operation lists so the JSON is deterministic). Deterministic
	serialization makes it easy to spot when a cached entry is "the
	same" as a freshly built one in tests.
	"""
	frappe.cache().set_value(
		_key(profile_name),
		json.dumps(matrix.to_dict()),
		expires_in_sec=CACHE_TTL_SECONDS,
	)


def invalidate_for_profile(doc, method=None) -> None:
	"""Drop one profile's cached matrix. Hook target for Agent Profile.on_update.

	Frappe's `doc_events` system calls every hook with two arguments:
	the document that changed (`doc`) and the method name that triggered
	it (`method`, e.g. "on_update"). We only need `doc`, but `method`
	must still be in the signature or Frappe's call would fail.

	Why `getattr(doc, "name", None) or str(doc)`? Almost always `doc` is
	a Frappe Document object with `.name` — that's the Agent Profile's
	primary key. We tolerate being called with a bare string (useful
	for ad-hoc invalidation from tests or shell) by falling through to
	`str(doc)`.
	"""
	profile_name = getattr(doc, "name", None) or str(doc)
	frappe.cache().delete_value(_key(profile_name))


def invalidate_all(doc=None, method=None) -> None:
	"""Drop every profile's cached matrix. Hook target for Role.on_update.

	A Role change can affect any profile that has that role. We don't
	track that mapping, so the conservative-correct move is to flush
	all permission caches. Role updates are rare (admin actions, not
	hot-path), so the rebuild cost is acceptable.

	`doc` and `method` are accepted because Frappe will pass them when
	called as a hook; both can be None when called directly.
	"""
	frappe.cache().delete_keys(CACHE_KEY_PREFIX)
