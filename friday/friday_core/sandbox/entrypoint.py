#!/usr/bin/env python3
# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt

"""
Container entrypoint — runs inside the Docker sandbox container.

Reads task JSON from stdin, calls the skill handler, writes result
envelope to stdout, and exits.

Usage inside container:
    python entrypoint.py < task.json

(task.json is piped by the orchestrator via attach_socket;
fallback: read from stdin directly)

Dependencies (installed in Dockerfile):
- requests==2.32.3  — HTTP calls to Frappe REST API
"""

import json
import os
import sys

RESULT_BEGIN = ">>>FRIDAY_RESULT_BEGIN<<<"
RESULT_END = "<<<FRIDAY_RESULT_END>>>"


def _load_payload() -> dict:
	"""Read and parse the task payload from stdin."""
	payload_bytes = sys.stdin.read()
	if not payload_bytes:
		raise ValueError("empty payload on stdin")
	return json.loads(payload_bytes)


def _call_skill(skill_name: str, parameters: dict) -> dict:
	"""
	Call the bundled skill handler inside the container.

	Phase 1: skills are co-written Python modules registered in handlers.py.
	(Loading skills from Frappe at runtime is Phase 1.5 per DOC 24 §4.3.)

	The handler uses FRIDAY_API_KEY from the container env for authentication
	against the Frappe REST API.
	"""
	# Registry of bundled skill handlers — co-written in same directory
	from handlers import get as _get_handler

	handler = _get_handler(skill_name)
	if handler is None:
		raise ImportError(f"skill {skill_name!r} not found in container")

	if not callable(handler):
		raise TypeError(f"handler for {skill_name!r} is not callable")

	return handler(parameters=parameters)


def main() -> None:
	"""
	1. Read payload from stdin.
	2. Call the skill.
	3. Write structured result to stdout.
	"""
	try:
		payload = _load_payload()

		skill_name = payload.get("skill_name")
		parameters = payload.get("parameters", {})

		if not skill_name:
			raise ValueError("skill_name is required in payload")

		result = _call_skill(skill_name, parameters)

		envelope = {
			"status": "success",
			"result": result,
		}

		sys.stdout.write(RESULT_BEGIN + "\n")
		sys.stdout.write(json.dumps(envelope) + "\n")
		sys.stdout.write(RESULT_END + "\n")
		sys.stdout.flush()
		sys.exit(0)

	except Exception as e:
		envelope = {
			"status": "failed",
			"result": None,
			"error": f"{type(e).__name__}: {e}",
		}

		sys.stdout.write(RESULT_BEGIN + "\n")
		sys.stdout.write(json.dumps(envelope) + "\n")
		sys.stdout.write(RESULT_END + "\n")
		sys.stdout.flush()
		sys.exit(1)


if __name__ == "__main__":
	main()
