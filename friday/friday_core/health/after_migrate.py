# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""
Post-migrate setup for the durable pipeline (design 61b, Q4).

Registers the ``friday`` queue in ``common_site_config.json`` so a fresh
bench clone does not silently lose the runner trigger to a non-existent
queue (the Legion bench-serve trap, dressed differently). Idempotent —
safe to call on every migrate.

The Procfile registration of ``bench worker --queue friday`` is a separate
manual step in the runbook: hooks can't safely modify the bench-level
Procfile from inside the app (different file, owned by the bench). We log
loudly when it's missing — see ``pipeline_health._inflight_jobs_by_queue``.
"""

from __future__ import annotations

import json
import os

import frappe

# Matches the timeout used in workflow.on_state_change and
# the connector client's enqueue_send so the queue config and the
# enqueue call stay aligned. 600s is generous: agentic LLM runs + sandbox
# starts can be slow on a cold worker.
FRIDAY_QUEUE_TIMEOUT_SECONDS = 600


def register_friday_queue() -> None:
	"""
	Idempotently add the ``friday`` worker to ``common_site_config.json``.

	Frappe reads ``workers`` from this file when validating queue names;
	without an entry, ``frappe.enqueue(..., queue="friday")`` raises
	``InvalidQueueName`` and the runner trigger silently dies.

	Reads the file atomically (read → mutate → temp-write → replace), so an
	interrupted migrate cannot leave a half-written config.
	"""
	bench_path = frappe.utils.get_bench_path()
	config_path = os.path.join(bench_path, "sites", "common_site_config.json")
	if not os.path.exists(config_path):
		# A bench may live under a path different from get_bench_path during
		# tests. Skip silently then — the registration will run on the real
		# bench's next migrate.
		return

	# config_path is built from frappe.utils.get_bench_path() — trusted, never user input.
	with open(config_path) as fh:  # nosemgrep: frappe-security-file-traversal
		config = json.load(fh)

	workers = config.get("workers") or {}
	if workers.get("friday", {}).get("timeout") == FRIDAY_QUEUE_TIMEOUT_SECONDS:
		return  # already registered with the right timeout — nothing to do

	workers["friday"] = {"timeout": FRIDAY_QUEUE_TIMEOUT_SECONDS}
	config["workers"] = workers

	# Atomic write: temp file in the same directory, then os.replace. This
	# matters because another process may read the file mid-write otherwise.
	tmp_path = config_path + ".tmp"
	# tmp_path is a sibling of config_path (also trusted).
	with open(tmp_path, "w") as fh:  # nosemgrep: frappe-security-file-traversal
		json.dump(config, fh, indent=1, sort_keys=True)
	os.replace(tmp_path, config_path)

	frappe.logger("friday.health").info(
		"after_migrate: registered 'friday' queue (timeout=%ss) in common_site_config.json",
		FRIDAY_QUEUE_TIMEOUT_SECONDS,
	)
