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


# Perspective "lenses" for a judge PANEL (Slice 3). When a panel has more seats than
# there are distinct independent providers, seats reuse a provider but each gets a
# different lens — so the votes are genuinely diverse perspectives, not the same call
# N times. Each lens is a one-sentence framing appended to the judge's instructions.
_LENSES: dict[str, str] = {
	"strict-literal": (
		"Judge LITERALLY and strictly: a criterion is met only if the reply clearly and "
		"unambiguously satisfies it; when in doubt, mark it not-met."
	),
	"charitable-intent": (
		"Judge by the reply's evident INTENT: if it plainly tries to satisfy the criterion "
		"and a reasonable reader would accept it, mark it met even if the wording is imperfect."
	),
	"fact-focused": (
		"Focus on FACTUAL soundness: be lenient about style and length, but mark a criterion "
		"not-met if the reply states anything false, fabricated, or unsupported."
	),
}
# The deterministic seat → lens order (so a panel's seats are reproducible run to run).
_LENS_ORDER: tuple[str, ...] = ("strict-literal", "charitable-intent", "fact-focused")


def build_judge_messages(
	reply: str, rubric: tuple[str, ...], rubric_note: str = "", lens: str = ""
) -> list[dict]:
	"""Assemble the (system, user) messages for one judge call.

	Factored out so a test can assert the prompt carries the reply + every criterion
	without invoking a model. `lens` (optional, Slice 3) appends a perspective framing
	so panel seats sharing a provider still judge from distinct angles.
	"""
	numbered = "\n".join(f"{i + 1}. {c}" for i, c in enumerate(rubric))
	note = f"\n\nGuidance for judging: {rubric_note}" if rubric_note else ""
	lens_hint = f"\n\nYour judging lens for this pass: {_LENSES[lens]}" if lens in _LENSES else ""
	user = (
		f"CRITERIA (judge each independently):\n{numbered}{note}{lens_hint}\n\n"
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


def judge_quality(
	reply: str, rubric: tuple[str, ...], *, provider, model: str | None = None, lens: str = ""
) -> dict:
	"""Score `reply` against `rubric` with an independent model. Never raises.

	Returns a verdict dict:
	  criteria      [{criterion, met, reason}] — one per rubric item the judge returned
	  unmet         the criteria the judge marked not-met (the credit-assignment view)
	  met_count/total
	  ok            True iff every rubric criterion is met (per-criterion checklist)
	  error         set (and ok False) if the judge call failed or was unparseable

	`lens` (Slice 3) selects a perspective framing for a panel seat; "" = neutral.
	"""
	total = len(rubric)
	if total == 0:
		# No rubric → nothing to judge. Treated as "not applicable" by the runner.
		return {"criteria": [], "unmet": [], "met_count": 0, "total": 0, "ok": True}

	messages = build_judge_messages(reply, rubric, "", lens)
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


def run_panel(reply: str, rubric: tuple[str, ...], seats: list[dict]) -> dict:
	"""Score `reply` with a PANEL of independent judges and vote per criterion.

	`seats` is a list of `{"provider": <built>, "name": <str>, "lens": <str>}`. Each
	seat judges the full rubric from its lens; a criterion is **met** iff a strict
	majority of seats marked it met (a seat that errored or omitted a verdict counts
	as not-met for that criterion — it cannot pass by omission). The scenario passes
	the quality axis iff every criterion wins its vote.

	Returns the same verdict shape as `judge_quality` (so the runner + report are
	unchanged) plus panel detail: `panel_size`, per-criterion `votes` ("k/N"), and a
	`seats` summary. A 1-seat panel is exactly the Slice 2 single-judge verdict.
	"""
	total = len(rubric)
	n = len(seats)
	if total == 0:
		return {"criteria": [], "unmet": [], "met_count": 0, "total": 0, "ok": True, "panel_size": n}
	if n == 0:
		return {**_judge_error(rubric, "panel has no seats"), "panel_size": 0, "seats": []}

	# Each seat's full verdict (judge_quality never raises).
	seat_verdicts = [
		judge_quality(reply, rubric, provider=s["provider"], lens=s.get("lens", "")) for s in seats
	]

	criteria = []
	unmet = []
	for i, crit in enumerate(rubric):
		votes_met = 0
		reasons = []
		for v in seat_verdicts:
			items = v.get("criteria", [])
			# Index-aligned: judges are told to return criteria verbatim, in order. A
			# missing i-th verdict (short/errored reply) is a not-met vote.
			if i < len(items) and items[i].get("met"):
				votes_met += 1
				if items[i].get("reason"):
					reasons.append(items[i]["reason"])
			elif i < len(items) and items[i].get("reason"):
				reasons.append(items[i]["reason"])
		majority = votes_met * 2 > n
		if not majority:
			unmet.append(crit)
		criteria.append(
			{
				"criterion": crit,
				"met": majority,
				"votes": f"{votes_met}/{n}",
				"reason": reasons[0] if reasons else "",
			}
		)

	return {
		"ok": not unmet,
		"panel_size": n,
		"criteria": criteria,
		"unmet": unmet,
		"met_count": sum(1 for c in criteria if c["met"]),
		"total": total,
		"seats": [
			{"name": s.get("name", ""), "lens": s.get("lens", ""), "ok": v.get("ok"), "error": v.get("error")}
			for s, v in zip(seats, seat_verdicts, strict=True)
		],
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


def resolve_independent_providers(agent_profile: str, judge_provider_name: str | None = None) -> dict:
	"""List the active LLM Provider names that may judge (none is the agent's own).

	Returns `{"names": [<row name>, ...]}` (possibly empty) plus `"reason"` when empty.
	When `judge_provider_name` is given it is the only candidate — still rejected if it
	equals the agent's provider. This is the panel-aware sibling of
	`resolve_judge_provider`: the panel builder cycles these names across its seats.
	"""
	import frappe
	from frappe.friday_core.llm.provider import _resolve_provider_row

	try:
		agent_row = _resolve_provider_row(agent_profile)
		agent_name = agent_row.get("name") if agent_row else None
	except Exception:
		agent_name = None

	if judge_provider_name:
		if judge_provider_name == agent_name:
			return {
				"names": [],
				"reason": (
					f"named judge provider {judge_provider_name!r} is the SAME as the agent's "
					f"provider — not independent. Name a different one."
				),
			}
		return {"names": [judge_provider_name]}

	rows = frappe.get_all("LLM Provider", filters={"is_active": 1}, fields=["name"], order_by="creation asc")
	names = [r["name"] for r in rows if r["name"] != agent_name]
	if not names:
		return {
			"names": [],
			"reason": (
				"no independent judge provider available — the only active LLM Provider is the "
				"agent's own. Configure a second LLM Provider to enable quality scoring."
			),
		}
	return {"names": names}


def build_panel_seats(names: list[str], panel_size: int) -> list[dict]:
	"""Build `panel_size` judge seats by cycling the independent provider `names`.

	Each seat is `{"provider": <built>, "name": <str>, "lens": <str>}`. Providers are
	built once and reused across seats that share a name; lenses are assigned by seat
	index from `_LENS_ORDER`, so two seats on the same provider still judge from
	different angles. A name that fails to build is skipped (the panel shrinks rather
	than crashing). Returns the seats actually built (may be fewer than `panel_size`).
	"""
	from frappe.friday_core.llm.provider import LLMError, get_provider_by_name

	if not names or panel_size < 1:
		return []
	cache: dict[str, object] = {}
	seats: list[dict] = []
	for i in range(panel_size):
		name = names[i % len(names)]
		if name not in cache:
			try:
				cache[name] = get_provider_by_name(name)
			except LLMError:
				cache[name] = None
		provider = cache[name]
		if provider is None:
			continue
		lens = _LENS_ORDER[i % len(_LENS_ORDER)] if panel_size > 1 else ""
		seats.append({"provider": provider, "name": name, "lens": lens})
	return seats
