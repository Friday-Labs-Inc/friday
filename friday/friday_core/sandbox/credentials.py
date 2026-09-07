# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt

"""
Scoped credential management for sandbox execution.

Phase 1 (this module): generate_scoped_token() uses a SHA-256 of profile +
execution_id; the container uses it as a bearer token for the Frappe REST API.
Frappe does not yet verify the token — Phase 1.5 validates it.

Phase 1.5 wiring (per DOC 23 §2 and DOC 24 §7):
- Generate a Frappe API Key + Secret for the agent profile
  via frappe.generate_hash() (stored nowhere; short-lived per-execution)
- Set expiry to the container's wall-clock timeout
- Pass as FRIDAY_API_KEY env var
- Container uses it as Bearer token against /api/method endpoints
- Frappe validates expiry and scope server-side
  before executing any skill

Skill-level credentials (per DOC 23 Table §2):
- For skills requiring external credentials (e.g. SMTP for email),
  read Skill Credential DocType rows linked to the (Agent Profile, Skill)
  combination
- Inject resolved values as prefixed env vars (FRIDAY_CREDS_<name>)
- Never write credentials to disk; container env is the only channel
"""

from __future__ import annotations

import frappe


def generate_scoped_token(agent_profile: str, execution_id: str) -> str:
	"""
	Generate a short-lived, scoped bearer token for one execution.

	Phase 1:    returns SHA-256(profile || execution_id || timestamp || random)
	Phase 1.5:  uses frappe.generate_hash() as a proper revocable secret.
	            Stored in a short-lived DB row with expiry timestamp.
	            Caller stores the row; expired rows are cleaned by janitor.

	Returns a hex string usable as an API key.
	"""
	# Phase 1.5: store a scoped token row with expiry
	# For now: use frappe's hash function as a proper random token
	return frappe.generate_hash(length=32)


def resolve_credentials(agent_profile: str, skill_name: str) -> dict[str, str]:
	"""
	Resolve all credential bindings for a (profile, skill) pair.

	Phase 1: returns {} — no external credentials wired yet.

	Phase 1.5: reads Skill Credential DocType rows:

	    SELECT sc.name, sc.api_key, sc.api_secret, sc.token
	      FROM `tabSkill Credential` sc
	     WHERE sc.agent_profile = %(agent_profile)s
	       AND sc.skill = %(skill_name)s
	       AND sc.enabled = 1

	Returns a dict of env-var names → values injected into the container:
	    FRIDAY_CREDS_<name> = <token value>

	The Skill Credential DocType columns:
	    api_key   : Data (Password) — service API key
	    api_token : Password        — bearer token for the service
	    username  : Data             — for services requiring username auth
	    password  : Password        — kept off disk; injected as FRIDAY_CREDS_password

	If no rows found: returns {}.
	"""
	try:
		rows = frappe.db.sql(
			"""
            SELECT name, api_key, api_token, username
              FROM `tabSkill Credential`
             WHERE agent_profile = %s
               AND skill = %s
               AND enabled = 1
            """,
			(agent_profile, skill_name),
			as_dict=True,
		)
	except Exception:
		# Roll back so the caller's transaction isn't poisoned by a
		# Postgres `InFailedSqlTransaction` for the rest of this request
		# (e.g. when the Skill Credential table is missing on a stale
		# site that hasn't migrated yet). Returning {} treats it as
		# "no credentials configured" — same as a clean empty result.
		try:
			frappe.db.rollback()
		except Exception:
			pass
		return {}

	env: dict[str, str] = {}
	for row in rows:
		cred_name = row["name"]
		# api_token is the primary bearer credential for skills
		token = row.get("api_token")
		if token:
			env[f"FRIDAY_CREDS_{cred_name}"] = token
		# api_key as secondary auth for HTTP-based services
		api_key = row.get("api_key")
		if api_key:
			env[f"FRIDAY_CREDS_{cred_name}_KEY"] = api_key
		# username/password for services that need it
		username = row.get("username")
		if username:
			env[f"FRIDAY_CREDS_{cred_name}_USER"] = username

	return env


def redact_credentials_from_logs(logs: str, credentials: dict[str, str]) -> str:
	"""
	Remove credential values from container logs before writing to Execution Log.

	Phase 1: pass-through (Phase 1 generated tokens are hashed; not leaks).

	Phase 1.5: replace known credential dict values with [REDACTED]
	to prevent accidental credential leakage in audit logs.
	"""
	if not logs or not credentials:
		return logs

	for name, value in credentials.items():
		if value and value not in ("", "[REDACTED]"):
			# Replace the raw value wherever it appears
			logs = logs.replace(value, f"[REDACTED:{name}]")
	return logs


__all__ = [
	"generate_scoped_token",
	"redact_credentials_from_logs",
	"resolve_credentials",
]
