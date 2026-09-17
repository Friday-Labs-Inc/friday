# ADR-0005 — If Friday is down, every product still works

**Status:** Accepted · 2026-09-17
**Relates:** ADR-0004

## Context

Friday is an AI platform: it depends on model providers, background workers,
vector search and a Postgres bench. Every one of those can be unavailable. The
products it serves are businesses that must keep operating regardless — a design
studio still has to take a brief, raise an invoice and deliver files.

No rule said so. The RandomPack seam happened to be built this way, but as an
implementation detail of one integration rather than a platform invariant.

## Decision

**Friday is never on a product's critical path.**

If Friday is unavailable, every product remains **operable by humans, end to
end** — degraded, never blocked. This holds for every current and future domain,
including robotics.

The mechanics that enforce it:

- A product **emits** facts; Friday **consumes** them. A product never calls
  Friday and waits for an answer to complete a user action.
- Friday **writes back** through the product's guarded, versioned API. A failed
  write-back is retried, never a lost transaction.
- The product's own database is the truth. Friday holds a **projection** —
  execution tasks linked by reference — never a second source of truth.
- Every human step a product needs must exist in the product's own UI, whether
  or not an agent normally does it.

## Consequences

- Any feature that makes a product block on Friday is a violation, however
  convenient. That includes synchronous agent calls in a request path.
- Outbound event delivery needs durable retry and replay on the product side.
- "Friday is down" must be a tested state for each domain, not a hypothetical.

## Evidence

- The RandomPack contract already follows this shape: signed webhooks outbound,
  `randompack.api.v1.*` write-back, `Pending Review` as a human signal.
- The engine's own projection rule: Friday's Task carries a reference to the
  product's record; the product's Project remains the truth.
