# Design 66b — The Project becomes the home of the agent's finished work (2026-06-13)

## The one-sentence version

The agent's deliverables are now real Frappe Files attached to the
Project, visible in the Desk attachment sidebar the moment they land —
no custom UI, no custom infrastructure, Hermes-beating because Frappe
just gives this to us.

## What you would have seen, before today

You open a Project in the Desk after the agents have spent hours on it.
The attachment sidebar is **empty**. The "deliverables" exist only as
Brand Direction DocType rows — *structured data,* not files anyone can
download, send to a client, or write back to RandomPack as artifacts.
"Where is the project's finished work?" had no answer.

## What this PR ships — three tools

**1. `attach-deliverable`** — save the agent's finished content as a
Frappe `File` attached to a Project (or Task). Default private. The
file is visible in the Desk attachment sidebar of that project
immediately — same surface a human attachment shows up on.

**2. `list-project-files`** — list the Files attached to a Project.
Same set the Desk sidebar shows. Permission-gated against the project.

**3. `get-project-file`** — read the bytes of one File attached to a
project. Cross-project guesses are refused (verified the File's
`attached_to_name` matches the project the caller named).

All three: permission-gated against the parent Project/Task; denials,
not-found, and cross-project-guess collapse to one error
(`denied_or_unreachable`) so an agent cannot probe forbidden existence.

## The Friday-beats-Hermes principle, again

Hermes builds file handling by hand. Frappe gives us the `File`
DocType with `attached_to_doctype` + `attached_to_name`, with
private/public flags, with native Desk UI, with permission gating
against the parent — for free. Three thin tools route content
through it. **Zero custom file infrastructure.**

## Live proof on this bench

Provisioned today on `friday.localhost`, then verified end-to-end:

1. **attach-deliverable** to project `RandomPack RP-PRJ-100` →
   file `3f7aff8355` created at `/private/files/naming_options_v1bfdeca.txt`,
   236 bytes, `is_private=true`.
2. **list-project-files** for that project → returns the file we just
   attached, with name + size + privacy flag.
3. **get-project-file** → reads the actual bytes back. The agent can
   round-trip its own deliverables.
4. **Cross-project guess** (`get-project-file` with a wrong project
   name) → returns `denied_or_unreachable`. Fail-loud, no information
   leakage about file existence in other projects.

## Tests

- **15 new** `test_files_skill.py` — parameter validation, all denial
  paths, attach with private default, attach to Task (not just
  Project), binary-content pass-through, list returns attached rows,
  cross-project-guess refusal, get-content path.
- 13 read-skill tests still green, plus all adjacent suites
  (workflow / dispatcher / reconciler / brand) untouched.

## What's NOT in this PR

- **Print-format-driven PDF generation** — text deliverables in v0.1.
  Use the print-format hook when an actual deliverable needs PDF
  encoding.
- **Public URLs** — every file is private by default; public requires
  explicit opt-in and a follow-up to consider whether v0.1 wants any
  public files at all.

## How an operator picks this up

After merging, on each existing bench, run:

```bash
bench --site <yoursite> execute \
  friday.friday_core.skills.bootstrap_files.provision
```

The Friday profile gains three skills, the `Friday File Author` role
is created with the right per-DocType grants. The agent can now write
deliverables that show up in the Desk sidebar of the relevant Project.
