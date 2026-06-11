# Testing Friday on Legion — crystal-clear runbook

**Tailored to:** Linux · an existing Frappe bench is already present (so we build
a fully **isolated** second bench on its own ports) · full capability test
(chat + brand directions + multi-agent delegation + Raven team chat).

Run every command from a terminal on Legion. Copy-paste blocks as-is.

---

## ⚠️ TWO THINGS BEFORE YOU START

1. **Rotate your MiniMax API key** in the MiniMax dashboard. The old key was
   pasted into a chat and must be treated as burned. Have the **new** key ready.
2. **Never put the key (or any password) into a file.** We pass the key through
   an environment variable that lives only in your current shell.

> **Shortcut option:** if you can briefly pause your other bench, you can skip
> all the port juggling — stop it, then in Part 1 **skip the "set isolated
> ports" block** and use defaults. Everything else is identical. The steps
> below assume you want **both benches running at once** (full isolation).

---

## PART 0 — Pick a free port slot (1 min)

Your existing bench likely uses 8000 / 9000 / 11000 / 13000. Friday will use the
"05" slot. Confirm it's free:

```bash
for p in 8005 9005 11005 13005 6792; do lsof -i :$p >/dev/null 2>&1 && echo "PORT $p BUSY" || echo "port $p free"; done
```

✅ **Expect:** all "free". If any says BUSY, change every `…05` below to `…06`.

---

## PART 1 — Create the isolated Friday bench

Friday **is** a fork of Frappe, so we init a bench that uses the fork as its
`frappe` app:

```bash
cd ~
bench init --frappe-path https://github.com/Friday-Labs-Inc/friday --frappe-branch main friday-bench
cd friday-bench
```

✅ **Expect:** it clones the fork, installs Python deps, builds frontend assets.

⚠️ **Gotchas:**
- Friday is **Frappe v16** → needs **Node ≥ 24** and **Python ≥ 3.10**.
- If the asset/yarn build fails on Node version: `nvm install 24 && nvm use 24`
  then re-run `bench init`. Or append `--skip-assets` (assets are only needed
  for the browser UI in Part 6 — the CLI tests work without them).
- If `bench init` complains about Python, add `--python python3.11`.

**Set the isolated ports** (so Friday's redis/web never touch your other bench):

```bash
bench set-config -g webserver_port 8005
bench set-config -g socketio_port 9005
bench set-config -g file_watcher_port 6792
bench set-config -g redis_cache    "redis://127.0.0.1:13005"
bench set-config -g redis_queue    "redis://127.0.0.1:11005"
bench set-config -g redis_socketio "redis://127.0.0.1:13005"
sed -i 's/^port .*/port 13005/' config/redis_cache.conf
sed -i 's/^port .*/port 11005/' config/redis_queue.conf
grep -H '^port' config/redis_cache.conf config/redis_queue.conf
```

✅ **Expect:** the last line prints `…redis_cache.conf:port 13005` and
`…redis_queue.conf:port 11005`.

---

## PART 2 — Create the site (Postgres)

```bash
bench new-site friday.localhost --db-type postgres --db-host 127.0.0.1 --db-port 5432
```

- It prompts for the **Postgres superuser password** (the `postgres` role on
  Legion).
- It prompts you to set a new **Administrator password** — remember it; that's
  your browser/Desk login.

✅ **Expect:** "Site friday.localhost created". This also installs Friday's
schema (the `friday_core` doctypes).

```bash
bench --site friday.localhost migrate
```

✅ **Expect:** ends clean. **This is the health gate** — if migrate is clean,
the whole Friday schema is good.

---

## PART 3 — Configure the model + skills

Paste your **new** key into THIS shell only, then run setup:

```bash
export FRIDAY_API_KEY='PASTE_YOUR_NEW_MINIMAX_KEY_HERE'
bench --site friday.localhost friday setup --provider-type minimax --model MiniMax-M2 --provider-name "Minimax" --profile "Friday"
```

✅ **Expect:**
```
✓ LLM Provider 'Minimax' (minimax, MiniMax-M2) configured.
✓ Agent Profile 'Friday' is Active.
```

Provision the skills and the specialist profile:

```bash
bench --site friday.localhost execute frappe.friday_core.skills.bootstrap_brand.provision
bench --site friday.localhost execute frappe.friday_core.skills.bootstrap_delegate.provision
bench --site friday.localhost execute frappe.friday_core.cli.setup.provision_profile --kwargs "{'profile_name':'Copywriter','provider_name':'Minimax','system_prompt':'You are a senior brand copywriter. Sharp, distinctive, ready-to-use copy.'}"
```

✅ **Expect:** `✓ Brand skills provisioned…`, `✓ Delegation provisioned…`, and
`Copywriter`.

---

## PART 4 — Start it

In its **own terminal** (leave it running):

```bash
cd ~/friday-bench && bench start
```

✅ **Expect:** web on **http://friday.localhost:8005**, plus socketio, redis,
and workers. (No dedicated friday-worker is needed for testing — turns run
inline automatically via the gateway's fallback.)

---

## PART 5 — Test every capability

Open a **second terminal**: `cd ~/friday-bench`

### Test 1 — the agent answers (smoke test)
```bash
bench --site friday.localhost execute frappe.friday_core.agent_runner.runner.run_turn --args "['Friday','legion-1','In one sentence, who are you?']"
```
✅ **Expect:** a real one-sentence MiniMax reply, with no `<think>` leakage.

### Test 2 — brand directions (the product)
```bash
bench --site friday.localhost execute frappe.client.insert --kwargs "{'doc':{'doctype':'Brand Brief','business_name':'Legion Coffee','industry':'Specialty roastery','what_they_do':'Single-origin subscription coffee','target_audience':'Urban pros 25-40','brand_personality':'warm, crafted, honest','status':'Ready'}}"
bench --site friday.localhost execute frappe.friday_core.cli.chat.handle_user_message --args "['Friday','legion-brand','Generate 3 distinct brand directions for brief BB-0001, each with palette, typography, logo concept and taglines.']"
bench --site friday.localhost execute frappe.client.get_list --kwargs "{'doctype':'Brand Direction','filters':{'brief':'BB-0001'},'fields':['name','direction_name']}"
```
✅ **Expect:** the agent describes 3 directions, and the last command lists 3
saved `Brand Direction` rows.

### Test 3 — multi-agent delegation
```bash
bench --site friday.localhost execute frappe.friday_core.cli.chat.handle_user_message --args "['Friday','legion-deleg','Delegate to the Copywriter profile: write 3 taglines for Legion Coffee. Then tell me your favorite and why.']"
bench --site friday.localhost execute frappe.client.get_list --kwargs "{'doctype':'Task','filters':{'workflow_state':'Completed'},'fields':['name','assigned_to_profile'],'order_by':'creation desc','limit_page_length':1}"
```
✅ **Expect:** Friday returns the Copywriter's taglines + its own pick, and a
Completed `Task` row assigned to `Copywriter`.

### Test 4 — the audit + cost trail
```bash
bench --site friday.localhost execute frappe.client.get_list --kwargs "{'doctype':'LLM Usage Log','fields':['session_id','model','total_tokens'],'order_by':'creation desc','limit_page_length':6}"
```
✅ **Expect:** rows with token counts for every turn above. (Set Input/Output
cost-per-million on the Minimax LLM Provider in Desk to see dollars.)

---

## PART 6 — Raven (team chat UI)

```bash
bench --site friday.localhost friday setup-raven --install
bench build --app raven
```
✅ **Expect:** `✓ Raven surface ready…`, then assets compile. **Restart**
`bench start` (Ctrl-C the running one and re-run it).

Then in a browser → **http://friday.localhost:8005/raven** → log in as
`Administrator` (the password from Part 2) → **DM the Friday bot**, or
**@mention it in a channel**.

✅ **Expect:** governed replies appear in the chat UI. The **FRIDAY_WAR_ROOM**
channel shows task/delegation updates.

---

## IF SOMETHING FAILS

- **A command errors:** copy the **first** `Error in query` line or traceback
  line and send it over — that's the real cause; everything after it is noise.
- **`bench start` won't bind a port:** something else grabbed it — switch the
  whole slot from `05` → `06` (Part 0/1).
- **chat returns `(no reply…)`:** check the latest errors:
  ```bash
  bench --site friday.localhost execute frappe.client.get_list --kwargs "{'doctype':'Error Log','fields':['method','creation'],'order_by':'creation desc','limit_page_length':3}"
  ```
- **Raven UI is blank/404:** the asset build didn't finish — re-run
  `bench build --app raven`, then restart `bench start`.

---

## WHAT "ALL GREEN" LOOKS LIKE

Tests 1–4 produce real output + saved rows, and Raven gives you a chat reply in
the browser. That's the full proof: a governed agent, producing sellable brand
work, delegating to a specialist, talking to your team — all audited and
cost-accounted — running on Legion.
