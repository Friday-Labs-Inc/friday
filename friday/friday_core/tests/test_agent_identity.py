# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""
Unit tests for agent-User provisioning (design 65a, Q4).

Every Agent Profile gets a backing Frappe User so an agent is a first-class,
assignable, @-mentionable, avatar-bearing actor in Desk — not a string. The
governing invariant: these users **cannot log in** (no password is ever set,
no API credentials issued, the email domain is non-routable). The provisioner
is idempotent (re-running never duplicates) and fail-loud-but-isolated (one bad
profile is logged and skipped, never aborting the whole backfill).

These are pure unit tests with ``frappe`` mocked — same style as
``test_health_after_migrate``.
"""

import unittest
from unittest.mock import MagicMock, patch


class _FakeDoc(dict):
	"""A dict that also supports attribute access + an .append() child-table op."""

	def __getattr__(self, k):
		try:
			return self[k]
		except KeyError as e:
			raise AttributeError(k) from e

	def __setattr__(self, k, v):
		self[k] = v

	def append(self, field, row):
		self.setdefault(field, []).append(row)
		return row

	def insert(self, *a, **kw):
		self["_inserted"] = True
		return self

	def save(self, *a, **kw):
		self["_saved"] = True
		return self


class TestProvisionAgentUser(unittest.TestCase):
	"""``provision_agent_user`` creates one no-login system User per profile."""

	def _profile(self, name="Copywriter", roles=None):
		return _FakeDoc(
			{
				"name": name,
				"profile_name": name,
				"frappe_user": None,
				"assigned_roles": [_FakeDoc({"role": r}) for r in (roles or [])],
			}
		)

	@patch("friday.friday_core.identity.agent_identity.frappe")
	def test_creates_user_with_expected_identity(self, mock_frappe):
		from friday.friday_core.identity.agent_identity import provision_agent_user

		created = {}

		def _get_doc(spec):
			doc = _FakeDoc(spec)
			# capture the User doc the provisioner builds
			if spec.get("doctype") == "User":
				created.update(spec)
			return doc

		mock_frappe.db.exists.return_value = False  # no user yet
		mock_frappe.get_doc.side_effect = _get_doc
		mock_frappe.get_value.return_value = None

		profile = self._profile("Copywriter")
		mock_frappe.get_doc.side_effect = lambda spec: _get_doc(spec)

		email = provision_agent_user(profile)

		self.assertEqual(email, "agent+copywriter@friday.local")
		self.assertEqual(created.get("email"), "agent+copywriter@friday.local")
		self.assertEqual(created.get("first_name"), "Copywriter")
		self.assertEqual(created.get("enabled"), 1)
		self.assertEqual(created.get("user_type"), "System User")
		# CANNOT LOG IN: no password is ever set, no welcome mail invites one.
		self.assertNotIn("new_password", created)
		self.assertEqual(created.get("send_welcome_email"), 0)

	@patch("friday.friday_core.identity.agent_identity.frappe")
	def test_links_user_back_to_profile(self, mock_frappe):
		from friday.friday_core.identity.agent_identity import provision_agent_user

		mock_frappe.db.exists.return_value = False
		mock_frappe.get_doc.side_effect = lambda spec: _FakeDoc(spec)

		profile = self._profile("Designer")
		provision_agent_user(profile)

		mock_frappe.db.set_value.assert_called_once_with(
			"Agent Profile", "Designer", "frappe_user", "agent+designer@friday.local", update_modified=False
		)

	@patch("friday.friday_core.identity.agent_identity.frappe")
	def test_idempotent_when_user_already_exists(self, mock_frappe):
		from friday.friday_core.identity.agent_identity import provision_agent_user

		# User row already present — must NOT insert a second one.
		mock_frappe.db.exists.return_value = True
		existing = _FakeDoc({"doctype": "User", "email": "agent+copywriter@friday.local", "roles": []})
		mock_frappe.get_doc.return_value = existing

		profile = self._profile("Copywriter")
		email = provision_agent_user(profile)

		self.assertEqual(email, "agent+copywriter@friday.local")
		# get_doc was used to fetch the existing user, never to build a new one
		# with insert(); assert no fresh User dict was inserted.
		self.assertNotIn("_inserted", existing)

	@patch("friday.friday_core.identity.agent_identity.frappe")
	def test_slug_sanitizes_punctuation_and_spaces(self, mock_frappe):
		from friday.friday_core.identity.agent_identity import provision_agent_user

		mock_frappe.db.exists.return_value = False
		mock_frappe.get_doc.side_effect = lambda spec: _FakeDoc(spec)

		profile = self._profile("Brand  Copywriter! (v2)")
		email = provision_agent_user(profile)

		self.assertEqual(email, "agent+brand-copywriter-v2@friday.local")

	@patch("friday.friday_core.identity.agent_identity.frappe")
	def test_mirrors_assigned_roles_onto_user(self, mock_frappe):
		from friday.friday_core.identity.agent_identity import provision_agent_user

		built = {}

		def _get_doc(spec):
			doc = _FakeDoc(spec)
			if spec.get("doctype") == "User":
				built["doc"] = doc
			return doc

		mock_frappe.db.exists.return_value = False
		mock_frappe.get_doc.side_effect = _get_doc

		profile = self._profile("Copywriter", roles=["Friday Reader", "Friday File Author"])
		provision_agent_user(profile)

		user_doc = built["doc"]
		got = {r["role"] for r in user_doc.get("roles", [])}
		self.assertEqual(got, {"Friday Reader", "Friday File Author"})

	@patch("friday.friday_core.identity.agent_identity.frappe")
	def test_empty_profile_name_is_refused(self, mock_frappe):
		from friday.friday_core.identity.agent_identity import provision_agent_user

		profile = self._profile("")
		email = provision_agent_user(profile)
		self.assertIsNone(email)
		mock_frappe.get_doc.assert_not_called()


class TestProvisionAllAgentUsers(unittest.TestCase):
	"""``provision_all_agent_users`` backfills every profile, isolating failures."""

	@patch("friday.friday_core.identity.agent_identity.provision_agent_user")
	@patch("friday.friday_core.identity.agent_identity.frappe")
	def test_backfills_each_profile(self, mock_frappe, mock_provision):
		from friday.friday_core.identity.agent_identity import provision_all_agent_users

		mock_frappe.get_all.return_value = [
			_FakeDoc({"name": "Copywriter"}),
			_FakeDoc({"name": "Designer"}),
		]
		mock_frappe.get_doc.side_effect = lambda dt, n: _FakeDoc({"name": n, "profile_name": n})
		mock_provision.side_effect = ["agent+copywriter@friday.local", "agent+designer@friday.local"]

		summary = provision_all_agent_users()

		self.assertEqual(summary["provisioned"], 2)
		self.assertEqual(summary["failed"], [])
		self.assertEqual(mock_provision.call_count, 2)

	@patch("friday.friday_core.identity.agent_identity.provision_agent_user")
	@patch("friday.friday_core.identity.agent_identity.frappe")
	def test_one_failure_does_not_abort_the_rest(self, mock_frappe, mock_provision):
		from friday.friday_core.identity.agent_identity import provision_all_agent_users

		mock_frappe.get_all.return_value = [
			_FakeDoc({"name": "Good1"}),
			_FakeDoc({"name": "Bad"}),
			_FakeDoc({"name": "Good2"}),
		]
		mock_frappe.get_doc.side_effect = lambda dt, n: _FakeDoc({"name": n, "profile_name": n})

		def _provision(profile):
			if profile["name"] == "Bad":
				raise RuntimeError("boom")
			return f"agent+{profile['name'].lower()}@friday.local"

		mock_provision.side_effect = _provision

		summary = provision_all_agent_users()

		self.assertEqual(summary["provisioned"], 2)
		self.assertEqual(summary["failed"], ["Bad"])
		# fail-loud: the failure was logged, not swallowed silently
		self.assertTrue(mock_frappe.log_error.called)


class TestAfterInsertHook(unittest.TestCase):
	"""The Agent Profile after_insert hook delegates to the provisioner."""

	@patch("friday.friday_core.identity.agent_identity.provision_agent_user")
	@patch("friday.friday_core.identity.agent_identity.frappe")
	def test_after_insert_delegates(self, mock_frappe, mock_provision):
		from friday.friday_core.identity.agent_identity import on_agent_profile_after_insert

		profile = _FakeDoc({"name": "Copywriter", "profile_name": "Copywriter"})
		on_agent_profile_after_insert(profile, "after_insert")

		mock_provision.assert_called_once_with(profile)

	@patch("friday.friday_core.identity.agent_identity.provision_agent_user")
	@patch("friday.friday_core.identity.agent_identity.frappe")
	def test_after_insert_never_raises(self, mock_frappe, mock_provision):
		from friday.friday_core.identity.agent_identity import on_agent_profile_after_insert

		mock_provision.side_effect = RuntimeError("db down")
		profile = _FakeDoc({"name": "Copywriter", "profile_name": "Copywriter"})

		# A provisioning hiccup must not block the profile from being created.
		on_agent_profile_after_insert(profile, "after_insert")
		self.assertTrue(mock_frappe.log_error.called)


if __name__ == "__main__":
	unittest.main()
