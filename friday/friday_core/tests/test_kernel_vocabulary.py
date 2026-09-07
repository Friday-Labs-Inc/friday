"""The kernel names no product and no customer — not even in comments.

CLAUDE.md rule 2. Skill descriptions and prompts ship to the LLM, docstrings
ship to the next engineer; both teach a vocabulary. Products (RandomPack) and
customers (Klick N Click) live in their own apps. Tests are excluded — they may
name a product to prove the boundary holds.
"""

import re
import unittest
from pathlib import Path

KERNEL = Path(__file__).resolve().parents[1]
FORBIDDEN = re.compile(r"randompack|random pack|brand brief|brand direction|\bknc\b|klick", re.IGNORECASE)


class TestKernelVocabulary(unittest.TestCase):
	def test_no_product_or_customer_names_in_kernel(self):
		hits = []
		for path in KERNEL.rglob("*.py"):
			rel = path.relative_to(KERNEL).as_posix()
			if rel.startswith("tests/") or "__pycache__" in rel:
				continue
			for n, line in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
				if FORBIDDEN.search(line):
					hits.append(f"{rel}:{n}: {line.strip()[:80]}")
		self.assertEqual(hits, [], "product/customer names in the kernel:\n" + "\n".join(hits))
