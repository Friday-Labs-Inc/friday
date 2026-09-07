# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""
Agent identity — give every Agent Profile a backing Frappe User (design 65a, Q4).

Why
===
Until now an agent was a *string*: ``Task.assigned_to_profile`` and a War Room
message like ``🤖 Copywriter``. You couldn't assign a task to it the Frappe way,
@-mention it in a comment, give it an avatar, or show it as a resource lane in a
Gantt chart. The user's complaint — *"only one agent in the War Room, what about
the others?"* — is, underneath, an identity problem: the other agents have no
first-class presence in Desk.

This module provisions one **system Frappe User per Agent Profile** so each
agent becomes a real, assignable, mentionable, avatar-bearing actor. The
``Agent Profile.frappe_user`` link (added in the same PR) ties the two together;
the 66a/66b skill bootstraps already read ``profile.get("frappe_user")`` and were
written expecting exactly this field.

The governing invariant: **these users cannot log in.**
========================================================
- No password is ever set (``new_password`` is never passed), so Frappe's
  password auth rejects them.
- No API key / secret is issued.
- ``send_welcome_email = 0`` so no e-mail ever invites them to set a password,
  and the address lives on the non-routable ``@friday.local`` domain anyway.

They are ``enabled = 1`` System Users purely so Frappe lets you *assign* and
*mention* them. On a single-tenant, first-party-trusted site
(``feedback_v01-skills-first-party-trust``) the CRITICAL bar is "no credential
path exists" — which holds — and the robustness of the provisioner is HIGH.

Idempotent + fail-loud-but-isolated
====================================
``provision_agent_user`` is safe to re-run (it never duplicates a user).
``provision_all_agent_users`` (the ``after_migrate`` entry) backfills every
profile; a single bad profile is logged loudly and skipped so it can never abort
the whole backfill. The ``after_insert`` hook provisions newly created profiles
and never raises — a provisioning hiccup must not block profile creation.
"""

from __future__ import annotations

import re

import frappe

# Non-routable domain: mail to these addresses goes nowhere, reinforcing the
# "no credential path" invariant (a welcome/reset mail can't be delivered).
AGENT_EMAIL_DOMAIN = "friday.local"


def _slug(profile_name: str) -> str:
	"""Lowercase, collapse any run of non-alphanumerics to a single hyphen.

	``"Brand  Copywriter! (v2)"`` -> ``"brand-copywriter-v2"``. Keeps the email
	local-part clean and deterministic so re-provisioning resolves the same user.
	"""
	return re.sub(r"[^a-z0-9]+", "-", (profile_name or "").lower()).strip("-")


def agent_email(profile_name: str) -> str:
	"""The deterministic system-user email for a profile (e.g. ``agent+copywriter@friday.local``)."""
	return f"agent+{_slug(profile_name)}@{AGENT_EMAIL_DOMAIN}"


def provision_agent_user(profile) -> str | None:
	"""Create (or ensure) the no-login system User backing one Agent Profile.

	Args:
		profile: an ``Agent Profile`` document (or doc-like with ``name`` /
			``profile_name`` / ``assigned_roles``).

	Returns:
		The user's email, or ``None`` if the profile name was empty (nothing to do).
	"""
	profile_name = profile.get("profile_name") or profile.get("name")
	if not _slug(profile_name):
		# An unnamed profile has no stable identity to mint — refuse rather than
		# create ``agent+@friday.local``.
		return None

	email = agent_email(profile_name)
	roles = [r.get("role") for r in (profile.get("assigned_roles") or []) if r.get("role")]

	if frappe.db.exists("User", email):
		# Already provisioned — only reconcile the role set (cheap, idempotent).
		_sync_roles(email, roles)
	else:
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": profile_name,
				"full_name": profile_name,
				"enabled": 1,
				"user_type": "System User",
				# CANNOT LOG IN: no new_password, no welcome mail to set one.
				"send_welcome_email": 0,
				"roles": [{"role": r} for r in roles],
			}
		)
		user.insert(ignore_permissions=True)

	# Link the user back onto the profile WITHOUT saving the profile (this runs
	# from after_insert / on_update; a save() here would re-fire those hooks).
	frappe.db.set_value("Agent Profile", profile.get("name"), "frappe_user", email, update_modified=False)
	return email


def _sync_roles(email: str, roles: list[str]) -> None:
	"""Add any profile roles the existing user is missing (never removes)."""
	user = frappe.get_doc("User", email)
	have = {r.get("role") for r in (user.get("roles") or [])}
	added = False
	for role in roles:
		if role and role not in have:
			user.append("roles", {"role": role})
			added = True
	if added:
		user.save(ignore_permissions=True)


def provision_all_agent_users() -> dict:
	"""Backfill a system User for every Agent Profile. The ``after_migrate`` entry.

	Idempotent and failure-isolated: one profile that errors is logged loudly
	(``frappe.log_error``) and recorded in the returned ``failed`` list, never
	aborting the rest of the backfill.
	"""
	provisioned = 0
	failed: list[str] = []

	for row in frappe.get_all("Agent Profile", pluck="name"):
		# ``pluck`` returns names; get_all may instead return dicts under mocks,
		# so normalise.
		name = row if isinstance(row, str) else row.get("name")
		try:
			profile = frappe.get_doc("Agent Profile", name)
			if provision_agent_user(profile):
				provisioned += 1
		except Exception:
			frappe.log_error(
				title=f"agent_identity: failed to provision user for {name!r}",
				message=frappe.get_traceback(),
			)
			failed.append(name)

	frappe.db.commit()  # nosemgrep: frappe-semgrep-rules.rules.frappe-manual-commit
	return {"provisioned": provisioned, "failed": failed}


def on_agent_profile_after_insert(doc, method=None) -> None:
	"""``doc_events['Agent Profile']['after_insert']`` — provision the new agent's User.

	Never raises: a provisioning failure is logged but must not roll back the
	profile the operator just created.
	"""
	try:
		provision_agent_user(doc)
	except Exception:
		frappe.log_error(
			title=f"agent_identity: after_insert provisioning failed for {doc.get('name')!r}",
			message=frappe.get_traceback(),
		)
