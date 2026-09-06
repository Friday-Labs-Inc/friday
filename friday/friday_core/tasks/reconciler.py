# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""
The durability reconciler (design 61, Q1 + Q7a).

Why this exists, in plain English
=================================
Before this module, Friday's autonomous loop was *event load-bearing*: a
task moved from Pending → Assigned, the workflow hook enqueued the runner,
and IF that single enqueue survived (worker up, queue named correctly,
network OK, …) the task ran. Lose the enqueue and the task sat in
Assigned forever — no one told anyone. On 2026-06-12 a real customer
pipeline stalled for four hours this way; even the AI watching it
declared "everything operating in harmony."

This file flips that. State is now the source of truth, the scheduler is
the heartbeat, and the event is only an optimisation. Every 60 seconds
`tick()` runs and drives tasks forward purely from DB facts:

    Pending             → (the existing dispatcher handles this — left alone)
    Assigned, no in-flight job, > 30s old  → re-enqueue the runner trigger
    Executing, no fresh heartbeat (15min)  → Block + raise a Failure Issue
    Blocked (transient), retry budget left → re-Pend; the dispatcher tries again
    Connector Event in Received/Failed     → re-enqueue process_event

The heartbeat (`last_heartbeat_at`) is updated by the runner during real
work, so genuinely long agentic runs are not killed by the executing-stale
sweep. The retry budget (3) caps the auto-heal so a truly broken task
stays Blocked for a human, with a reason a human can read.

Q4 (locked): the canonical queue is `friday`. Every enqueue here uses it.
"""

from __future__ import annotations

import frappe
from frappe.utils.background_jobs import get_jobs

_logger = frappe.logger("friday.tasks.reconciler")

# How fresh an Assigned task must be before we will re-fire the runner trigger.
# Smaller than this and we risk racing the original enqueue; larger and lost-
# enqueue stalls take longer to heal. 30s is the sweet spot for a 60s cron.
ASSIGNED_GRACE_SECONDS = 30

# An Executing task without a heartbeat for this long is considered runner_lost.
# Heartbeats fire every 30s during agentic runs and at each skill boundary for
# mechanical runs, so 15 minutes is well beyond any healthy gap.
EXECUTING_STALE_MINUTES = 15

# How long a transient-Blocked task waits before we re-Pend it. Short enough
# that a flake recovers within one project sprint, long enough that we don't
# hammer a stuck dependency.
TRANSIENT_BLOCKED_GRACE_MINUTES = 5

# Beyond this many auto-retries we leave the task Blocked for a human. The cap
# exists so a permanently-broken skill cannot ping-pong forever.
RETRY_BUDGET = 3

# Reasons we auto-retry. Semantic blocks (dependency_failed, no_profile_for_
# skills:*, profile_has_no_llm_provider) and non-retryable LLM failures (auth,
# billing, model_not_found, format_error, context_overflow) are NOT in this set:
# they need a human to resolve, retrying them just spams.
#
# The LLM transport transients (rate_limit/overloaded/server_error/timeout) are
# the retryable FailoverReasons the runner records on Task.blocked_reason from an
# LLMError — a provider hiccup that exhausted the in-call retries gets a few more
# shots here (capped by RETRY_BUDGET). "timeout" also covers sandbox timeouts.
TRANSIENT_BLOCKED_REASONS = (
	"oom",
	"timeout",
	"runner_lost",
	"rate_limit",
	"overloaded",
	"server_error",
)

# Stuck Connector Event grace: shorter than tasks because events are dirt-cheap
# to re-process (the handler is idempotent / status-guarded already).
CONNECTOR_EVENT_RECEIVED_GRACE_SECONDS = 60
CONNECTOR_EVENT_FAILED_GRACE_MINUTES = 5

# The single job-name convention used everywhere the runner is enqueued. Lets
# get_jobs() tell us "is this task already in flight" without false positives.
TASK_JOB_NAME = "task:{name}"
EVENT_JOB_NAME = "connector-event:{event_id}"

# Per-row isolation savepoint for the rescue sweeps. All four sweeps share one
# tick transaction, and on Postgres ANY failed statement aborts the WHOLE tx —
# so without a savepoint, one task whose .save() raises would poison every later
# row AND every later sweep (each phase's try/except catches the Python error but
# the tx stays aborted, so the rescues silently no-op). Wrapping each row's writes
# in this savepoint means a bad row rolls back to here and the tick carries on;
# the task stays stale and is retried on the next tick.
_ROW_SAVEPOINT = "friday_reconcile_row"


# ---------------------------------------------------------------------------
# Entry point — wired in hooks.scheduler_events["cron"]["* * * * *"]
# ---------------------------------------------------------------------------


def tick() -> None:
	"""
	One reconciler cycle — four independent sweeps.

	The sweeps are isolated: a DB blip in one must NOT abort the others
	(this is the heartbeat; partial work is better than no work). Each
	failure is logged loudly so we never silently regress to the bad old
	"all settings seem fine" state.

	Design 72 — emits one ``reconciler.tick`` event per cycle with per-phase
	counts (failures land in the same event with ``phase_errors``). Per-action
	events (re-pend, runner_lost, re-enqueue) are emitted by the sweeps
	themselves so the Lifecycle Trace can attribute them to a specific task.
	"""
	from friday.friday_core.observability import emit

	phase_results = {}
	phase_errors = []
	for phase, fn in (
		("assigned_orphans", _reconcile_assigned_orphans),
		("executing_stale", _reconcile_executing_stale),
		("transient_blocked", _reconcile_transient_blocked),
		("connector_events", _reconcile_connector_events),
	):
		try:
			# Each sweep returns its action count; legacy sweeps return None
			# (treated as 0 for the tick summary).
			phase_results[phase] = fn() or 0
		except Exception:
			# log_error persists; logger.exception goes to the worker log. Both,
			# so the operator and the AI watching it both have a trail.
			_logger.exception("reconciler phase %s failed", phase)
			frappe.log_error(title=f"friday.reconciler phase failed: {phase}")
			phase_errors.append(phase)

	emit(
		"reconciler.tick",
		trigger_source="scheduler",
		summary=(
			"tick: "
			+ ", ".join(f"{p}={n}" for p, n in phase_results.items())
			+ (f" (errors: {', '.join(phase_errors)})" if phase_errors else "")
		),
		payload={"phase_actions": phase_results, "phase_errors": phase_errors},
	)


# ---------------------------------------------------------------------------
# Sweeps
# ---------------------------------------------------------------------------


def _reconcile_assigned_orphans() -> int:
	"""
	An Assigned task that no worker is actually working on is an orphan: the
	original `frappe.enqueue` in workflow.on_state_change was lost (worker
	wasn't up; queue wasn't registered; Redis blip; etc.). We re-fire the
	runner trigger with the same idempotent payload — the runner's
	check-and-set lease (Q5) makes a duplicate trigger a clean no-op.

	The 30-second grace window matters: without it we'd race the legitimate
	first enqueue and spam the queue. With it, we still heal a stall within
	~90 seconds of it happening.
	"""
	# Python-side cutoff: TIMESTAMPDIFF is MySQL-only and breaks on Postgres
	# (the database backend this bench actually runs). Computing the cutoff
	# in Python and comparing as a parameter is portable across both, and
	# also more readable than DB-specific interval arithmetic.
	cutoff = frappe.utils.add_to_date(frappe.utils.now_datetime(), seconds=-ASSIGNED_GRACE_SECONDS)
	rows = frappe.db.sql(
		"""
		SELECT name, assigned_to_profile
		FROM `tabAgent Task`
		WHERE workflow_state = 'Assigned'
		  AND assigned_to_profile IS NOT NULL
		  AND (executing_token IS NULL OR executing_token = '')
		  AND COALESCE(assigned_at, modified) < %(cutoff)s
		LIMIT 50
		""",
		{"cutoff": cutoff},
		as_dict=True,
	)
	if not rows:
		return 0

	from friday.friday_core.observability import emit

	in_flight = _in_flight_job_names()
	acted = 0
	for row in rows:
		job_name = TASK_JOB_NAME.format(name=row["name"])
		if job_name in in_flight:
			continue  # the original trigger is still ticking — leave it
		_logger.warning(
			"reconciler: re-enqueuing Assigned-orphan task %s (profile=%s)",
			row["name"],
			row["assigned_to_profile"],
		)
		frappe.enqueue(
			"friday.friday_core.tasks.runner.on_agent_task_assigned",
			queue="friday",
			timeout=600,
			job_name=job_name,
			message={
				"task_name": row["name"],
				"assigned_to_profile": row["assigned_to_profile"],
				"workflow_state": "Assigned",
			},
		)
		emit(
			"reconciler.action",
			task=row["name"],
			agent_profile=row["assigned_to_profile"],
			trigger_source="re_enqueue_assigned_orphan",
			summary=f"re-enqueue: {row['name']} (orphaned Assigned)",
		)
		acted += 1
	return acted


def _reconcile_executing_stale() -> int:
	"""
	An Executing task without a recent heartbeat AND no in-flight job is
	one whose runner died mid-execution (worker crash; sandbox kill; OS
	signal). We block it with the structured reason `runner_lost`, file a
	Failure Issue (D6 — visible to humans), and post to the War Room.

	The heartbeat check matters: a long agentic turn keeps the heartbeat
	fresh, so this sweep cannot kill it. Only truly silent workers get
	caught.
	"""
	cutoff = frappe.utils.add_to_date(frappe.utils.now_datetime(), minutes=-EXECUTING_STALE_MINUTES)
	rows = frappe.db.sql(
		"""
		SELECT name
		FROM `tabAgent Task`
		WHERE workflow_state = 'Executing'
		  AND (last_heartbeat_at IS NULL OR last_heartbeat_at < %(cutoff)s)
		  AND COALESCE(started_at, modified) < %(cutoff)s
		LIMIT 50
		""",
		{"cutoff": cutoff},
		as_dict=True,
	)
	if not rows:
		return 0

	from friday.friday_core.observability import emit

	in_flight = _in_flight_job_names()
	acted = 0
	for row in rows:
		job_name = TASK_JOB_NAME.format(name=row["name"])
		if job_name in in_flight:
			continue  # genuinely running, just slow on heartbeats — leave it
		task = frappe.get_doc("Agent Task", row["name"])
		frappe.db.savepoint(_ROW_SAVEPOINT)
		frappe.flags.dispatcher_event_source = "reconciler_runner_lost"
		try:
			task.workflow_state = "Blocked"
			task.blocked_reason = "runner_lost"
			task.save(ignore_permissions=True)
			_raise_runner_lost_issue(row["name"])
			emit(
				"reconciler.action",
				task=row["name"],
				trigger_source="runner_lost",
				summary=f"runner_lost: {row['name']} (no heartbeat, no job in flight)",
			)
		except Exception:
			# Isolate the bad row: undo its partial writes so the aborted Postgres
			# tx is usable again, log loudly, and let the next tick retry it.
			frappe.db.rollback(save_point=_ROW_SAVEPOINT)
			_logger.warning(
				"reconciler: runner_lost rescue failed for %s — rolled back, will retry next tick",
				row["name"],
				exc_info=True,
			)
			continue
		finally:
			frappe.flags.dispatcher_event_source = None
		acted += 1
	return acted


def _reconcile_transient_blocked() -> int:
	"""
	A task blocked by a transient cause (oom, timeout, runner_lost) gets
	one more shot per tick (up to RETRY_BUDGET total). Re-Pend it cleanly:
	clear `assigned_to_profile` + `executing_token` so the dispatcher picks
	it up fresh on the next tick. Increment `retry_count` so we eventually
	stop.

	Semantic blocks (dependency_failed, no_profile_for_skills:*) need a
	human to fix the underlying condition — they are NOT retried here.
	"""
	cutoff = frappe.utils.add_to_date(frappe.utils.now_datetime(), minutes=-TRANSIENT_BLOCKED_GRACE_MINUTES)
	rows = frappe.db.sql(
		"""
		SELECT name, retry_count
		FROM `tabAgent Task`
		WHERE workflow_state = 'Blocked'
		  AND blocked_reason IN %(reasons)s
		  AND retry_count < %(budget)s
		  AND modified < %(cutoff)s
		LIMIT 50
		""",
		{"reasons": TRANSIENT_BLOCKED_REASONS, "budget": RETRY_BUDGET, "cutoff": cutoff},
		as_dict=True,
	)
	if not rows:
		return 0

	from friday.friday_core.observability import emit

	acted = 0
	for row in rows:
		task = frappe.get_doc("Agent Task", row["name"])
		old_blocked_reason = task.blocked_reason
		frappe.db.savepoint(_ROW_SAVEPOINT)
		frappe.flags.dispatcher_event_source = "reconciler_reset"
		try:
			task.workflow_state = "Pending"
			task.assigned_to_profile = None
			task.executing_token = None
			task.blocked_reason = None
			task.retry_count = (row.get("retry_count") or 0) + 1
			task.save(ignore_permissions=True)
			_logger.info(
				"reconciler: re-Pending transient-Blocked task %s (retry %s/%s)",
				row["name"],
				task.retry_count,
				RETRY_BUDGET,
			)
			emit(
				"reconciler.action",
				task=row["name"],
				trigger_source="re_pend_transient",
				summary=f"re-pend: {row['name']} (was Blocked: {old_blocked_reason}, retry {task.retry_count}/{RETRY_BUDGET})",
				payload={"blocked_reason": old_blocked_reason, "retry_count": task.retry_count},
			)
		except Exception:
			frappe.db.rollback(save_point=_ROW_SAVEPOINT)
			_logger.warning(
				"reconciler: re-pend failed for %s — rolled back, will retry next tick",
				row["name"],
				exc_info=True,
			)
			continue
		finally:
			frappe.flags.dispatcher_event_source = None
		acted += 1
	return acted


def _reconcile_connector_events() -> int:
	"""
	The connector durability gap (Design 81; was Q7a for RandomPack). The
	intake acks 200 and persists the event row as `Received`, then enqueues
	processing on the friday queue. If that worker was down at the moment of
	enqueue, the event sits Received forever — the source sees `Delivered` but
	Friday never processed it (the same disease this design treats for tasks).

	The sweep re-enqueues:
	  - Received events older than 60s (the original enqueue was lost), and
	  - Failed events older than 5 min, still under their retry budget.

	`process_event` is already short-circuited on `Processed`, so duplicate
	re-enqueues of a succeeded event are a no-op. We increment retry_count
	via SQL to dodge a get/save round trip per row.
	"""
	# Two cutoffs, one per status — Received events get a tight 60s grace
	# (the original enqueue should have fired by now), Failed events get a
	# longer 5-minute backoff before retrying.
	received_cutoff = frappe.utils.add_to_date(
		frappe.utils.now_datetime(), seconds=-CONNECTOR_EVENT_RECEIVED_GRACE_SECONDS
	)
	failed_cutoff = frappe.utils.add_to_date(
		frappe.utils.now_datetime(), minutes=-CONNECTOR_EVENT_FAILED_GRACE_MINUTES
	)
	rows = frappe.db.sql(
		"""
		SELECT name, status
		FROM `tabConnector Event`
		WHERE status IN ('Received', 'Failed')
		  AND retry_count < %(budget)s
		  AND (
		    (status = 'Received' AND modified < %(received_cutoff)s)
		    OR
		    (status = 'Failed' AND modified < %(failed_cutoff)s)
		  )
		LIMIT 50
		""",
		{
			"budget": RETRY_BUDGET,
			"received_cutoff": received_cutoff,
			"failed_cutoff": failed_cutoff,
		},
		as_dict=True,
	)
	if not rows:
		return 0

	acted = 0
	for row in rows:
		# Increment first, then enqueue. If the enqueue itself fails the row
		# is still marked as having been retried — exactly what we want for
		# observability (no infinite "we keep trying but no-one knows" loops).
		frappe.db.sql(
			"UPDATE `tabConnector Event` SET retry_count = COALESCE(retry_count, 0) + 1 WHERE name = %s",
			(row["name"],),
		)
		frappe.enqueue(
			"friday.friday_core.connectors.core.process_event",
			queue="friday",
			timeout=600,
			job_name=EVENT_JOB_NAME.format(event_id=row["name"]),
			event_id=row["name"],
		)
		_logger.warning(
			"reconciler: re-enqueuing stuck Connector Event %s (was %s)",
			row["name"],
			row["status"],
		)
		acted += 1
	return acted


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _in_flight_job_names() -> set[str]:
	"""
	Return the set of currently-known RQ job_names across all queues.

	`get_jobs()` returns {queue_name: [job_name, …]}; we flatten to a single
	set so callers can do a cheap O(1) membership check per row.
	"""
	try:
		jobs = get_jobs() or {}
	except Exception:
		_logger.warning("reconciler: get_jobs() failed; assuming no in-flight jobs")
		return set()
	flat: set[str] = set()
	for names in jobs.values():
		flat.update(names or [])
	return flat


def _raise_runner_lost_issue(task_name: str) -> None:
	"""
	File a Friday Issue for a runner-lost task and post to the War Room.

	The Issue lives in the existing Friday Issue tracker (it's the durable
	human-facing ledger for "agent system needs attention" events). The
	War Room post is the realtime nudge. Both fail-soft: if either path
	errors we still want the task marked Blocked so it doesn't keep
	getting picked up by the executing-stale sweep on the next tick.
	"""
	try:
		from friday.friday_core.issues.raise_issue import raise_failure_issue

		raise_failure_issue(task_name, "runner_lost")
	except Exception:
		_logger.exception("reconciler: failed to file runner_lost Issue for %s", task_name)
		frappe.log_error(title=f"friday.reconciler runner_lost issue failed: {task_name}")

	try:
		from friday.friday_core.warroom.publisher import post_task_update

		post_task_update(task_name, "runner_lost", {"reason": "no heartbeat / no in-flight job"})
	except Exception:
		_logger.warning("reconciler: War Room post failed for %s", task_name)
