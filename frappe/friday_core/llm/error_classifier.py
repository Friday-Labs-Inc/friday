# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""
LLM API error classification (Feature F, doc 51 §4.F).

PLAIN ENGLISH
=============
When a call to an AI model fails, *why* it failed decides what to do next:
a rate-limit means "wait and try again", a bad API key means "stop and tell
the user", a too-long conversation means "shorten it". This module turns a
raw failure (an HTTP status code and/or an error message) into a single
labelled answer — a `FailoverReason` — plus three plain hints:

  - `retryable`        — the provider's backoff loop should try again.
  - `should_compress`  — the conversation is too long; shorten it (Feature C).
  - `should_fallback`  — can't recover here; surface a clean error to the user.
    (v0.1 has no provider-fallback chain — Feature G is deferred — so this
    simply means "give up cleanly", not "silently switch providers".)

This is a trimmed port of Hermes' `agent/error_classifier.py`. Hermes carries
deep provider-specific exotica (Anthropic thinking signatures, llama.cpp
grammar, OpenRouter policy blocks, …); we port only the v0.1-relevant subset
and add the rest when the provider that needs them lands.

Pure logic — no `frappe`, no `requests`. Every provider adapter and the
agent loop share this one classifier instead of re-deriving status-code checks.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass


# ── Taxonomy (F.1 — trimmed) ────────────────────────────────────────────────


class FailoverReason(enum.Enum):
	"""Why an API call failed — determines the recovery strategy."""

	auth = "auth"  # 401/403 — bad/expired credentials
	billing = "billing"  # 402 or credit exhaustion
	rate_limit = "rate_limit"  # 429 transient throttling
	overloaded = "overloaded"  # 503/529 — provider overloaded
	server_error = "server_error"  # 500/502 — internal server error
	timeout = "timeout"  # connection/read timeout
	context_overflow = "context_overflow"  # conversation too long — compress
	model_not_found = "model_not_found"  # 404 / unknown model
	format_error = "format_error"  # 400 — malformed request
	unknown = "unknown"  # unclassifiable — retry with backoff


# reason -> (retryable, should_compress, should_fallback). F.3 semantics.
_HINTS: dict[FailoverReason, tuple[bool, bool, bool]] = {
	FailoverReason.auth: (False, False, True),
	FailoverReason.billing: (False, False, True),
	FailoverReason.rate_limit: (True, False, False),
	FailoverReason.overloaded: (True, False, False),
	FailoverReason.server_error: (True, False, False),
	FailoverReason.timeout: (True, False, False),
	FailoverReason.context_overflow: (False, True, False),
	FailoverReason.model_not_found: (False, False, True),
	FailoverReason.format_error: (False, False, True),
	FailoverReason.unknown: (True, False, False),
}


# ── Classification result (F.2) ─────────────────────────────────────────────


@dataclass
class ClassifiedError:
	"""A failure, labelled, with recovery hints. (`should_rotate_credential`
	is omitted vs. Hermes — v0.1 has no key pool.)"""

	reason: FailoverReason
	status_code: int | None = None
	message: str = ""
	provider: str | None = None
	model: str | None = None
	retryable: bool = True
	should_compress: bool = False
	should_fallback: bool = False

	@property
	def is_auth(self) -> bool:
		return self.reason is FailoverReason.auth


# ── Provider-agnostic message patterns (trimmed from Hermes) ────────────────

_BILLING_PATTERNS = (
	"insufficient credits",
	"insufficient_quota",
	"insufficient balance",
	"credit balance",
	"credits have been exhausted",
	"payment required",
	"exceeded your current quota",
	"billing hard limit",
)

_RATE_LIMIT_PATTERNS = (
	"rate limit",
	"rate_limit",
	"too many requests",
	"throttled",
	"requests per minute",
	"tokens per minute",
	"try again in",
	"please retry after",
	"resource_exhausted",
)

_CONTEXT_PATTERNS = (
	"context length",
	"maximum context",
	"context_length_exceeded",
	"context window",
	"too many tokens",
	"reduce the length",
)

_MODEL_NOT_FOUND_PATTERNS = (
	"model not found",
	"model_not_found",
	"does not exist",
	"no such model",
	"invalid model",
	"unknown model",
)


# ── Classifier ──────────────────────────────────────────────────────────────


def classify_api_error(
	error: Exception | None = None,
	*,
	status_code: int | None = None,
	provider: str | None = None,
	model: str | None = None,
	message: str | None = None,
) -> ClassifiedError:
	"""Classify an LLM API failure into a `ClassifiedError` with recovery hints.

	Pass any of: the raised `error` (used to spot timeouts by type/message),
	the HTTP `status_code`, and/or a `message` (response body or error text).
	The most specific signal wins (status code first, then message patterns).
	"""
	text = (message or (str(error) if error is not None else "")).lower()
	err_type = type(error).__name__.lower() if error is not None else ""

	reason = _determine_reason(status_code, text, err_type)
	retryable, should_compress, should_fallback = _HINTS[reason]
	return ClassifiedError(
		reason=reason,
		status_code=status_code,
		message=message or (str(error) if error is not None else ""),
		provider=provider,
		model=model,
		retryable=retryable,
		should_compress=should_compress,
		should_fallback=should_fallback,
	)


def _matches(text: str, patterns: tuple[str, ...]) -> bool:
	return any(p in text for p in patterns)


def _determine_reason(status_code: int | None, text: str, err_type: str) -> FailoverReason:
	"""Priority-ordered reason resolution. Transport timeout first (it can
	carry a misleading status), then status code, then message patterns."""
	# 1. Transport timeout — by exception type or message.
	if "timeout" in err_type or "timed out" in text or "timeout" in text:
		return FailoverReason.timeout

	# 2. HTTP status code — the primary signal.
	if status_code is not None:
		if status_code in (401, 403):
			return FailoverReason.auth
		if status_code == 402:
			return FailoverReason.billing
		if status_code == 429:
			# A 429 is usually transient throttling, but some providers return
			# 429 for credit exhaustion — the message disambiguates.
			return FailoverReason.billing if _matches(text, _BILLING_PATTERNS) else FailoverReason.rate_limit
		if status_code == 404:
			return FailoverReason.model_not_found
		if status_code == 413:
			return FailoverReason.context_overflow
		if status_code == 400:
			# A 400 is a malformed request, unless it's specifically the
			# context being too long (which we compress, not abort).
			return FailoverReason.context_overflow if _matches(text, _CONTEXT_PATTERNS) else FailoverReason.format_error
		if status_code in (503, 529):
			return FailoverReason.overloaded
		if status_code >= 500:
			return FailoverReason.server_error

	# 3. No decisive status — fall back to message patterns.
	if _matches(text, _BILLING_PATTERNS):
		return FailoverReason.billing
	if _matches(text, _RATE_LIMIT_PATTERNS):
		return FailoverReason.rate_limit
	if _matches(text, _CONTEXT_PATTERNS):
		return FailoverReason.context_overflow
	if _matches(text, _MODEL_NOT_FOUND_PATTERNS):
		return FailoverReason.model_not_found

	# 4. Unclassifiable — retry with backoff and move on.
	return FailoverReason.unknown
