"""Every third-party module the kernel imports is declared, or knowingly optional.

An undeclared dependency does not fail at install — it fails the first time the
code path runs, which for the LLM transport means a customer's first message.
`httpx` and `openai` reached production undeclared exactly that way, surviving
because a developer had installed them by hand; the miss only surfaced on a
clean deploy.

OPTIONAL lists the modules the kernel imports behind a fallback and can run
without. Adding a name there is a deliberate act; forgetting to declare a real
dependency is not.
"""

import ast
import importlib.metadata
import re
import sys
import unittest
from pathlib import Path

KERNEL = Path(__file__).resolve().parents[1]  # frappe/friday_core
PYPROJECT = KERNEL.parents[1] / "pyproject.toml"  # the app root

# Imported behind a guard/fallback; the kernel runs without them.
#   fastembed / sentence_transformers — local embedding fallbacks, only reached
#     when the configured provider has no embedding endpoint.
#   docker — the sandbox runner; absent on a developer machine by design.
OPTIONAL = {"fastembed", "sentence_transformers", "docker"}

# import name -> distribution name, where they differ.
DISTRIBUTION = {
	"psycopg2": "psycopg2-binary",
	"dateutil": "python-dateutil",
	"yaml": "pyyaml",
	"jwt": "pyjwt",
	"bs4": "beautifulsoup4",
	"PIL": "pillow",
	"git": "gitpython",
	"sentence_transformers": "sentence-transformers",
}

# Bench apps: installed by `bench get-app`, declared via hooks required_apps,
# never a PyPI distribution.
BENCH_APPS = {"frappe", "raven"}


def _imported_top_level_modules() -> set[str]:
	"""Top-level modules imported by the kernel, excluding same-directory siblings.

	`sandbox/entrypoint.py` does `from handlers import get`: inside the sandbox
	image that resolves to the handlers.py sitting beside it, not to a package.
	"""
	found: set[str] = set()
	for path in KERNEL.rglob("*.py"):
		rel = path.relative_to(KERNEL).as_posix()
		if "__pycache__" in rel:
			continue
		# A syntax error here must fail loudly rather than silently shrink the
		# scan — that is how the first audit of this missed provider.py.
		tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
		for node in ast.walk(tree):
			names = []
			if isinstance(node, ast.Import):
				names = [a.name.split(".")[0] for a in node.names]
			elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
				names = [node.module.split(".")[0]]
			for name in names:
				sibling = path.parent / name
				if sibling.with_suffix(".py").exists() or (sibling / "__init__.py").exists():
					continue
				found.add(name)
	return found


def _declared_distributions() -> set[str]:
	block = re.search(r"dependencies = \[(.*?)\n\]", PYPROJECT.read_text(), re.S)
	assert block, "could not find [project] dependencies in pyproject.toml"
	names = set()
	for line in block.group(1).splitlines():
		line = line.strip().strip('",')
		if not line or line.startswith("#"):
			continue
		name = re.split(r"[~=<>@\[ ]", line)[0].strip().lower()
		if name:
			names.add(name)
	return names


class TestKernelDependencies(unittest.TestCase):
	def test_every_third_party_import_is_declared(self):
		declared = _declared_distributions()
		stdlib = set(sys.stdlib_module_names)
		undeclared = []
		for module in sorted(_imported_top_level_modules()):
			if module in stdlib or module in BENCH_APPS or module in OPTIONAL or module.startswith("_"):
				continue
			dist = DISTRIBUTION.get(module, module).lower()
			if dist not in declared:
				undeclared.append(f"{module} (distribution: {dist})")
		self.assertEqual(
			undeclared,
			[],
			"friday_core imports these but pyproject.toml does not declare them. "
			"Declare them, or add to OPTIONAL if the kernel genuinely runs without them:\n  "
			+ "\n  ".join(undeclared),
		)

	def test_optional_modules_are_actually_optional(self):
		"""Guard the escape hatch: OPTIONAL must not quietly absorb a real dependency."""
		for module in sorted(OPTIONAL):
			self.assertNotIn(
				module,
				_declared_distributions(),
				f"{module} is declared in pyproject.toml, so it is not optional — "
				"remove it from OPTIONAL.",
			)

	def test_the_llm_transport_is_installed(self):
		"""httpx and openai are the chat path; a bench without them cannot answer."""
		for dist in ("httpx", "openai"):
			try:
				importlib.metadata.version(dist)
			except importlib.metadata.PackageNotFoundError:  # pragma: no cover
				self.fail(f"{dist} is not installed in this bench — `bench setup requirements`")
