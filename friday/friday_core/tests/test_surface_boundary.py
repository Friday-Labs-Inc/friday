"""Ratchet: no NEW kernel file may name Raven (Design 98, issue #222).

Raven is a chat surface that is leaving the kernel behind the `friday_surfaces`
contract. Until that lands, the 32 files that already mention it are
allow-listed in surface_boundary_allowlist.txt. This test fails when

  - a kernel file NOT on the list mentions Raven (a new leak), or
  - a listed file no longer mentions Raven (delete its line — the list only shrinks).

Tests are excluded: they may name Raven to prove the boundary holds.
"""

import re
import unittest
from pathlib import Path

KERNEL = Path(__file__).resolve().parents[1]  # friday/friday_core
ALLOWLIST = Path(__file__).with_name("surface_boundary_allowlist.txt")
RAVEN = re.compile(r"raven", re.IGNORECASE)


def _mentions_raven() -> set[str]:
	found = set()
	for path in KERNEL.rglob("*.py"):
		rel = path.relative_to(KERNEL).as_posix()
		if rel.startswith("tests/") or "__pycache__" in rel:
			continue
		if RAVEN.search(path.read_text(encoding="utf-8", errors="ignore")):
			found.add(rel)
	return found


def _allowed() -> set[str]:
	return {
		line.split("#", 1)[0].strip()
		for line in ALLOWLIST.read_text().splitlines()
		if line.split("#", 1)[0].strip()
	}


class TestSurfaceBoundary(unittest.TestCase):
	def test_no_new_kernel_file_names_raven(self):
		new = sorted(_mentions_raven() - _allowed())
		self.assertEqual(
			new, [],
			"NEW kernel files mention Raven — route through the surface contract "
			"(docs/design/98-surface-contract.md) instead: " + ", ".join(new),
		)

	def test_allowlist_only_shrinks(self):
		stale = sorted(_allowed() - _mentions_raven())
		self.assertEqual(
			stale, [],
			"these files no longer mention Raven — remove them from "
			"surface_boundary_allowlist.txt: " + ", ".join(stale),
		)
