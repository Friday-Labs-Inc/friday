# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt

"""The LLM-as-judge for open-ended quality (Design 91 · Slice 2).

`expect_contains` (a substring match) can grade a closed answer, but not a brief or
a summary: a good summary may lack a specific word; a bad one may contain it. So a
scenario can carry a `rubric` — plain-sentence criteria — and this module asks a
SEPARATE, INDEPENDENT model to mark each criterion met / not-met with a reason.

WHY AN INDEPENDENT PROVIDER (the locked decision)
-------------------------------------------------
Letting the agent grade itself bakes in the agent's own blind spots and an
optimistic bias. So the judge MUST run on a different `LLM Provider` row than the
one the agent ran on. `resolve_judge_provider` enforces that: you may name a judge
provider explicitly, or it auto-discovers the first active provider that differs
from the agent's. If none exists, the quality axis is **blocked** — reported as a
visible SKIP, never a silent pass and never a hard fail. (That is exactly what
"require a separate independent judge provider" means: no second model → no quality
score, and the report says so loudly.)

PURITY
------
`judge_quality` is pure w.r.t. Friday: it takes a built provider object (anything
with a `.chat(messages)` returning `{"content": ...}`) and returns a verdict dict.
It never raises — a provider error or unparseable output becomes a quality FAIL with
a reason, so one judge hiccup can't crash a whole eval run. That makes it unit-
testable with a fake provider, no LLM and no DB.
"""

from __future__ import annotations

import json
import re

# A judge reply we cannot parse is a quality FAIL (not a crash). The model is told
# to answer with strict JSON; if it doesn't, we surface that rather than guess.
_JUDGE_SYSTEM = (
	"You are a strict, fair evaluator of an AI assistant's reply. You are given the "
	"reply and a checklist of criteria. For EACH criterion, decide if the reply meets "
	"it. Judge only what the criterion asks — do not invent extra requirements. "
	"Respond with STRICT JSON and nothing else, in exactly this shape:\n"
	'{"criteria": [{"criterion": "<verbatim criterion text>", "met": true, '
	'"reason": "<one short sentence>"}]}\n'
	"`met` must be a JSON boolean. Include one object per criterion, in order."
)


def build_judge_messages(reply: str, rubric: tuple[str, ...], rubric_note: str = "") -> list[dict]:
	"""Assemble the (system, user) messages for one judge call.

	Factored out so a test can assert the prompt carries the reply + every criterion
	without invoking a model.
	"""
	numbered = "\n".join(f"{i + 1}. {c}" for i, c in enumerate(rubric))
	note = f"\n\nGuidance for judging: {rubric_note}" if rubric_note else ""
	user = (
		f"CRITERIA (judge each independently):\n{numbered}{note}\n\n"
		f"REPLY TO JUDGE (between the markers):\n"
		f"<<<REPLY>>>\n{reply}\n<<<END REPLY>>>"
	)
	return [
		{"role": "system", "content": _JUDGE_SYSTEM},
		{"role": "user", "content": user},
	]


def _extract_json(text: str) -> dict | None:
	"""Pull a JSON object out of a model reply that may be fenced or chatty.

	Tries, in order: the whole string; a ```json fenced block; the first balanced
	`{...}` span. Returns the parsed dict, or None if nothing parses.
	"""
	if not text:
		return None
	candidates: list[str] = [text.strip()]
	fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
	if fence:
		candidates.append(fence.group(1))
	brace = re.search(r"\{.*\}", text, re.DOTALL)
	if brace:
		candidates.append(brace.group(0))
	for cand in candidates:
		try:
			parsed = json.loads(cand)
		except json.JSONDecodeError, TypeError:
			continue
		if isinstance(parsed, dict):
			return parsed
	return None


def judge_quality(reply: str, rubric: tuple[str, ...], *, provider, model: str | None = None) -> dict:
	"""Score `reply` against `rubric` with an independent model. Never raises.

	Returns a verdict dict:
	  criteria      [{criterion, met, reason}] — one per rubric item the judge returned
	  unmet         the criteria the judge marked not-met (the credit-assignment view)
	  met_count/total
	  ok            True iff every rubric criterion is met (per-criterion checklist)
	  error         set (and ok False) if the judge call failed or was unparseable
	"""
	total = len(rubric)
	if total == 0:
		# No rubric → nothing to judge. Treated as "not applicable" by the runner.
		return {"criteria": [], "unmet": [], "met_count": 0, "total": 0, "ok": True}

	messages = build_judge_messages(reply, rubric, "")
	try:
		resp = provider.chat(messages)
		content = resp["content"] if isinstance(resp, dict) else getattr(resp, "content", "")
	except Exception as exc:  # a judge transport failure is a quality fail, not a crash.
		return _judge_error(rubric, f"judge call failed: {type(exc).__name__}")

	parsed = _extract_json(content or "")
	if not parsed or not isinstance(parsed.get("criteria"), list):
		return _judge_error(rubric, "judge returned unparseable output")

	criteria = []
	for item in parsed["criteria"]:
		if not isinstance(item, dict):
			continue
		criteria.append(
			{
				"criterion": str(item.get("criterion", "")),
				"met": bool(item.get("met", False)),
				"reason": str(item.get("reason", "")),
			}
		)
	unmet = [c["criterion"] for c in criteria if not c["met"]]
	met_count = sum(1 for c in criteria if c["met"])
	# A judge that returned fewer verdicts than criteria hasn't covered the checklist —
	# treat the shortfall as not-met so a truncated judge reply can't pass by omission.
	covered = len(criteria)
	ok = covered >= total and not unmet
	return {
		"criteria": criteria,
		"unmet": unmet,
		"met_count": met_count,
		"total": total,
		"ok": ok,
	}


def _judge_error(rubric: tuple[str, ...], reason: str) -> dict:
	"""A failed/unparseable judge call → a quality FAIL carrying the reason."""
	return {
		"criteria": [],
		"unmet": list(rubric),
		"met_count": 0,
		"total": len(rubric),
		"ok": False,
		"error": reason,
	}


def resolve_judge_provider(agent_profile: str, judge_provider_name: str | None = None) -> dict:
	"""Pick an INDEPENDENT judge provider (a different LLM Provider than the agent's).

	Returns `{"provider": <built provider>, "name": <row name>}` on success, or
	`{"provider": None, "name": None, "reason": "<why blocked>"}` when no independent
	judge is available — the runner then reports the quality axis as skipped.

	Independence rule: the judge row must NOT be the same row the agent resolves to.
	An explicit `judge_provider_name` is honored but still checked for independence.
	Otherwise we auto-discover the first active provider whose name differs.
	"""
	import frappe
	from frappe.friday_core.llm.provider import (
		LLMError,
		_resolve_provider_row,
		get_provider_by_name,
	)

	# The agent's provider row name — so we can guarantee the judge differs. If the
	# agent's own provider can't be resolved (a misconfig the run will hit anyway),
	# proceed best-effort with `None` so any active provider counts as independent.
	try:
		agent_row = _resolve_provider_row(agent_profile)
		agent_name = agent_row.get("name") if agent_row else None
	except Exception:
		agent_name = None

	if judge_provider_name:
		if judge_provider_name == agent_name:
			return {
				"provider": None,
				"name": None,
				"reason": (
					f"named judge provider {judge_provider_name!r} is the SAME as the "
					f"agent's provider — not independent. Name a different one."
				),
			}
		try:
			provider = get_provider_by_name(judge_provider_name)
		except LLMError as exc:
			return {"provider": None, "name": None, "reason": str(exc)}
		return {"provider": provider, "name": judge_provider_name}

	# Auto-discover: first active provider whose name differs from the agent's.
	rows = frappe.get_all(
		"LLM Provider",
		filters={"is_active": 1},
		fields=["name"],
		order_by="creation asc",
	)
	for row in rows:
		if row["name"] != agent_name:
			try:
				provider = get_provider_by_name(row["name"])
			except LLMError:
				continue
			return {"provider": provider, "name": row["name"]}

	return {
		"provider": None,
		"name": None,
		"reason": (
			"no independent judge provider available — the only active LLM Provider is "
			"the agent's own. Configure a second LLM Provider to enable quality scoring."
		),
	}
