# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""
Unit tests for the scoped-credential token (H3, doc 49 §H3 / doc 51 S9).

H3 fixed the "two disagreeing generators" half: there must be exactly ONE
scoped-token generator (`sandbox/credentials.generate_scoped_token`), and the
sandbox runner must use it rather than minting its own. The genuine
REST-boundary validation (a real Frappe API Key/Secret checked server-side)
stays an explicitly-flagged Phase 1.5 item — there is no live sandbox callback
to validate yet.

Mock-based — no DB, no Docker.
"""

import os
import re
import unittest
from unittest.mock import patch

from frappe.friday_core.sandbox import credentials


class TestScopedTokenGenerator(unittest.TestCase):
	def test_exactly_one_generator_in_sandbox_package(self):
		# The locked acceptance criterion (S9): "grep finds no second generator".
		sandbox_dir = os.path.dirname(credentials.__file__)
		found = []
		for fname in sorted(os.listdir(sandbox_dir)):
			if not fname.endswith(".py"):
				continue
			with open(os.path.join(sandbox_dir, fname), encoding="utf-8") as fh:
				for name in re.findall(r"def (\w*generate_scoped_token\w*)\(", fh.read()):
					found.append((fname, name))
		self.assertEqual(
			found,
			[("credentials.py", "generate_scoped_token")],
			f"H3: expected exactly one generator in credentials.py, found {found}",
		)

	def test_runner_uses_the_shared_generator(self):
		# The sandbox runner must reference the shared generator, not define one.
		from frappe.friday_core.sandbox import runner

		self.assertFalse(
			hasattr(runner, "_generate_scoped_token"),
			"H3: the duplicate runner._generate_scoped_token stub must be gone",
		)
		self.assertIs(runner.generate_scoped_token, credentials.generate_scoped_token)

	@patch("frappe.generate_hash", return_value="ab12" * 8)
	def test_generator_returns_the_token(self, _mock_hash):
		token = credentials.generate_scoped_token("Profile-A", "exec-123")
		self.assertEqual(token, "ab12" * 8)


if __name__ == "__main__":
	unittest.main()
