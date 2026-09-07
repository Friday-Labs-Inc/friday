# Slice 1 — Foundations & Friday Core DocTypes

> **Status:** READY. Pre-implementation prompt for any AI coding agent (Codex, Claude Code, Cursor, Aider) or human contributor.
>
> **Self-contained.** You should not need to read other design docs to complete this slice. References are provided if you want context.
>
> **Hand-off rule:** if any step blocks you, stop and file a Blocker Report (see CODEX.md §8). Do not silently guess.

---

## 1. Big Picture

Friday is a hard fork of Frappe v16 with agent-native modifications. The Friday repository IS the kernel — there is no separate Friday app. Agent kernel DocTypes live inside the Frappe source tree under a new module called `Friday Core`.

Slice 1 creates that module and the eight core DocTypes that the rest of Phase 1 depends on. Nothing more.

**Done = all eight DocTypes exist, migrations run clean, you can create one row of each from the Frappe Desk UI, one test asserts they exist with correct fields.**

---

## 2. Pre-flight Checks (verify before starting)

Run these on the Legion. Each must pass.

```bash
cd /home/friday/friday/friday-bench

# 1. apps/frappe points at Friday-Labs-Inc/friday, on main
cd apps/frappe
git remote -v | grep -q "Friday-Labs-Inc/friday.git" || echo "FAIL: wrong remote"
git rev-parse --abbrev-ref HEAD | grep -q "^main$" || echo "FAIL: not on main"
cd ../..

# 2. Site exists, migrations clean
bench --site friday.localhost migrate
# Expected: no errors, output ends without 'pending patches'

# 3. PostgreSQL extensions enabled
bench --site friday.localhost mariadb-or-psql -c "SELECT extname FROM pg_extension;" 2>/dev/null \
  || sudo -u postgres psql friday_localhost -c "SELECT extname FROM pg_extension;"
# Expected: list includes 'vector' and 'pg_trgm'

# 4. Developer mode on
bench --site friday.localhost console <<< "import frappe; print(frappe.conf.developer_mode)"
# Expected: 1 (or True)
```

If any check fails, **STOP** and resolve before continuing.

---

## 3. Build Steps

### Step 3.1 — Create the `friday_core` module

```bash
cd /home/friday/friday/friday-bench/apps/frappe/frappe

# Module directory + Python package marker + doctype subfolder + tests subfolder
mkdir -p friday_core/doctype friday_core/tests
touch friday_core/__init__.py friday_core/tests/__init__.py

# Register the module by appending to Frappe's modules.txt
grep -qxF "Friday Core" modules.txt || echo "Friday Core" >> modules.txt
```

### Step 3.2 — Create the eight DocTypes

For each DocType below: create a folder `friday_core/doctype/<snake_name>/` and inside it create three files:

1. `__init__.py` (empty)
2. `<snake_name>.json` — the DocType definition (template below)
3. `<snake_name>.py` — empty controller class (template below)

#### JSON template (replace placeholders)

```json
{
 "doctype": "DocType",
 "name": "<HUMAN NAME>",
 "module": "Friday Core",
 "engine": "InnoDB",
 "naming_rule": "<see per-doctype>",
 "autoname": "<see per-doctype>",
 "is_submittable": 0,
 "track_changes": 1,
 "fields": [<see per-doctype>],
 "permissions": [
   {"role": "System Manager", "read": 1, "write": 1, "create": 1, "delete": 1, "submit": 0, "cancel": 0, "amend": 0},
   {"role": "Agent Supervisor", "read": 1, "write": 1, "create": 1, "delete": 0, "submit": 0, "cancel": 0, "amend": 0}
 ]
}
```

(For submittable DocTypes, set `is_submittable: 1` and add `"submit": 1, "cancel": 1, "amend": 1` to the System Manager permission row.)

#### Python controller template

```python
# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class <ClassName>(Document):
    pass
```

(`<ClassName>` is the CamelCase of the DocType name. E.g. `Agent Profile` → `AgentProfile`.)

#### DocType specs

Naming rule: where the table says "Set by user", `naming_rule = "Set by user"` and `autoname = "field:<fieldname>"` — pick the natural identifier. Where the table says "Autoincrement", `naming_rule = "Autoincrement"` and omit `autoname`.

##### (1) Agent Profile

- **Naming:** Set by user, field = `profile_name`
- **Submittable:** No

| fieldname | label | fieldtype | options | reqd |
|---|---|---|---|---|
| profile_name | Profile Name | Data |  | 1 |
| description | Description | Text |  | 0 |
| assigned_roles | Assigned Roles | Table | Has Role | 0 |
| model_provider | Model Provider | Link | DocType (later replaced by Provider DocType) | 0 |
| model_name | Model Name | Data |  | 0 |
| system_prompt | System Prompt | Long Text |  | 0 |
| permitted_skills | Permitted Skills | Table | Agent Profile Skill | 0 |
| network_allowlist | Network Allowlist | Small Text |  | 0 |
| requires_approval_above_risk | Requires Approval Above Risk | Select | low\nmedium\nhigh\nalways | 0 |
| status | Status | Select | Active\nSuspended\nRetired | 1 |

> Note: `model_provider` is a Link to `DocType` in Slice 1 as a placeholder. Slice 5 (LLM Integration) replaces this with a real `LLM Provider` DocType.

##### (2) Agent Profile Skill (child table for permitted_skills)

- **Naming:** Autoincrement
- **Submittable:** No
- **is_child_table:** Yes (`"istable": 1` in JSON)

| fieldname | label | fieldtype | options | reqd |
|---|---|---|---|---|
| skill | Skill | Link | Skill | 1 |
| notes | Notes | Small Text |  | 0 |

##### (3) Skill

- **Naming:** Set by user, field = `skill_name`
- **Submittable:** No

| fieldname | label | fieldtype | options | reqd |
|---|---|---|---|---|
| skill_name | Skill Name | Data |  | 1 |
| description | Description | Text |  | 1 |
| when_to_use | When To Use | Long Text |  | 0 |
| instructions | Instructions | Long Text |  | 0 |
| parameters_schema | Parameters Schema (JSON) | JSON |  | 0 |
| required_doctypes | Required DocTypes | Table | Skill Required DocType | 0 |
| risk_level | Risk Level | Select | low\nmedium\nhigh\ncritical | 1 |
| requires_approval | Requires Approval | Check |  | 0 |
| status | Status | Select | Draft\nExperimental\nActive\nRetired\nArchived | 1 |
| usage_count | Usage Count | Int |  | 0 |
| last_used | Last Used | Datetime |  | 0 |
| created_by_agent | Created By Agent | Link | Agent Profile | 0 |

##### (4) Skill Required DocType (child table)

- **Naming:** Autoincrement
- **is_child_table:** Yes

| fieldname | label | fieldtype | options | reqd |
|---|---|---|---|---|
| target_doctype | Target DocType | Link | DocType | 1 |
| operation | Operation | Select | read\nwrite\ncreate\nsubmit\ncancel\ndelete | 1 |

##### (5) Agent Project

- **Naming:** Set by user, field = `project_name`
- **Submittable:** No

| fieldname | label | fieldtype | options | reqd |
|---|---|---|---|---|
| project_name | Project Name | Data |  | 1 |
| description | Description | Long Text |  | 0 |
| status | Status | Select | Open\nIn Progress\nCompleted\nCancelled | 1 |

##### (6) Agent Task

- **Naming:** Autoincrement (so tasks are numbered)
- **Submittable:** No

| fieldname | label | fieldtype | options | reqd |
|---|---|---|---|---|
| title | Title | Data |  | 1 |
| description | Description | Long Text |  | 0 |
| project | Project | Link | Agent Project | 0 |
| assigned_to_profile | Assigned To Profile | Link | Agent Profile | 0 |
| required_skills | Required Skills | Table | Agent Task Skill | 0 |
| workflow_state | Workflow State | Data |  | 0 |
| dispatchable | Dispatchable | Check |  | 0 |
| priority | Priority | Select | low\nnormal\nhigh\nurgent | 1 |
| result | Result (JSON) | JSON |  | 0 |
| started_at | Started At | Datetime |  | 0 |
| completed_at | Completed At | Datetime |  | 0 |

##### (7) Agent Task Skill (child table)

- **Naming:** Autoincrement
- **is_child_table:** Yes

| fieldname | label | fieldtype | options | reqd |
|---|---|---|---|---|
| skill | Skill | Link | Skill | 1 |

##### (8) Chat Message

- **Naming:** Autoincrement
- **Submittable:** No

| fieldname | label | fieldtype | options | reqd |
|---|---|---|---|---|
| session_id | Session ID | Data |  | 1 |
| platform | Platform | Link | Chat Platform | 0 |
| direction | Direction | Select | inbound\noutbound | 1 |
| sender_id | Sender ID | Data |  | 0 |
| agent_profile | Agent Profile | Link | Agent Profile | 0 |
| content | Content | Long Text |  | 0 |
| timestamp | Timestamp | Datetime |  | 1 |
| processed | Processed | Check |  | 0 |

##### (9) Chat Platform

- **Naming:** Set by user, field = `platform_name`
- **Submittable:** No

| fieldname | label | fieldtype | options | reqd |
|---|---|---|---|---|
| platform_name | Platform Name | Data |  | 1 |
| adapter_module | Adapter Module | Data |  | 1 |
| enabled | Enabled | Check |  | 0 |
| config_json | Config (JSON) | JSON |  | 0 |

##### (10) Execution Log

- **Naming:** Autoincrement
- **Submittable:** YES (`is_submittable: 1`)

| fieldname | label | fieldtype | options | reqd |
|---|---|---|---|---|
| agent_profile | Agent Profile | Link | Agent Profile | 1 |
| skill | Skill | Link | Skill | 1 |
| task | Task | Link | Agent Task | 0 |
| parameters | Parameters (JSON) | JSON |  | 0 |
| result | Result (JSON) | JSON |  | 0 |
| status | Status | Select | success\nfailed\nrejected\ntimeout | 1 |
| permission_decision | Permission Decision | Link | Permission Decision Log | 0 |
| duration_ms | Duration (ms) | Int |  | 0 |
| tokens_used | Tokens Used | Int |  | 0 |

##### (11) Permission Decision Log

- **Naming:** Autoincrement
- **Submittable:** YES (`is_submittable: 1`)

| fieldname | label | fieldtype | options | reqd |
|---|---|---|---|---|
| agent_profile | Agent Profile | Link | Agent Profile | 1 |
| skill | Skill | Link | Skill | 1 |
| decision | Decision | Select | allowed\ndenied | 1 |
| reason | Reason | Small Text |  | 0 |
| matrix_snapshot | Matrix Snapshot (JSON) | JSON |  | 0 |
| decided_at | Decided At | Datetime |  | 1 |

> Note: there are 11 entries above because three are child tables (Agent Profile Skill, Skill Required DocType, Agent Task Skill). The "eight DocTypes" headline counts main DocTypes: Agent Profile, Skill, Agent Project, Agent Task, Chat Message, Chat Platform, Execution Log, Permission Decision Log.

### Step 3.3 — Create the Agent Supervisor role

The DocType permissions reference `Agent Supervisor` which doesn't exist yet. Create it programmatically as a one-time fixture:

```bash
bench --site friday.localhost console
```

Then inside the console:

```python
if not frappe.db.exists("Role", "Agent Supervisor"):
    frappe.get_doc({
        "doctype": "Role",
        "role_name": "Agent Supervisor",
        "desk_access": 1
    }).insert()
    frappe.db.commit()
print("Role exists:", frappe.db.exists("Role", "Agent Supervisor"))
exit()
```

### Step 3.4 — Run migrations

```bash
cd /home/friday/friday/friday-bench
bench --site friday.localhost migrate
```

**Expected:** clean run, no errors. The Friday Core module appears in `frappe.get_module_list()`.

If migration fails: **STOP**. Read the error carefully. The most common failures at this step:
- Missing `__init__.py` in a folder
- Typo in JSON (run `python -m json.tool friday_core/doctype/<name>/<name>.json` to validate each)
- Referencing a DocType in a Link that doesn't exist yet (create-order matters — create Skill before Execution Log)

### Step 3.5 — Write the test

Create `apps/frappe/friday/friday_core/tests/test_doctypes_exist.py`:

```python
# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt

import unittest

import frappe

EXPECTED_DOCTYPES = {
    "Agent Profile": {"profile_name", "status"},
    "Agent Profile Skill": {"skill"},
    "Skill": {"skill_name", "description", "risk_level", "status"},
    "Skill Required DocType": {"target_doctype", "operation"},
    "Agent Project": {"project_name", "status"},
    "Agent Task": {"title", "priority"},
    "Agent Task Skill": {"skill"},
    "Chat Message": {"session_id", "direction", "timestamp"},
    "Chat Platform": {"platform_name", "adapter_module"},
    "Execution Log": {"agent_profile", "skill", "status"},
    "Permission Decision Log": {"agent_profile", "skill", "decision", "decided_at"},
}


class TestDocTypesExist(unittest.TestCase):
    def test_each_doctype_exists_with_required_fields(self):
        for doctype, required_fieldnames in EXPECTED_DOCTYPES.items():
            with self.subTest(doctype=doctype):
                self.assertTrue(
                    frappe.db.exists("DocType", doctype),
                    f"DocType {doctype!r} missing"
                )
                meta = frappe.get_meta(doctype)
                actual = {f.fieldname for f in meta.fields}
                missing = required_fieldnames - actual
                self.assertFalse(
                    missing,
                    f"DocType {doctype!r} missing required fields: {missing}"
                )

    def test_submittable_doctypes_are_submittable(self):
        for doctype in ("Execution Log", "Permission Decision Log"):
            with self.subTest(doctype=doctype):
                meta = frappe.get_meta(doctype)
                self.assertEqual(
                    meta.is_submittable, 1,
                    f"{doctype!r} must be submittable for audit-trail integrity"
                )
```

Run it:

```bash
bench --site friday.localhost run-tests --module friday.friday_core.tests.test_doctypes_exist
```

**Expected:** all tests pass.

### Step 3.6 — Manual sanity check in the Desk

1. Open `http://friday.localhost:<port>/app/agent-profile/new`
2. Fill in `profile_name = test`, `status = Active`, save
3. Repeat for each of the 8 main DocTypes
4. Verify list views load: `http://friday.localhost:<port>/app/agent-profile`

If anything 500s or any DocType doesn't load, debug the JSON for that DocType.

---

## 4. Commit & PR

```bash
cd /home/friday/friday/friday-bench/apps/frappe
git checkout -b slice-1/friday-core-doctypes
git add friday/friday_core/ frappe/modules.txt
git status   # verify only Friday Core changes are staged
git commit -m "feat(friday-core): scaffold Friday Core module with 8 agent kernel DocTypes

Implements Slice 1 of Phase 1 per docs/contributing/slices/SLICE_1.md.

- New module 'Friday Core' inside the Frappe source tree
- 8 main DocTypes: Agent Profile, Skill, Agent Project, Agent Task,
  Chat Message, Chat Platform, Execution Log (submittable),
  Permission Decision Log (submittable)
- 3 child tables: Agent Profile Skill, Skill Required DocType,
  Agent Task Skill
- Agent Supervisor role created as fixture
- test_doctypes_exist asserts presence and required fields
- bench migrate runs clean on a fresh site"
git push origin slice-1/friday-core-doctypes
```

Then open a PR against `main` of `Friday-Labs-Inc/friday`. PR title: `Slice 1 — Friday Core DocType scaffolding`.

---

## 5. Done When (Validation)

Tick each box. Do not consider Slice 1 done until every box is green.

- [ ] `apps/frappe/friday/friday_core/` exists with `__init__.py`, `doctype/`, `tests/`
- [ ] `apps/frappe/frappe/modules.txt` contains `Friday Core`
- [ ] All 11 DocType folders exist under `friday_core/doctype/` with their `.json` and `.py` files
- [ ] `bench --site friday.localhost migrate` runs clean (no errors, no pending patches)
- [ ] `Agent Supervisor` role exists
- [ ] `bench --site friday.localhost run-tests --module friday.friday_core.tests.test_doctypes_exist` passes
- [ ] Each of the 8 main DocTypes can be created from the Desk UI without errors
- [ ] List views render for all 8 main DocTypes
- [ ] `Execution Log` and `Permission Decision Log` show Submit/Cancel buttons in the Desk
- [ ] PR opened, branch is `slice-1/friday-core-doctypes`
- [ ] IMPLEMENTATION_LOG.md updated with a dated section for Slice 1

---

## 6. If You Get Stuck

Do **not** invent a workaround. File a Blocker Report per CODEX.md §8. Most likely blockers and how to recognize them:

| Symptom | Likely cause | What to do |
|---|---|---|
| `ModuleNotFoundError: friday_core` during migrate | missing `__init__.py` | add it |
| `frappe.exceptions.DoesNotExistError: Module Friday Core not found` | not in modules.txt | append |
| JSON parse error | typo or stray comma | `python -m json.tool <file>` |
| Submit button missing on Execution Log | `is_submittable` not set to 1 | fix JSON, re-migrate |
| Link field fails because target DocType doesn't exist | wrong create-order | create Agent Profile and Skill BEFORE Execution Log |
| Permission errors creating from Desk | role mismatch | confirm System Manager perm is in the JSON |

---

## 7. References (optional reading)

If anything in this prompt is unclear, the original design intent is in these documents:

- `docs/design/05-module-design.md` §"Core DocTypes (Phase 1)" — field-level schemas
- `docs/design/11-agent-validation-checklist.md` Slice 1 — the validation criteria this prompt implements
- `docs/design/45-fork-policy.md` §1 — why the kernel module lives inside Frappe
- `CODEX.md` §5 Slice 1 — the higher-level slice description (will be updated to match this prompt)

---

**This prompt is the source of truth for Slice 1. If anything else conflicts with it, this wins until the slice is merged.**
