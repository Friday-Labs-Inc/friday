#!/usr/bin/env python3
"""Run a Frappe app's test suite and gate on it with a ratchet.

    python ci/run_tests.py --site test.localhost --app friday --known-red ci/known-red.txt

Default mode runs ONE `bench run-tests --module <m>` PROCESS PER TEST MODULE, in
sorted order. That is deterministic on every machine and state leaked by one
module (a lingering mock, an after_commit callback, a patched global) cannot
poison the next — `bench run-tests --app` runs everything in one process in
os.walk order, which differs between a dev container and CI and made the same
suite report different red modules on each (friday#215).

`--whole-suite` runs the single-process `--app` mode instead: faster, stricter,
and the right tool for hunting those leaks.

Output is teed to test-output.log; FAIL:/ERROR: lines say which MODULES went red.

The gate then fails if:
  - any module NOT listed in known-red went red        (a regression), or
  - any module listed in known-red is now green         (the list is stale —
    delete the line, so the ratchet only ever tightens), or
  - the run crashed before reporting.

known-red.txt: one module per line, `#` comments allowed. Every entry must
carry the issue that tracks fixing it.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

# unittest prints "FAIL: name (dotted)"; Frappe's runner prints " FAIL  name (dotted)"
# (padded label, optional ANSI colour) when stdout is not a TTY. Accept both.
ANSI = r"(?:\x1b\[[\d;]*m)?"
RED_LINE = re.compile(rf"^\s*{ANSI}\s*(?:FAIL|ERROR)\s*{ANSI}\s*:?\s+\S+ \(([\w.]+)\)")
RAN_LINE = re.compile(r"^Ran (\d+) tests? in")


def read_known(path: Path | None) -> set[str]:
	if not path or not path.exists():
		return set()
	return {
		line.split("#", 1)[0].strip()
		for line in path.read_text().splitlines()
		if line.split("#", 1)[0].strip()
	}


def discover_modules(app_path: Path) -> list[str]:
	"""Same rule as frappe.testing.discovery.discover_all_tests, but SORTED."""
	skip = {"node_modules", "locals", "public", "__pycache__"}
	found = []
	for path in sorted(app_path.rglob("test_*.py")):
		if path.name == "test_runner.py" or any(part in skip or part.startswith(".") for part in path.parts):
			continue
		if "doctype/doctype/boilerplate" in path.as_posix():
			continue
		found.append(".".join(path.relative_to(app_path.parent).with_suffix("").parts))
	return found


def module_of(dotted: str) -> str:
	"""friday.friday_core.tests.test_x.TestCase.test_method -> ...tests.test_x

	Cut at the first CapitalisedSegment (the TestCase class) rather than a fixed
	number of trailing parts: `setUpClass (pkg.tests.test_x.TestX)` has one part
	fewer than a method id, and `unittest.loader._FailedTest.test_x` (an import
	failure) has no module of ours at all.
	"""
	parts = dotted.split(".")
	for i, part in enumerate(parts):
		if part[:1].isupper() or part.startswith("_"):
			return ".".join(parts[:i]) or dotted
	return dotted


def main() -> int:
	ap = argparse.ArgumentParser()
	ap.add_argument("--site", required=True)
	ap.add_argument("--app", required=True)
	ap.add_argument("--known-red", type=Path)
	ap.add_argument("--log", type=Path, default=Path("test-output.log"))
	ap.add_argument(
		"--min-tests", type=int, default=0,
		help="fail if fewer tests ran (guards against discovery silently collapsing)",
	)
	ap.add_argument("--whole-suite", action="store_true", help="single process via --app (leak hunting)")
	ap.add_argument("--app-path", type=Path, help="package dir of the app (default apps/<app>/<app>)")
	args = ap.parse_args()

	red: set[str] = set()
	ran = None
	returncode = 0
	with args.log.open("w") as log:
		if args.whole_suite:
			cmds = [["bench", "--site", args.site, "run-tests", "--app", args.app]]
		else:
			app_path = args.app_path or Path("apps") / args.app / args.app
			modules = discover_modules(app_path)
			print(f"{len(modules)} test modules under {app_path}", flush=True)
			cmds = [["bench", "--site", args.site, "run-tests", "--module", m] for m in modules]
		for cmd in cmds:
			print("+", " ".join(cmd), flush=True)
			log.write("+ " + " ".join(cmd) + "\n")
			ran_here = None
			proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
			assert proc.stdout
			for line in proc.stdout:
				sys.stdout.write(line)
				log.write(line)
				if m := RED_LINE.match(line):
					red.add(module_of(m.group(1)))
				elif m := RAN_LINE.match(line):
					# one "Ran N tests" line per suite block — accumulate, don't overwrite
					ran_here = (ran_here or 0) + int(m.group(1))
			proc.wait()
			if ran_here is not None:
				ran = (ran or 0) + ran_here
			if not args.whole_suite and (proc.returncode != 0 or ran_here is None):
				# a module that crashes before reporting, or exits non-zero with no
				# parsable FAIL/ERROR line, is red — never silently green
				red.add(cmd[-1])
			returncode = returncode or proc.returncode

	known = read_known(args.known_red)
	new_red = sorted(red - known)
	now_green = sorted(known - red)

	print("\n" + "=" * 70)
	print(f"tests ran: {ran}   red modules: {len(red)}   known-red: {len(known)}")
	status = 0
	if ran is None:
		print("GATE: the run did not report a test count — treating as a crash")
		status = 1
	elif ran < args.min_tests:
		print(f"GATE: only {ran} tests ran, expected at least {args.min_tests} — discovery collapsed?")
		status = 1
	# A non-zero exit is expected only while known-red modules are still red.
	expected_failure = bool(red) and red <= known and ran is not None
	if returncode != 0 and not expected_failure and not new_red:
		print(f"GATE: bench exited {returncode} without a matching red module — treating as a crash")
		status = 1
	if new_red:
		print("GATE: NEW red modules (regressions):")
		for m in new_red:
			print(f"  - {m}")
		status = 1
	if now_green:
		print("GATE: these known-red modules are GREEN now — remove them from known-red.txt:")
		for m in now_green:
			print(f"  - {m}")
		status = 1
	if status == 0:
		print("GATE: pass — no regressions" + (f" ({len(red)} known-red modules still red)" if red else ""))
	return status


if __name__ == "__main__":
	sys.exit(main())
