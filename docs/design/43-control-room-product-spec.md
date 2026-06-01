# 43 — Control Room Product Spec

> **Purpose:** Specify the operator-facing product surface of Friday. Doc 39 declares "the Control Room is the product surface, the agent runtime is the engine." This document turns that slogan into something an engineer can build and an operator can trust.

---

## 1. North Star

The Control Room must answer five operator questions at a glance:

1. What can each agent do? (capability visibility)
2. What is it doing right now? (live activity)
3. What did it do? (history and replay)
4. What is waiting for me? (approval queue)
5. How do I stop it? (kill switch)

If these five answers are not visible within two clicks from the Control Room home, the product has failed.

The Control Room is the trust contract between human supervisors and Friday agents. Every other system in Friday exists to make these five answers true.

---

## 2. Why the Control Room Is the Product

Friday's defensibility is not "AI agents for ERPNext." That is a market. The defensibility is **auditable, permission-bound agent execution inside business software**.

The Control Room is where that defensibility becomes a product surface. Operators trust Friday only when they can see, approve, replay, and stop. Backend governance without a visible control surface is invisible governance, and invisible governance does not earn trust.

This document is therefore not a "UI module." It is the primary product spec.

---

## 3. Personas

Three personas use the Control Room:

| Persona | Primary Need | Frequency |
|---|---|---|
| **Business Supervisor** | Approve/deny agent actions, see daily activity, respond to escalations | Daily |
| **Operations Lead** | Configure agents, audit performance, tune policies | Weekly |
| **Friday Administrator** | Manage profiles, permissions, integrations, sandbox config | Setup + as-needed |

All three share the same Control Room shell. Views and actions differ by Frappe role.

---

## 4. Information Architecture

The Control Room is a Frappe Workspace named "Friday Control Room." It is the default landing page for any user with a Friday role.

Top-level navigation:

1. **Now** — live activity dashboard (default landing view)
2. **Inbox** — approval queue, escalations, agent questions
3. **Agents** — profile list with status, capabilities, recent activity
4. **Tasks** — Agent Project / Agent Task workspace with workflow Kanban
5. **Executions** — searchable Execution Log with replay capability
6. **Permissions** — Permission Decision Log with denials surfaced
7. **Policies** — Operations Policy, approval thresholds, autopilot config (Phase 2+)
8. **Settings** — credentials, profiles, sandbox, integrations

The navigation is consistent. Each view follows the same shape: filter strip on top, list/board in the middle, detail panel on the right.

---

## 5. View Specifications

### 5.1 Now (Live Activity)

The home view. Answers "what is happening?" without requiring the operator to know what to look for.

Three zones:

- **Active Executions** — agents currently running, with current step, elapsed time, agent profile, target document. Each row has a "stop" action that emits a graceful cancel signal.
- **Pending Approvals** — count badge + top 5 oldest items. Click expands to Inbox.
- **Recent Outcomes** — last 20 completed/failed executions with status icon, summary, link to Execution Log.

Real-time updates via Frappe's socket.io / Redis pubsub. Stale data acceptable up to 5 seconds.

Empty state: "All quiet. No agents are currently working." with a one-click link to create a task.

### 5.2 Inbox

The operator's queue. Items appear here when human attention is required.

Item types:

- **Approval Request** — agent has drafted an action requiring sign-off (e.g. a financial action above threshold)
- **Escalation** — agent encountered a situation outside its training and paused
- **Anomaly Flag** — automated validation detected unusual output during execution
- **Question** — agent needs a piece of information not in memory

Each item shows: context summary, what the agent proposes, what evidence it gathered, action buttons (Approve / Reject / Modify / Discuss).

Approve/Reject/Modify trigger workflow state changes on the underlying Agent Task. Discuss opens a thread (Frappe Communication in Phase 1, Raven channel in Phase 2 if Raven is included).

Inbox items have SLA timers. Items older than the configured SLA highlight in red.

### 5.3 Agents

A list of all Agent Profiles. For each agent:

- Status (Active / Suspended / Blocked / Idle)
- Role profile and capabilities (skill count, permission scope summary)
- Current task count
- 30-day success rate
- Last execution timestamp
- Quick actions: Suspend / Resume / View capabilities / View history

Clicking an agent opens the detail page showing:

- Identity (linked Frappe User, ERPNext User if applicable)
- Permitted skills (with link to each Skill record)
- Memory scope and domain assignments
- Active workflow assignments
- Execution timeline (last 100)
- Permission denial history (last 30)

"View capabilities" produces a human-readable summary: "This agent can read Contact, create Note drafts, and message teammates. It cannot submit financial documents above ₹50,000 or modify master data."

### 5.4 Tasks

The Agent Project / Agent Task workspace. Combines Kanban, List, and Calendar views (Frappe standard) with Friday-specific columns and filters.

Kanban renders the configured workflow states as columns (per doc 41 — Kanban is a view, not the workflow).

Each task card shows: title, assigned agent profile, priority, due date, risk level, current execution status if mid-flight.

Card actions: Open / Reassign / Pause / Promote-to-supervisor / Cancel.

Filters: by project, agent, status, risk level, blocked-only.

### 5.5 Executions

A searchable log of every Agent Execution. Filters: agent, skill, outcome (success/failed/blocked/cancelled), date range, target DocType.

Each execution detail shows:

- Triggered by (which task, which user/agent)
- Skill called with full input arguments
- Permission decisions taken (with link to Permission Decision Log)
- Sandbox runtime details (container ID, resource usage, duration)
- LLM provider, model, prompt tokens, completion tokens, cost
- Captured stdout/stderr/result
- Documents created/modified (with links)
- Validation results
- Confidence score
- Final outcome and reasoning

**Replay capability:** every execution can be re-rendered as a timeline. This is the "show me exactly what happened" UX. Operators can step through skill calls, see the agent's reasoning, see what data it read, what it wrote, and what was denied.

Replay is read-only. It does not re-execute; it reconstructs from logs.

### 5.6 Permissions

The Permission Decision Log surfaced as a searchable view, with denials prominently filtered.

Denials answer: "an agent tried to do X, was blocked, why?"

Each denial shows: agent, attempted action, target DocType, reason for denial, time, related execution. Clicking opens the broader execution context.

A weekly summary surfaces: top 10 most-denied (agent, skill) pairs. These are candidates for either (a) skill scope tightening or (b) profile permission expansion — but always through the supervisor's explicit decision, never automatically.

### 5.7 Policies (Phase 2+)

Operations Policy DocType editor. Thresholds for approval, autopilot rules, value caps, time windows, blackout dates.

Phase 1 ships this view in read-only / schema-only mode. Phase 2 enables editing with supervisor permission.

### 5.8 Settings

Standard Frappe Workspace for admin: Agent Profile creation, Skill management, Credential Profiles, Sandbox configuration, LLM Provider configuration, integration settings (Raven if installed, etc.).

---

## 6. Core Actions

These actions must be available from any view where they are contextually relevant:

| Action | Effect | Permission |
|---|---|---|
| **Stop** (single execution) | Sends graceful cancel signal to running sandbox; logs cancellation reason | Any user with supervisor role on the agent's domain |
| **Suspend Agent** | Agent stops claiming new tasks; in-flight executions complete or timeout | Supervisor |
| **Revoke Agent** | Agent immediately disabled, all in-flight executions cancelled, no new claims, audit log entry created | Admin only |
| **Approve / Reject / Modify** | Workflow transition on the Agent Task or skill draft | Per workflow definition |
| **Pause Project** | All tasks in project move to "paused" state; dispatcher excludes them | Project supervisor |
| **Replay Execution** | Opens read-only replay view | Any user with read access to the execution |
| **Kill Switch (All)** | Suspends every agent in the site immediately; requires re-enable to resume | Admin only, requires confirmation |

The Kill Switch is a deliberately heavy action. It is one click but requires confirmation. It is the operator's "panic button" and must always work even if other views are slow.

---

## 7. Notifications

The Control Room is not a dashboard the operator must remember to check. It pushes:

- **In-app** — Frappe notification bell for approvals, escalations, anomalies
- **Email** — daily summary at configurable time (default 07:00 site timezone)
- **Raven** (if installed) — channel-specific notifications per Agent Project
- **Webhook** — outbound notifications to operator-configured endpoints (Slack, Teams, custom) — Phase 2

Notification routing is configured per role and per event type. Default: approvals and escalations go in-app immediately; daily summary goes via email; anomalies surface in-app + email.

---

## 8. Real-Time Data Flow

The Control Room must feel live. Mechanism:

- Frappe socket.io for in-page real-time updates
- Redis pubsub channels for cross-process event distribution
- Event topics: `agent.execution.started`, `agent.execution.completed`, `agent.execution.failed`, `task.state.changed`, `permission.denied`, `approval.requested`, `agent.suspended`

Each view subscribes to relevant topics on mount and unsubscribes on navigation.

Fallback: if socket.io is unavailable, views auto-refresh every 10 seconds via polling. The "live" indicator badges show actual freshness.

---

## 9. Mobile Considerations

Phase 1 targets desktop primarily. The Control Room must render on mobile (Frappe Desk is mobile-responsive), but mobile UX is degraded.

What must work on mobile:

- Inbox approvals (a supervisor approving a request from their phone is a common case)
- Kill Switch (panic button must work from anywhere)
- Stop single execution
- View live activity

What can degrade on mobile:

- Replay UI (read on desktop)
- Permission Decision Log search (filter limited)
- Settings (not for phone)

Phase 2+ may include a dedicated Friday mobile app. Out of scope for v0.1.

---

## 10. Phase 1 Scope

For v0.1, the Control Room ships with:

- Workspace shell with eight top-level navs (Policies and Settings can be stubs)
- Now view (Active Executions, Pending Approvals, Recent Outcomes)
- Inbox view (Approval Request, Escalation, Anomaly Flag, Question item types)
- Agents view (list + detail page with capability summary)
- Tasks view (Kanban + List + detail)
- Executions view (search + detail + basic replay timeline)
- Permissions view (denials filter + detail link to execution)
- Core actions: Stop, Suspend, Revoke, Approve/Reject/Modify, Pause Project, Kill Switch
- In-app + email notifications

Out of scope for v0.1:

- Webhook notifications
- Policies editor (read-only schema view only)
- Raven notification routing (only if Raven is included per doc 42)
- Mobile app
- Custom dashboards
- Predictive widgets (forecast, anomaly heatmap, cost analytics)

---

## 11. Visual Direction

The Control Room is built on Frappe Workspace primitives. It does not require a custom frontend framework. Use:

- Frappe's Workspace, List View, Kanban View, Form View, Report View
- Frappe charts library for trend widgets
- Standard Frappe number cards and indicators
- Frappe's notification components
- Friday-specific custom blocks only where standard Frappe components fall short (e.g. the live activity feed, the execution replay timeline)

Resist the urge to build a custom React/Vue frontend in Phase 1. Frappe Desk is sufficient and ships free.

Phase 2+ may introduce a more product-branded shell once the Control Room concepts have proven themselves.

---

## 12. Trust UX Principles

Five rules the Control Room must obey:

1. **Show, don't summarize.** If an agent did something, the operator must be able to see exactly what it did, not just a summary. Replay is mandatory.
2. **Stop must always work.** The Kill Switch is the most important button in the product. If it ever feels slow or unresponsive, trust is gone.
3. **No magic, no hidden state.** Every state change is visible. No agent action happens without an Execution Log row.
4. **Reasons, not just outcomes.** Why was this denied? Why did this fail? The Control Room surfaces reasons inline, not buried in detail pages.
5. **Default safe.** Default permissions are restrictive. Default actions require approval. The operator opts into autonomy, not out of caution.

---

## 13. Completion Gate for v0.1

The Control Room is "done" for v0.1 when:

- A new operator can land on the Workspace and identify Active Executions, Pending Approvals, and Recent Outcomes within 30 seconds.
- Any execution in the log can be replayed step-by-step.
- A supervisor can approve / reject any pending approval in two clicks.
- A supervisor can stop any individual running execution in one click.
- An admin can revoke an agent or trigger the Kill Switch in two clicks with confirmation.
- All eight navigation items render without errors.
- The view passes the doc 42 completion gate items related to "Control Room exists" and "task state changes are visible."

---

## 14. Open Questions

1. Do we need a public-read landing page (for non-authenticated visitors) summarizing the Control Room concept, or is it fully gated? Lean: fully gated; public marketing lives on the website.
2. How do we handle Control Room performance with hundreds of concurrent active executions? Pagination and aggregation; virtual scrolling for live feed. Detailed performance work goes in doc 38.
3. Should the Replay UI eventually allow "fork from this point" — i.e. supervisor takes over from where the agent stopped? Interesting; Phase 3 consideration.
4. Bilingual UI for India deployments (Hindi, Tamil, Telugu, etc.)? Phase 2 ships English; Frappe i18n covers the rest with translation work.
5. Audit retention period for displaying executions older than 90 days? Cold tier per doc 34. Control Room shows last 90 days by default with "load older" option.

---

## 15. Summary

The Control Room is the product. Everything else in Friday — Agent Profile, Skill, Permission Decision, Sandbox, Execution Log, Workflow — exists to make the Control Room's five questions answerable in seconds.

Build the Control Room shell first. Build the agent kernel to feed it. Build flagship business use cases on top.

If a supervisor cannot trust what they see in the Control Room, no amount of backend governance will earn the trust required for autonomous business operations.

---

**This document is authoritative for the Control Room product surface in v0.1. Where docs 14, 16, or 30 describe Control Room behavior in conflict with this spec, this document wins.**
