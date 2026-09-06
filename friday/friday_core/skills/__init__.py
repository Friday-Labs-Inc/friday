# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt

"""
The Friday skill loader — turning database rows into LLM tool menus.

When an AI agent wakes up to handle a task, the very first thing it
needs is the answer to:

    "What tools do I have available right now?"

That answer is a list of tool definitions in the format the LLM
provider expects (OpenAI, Anthropic, etc.). This package builds that
list — fresh enough to reflect recent permission changes, fast enough
to run before every conversation turn.

One module:

  - **loader.py** — the public functions `load_for_profile(profile)`
    and `to_tool_definition(skill)`. Also owns the Redis cache for
    skill lists and the invalidation hooks wired in `frappe/hooks.py`.

See also:
  - `docs/design/10-agent-execution-guide.md` §Slice 3 — what to build.
  - `docs/design/05-module-design.md` — the Skill DocType schema.
  - `friday/friday_core/permissions/` — the Slice 2 permission engine
    this loader reuses to filter the skill list.
"""
