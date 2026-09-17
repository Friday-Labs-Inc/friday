# 16 — Raven Integration Strategy

> See `00-glossary.md` for term definitions.
> See `42-phase-one-authority-contract.md` §3 — Raven is optional for v0.1 unless the feasibility spike (`44-technical-feasibility-spike.md`) confirms low risk. If included, Raven is a War Room bridge only.
>
> Raven repo: `The-Commit-Company/raven`. License compatible with Friday's GPL v3.

---

## 1. Why Raven

Building chat from scratch is reinvention. Raven exists, is GPL-compatible, integrates natively with Frappe (channels, DMs, files, reactions, Message Actions, document sharing, Timeline), and runs Socket.io for real-time.

Friday adopts Raven for:

| Purpose | Raven feature |
|---|---|
| Project War Room | Public / private channel per Agent Project |
| Direct human ↔ agent chat | Direct messages |
| File sharing in context | Native uploads with permission inheritance |
| Status indicators | Custom emoji reactions |
| Triggering workflows from chat | Message Actions (right-click → create DocType) |
| Embedded document previews | Document sharing with form actions |
| Audit thread per project | Timeline integration on Frappe documents |

Raven reflects truth. Raven does not own truth — Frappe DocTypes do.

---

## 2. Integration points

### 2.1 War Room as a Raven channel

Every Agent Project auto-creates one Raven channel on `after_insert`. Naming: `war-room/{project-code}`.

| Property | Value |
|---|---|
| Channel visibility | Mirrors Agent Project visibility (public / private / restricted) |
| Members on creation | Linked Users of all assigned Agent Profiles + supervisors |
| Pinned message | Project brief + emoji legend |
| Archive policy | Channel becomes read-only on project Completed; see §6 |

```python
# friday/integrations/raven/hooks.py
def on_project_created(doc, method=None):
    channel = create_raven_channel(
        name=f"war-room/{doc.project_code}",
        type="Public" if doc.visibility == "Public" else "Private",
        description=doc.brief[:200],
    )
    add_members(channel, agent_profiles_to_users(doc.assigned_profiles))
    pin_message(channel, render_project_brief(doc))
```

### 2.2 Message Actions for agent workflows

Right-click a message → trigger a configured DocType action. Friday ships four:

| Action | Effect |
|---|---|
| **Escalate** | Creates an `Escalation` DocType pre-filled with message context |
| **Log Decision** | Creates a `Decision Record` from the message + thread context |
| **Approve Skill** | Resolves a pending `Workflow Request` (`approved=true`) |
| **Import Skill** | Validates an attached skill JSON/YAML, creates `Skill Draft` |

Permission: each action is gated by the underlying DocType's role permissions. Only `supervisor_agent` or human supervisors can trigger `Approve Skill`. Misuse is not possible — the permission engine enforces it.

### 2.3 Document sharing

Raven document-share renders an inline preview with workflow buttons. Friday extends it for:

- **Agent Task share** → state, assignee, due date; buttons: reassign, change priority, mark blocked.
- **Execution Log share** → skill, parameters (masked), result; button: re-run with parameters.
- **Skill share** → L0 header; button: open L1 / L2 in the Framework Console.

### 2.4 Timeline sync

Every War Room message mirrors into the Agent Project's Frappe Timeline. Timeline is the canonical audit record; Raven is the live-conversation view.

```python
# friday/integrations/raven/timeline_sync.py
def on_raven_message(message):
    if message.channel.startswith("war-room/"):
        project = resolve_project_from_channel(message.channel)
        frappe.get_doc({
            "doctype": "Communication",
            "reference_doctype": "Agent Project",
            "reference_name": project.name,
            "content": message.text,
            "sender": message.sender,
            "communication_medium": "Raven",
        }).insert(ignore_permissions=False)
```

Permissions still enforce: a user only sees Timeline entries for Projects they have access to. No leak from Raven to Timeline.

### 2.5 Standard emoji as status indicators

Installed on Raven activation:

| Emoji | Meaning | Auto-trigger |
|---|---|---|
| 🚀 | Skill execution started | Gateway posts on skill dispatch |
| ✅ | Task completed | Gateway posts on Task → Completed |
| ⚠️ | Blocker hit | Gateway posts on Task → Blocked |
| ❌ | Permission denied | Gateway posts on denied invocation |
| 🔄 | Retry attempt | Gateway posts on retried execution |
| 👀 | Under human review | Gateway posts on Workflow Request created |
| 🧠 | Skill learned / improved | Gateway posts when curator promotes a Skill |
| 🛑 | Emergency pause | Supervisor reacts to halt the agent in real time |

A 🛑 reaction triggers a pause-agent action, gated by supervisor role.

### 2.6 Direct messages for supervisor interventions

Supervisors can DM an Agent Profile's linked User. The agent treats DMs as direct instructions, scoped to the supervisor's permission level. DMs are Timelined for audit.

---

## 3. Security and permissions

| Concern | Mitigation |
|---|---|
| Channel membership reveals project scope | Channel visibility mirrors Agent Project permission; users without project access cannot see the channel exists |
| Messages may contain secrets | Field masking (`13-frappe-v16-leverage-strategy.md` §4) applies on Timeline; Raven respects the same masking via render hook |
| Message Action abuse | Each action gates on the underlying DocType permission |
| Channel archive | When project closes, channel becomes read-only. Deletion is a separate, explicit operator action |
| File uploads | Inherit Frappe File DocType permissions; private by default |

---

## 4. Setup sequence

On Friday installation with Raven:

1. Verify Raven app is installed: `bench --site {site} list-apps | grep raven`.
2. Install the Friday-Raven bridge: `bench --site {site} install-app friday-raven-bridge`.
3. Migrate: `bench --site {site} migrate`.
4. The bridge installs Message Action definitions, the standard emoji set, and hooks on Agent Project, Agent Task, Workflow Request.
5. First-run wizard creates a default "Friday Operations" channel for system-wide notifications.

If Raven is not installed, Friday falls back to Frappe Comments on Agent Project. Functional but degraded — no real-time, no Message Actions, no rich UX.

---

## 5. Use cases

### A — Task execution with real-time coordination

1. Supervisor creates an Agent Task in the Framework Console.
2. War Room channel exists from project creation.
3. Dispatcher claims the task → posts 🚀 in the channel.
4. Agent executes, posting intermediate updates.
5. On a question → tags supervisor; supervisor replies in the channel.
6. Agent completes → posts ✅ with a link to the result document.
7. Supervisor right-clicks the completion message → "Approve Skill" if a new skill was learned.

### B — Escalation flow

1. Agent hits `permission_denied`.
2. Gateway posts ⚠️ in War Room with structured context and `[Approve in Console] [Take Over] [Decline]` buttons.
3. Supervisor clicks `Take Over` → Message Action invokes the underlying skill as the supervisor's user; result posted back.
4. Original agent resumes its task with the new data.

### C — Skill import discussion

1. Engineer pastes a Skill JSON file in War Room.
2. Team discusses inline.
3. Supervisor right-clicks the file message → "Import Skill".
4. Validator runs; Skill Draft created; supervisor reviews in the Framework Console.
5. After approval, the Skill becomes Active and propagates to permitted agents.

---

## 6. Lifecycle policy

| Project state | Channel state |
|---|---|
| Active | Writeable, real-time |
| Completed | Read-only; pinned message updated with completion summary |
| Archived | Hidden from the default channel list; still searchable; Timeline preserved |
| Deleted | Archived; Timeline retained on Agent Project for audit |

Retention: channels persist indefinitely by default. Operators configure age-based archival (e.g. archive channels for projects completed > 180 days ago).

**Open question:** Raven's channel deletion semantics — does it preserve message history in the database after delete, or hard-delete? Friday requires preservation for audit. Verified in the integration spike before Raven is included in v0.1.

---

## 7. Known limitations

- **Scale:** untested with > 100 active agents in a single channel. Phase 2 load test required.
- **Mobile UX:** Raven's mobile app surfaces standard messages well; Message Actions need verification.
- **Cross-site:** Raven channels are per-site. Cross-site supervision needs federation, not in Phase 1 — see `37-multi-site-inter-agent-communication.md`.
- **Voice / video:** not in Raven scope. Out of scope Phase 1–2.
- **Retention compliance:** no built-in retention policy in Raven. Friday wraps this via a scheduler job.

---

## 8. Phasing

| Phase | Raven scope |
|---|---|
| 1 (v0.1) | Channel auto-creation; Timeline sync; standard emoji set; basic Message Actions (Escalate, Log Decision). Conditional on spike approval per `42-phase-one-authority-contract.md` |
| 2 | Approve Skill / Import Skill actions; document-share previews with workflow buttons; archive automation |
| 3 | Cross-site channel federation (if multi-site deployment matures) |

---

## 9. Dependencies

- Raven app v2.0+ (Message Actions and document sharing).
- Frappe v16 — the Friday fork target.
- Friday Core DocTypes: Agent Project, Agent Task, Execution Log, Workflow Request, Skill, Agent Profile.

---

## 10. Rollback

The integration ships as a separate Frappe app (`friday-raven-bridge`). If Raven proves unstable or becomes unmaintained, disabling the bridge falls back to Frappe Comments on Agent Project. No data loss — Timeline is the source of truth; Raven is the surface.
