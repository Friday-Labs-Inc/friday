# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt

"""
The concurrent friday-queue worker launcher.

PLAIN ENGLISH
=============

Every agent turn (a chat reply or a pipeline task) runs as a background
job on the dedicated ``friday`` Redis queue. By default ONE process
drains that queue, so it handles one turn at a time — and because a turn
is mostly spent *waiting* for the language model to answer, a second
user's message just sits in line behind the first. Under load the line
grows: at ten simultaneous turns the last one waited ~18s in our Legion
benchmark, even though a single turn finishes in ~4s.

This module lets you drain the ``friday`` queue with MORE THAN ONE worker
at once. Because each worker spends almost all its time blocked on the
model's network call, N workers overlap their waits and the line
collapses — the same ten turns finished in ~3.4s (5.4x faster) with the
queue wait effectively gone.

How many workers run is one knob: ``Agent Settings.max_concurrent_turns``.

  * ``1`` (the DEFAULT) → behaves EXACTLY like today: a single
    ``bench worker --queue friday`` via Frappe's standard ``start_worker``.
    Flag off, zero behaviour change.
  * ``N > 1`` → Frappe's native RQ ``WorkerPool`` spawns N worker
    PROCESSES on the ``friday`` queue (``start_worker_pool``).

WHY PROCESSES, NOT THREADS
==========================

We proved the win with a thread pool in the benchmark, but the
production launcher uses PROCESSES (Frappe's ``start_worker_pool``) for
three reasons that matter on a live system:

  1. Each pooled worker registers itself as a real RQ ``Worker``, so
     ``gateway.service._friday_worker_alive()`` and ``pipeline_health``
     keep seeing a live worker. A hand-rolled threaded worker would NOT
     register and the gateway would silently fall back to inline
     execution — a regression.
  2. It reuses Frappe's own battle-tested ``WorkerPool`` instead of
     re-implementing RQ's job lifecycle (registries, heartbeats, failure
     handling). "Don't reinvent the queue."
  3. Crash isolation: one turn blowing up its process can't take the
     others down.

The throughput win is identical either way — the bottleneck is the
model wait, and N independent workers each wait in parallel.

DISCLOSURE: Frappe marks ``start_worker_pool`` as EXPERIMENTAL in
``frappe/utils/background_jobs.py``. We lean on it deliberately and gate
it behind a default-off flag; ``max_concurrent_turns = 1`` never touches
that code path.
"""

from __future__ import annotations

import frappe

# The ``friday`` queue name — the single dedicated queue every agent turn
# runs on (mirrors gateway.service.FRIDAY_QUEUE and tasks.workflow).
FRIDAY_QUEUE = "friday"

# A hard safety ceiling on concurrency. A misconfigured huge value would
# fork that many worker processes and exhaust Postgres connections / RAM,
# so we clamp. 16 is comfortably above any single-tenant need and well
# under Postgres's default 100-connection limit (each worker holds one).
CONCURRENCY_HARD_CEILING = 16

# What we fall back to when the setting is missing, blank, or unreadable:
# a single worker — i.e. exactly today's behaviour.
DEFAULT_CONCURRENCY = 1


def resolve_concurrency(override: int | None = None) -> int:
	"""Decide how many ``friday`` workers to run.

	Resolution order:
	  1. ``override`` (the ``--concurrency`` CLI flag), when given.
	  2. ``Agent Settings.max_concurrent_turns``.
	  3. ``DEFAULT_CONCURRENCY`` (1) on any miss or error.

	The result is always clamped to ``[1, CONCURRENCY_HARD_CEILING]`` so a
	bad value can never fork an unbounded number of processes or disable
	the worker entirely.

	Reading the setting must never crash worker start-up, so any error
	degrades to the safe default (1).
	"""
	value = override
	if value is None:
		try:
			from friday.friday_core.doctype.agent_settings.agent_settings import get_agent_settings

			raw = get_agent_settings().get("max_concurrent_turns")
			value = int(raw) if raw not in (None, "") else DEFAULT_CONCURRENCY
		except Exception:
			frappe.logger("friday.worker_pool").warning(
				"could not read max_concurrent_turns — defaulting to 1", exc_info=True
			)
			value = DEFAULT_CONCURRENCY

	return _clamp(value)


def _clamp(value: int) -> int:
	"""Force ``value`` into ``[1, CONCURRENCY_HARD_CEILING]``."""
	try:
		value = int(value)
	except (TypeError, ValueError):
		return DEFAULT_CONCURRENCY
	if value < 1:
		return 1
	if value > CONCURRENCY_HARD_CEILING:
		return CONCURRENCY_HARD_CEILING
	return value


def start_friday_worker(concurrency: int | None = None, quiet: bool = False) -> None:
	"""Start the friday-queue worker(s), honouring the concurrency flag.

	``concurrency=1`` (the default after resolution) goes through Frappe's
	standard single-worker ``start_worker`` — byte-for-byte the current
	``bench worker --queue friday``. ``concurrency>1`` starts an RQ
	``WorkerPool`` of that many processes via ``start_worker_pool``.

	Both calls block forever (they run the worker event loop), so this is
	the entry point a process manager (Procfile / supervisor) supervises.
	"""
	from frappe.utils.background_jobs import start_worker, start_worker_pool

	n = resolve_concurrency(concurrency)
	log = frappe.logger("friday.worker_pool")

	if n <= 1:
		log.info("friday worker: single worker (max_concurrent_turns=1)")
		start_worker(queue=FRIDAY_QUEUE, quiet=quiet)
		return

	log.info("friday worker: pool of %s workers on the '%s' queue", n, FRIDAY_QUEUE)
	start_worker_pool(queue=FRIDAY_QUEUE, num_workers=n, quiet=quiet)
