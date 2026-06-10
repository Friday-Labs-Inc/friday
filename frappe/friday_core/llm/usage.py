# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt

"""
Per-call LLM usage + cost recording (one LLM Usage Log row per API call).

PLAIN ENGLISH
=============
After every model call, the runner records what it cost: input/output tokens
(from the provider's usage block) and — when the LLM Provider row has
per-million-token rates set — an estimated USD cost. "What is the agent costing
us per session / profile / day" becomes a Desk query.

HERMES EQUIVALENT (divergences disclosed)
=========================================
Hermes `agent/usage_pricing.py` + `account_usage.py`: cost = tokens/1M × rate,
with rates from a bundled per-model pricing dataset (~877 lines, models.dev
style) and totals accumulated in process memory. Friday keeps the same
cost formula but:
  - rates are OPERATOR-SET fields on the LLM Provider row (no bundled dataset
    to maintain; blank = no cost estimate),
  - each call is a durable DocType row (auditable, queryable) instead of an
    in-memory accumulator — consistent with "every meaningful event is a row".

SAFETY: NEVER BREAKS A TURN
===========================
`record_usage` is double-guarded — any failure (missing table mid-migration,
permissions, even logging itself) is swallowed and the turn continues.
"""

from __future__ import annotations

import frappe

_TOKENS_PER_UNIT = 1_000_000


def estimate_cost(
    prompt_tokens: int,
    completion_tokens: int,
    input_cost_per_million: float | None,
    output_cost_per_million: float | None,
) -> float | None:
    """Cost in USD for one call, or None when no rates are configured.

    Hermes' formula: tokens / 1M × per-million rate, input and output priced
    separately. A rate left blank (None/0) contributes nothing; both blank →
    None (no estimate, distinct from "free").
    """
    if not input_cost_per_million and not output_cost_per_million:
        return None
    cost = 0.0
    if input_cost_per_million:
        cost += (prompt_tokens / _TOKENS_PER_UNIT) * input_cost_per_million
    if output_cost_per_million:
        cost += (completion_tokens / _TOKENS_PER_UNIT) * output_cost_per_million
    return cost


def record_usage(
    *,
    profile_name: str,
    session_id: str,
    provider,
    model: str | None,
    usage: dict,
) -> str | None:
    """Insert one LLM Usage Log row for a completed API call. NEVER raises.

    `provider` is the LLMProvider instance the call went through — it carries
    `PROVIDER_NAME` and the row's per-million rates (attached by
    `_build_provider`). Returns the new row name, or None on any failure.
    """
    try:
        prompt_tokens = int(usage.get("prompt_tokens") or 0)
        completion_tokens = int(usage.get("completion_tokens") or 0)
        total_tokens = int(usage.get("total_tokens") or 0) or (prompt_tokens + completion_tokens)
        cost = estimate_cost(
            prompt_tokens,
            completion_tokens,
            getattr(provider, "input_cost_per_million", None),
            getattr(provider, "output_cost_per_million", None),
        )
        doc = frappe.get_doc(
            {
                "doctype": "LLM Usage Log",
                "session_id": session_id,
                "agent_profile": profile_name,
                "provider": getattr(provider, "PROVIDER_NAME", ""),
                "model": model or "",
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
                "estimated_cost": cost,
            }
        )
        doc.insert(ignore_permissions=True)
        return doc.name
    except Exception:
        try:
            frappe.logger("friday.usage").warning(
                f"Failed to record LLM usage for session {session_id!r}; "
                f"the turn continues without it."
            )
        except Exception:
            pass
        return None
