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
	  criteria      [{criterion, met, reason}] — one per RUBRIC criterion (in rubric
	                order), each matched to the judge's verdict by normalised text
	  unmet         the rubric criteria not met (the credit-assignment view)
	  met_count/total
	  ok            True iff every rubric criterion is met (per-criterion checklist)
	  error         set (and ok False) if the judge call failed or was unparseable

	Scoring is anchored on the RUBRIC, not on whatever the judge echoed: a criterion the
	judge reordered is still matched (by text); one it duplicated, skipped, or invented
	can't shift the verdict — an unmatched rubric criterion is not-met. So a judge can't
	pass the checklist by returning the right COUNT of wrong items.

	`lens` (Slice 3) selects a perspective framing for a panel seat; "" = neutral.
	"""
	total = len(rubric)
	if total == 0:
		# No rubric → nothing to judge. Treated as "not applicable" by the runner.
		return {"criteria": [], "unmet": [], "met_count": 0, "total": 0, "ok": True}

	messages = build_judge_messages(reply, rubric, "", lens)
	try:
		resp = provider.chat(messages, model=model)
		content = resp["content"] if isinstance(resp, dict) else getattr(resp, "content", "")
	except Exception as exc:  # a judge transport/auth failure: the seat could not run.
		return _judge_error(rubric, f"judge call failed: {type(exc).__name__}", unavailable=True)

	parsed = _extract_json(content or "")
	if not parsed or not isinstance(parsed.get("criteria"), list):
		return _judge_error(rubric, "judge returned unparseable output")

	raw = [item for item in parsed["criteria"] if isinstance(item, dict)]
	# Anchor on the rubric: one output entry per rubric criterion, matched to the judge's
	# verdict by text (fallback index). An unmatched criterion is not-met — so omission,
	# duplication, or reordering by the judge can't game the checklist.
	criteria = []
	for crit in rubric:
		item = _seat_item_for(raw, crit)
		criteria.append(
			{
				"criterion": crit,
				"met": bool(item.get("met", False)) if item else False,
				"reason": str(item.get("reason", "")) if item else "",
			}
		)
	unmet = [c["criterion"] for c in criteria if not c["met"]]
	return {
		"criteria": criteria,
		"unmet": unmet,
		"met_count": sum(1 for c in criteria if c["met"]),
		"total": total,
		"ok": not unmet,
	}


def _judge_error(rubric: tuple[str, ...], reason: str, unavailable: bool = False) -> dict:
	"""A failed/unparseable judge call → a quality FAIL carrying the reason.

	`unavailable=True` marks a seat that COULD NOT RUN (auth/transport failure) vs one
	that ran but returned junk. A panel excludes unavailable seats from the vote (and
	SKIPs if all seats are unavailable) — a misconfigured judge must not be scored as the
	agent failing the rubric. Unparseable output is NOT unavailable: the judge ran, so it
	counts as a not-met vote (a working-but-junk judge can't pass a reply by omission).
	"""
	return {
		"criteria": [],
		"unmet": list(rubric),
		"met_count": 0,
		"total": len(rubric),
		"ok": False,
		"error": reason,
		"unavailable": unavailable,
	}


def _norm(s: str) -> str:
	"""Normalise a criterion string for matching: lowercase, punctuation → space, collapse.

	So "Is concise." and "is concise" match, but two genuinely different criteria don't.
	"""
	return " ".join(re.sub(r"[^a-z0-9 ]+", " ", (s or "").lower()).split())


def _seat_item_for(items: list[dict], criterion: str) -> dict | None:
	"""Find a judge's verdict for ONE rubric criterion, matched by normalised text.

	Match is by text, NOT array position — so a judge that reorders criteria is still
	scored correctly, and one that omits, duplicates, or invents criteria can't shift a
	verdict by position. Returns None when this criterion was not addressed at all, which
	the caller treats as not-met (a criterion can't be met without an explicit verdict).
	No index fallback by design: falling back to position is exactly what lets a judge
	pass a criterion it never actually judged (e.g. two copies of criterion A, no B → B
	must be not-met, not silently matched to the second A).
	"""
	target = _norm(criterion)
	for it in items:
		if _norm(it.get("criterion", "")) == target:
			return it
	return None


def run_panel(reply: str, rubric: tuple[str, ...], seats: list[dict]) -> dict:
	"""Score `reply` with a PANEL of independent judges and vote per criterion.

	`seats` is a list of `{"provider": <built>, "name": <str>, "lens": <str>}`. Each
	seat judges the full rubric from its lens; a criterion is **met** iff a strict
	majority of the VOTABLE seats marked it met. A seat that could not run (auth/
	transport failure) is excluded from the vote, not counted against the reply; a seat
	that ran but omitted/garbled a criterion is a not-met vote (no passing by omission).
	If every seat is unavailable, the verdict is **skipped** (`ok=None, skipped=True`) —
	a misconfigured judge is never scored as the agent failing.

	Returns the `judge_quality` verdict shape (so the runner + report are unchanged) plus
	panel detail: `panel_size`, per-criterion `votes` ("k/N" over votable seats), and a
	`seats` summary. A 1-seat panel is exactly the Slice 2 single-judge verdict.
	"""
	total = len(rubric)
	n = len(seats)
	if total == 0:
		return {"criteria": [], "unmet": [], "met_count": 0, "total": 0, "ok": True, "panel_size": n}
	if n == 0:
		# No seat could be built (every independent provider failed to construct) → the
		# quality axis is unavailable, which is a SKIP, not the agent failing the rubric.
		return {
			"ok": None,
			"skipped": True,
			"reason": "panel has no seats — no independent judge provider could be built",
			"criteria": [],
			"unmet": [],
			"met_count": 0,
			"total": total,
			"panel_size": 0,
			"seats": [],
		}

	# Each seat's full verdict (judge_quality never raises).
	seat_verdicts = [
		judge_quality(reply, rubric, provider=s["provider"], lens=s.get("lens", "")) for s in seats
	]
	seats_summary = [
		{"name": s.get("name", ""), "lens": s.get("lens", ""), "ok": v.get("ok"), "error": v.get("error")}
		for s, v in zip(seats, seat_verdicts, strict=True)
	]

	# A seat that COULD NOT RUN (auth/transport failure) is EXCLUDED from the vote — an
	# absent verdict, not a not-met one. If EVERY seat is unavailable, the panel can't
	# judge at all → SKIP (never score the agent down for a misconfigured judge; a live
	# run caught 3 keyless judge rows → LLMAuthError on every seat). A seat that ran but
	# returned junk (unparseable) STAYS in the vote as not-met — a working-but-broken
	# judge can't pass a reply by omission.
	votable = [v for v in seat_verdicts if not v.get("unavailable")]
	unavailable_errors = [v["error"] for v in seat_verdicts if v.get("unavailable")]
	if not votable:
		reason = unavailable_errors[0] if unavailable_errors else "no judge produced a verdict"
		return {
			"ok": None,
			"skipped": True,
			"reason": f"all {n} judge seat(s) unavailable — {reason}",
			"criteria": [],
			"unmet": [],
			"met_count": 0,
			"total": total,
			"panel_size": n,
			"seats": seats_summary,
		}

	nv = len(votable)
	criteria = []
	unmet = []
	for crit in rubric:
		votes_met = 0
		met_reasons: list[str] = []
		unmet_reasons: list[str] = []
		for v in votable:
			# Match this votable seat's verdict to THIS criterion by text; one that didn't
			# address it (None / unparseable) is a not-met vote — it stays in the
			# denominator, so a criterion can't be met by omission.
			item = _seat_item_for(v.get("criteria", []), crit)
			if item is None:
				continue
			if item.get("met"):
				votes_met += 1
				if item.get("reason"):
					met_reasons.append(item["reason"])
			elif item.get("reason"):
				unmet_reasons.append(item["reason"])
		majority = votes_met * 2 > nv
		if not majority:
			unmet.append(crit)
		# Surface a reason that EXPLAINS the verdict: a dissent for a failed criterion,
		# else a supporting reason — so the report's "why" line is actually informative.
		reason = (unmet_reasons or met_reasons) if not majority else (met_reasons or unmet_reasons)
		criteria.append(
			{
				"criterion": crit,
				"met": majority,
				"votes": f"{votes_met}/{nv}",
				"reason": reason[0] if reason else "",
			}
		)

	return {
		"ok": not unmet,
		"panel_size": n,
		"criteria": criteria,
		"unmet": unmet,
		"met_count": sum(1 for c in criteria if c["met"]),
		"total": total,
		"seats": seats_summary,
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
		except Exception as exc:
			# ANY build failure (LLMError, or frappe.ValidationError for a row with no
			# stored api_key) → blocked, not a crash.
			return {"provider": None, "name": None, "reason": f"{type(exc).__name__}: {exc}"}
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
			except Exception:
				# Skip a row that won't build (e.g. no stored api_key) — try the next.
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

	A build can fail for MANY reasons, not just `LLMError`: a sandbox often has stale
	`LLM Provider` rows with no stored `api_key`, and `get_provider_by_name` then raises
	`frappe.ValidationError` ("Password not found") — NOT an `LLMError`. So we skip on
	ANY exception; one junk provider row must never crash the whole eval. (A real live
	run on friday.localhost caught exactly this — a leftover `*-test-provider` with no
	key — which the old `except LLMError` let through to a crash.)
	"""
	from frappe.friday_core.llm.provider import get_provider_by_name

	if not names or panel_size < 1:
		return []
	cache: dict[str, object] = {}
	seats: list[dict] = []
	for i in range(panel_size):
		name = names[i % len(names)]
		if name not in cache:
			try:
				cache[name] = get_provider_by_name(name)
			except Exception:
				cache[name] = None
		provider = cache[name]
		if provider is None:
			continue
		lens = _LENS_ORDER[i % len(_LENS_ORDER)] if panel_size > 1 else ""
		seats.append({"provider": provider, "name": name, "lens": lens})
	return seats
