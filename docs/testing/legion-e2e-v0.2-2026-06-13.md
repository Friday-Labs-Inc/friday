# Friday v0.2 — Full End-to-End Test on Legion (RandomPack loop)

**Audience:** the operator (you) **and** the Claude agent running on the Legion
machine. This runbook is written so the agent can drive each step, run the
verification, read the result, and tell you in plain English whether it passed.

**What this proves:** the whole v0.2 build, end to end — a real RandomPack
`project.created` becomes a planned pipeline, agents (each a real identity) run
it durably, report back in the War Room as themselves, produce real
deliverables without hallucinating, and you watch all of it live on the Project
Console with progress + cost rolling up — and when something dies, the pipeline
heals itself instead of stalling silently.

It covers Designs **61** (durable/observable pipeline), **62** (agents report
back), **63** (provider/model discovery), **65** (project module + live
console), **66** (agent toolbox + deliverables), and the **RandomPack** loop
(Design 60).

---

## How to use this (for the Claude agent on Legion)

- Replace `$SITE` with the Legion site name (e.g. `friday.localhost` or the real
  site). Find it with `bench --site all list` or read `currentsite.txt`.
- Run server checks with `bench --site $SITE execute <dotted.path> --kwargs '{...}'`
  or `bench --site $SITE console`.
- Hit whitelisted endpoints with `curl` using an authenticated session, **or**
  just call them in `bench console` — e.g.
  `frappe.call("frappe.friday_core.health.pipeline_health.pipeline_health")`.
- Every phase has a **VERIFY** block with the exact expected result. If a VERIFY
  fails, jump to **Troubleshooting** at the bottom — it's keyed to the health
  verdict. Do not proceed past a failed gate; report it.
- Drive Desk UI checks by giving the operator the exact URL and what to look
  for; the agent can't click for them, so describe the expected screen.

A note on pacing: the demo pipeline **pauses on purpose** at the two client
gates (`gate1`, `gate2`). That is not a stall — see Phase 7.

---

## Phase 0 — Preconditions & one-time setup

**0.1 — Code is current and migrated.**
```bash
cd ~/friday-bench   # or wherever the bench lives
git -C apps/frappe log --oneline -1     # should include the design-65d merge
bench --site $SITE migrate
```
`migrate` auto-runs the after_migrate provisioners: agent-User backfill, the
console views, the `friday` queue registration, the Agent Settings singleton.

**0.2 — Build assets (for the Gantt button + console page JS).**
```bash
bench build --app frappe
```

**0.3 — The `friday` queue worker is running.** This is the #1 cause of the
"tasks sit Pending forever" failure. It must be up.
```bash
# Is it in the Procfile? (bench start runs it automatically)
grep friday Procfile
# Running standalone (if not using `bench start`):
OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES NO_PROXY=* bench worker --queue friday &
```

**0.4 — The scheduler is on** (drives the dispatcher + reconciler cron).
```bash
bench --site $SITE scheduler status     # -> "enabled" and "active"
bench --site $SITE scheduler enable
```

**0.5 — Provision the surfaces + tools (idempotent; safe to re-run).**
```bash
bench --site $SITE execute frappe.friday_core.surfaces.bootstrap_raven.provision --kwargs '{"profile_name": "Friday"}'
bench --site $SITE execute frappe.friday_core.skills.bootstrap_read.provision  --kwargs '{"profile_name": "Friday"}'
bench --site $SITE execute frappe.friday_core.skills.bootstrap_files.provision --kwargs '{"profile_name": "Friday"}'
```

**0.6 — RandomPack settings are configured** (you said the RandomPack bench +
app are already installed). In Desk → **RandomPack Settings**:
- `enabled` = checked
- `webhook_secret` set (the HMAC secret the RandomPack side signs with)
- `api_base_url`, `api_key`, `api_secret` set (for write-back to RandomPack)

**VERIFY 0:**
```bash
bench --site $SITE console
```
```python
>>> import frappe
>>> frappe.db.count("Agent Profile")                 # >= 1
>>> frappe.db.get_value("RandomPack Settings", None, "enabled")   # 1
>>> frappe.db.exists("Raven Channel", {"channel_name": "friday_war_room"})  # truthy
```
✅ Pass when: at least one Agent Profile exists, RandomPack is enabled, the War
Room channel exists.

---

## Phase 1 — Health baseline

**1.1 — Pipeline health endpoint.**
```bash
bench --site $SITE console
```
```python
>>> frappe.call("frappe.friday_core.health.pipeline_health.pipeline_health")
```
**VERIFY 1:** the result dict has:
- `verdict` == `"ok"` (or `"degraded"` only if you already have >10 pending /
  >5 open issues — not `"down"`).
- `workers.friday.present` == `True`  ← if `False`, the worker (0.3) isn't up.
- `stuck.*` all `0`.

✅ This is the single "is the loop alive?" signal. If `verdict == "down"`, fix
that **before** loading any work — see Troubleshooting.

---

## Phase 2 — Agent identity (Design 65a)

Every Agent Profile should now have a backing, login-disabled Frappe User.

**VERIFY 2** (`bench console`):
```python
>>> profiles = frappe.get_all("Agent Profile", fields=["name", "frappe_user"])
>>> profiles                       # every row has a non-empty frappe_user
>>> # the user exists, is enabled, and CANNOT log in (no password):
>>> u = frappe.get_doc("User", profiles[0].frappe_user)
>>> (u.enabled, u.user_type)       # (1, "System User")
```
Desk check: **Settings → Users** → you'll see one user per agent
(`agent+<slug>@friday.local`), each with an avatar. Open one — there is no
password set; it exists only to be assigned/mentioned.

✅ Pass: each profile links to a system user that's enabled but has no
credential path.

---

## Phase 3 — Provider, model discovery & cost rates (Designs 63 + 65d)

**3.1 — Model discovery.** Desk → **LLM Provider** → open your provider (e.g.
Minimax/Anthropic/OpenAI) → click **Discover Models**. A picker lists the live
models; click one to set `default_model`. The badge shows **● live** (or
**● catalog** if no key).

**3.2 — Cost rates (needed for real cost rollup in Phase 9).** On the same LLM
Provider, set **Input Cost per Million** and **Output Cost per Million** (USD).
Without these, the pipeline still runs and progress rolls up, but cost shows
"—" instead of a number — by design (never a fabricated 0).

**VERIFY 3** (`bench console`):
```python
>>> frappe.call("frappe.friday_core.llm.model_discovery.list_models",
...             provider_name="<your provider name>")     # source: "live", models: [...]
>>> frappe.db.get_value("LLM Provider", "<name>", ["default_model", "input_cost_per_million"])
```
✅ Pass: a model is listed, `default_model` is set, and (for cost) rates are non-zero.

---

## Phase 4 — Native views exist (Design 65b)

Pure Desk checks — these were provisioned on migrate.

- **Workspace:** open `/app/projects` (the **Projects** workspace). You should
  see number cards (Active Projects, Tasks Executing, Tasks Blocked, Open
  Issues), two charts, and shortcuts (Project Console, Projects, Task Pipeline).
- **Kanban:** `/app/task/view/kanban/Task Pipeline` — columns are the 7 states
  (Pending → … → Cancelled).
- **Gantt:** `/app/task/view/gantt` — the Gantt button is present (it appears
  because `task_calendar.js` is built; if missing, re-run `bench build`).

**VERIFY 4** (`bench console`):
```python
>>> frappe.db.exists("Workspace", "Projects")            # truthy
>>> frappe.db.exists("Kanban Board", "Task Pipeline")    # truthy
>>> frappe.db.exists("Number Card", "Friday Tasks Executing")  # truthy
```
✅ Pass: workspace, kanban board, and number cards exist.

---

## Phase 5 — Drive a real RandomPack project into a pipeline (Designs 60 + 61)

This is the heart of the test. Two ways — prefer **5A** (true end-to-end from
the RandomPack side); use **5B** if you want to drive it locally.

### 5A — From the RandomPack app (true E2E)

In the RandomPack bench/app, take a project through to the point where it emits
`payment.received` then `project.created` to Friday's webhook:
```
POST /api/method/frappe.friday_core.surfaces.randompack.receive_event
Header: X-RP-Signature: t=<unix>,v1=<hmac_sha256( "<t>.<raw_body>", webhook_secret )>
```
(`payment.received` first creates the Brand Brief; `project.created` then creates
the Project and plans the pipeline.)

### 5B — Simulate the inbound events locally (`bench console`)

```python
import frappe, json, time
from frappe.friday_core.surfaces import randompack

brief = {"company":"Acme","industry":"SaaS","audience":"Developers",
         "differentiator":"Fastest CI","personality_attributes":["bold","clear"],
         "references":"stripe.com","brands_admired":"Notion","brands_avoid":"legacy ERP"}

# 1) payment.received -> creates the Brand Brief tagged [rp:rp-proj-001]
randompack.handle_payment_received({"project_id":"rp-proj-001","brief_snapshot":brief}, event=None)
# 2) project.created  -> creates the Project + instantiates the 9-task pipeline
randompack.handle_project_created({"project_id":"rp-proj-001"}, event=None)
frappe.db.commit()
```

**VERIFY 5** (`bench console`):
```python
>>> proj = frappe.db.get_value("Project", {"backend_ref": "rp-proj-001"}, "name")
>>> proj                                  # a Project exists
>>> frappe.db.count("Task", {"project": proj})        # 9 tasks
>>> frappe.get_all("Task", filters={"project": proj},
...     fields=["title","workflow_state","execution_mode","backend_ref"], order_by="creation")
```
✅ Pass: a Project with **9 Tasks** — `strategy, naming, directions, gate1_prep,
gate1 (milestone), buildout, gate2_prep, gate2 (milestone), guidelines` — with
dependencies wired. The `strategy` task should be `Pending` and dispatchable;
the rest wait on their dependencies.

---

## Phase 6 — Watch it run, live (Designs 61 + 62 + 65c)

**6.1 — Open the live console:** `/app/project-console`.
- **Health strip** shows 🟢 ok + live counts + `friday worker: up`.
- **Project lane** shows your project card; click it to scope.
- **Live activity feed** updates **in real time** (no refresh) as tasks move:
  you'll see rows like `🤖 Strategist — strategy · Executing` then `· Completed`,
  each naming the agent that did the work.

**6.2 — Watch the War Room:** the Raven `FRIDAY_WAR_ROOM` channel narrates the
same transitions, each posted **as the agent** (not one faceless "Friday").

Within a minute or two (the dispatcher tick + agent turns), tasks should flow
`Pending → Assigned → Executing → Review/Completed`. `directions` produces brand
directions via the `create-brand-direction` skill.

**VERIFY 6** (`bench console`, after ~2–5 min):
```python
>>> frappe.call("frappe.friday_core.console.console_snapshot.console_snapshot", project=proj)
```
Check: `health.verdict` ok; `active_tasks` shows what's running; `recent_activity`
lists completed transitions with their `assigned_to_profile`. And the **console
page feed moved without you refreshing**.

✅ Pass: tasks progress on their own; the console feed and War Room both show
per-agent activity live. **No task sits Pending with the worker up** (if one
does, that's the exact bug Design 61 fixes — check Troubleshooting).

---

## Phase 7 — The gates pause on purpose (milestone tasks)

The pipeline will run up to `gate1_prep`, then **stop at `gate1`** — a
`milestone` task that is *not* auto-run; it waits for the client to pick a
direction. **This is correct behavior, not a stall.** The health verdict stays
`ok`; `gate1` sits `Pending` as a milestone.

**Advance the gate** (simulating the client's pick) — either from RandomPack
(`gate.decided` event) or locally:
```python
randompack.handle_gate_decided({"project_id":"rp-proj-001","gate":"gate1","decision":"approved","choice":"Direction B"}, event=None)
frappe.db.commit()
```
Then `buildout` unblocks and runs; repeat for `gate2` to reach `guidelines`.

**VERIFY 7:** after deciding gate1, `buildout` leaves Pending and runs; the
console feed shows it. ✅ Pass: gates hold until decided, then downstream tasks
flow.

---

## Phase 8 — Tools, no hallucination, real deliverables (Design 66)

**8.1 — Deliverables are real Files.** When `directions`/`buildout` finish, the
agent should have attached deliverables to the Project via `attach-deliverable`.

**VERIFY 8** (`bench console`):
```python
>>> frappe.get_all("File", filters={"attached_to_doctype":"Project","attached_to_name":proj},
...                 fields=["file_name"])
```
Desk check: open the Project → the **attachments sidebar** lists the deliverable
files. The console project card shows a deliverable count.

**8.2 — No fabrication.** Read a completed task's `result` summary
(`frappe.db.get_value("Task", "<name>", "result")`). The agent's summary should
reference records/files it actually created (which exist per 8.1) — not invented
ones. If an agent lacked a tool, it should have said so plainly, not fabricated.

✅ Pass: finished work exists as real attached Files; task summaries reference
only things that actually exist.

---

## Phase 9 — Progress & cost rollup (Design 65d)

As tasks complete, the Project's derived fields fill in.

**VERIFY 9** (`bench console`):
```python
>>> frappe.db.get_value("Project", proj, ["percent_complete","total_tasks",
...     "completed_tasks","actual_start_date","actual_end_date","actual_cost_usd"], as_dict=True)
```
Check:
- `total_tasks` == 9; `completed_tasks` rises as tasks finish; `percent_complete`
  tracks it.
- `actual_start_date` set once the first task started.
- `actual_end_date` stays empty until **every** task is terminal (and not while
  any is Blocked) — then it's the last completion date.
- `actual_cost_usd`: a real number **if** you set provider rates in Phase 3;
  otherwise `None`/blank (the console shows "—"). A per-task value:
  `frappe.db.get_value("Task","<agentic task>","cost_usd")`.

The console project card's **%-complete bar** and the number cards reflect all
of this.

✅ Pass: counts + %-complete advance with real task completion; cost is a real
figure when rates are set, honestly blank otherwise.

---

## Phase 10 — Durability / self-heal (Design 61) — the anti-stall proof

This proves the system heals instead of silently dying (the original Legion
incident).

**10.1 — Kill the worker mid-run**, then load more work:
```bash
# find and stop the friday worker process
pkill -f "bench worker --queue friday"
```
Trigger a task (e.g. decide the next gate, or re-run 5B with a new project_id).
The task enters `Assigned`/`Pending` but cannot execute.

**VERIFY 10a:** within ~60s, `pipeline_health()` flips to `verdict: "down"` with
`workers.friday.present: False`. The console health strip turns 🔴. **The
failure is loud, not silent.**

**10.2 — Bring the worker back:**
```bash
OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES NO_PROXY=* bench worker --queue friday &
```
**VERIFY 10b:** within a minute the reconciler re-enqueues the stranded task (no
manual poke), it runs, health returns to 🟢. ✅ Pass: the pipeline self-heals;
nothing sits stranded for hours.

(Optional) Kill a worker *while a task is Executing*: after the 15-minute
heartbeat grace, the reconciler marks it `Blocked` with `runner_lost`, raises an
Issue, and (for transient reasons) retries up to 3×. You'll see the Issue in
**Open Issues** and the War Room.

---

## Phase 11 — Cleanup (optional)

```python
# remove the test project + its tasks (bench console)
proj = frappe.db.get_value("Project", {"backend_ref":"rp-proj-001"}, "name")
for t in frappe.get_all("Task", filters={"project": proj}, pluck="name"):
    frappe.delete_doc("Task", t, force=1)
frappe.delete_doc("Project", proj, force=1)
frappe.db.commit()
```
Leave the agent users, views, and bootstrapped tools in place — they're
permanent infrastructure.

---

## Troubleshooting (keyed to the health verdict)

| Symptom | Likely cause | Fix |
|---|---|---|
| `verdict: down`, `workers.friday.present: False` | the `friday` worker isn't running | start it (0.3); confirm `bench start` includes `worker_friday` |
| Tasks stuck `Pending`, worker up | scheduler off (dispatcher cron not firing) | `bench --site $SITE scheduler enable` (0.4) |
| `verdict: down`, `stuck.* > 0` | a task lost its runner / went stale | the reconciler heals on the next tick; check **Open Issues** for `runner_lost` |
| `project.created` did nothing | HMAC mismatch, or no Brand Brief for the ref | check `X-RP-Signature` + `webhook_secret`; run `payment.received` first (5B step 1) |
| Pipeline "stuck" at `gate1`/`gate2` | **not a bug** — milestones wait for a decision | decide the gate (Phase 7) |
| Console feed not updating live | realtime/socketio not connected | hard-refresh; confirm `bench start` runs the socketio process; the 30s poll still updates it |
| `cost_usd` / `actual_cost_usd` blank | no per-million rates on the LLM Provider | set them (Phase 3) — blank-when-unset is intended, never a fake 0 |
| Gantt button missing | assets not built | `bench build --app frappe` + hard-refresh |

**Where to look when in doubt:** the **Project Console** health strip + the
`pipeline_health()` endpoint are the single source of truth. If they say `ok`
and a task isn't moving, it's almost certainly a milestone gate waiting for a
decision (Phase 7), not a failure.
