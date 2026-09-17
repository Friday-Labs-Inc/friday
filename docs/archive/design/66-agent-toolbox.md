# Design 66 — The Agent Toolbox

**Status:** LOCKED 2026-06-13 (all Qs as recommended; user gave the
"just go build" instruction, no Q-by-Q this slice). Implementation lands
as **two PRs**: 66a (generic governed read + fail-loud frame), 66b
(Frappe-File deliverable production + retrieval). MCP is deferred to a
later design.

## Why this exists — the smoking-gun moment

From the Legion validation transcript, line 5142:

> *"I'm having trouble retrieving the saved directions from the system.
> Let me create fresh ones for you now based on the Legion Coffee brief."*

The user had asked the agent about saved brand directions. The agent had
**actually saved 24 of them** (BD-0002 through BD-0025) during the
pipeline. But it had a `create-brand-direction` tool and **no
`get-brand-direction` tool**. So instead of saying "I can't read those
back," it **fabricated three new ones and presented them as if they were
the real saved work.**

This is the worst possible failure mode for a **governance** framework.
The whole pitch is trustworthy, audited, human-gated. An agent that
silently invents data when a tool is missing is the *opposite* of
trustworthy. The transcript marked this as "Bug 5, low severity." It's
the most important bug in the report.

Three problems stacked into one moment:

1. **Write-only toolbox.** Skills were built as one-directional verbs
   for the demo (`create-brand-direction`) with no symmetric read. Every
   create needs a get/list — Friday's tools are structurally write-biased.
2. **No "fail loud" on a missing tool.** The agent should have said
   *"I don't have a tool to fetch those."* Instead it hallucinated. The
   same silent-failure disease as the dispatcher, but now in the agent's
   mouth.
3. **Agents are blind to their own work.** They cannot see what they
   created — not just brand directions, but tasks, projects, issues,
   anything.

## The principle that drives every Q below

> **An agent never speaks beyond the evidence its tools can show it.**

The same governance discipline Design 61 applied to the pipeline applies
here to the toolbox: state and audit are the source of truth, and the
agent's voice must trace back to them — never to thin air.

## Compare with Hermes — what it does, what we surpass

Hermes builds **every tool by hand**: a terminal tool, a web-search
tool, a browser tool, a file-read tool. Powerful, but each one is
bespoke; reading "the records you created" requires a separate skill
per record type, and Hermes has no native database to read from.

Friday surpasses this **because Frappe is a permissioned database**:

> A single generic `read-record` tool, scoped by the agent's permissions
> and audited like every other write, gives an agent read access to
> **every DocType it can write to** — for free, no per-type skill.

Save a `Brand Direction`? You can read it back. Save a `Task`? You can
read it back. Save a `Project`? You can read it back. **Hermes can't do
this; Friday's foundation hands it to us.** This is the surpass-Hermes
axis on this slice, named explicitly per
[[feedback_hermes-floor-not-ceiling]].

## What this slice gives the agent — five tools

| Tool | Purpose | The bug it kills |
|---|---|---|
| **`read-record`** | Get one row by DocType + name. Permission-gated, audited. | "Trouble retrieving the saved directions" — now it can fetch BD-0002 by name. |
| **`list-records`** | List rows of one DocType, with simple filters. Permission-gated. | The same — now it can list `Brand Direction` for a brief. |
| **`attach-deliverable`** | Produce content (text/PDF/structured doc) and save it as a Frappe `File` attached to a Project (or Task). | "Brand directions are DB rows, not files. The Project doesn't hold any finished work." Now it does. |
| **`list-project-files`** | List the File attachments on a Project. Permission-gated. | "I have no idea what files exist on this project" → now it does. |
| **`get-project-file`** | Read the bytes of one attached File. | Round-trips the agent's own deliverables for retrieval (RandomPack write-back, refinements, etc.). |

Plus a **system-prompt change** (the cheapest, highest-leverage fix):

> **The fail-loud frame.** Every agent's system prompt gains one
> non-negotiable sentence:
>
> > *"If you do not have a tool that can fetch information someone asks
> > about, say so plainly. Never invent records, files, or data that you
> > did not retrieve through a tool call."*

This is the same fail-loud rule Design 61 made the pipeline obey, now
applied to the agent's voice.

---

## Q1 — Permission model for `read-record` and `list-records`

*Recommendation:* the read tools call `frappe.has_permission(doctype,
"read", doc=...)` for the agent's User (one-user-per-agent, doc 23) and
**refuse with a structured error if the check fails** — no
`ignore_permissions`. Friday already wires each Agent Profile to a Frappe
User; we route the read through that User's session via
`frappe.set_user(...)`. The same governance contract every other write
goes through.

Returning a denial is itself observable: the dispatcher already writes a
`Permission Decision Log` row for denials; we make `read-record` /
`list-records` denials appear there too.

**Edge cases:**
- DocType doesn't exist → structured error `"unknown_doctype"`.
- Record doesn't exist (or is filtered out by permissions) → structured
  error `"not_found_or_unreadable"` (deliberately ambiguous so we don't
  leak existence of forbidden rows).
- A standard Frappe `Password` field type returns the encrypted hash;
  the read tools strip those automatically (`get_password` is gated).

## Q2 — `attach-deliverable` shape

*Recommendation:* the tool takes:

```python
{
  "project_name": "PRJ-XXXX",         # required; or task_name (one of)
  "task_name":    "TSK-YYYY",         # optional alternative
  "file_name":    "naming_options_v1.txt",
  "content":      "<the deliverable bytes/text>",
  "is_private":   true,                # default true; v0.1 never public
  "description":  "Three naming options..."
}
```

Calls Frappe's native
`frappe.utils.file_manager.save_file(name, content, doctype, name,
is_private=1)` — the same API the Desk attachment UI uses. The created
`File` row appears in the **Desk attachment sidebar** of the Project
immediately. No custom UI to build.

**MIME type and binary safety**: content can be `str` or `bytes`. For
agent-text deliverables (naming options, brand-direction copy, etc.) the
tool wraps bytes in UTF-8; for opaque binaries (PDFs from print formats
later) it passes through. v0.1 stays text/plain; PDF generation via
Frappe print formats lands when we need a non-text deliverable.

**Auditability**: each attach writes a row in our existing `Execution
Log` (skill execution audit trail) keyed by skill name +
`agent_profile` + the resulting `File.name`. Standard governance.

## Q3 — Fail-loud system-prompt frame

*Recommendation:* extend `prompt_builder._build_system_prompt` with one
hard line of governance text **before** the operator's system prompt:

```python
frame = (
    "You are a Friday AI Agent. Respond conversationally or use a tool "
    "when appropriate. Think step by step. When you use a tool, output "
    "only the tool call — do not describe it.\n\n"
    "GOVERNANCE: If you do not have a tool that can fetch the "
    "information someone is asking about, say so plainly. Never invent "
    "records, files, or data you did not retrieve through a tool call. "
    "Hallucination is a governance failure, not a creativity feature.\n\n"
)
```

This is the cheapest mitigation we can ship — one line of text that, in
combination with the new read tools, ends the fabrication pattern.

## Q4 — Scope

In scope for Design 66:
- the five tools above (read-record, list-records, attach-deliverable,
  list-project-files, get-project-file),
- the prompt-frame change (Q3),
- their bootstrap modules + role + grants for `Friday` and `Copywriter`,
- unit tests for each, including the fail-loud denial path,
- a live live-bench proof (we have a running bench from Design 61).

Out of scope for 66:
- **MCP** — the universal-tool protocol, deferred to its own design.
  Read tools + governed DocType writes already cover most of the
  "agent's own work" surface; MCP is for the *outside world* (web
  search, browser, GitHub) and is its own substantial slice.
- **Write tools as generic `write-record`** — too dangerous to expose
  generically v0.1. Specific writes stay per-DocType skills with
  per-DocType validation (the existing `create-brand-direction`,
  `remember`, `plan-project` pattern).
- **PDF / image deliverables** — text-only v0.1. Print-format-driven
  PDF lands when an actual deliverable needs one.
- **Cross-Project file access** (one agent reading another project's
  deliverables) — permission-gated, but the agent doesn't get a
  list-all-files surface in v0.1; it explicitly names the project.

## What lands on disk — two PRs

**66a — generic governed read + fail-loud frame**
- `skills/handlers_read.py` — `read-record` and `list-records`.
- `skills/bootstrap_read.py` — registration + role grants.
- `llm/prompt_builder.py` — the fail-loud frame line (Q3).
- Tests: permission-denied, not-found, success, password-field scrub,
  prompt-frame text presence.
- Live proof: create a Brand Direction; ask the agent on the live bench
  to "list the brand directions you have for brief BB-0001"; it
  retrieves them, not invents them.

**66b — Project-as-deliverables**
- `skills/handlers_files.py` — `attach-deliverable`,
  `list-project-files`, `get-project-file`.
- `skills/bootstrap_files.py` — registration + role grants.
- Tests: attach writes a real `File` row with the right
  `attached_to_doctype`/`attached_to_name`; list returns it; get reads
  it back; permission denials.
- Live proof: agent saves a "naming options" deliverable to a real
  Project; the Desk attachment sidebar of that Project shows it.

## How we'll know it works — live proof

For 66a: on the live bench, manually create a `Brand Direction` row.
Then ask Friday in chat: *"What brand directions do you have saved for
brief BB-0001?"* The agent calls `list-records` and returns the real
ones — **not the fabrication pattern from Legion**. If we then revoke
its read permission and ask again, it responds with the fail-loud
sentence, not a hallucination.

For 66b: ask Friday: *"Create a naming-options deliverable for project
PRJ-0001 with three options: A, B, C."* It calls `attach-deliverable`.
We open the Project in the Desk; the attachment sidebar shows the file.
We then ask: *"What deliverables do you have on PRJ-0001?"* It calls
`list-project-files`, returns the real list, including the one it just
made.

## Risks called out

- A generic read tool that respects permissions can still leak schema
  shape (column names) to the agent. The agent already sees DocType
  schemas via the `required_doctypes` skill metadata; this is not new.
- Fail-loud frame text is a behaviour change. Operators with very
  agent-specific system prompts might prefer to write their own
  fail-loud line. The frame's wording is concise so it composes; we
  publish it in `docs/rollouts/design-66a-*.md` so operators know what
  they're getting.
- `attach-deliverable` writes a Frappe `File`. Files attached privately
  are still readable by anyone with `read` on the parent doctype +
  `read` on `File`; standard Frappe model, but the bootstrap grants
  must be explicit.
