# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt

"""Non-chat eval probes (Design 91 · Slice 3).

The chat scenarios drive `run_turn` and score tool-selection / quality. But two of
the four bugs that motivated this harness are NOT chat turns:

  * **#138 `/stop force`** — a robustness/interrupt case. The bug: a force-kill
    targeted the wrong RQ job key ("0 jobs cancelled"). The real-path gap a unit test
    can't cover: does `force_kill_session` actually transition live Task rows to
    `ForceKilled` and write the audit fields? The probe sets up a real in-flight task,
    drives the genuine force-stop function, and scores the audit trail.

  * **#132 pgvector migrate-gate** — a migration/infra case. The bug: a failing DDL
    (pgvector absent) poisoned the whole Postgres transaction, so every later
    `after_migrate` hook died with `InFailedSqlTransaction`. The unit tests mock the
    failure; only a REAL Postgres connection can prove the savepoint-rollback recovery
    actually keeps the transaction usable. The probe re-runs the real schema setup
    (idempotent) and proves a failed statement inside a savepoint leaves the txn alive.

A probe is `probe(scenario, session_id) -> {"ok": bool, "checks": [{name, ok, detail}],
"detail": str}`. The runner calls it instead of the chat flow and passes/fails the run
on `ok`. Probes are SANDBOX-ONLY (they write rows / run DDL) — `run.run` already
refuses production. Each probe cleans up rows it creates.

HONEST SCOPE
------------
The force-kill probe pins the real-path AUDIT outcome (Task → ForceKilled + fields +
event); it does NOT spin up a real RQ worker, so the job-id transform regression (#138's
exact root cause) stays pinned by the mocked unit test `test_stop_force.py`. The
pgvector probe proves the savepoint *recovery* works on the real backend; on a box that
HAS pgvector the schema DDL simply succeeds, so the savepoint check is what carries the
#132 regression signal.
"""

from __future__ import annotations

import frappe

_FORCE_KILL_OPERATOR = "eval-operator@friday.local"


def probe_force_kill_audit(scenario, session_id: str) -> dict:
	"""Drive the real `/stop force` path against a live task; score the audit trail (#138)."""
	from friday.friday_core.gateway.interrupt import force_kill_session

	created: list[tuple[str, str]] = []
	checks: list[dict] = []
	try:
		task = frappe.get_doc(
			{
				"doctype": "Agent Task",
				"title": f"eval force-kill {session_id}",
				"priority": "normal",
				"workflow_state": "Executing",
				"originating_session": session_id,
			}
		).insert(ignore_permissions=True)
		created.append(("Agent Task", task.name))

		# We deliberately do NOT insert an inbound Chat Message to fake an in-flight chat
		# job. Inserting one fires the gateway `after_insert` (gateway.service.handle_inbound),
		# which immediately CONSUMES the row (so force-kill's own `_latest_running_job`
		# lookup can't find it) AND would enqueue a REAL agent turn — a side effect a probe
		# must never cause. A live run caught exactly this (cancelled=0/already_done=0). The
		# chat-job SIGTERM + #138 job-id transform stay pinned by the mocked unit test
		# (test_stop_force.py); this probe's job is the LIVE AUDIT OUTCOME on a real Task.
		result = force_kill_session(session_id, _FORCE_KILL_OPERATOR)

		state = frappe.db.get_value(
			"Agent Task",
			task.name,
			["workflow_state", "force_killed_by", "force_kill_reason"],
			as_dict=True,
		)
		checks.append(
			{
				"name": "task → ForceKilled",
				"ok": state.workflow_state == "ForceKilled",
				"detail": state.workflow_state,
			}
		)
		checks.append(
			{
				"name": "force_killed_by recorded",
				"ok": state.force_killed_by == _FORCE_KILL_OPERATOR,
				"detail": state.force_killed_by,
			}
		)
		checks.append(
			{
				"name": "force_kill_reason recorded",
				"ok": state.force_kill_reason == "operator /stop force",
				"detail": state.force_kill_reason,
			}
		)
		checks.append(
			{
				"name": "task in force-kill summary",
				"ok": task.name in result.get("tasks_now_forcekilled", []),
				"detail": str(result),
			}
		)
		# Soft check: the audit event landed (best-effort emit) — reported, but it does
		# NOT gate the probe (a missing observability row isn't a force-kill failure).
		ev = frappe.get_all("Dispatcher Event", filters={"event_type": "gateway.force_kill"}, limit=1)
		checks.append(
			{
				"name": "gateway.force_kill audit event",
				"ok": bool(ev),
				"detail": "present" if ev else "absent",
				"soft": True,
			}
		)
	finally:
		for doctype, name in reversed(created):
			try:
				frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)
			except Exception:
				pass

	# Gate the probe on the HARD checks (the live audit outcome); soft checks (the
	# best-effort audit event) are reported but don't fail the probe.
	hard = [c for c in checks if not c.get("soft")]
	return {"ok": all(c["ok"] for c in hard), "checks": checks, "detail": f"force_kill on {session_id}"}


def probe_pgvector_no_poison(scenario, session_id: str) -> dict:
	"""Re-run the pgvector schema setup + prove savepoint recovery on real Postgres (#132)."""
	checks: list[dict] = []

	if frappe.db.db_type != "postgres":
		return {
			"ok": True,
			"checks": [
				{
					"name": "postgres-only probe",
					"ok": True,
					"detail": f"db_type={frappe.db.db_type} — skipped",
				}
			],
			"detail": "non-postgres: nothing to prove",
		}

	from friday.friday_core.llm import after_migrate

	# 1) Re-run the REAL idempotent schema setup. Each must leave the transaction
	#    usable (a follow-up SELECT 1 must still work) — the exact #132 invariant.
	for fn in (
		after_migrate.ensure_memory_search_schema,
		after_migrate.ensure_memory_embedding_schema,
		after_migrate.ensure_chatmessage_search_schema,
	):
		try:
			fn()
			alive = frappe.db.sql("SELECT 1")
			checks.append(
				{"name": f"{fn.__name__} leaves txn alive", "ok": bool(alive), "detail": "SELECT 1 ok"}
			)
		except Exception as exc:
			checks.append(
				{
					"name": f"{fn.__name__} leaves txn alive",
					"ok": False,
					"detail": f"{type(exc).__name__}: {exc}",
				}
			)

	# 2) Direct proof the savepoint-rollback recovery (#132's fix) works on THIS
	#    Postgres: a guaranteed-failing statement inside a savepoint, rolled back, must
	#    leave the surrounding transaction usable. WITHOUT the rollback this SELECT 1
	#    would raise InFailedSqlTransaction — which is exactly the bug.
	sp = "eval_pgvector_probe"
	# Heads-up: the next statement is MEANT to fail, so Postgres/frappe will log a scary
	# "Error in query" + traceback to stderr. That is the probe working (proving the
	# savepoint rolls it back), NOT a crash — the run continues and the report is clean.
	print("[pgvector probe] the next 'Error in query' on stderr is INTENTIONAL (proving savepoint recovery).")
	try:
		frappe.db.savepoint(sp)
		try:
			frappe.db.sql("SELECT 1 FROM `__friday_eval_nonexistent_xyz`")
		except Exception:
			frappe.db.rollback(save_point=sp)
		alive = frappe.db.sql("SELECT 1")
		checks.append(
			{
				"name": "savepoint rollback keeps txn alive",
				"ok": bool(alive),
				"detail": "recovered after a failed statement",
			}
		)
	except Exception as exc:
		checks.append(
			{
				"name": "savepoint rollback keeps txn alive",
				"ok": False,
				"detail": f"{type(exc).__name__}: {exc}",
			}
		)

	return {
		"ok": all(c["ok"] for c in checks),
		"checks": checks,
		"detail": "pgvector re-run + savepoint recovery",
	}


# The registry the runner resolves `Scenario.probe` against.
PROBES = {
	"force_kill_audit": probe_force_kill_audit,
	"pgvector_no_poison": probe_pgvector_no_poison,
}
