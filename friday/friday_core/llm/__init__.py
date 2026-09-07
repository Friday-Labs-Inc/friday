# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt

"""
The Friday LLM integration — provider abstraction and prompt assembly.

PLAIN ENGLISH
=============

When the agent runner needs to call an LLM, it goes through this package.
The runner never calls an LLM API directly — it calls `get_provider_for_profile()`
which returns a `LLMProvider` instance, then calls `.chat()` on it.

The provider is determined by:
  1. `Agent Profile.model_provider` → a `LLM Provider` DocType row.
  2. Falls back to `Agent Settings.default_provider` if the link is empty.
  3. Falls back to the first active `LLM Provider` row if neither is set.

The actual LLM call is made by the provider adapter. In Phase 1 the only
adapter is `MinimaxProvider` (Minimax M2). The `LLMProvider` ABC makes it
trivial to add OpenAI, Claude, OpenRouter, or any other provider later
without changing the runner or prompt builder.

One module:

  - **provider.py** — `LLMProvider` ABC and the `MinimaxProvider`
    implementation. The runner calls `get_provider_for_profile()` which
    returns the right provider instance for the given agent.

  - **prompt_builder.py** — `build(profile_name, session_id, inbound_content)`
    assembles the messages list (system prompt + conversation history + tools)
    ready for `provider.chat()`. Pure function — no side effects.

See also:
  - `docs/contributing/proposals/slice-5-llm-integration.md` — the spec.
  - `docs/design/10-agent-execution-guide.md` §Slice 5 — what to build.
  - `docs/design/03-technical-stack.md` — Minimax as Phase 1 provider.
"""

from __future__ import annotations

from friday.friday_core.llm.prompt_builder import build
from friday.friday_core.llm.provider import (
	LLMProvider,
	MinimaxProvider,
	get_provider_for_profile,
)

__all__ = [
	"LLMProvider",
	"MinimaxProvider",
	"build",
	"get_provider_for_profile",
]
