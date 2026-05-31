# 37 — Multi-Site Inter-Agent Communication

> See `00-glossary.md` for term definitions.
> Phase: not in v0.1 per `42-phase-one-authority-contract.md` §4 ("Cross-site agent communication"). Phase 2+.

---

## 1. Why multi-site

A single Friday installation runs on a single Frappe site. Real organisations have:

- Multiple Frappe sites (one per company, one per region).
- Parent and subsidiaries each running separate Friday instances.
- Friday running locally for a customer alongside Friday Labs cloud services.
- Partner Friday instances that need to coordinate directly across organisations.

Agents in different Friday sites must discover, authenticate, and exchange messages with each other — safely.

---

## 2. Agent Communication Protocol (ACP)

ACP is a minimal, secure, async messaging protocol between Friday sites.

### Transport

- HTTPS only (no plaintext HTTP).
- mTLS by default — each Friday site has its own X.509 certificate.
- HTTP/2 multiplexing for high-throughput pairs (optional).
- Body: JSON.

### Message structure

```json
{
  "version": "acp/1.0",
  "message_id": "uuid-v4",
  "conversation_id": "uuid-v4",
  "sender": {
    "site": "https://friday-a.example.com",
    "agent": "support-agent",
    "instance_id": "uuid"
  },
  "recipient": {
    "site": "https://friday-b.example.com",
    "agent": "support-agent"
  },
  "intent": "purchase_order_announce",
  "payload": { ... },
  "signed_at": "2026-04-12T14:23:11Z",
  "signature": "ed25519-sig-base64"
}
```

### Intents

A small, versioned catalogue. Initial set:

- `task_announce` — one site announces a new cross-org request to a partner site.
- `status_notification` — a site notifies a partner of a status change.
- `result_announce` — a site announces that a deliverable or result is ready.
- `receipt_confirmation` — a site confirms it received and accepted a message.
- `resource_query` — request resource/availability information from a partner.
- `resource_response` — answer to query.
- `escalation_handoff` — escalate a problem to a partner's human supervisor.
- `acknowledgment` — generic ACK with optional payload.

Intents are namespaced (`erpnext.purchase_order_announce`) and versioned (`v1`).

---

## 3. Friday Partner Site DocType

| Field | Type |
|---|---|
| `site_name` | Data (unique) — e.g. "Acme Org Friday" |
| `site_url` | Data — base URL |
| `public_key` | Long Text — signature verification |
| `certificate_fingerprint` | Data — mTLS cert pin |
| `trust_level` | Select — Untrusted / Verified / Trusted |
| `allowed_intents` | Child table — permitted intents from this site |
| `rate_limit_per_minute` | Int |
| `last_heartbeat_at` | Datetime |
| `status` | Select — Active / Suspended / Revoked |

---

## 4. Service discovery

### Mode 1 — Manual

Supervisor adds a Partner Site record by hand with URL, public key, and certificate fingerprint exchanged out-of-band (email, phone confirmation). **Phase 2 default.**

### Mode 2 — Well-known endpoint

Each Friday site exposes `https://{site}/.well-known/friday-acp`:

```json
{
  "site_name": "Acme Org Friday",
  "public_key": "ed25519-pubkey-base64",
  "supported_intents": [ ... ],
  "contact": "ops@acme.com",
  "trust_anchors": [ ... ]
}
```

A supervisor pastes a partner's URL; Friday auto-fetches and presents the discovered config for approval.

### Mode 3 — Registry (Phase 4)

A Friday Labs-hosted partner registry. Opt-in publish; opt-in search. Auditable.

---

## 5. Authentication

mTLS at transport ensures only certified sites connect. Each message also carries an Ed25519 signature over the canonical body, verified using the partner's public key from the Partner Site record.

Replay protection: each message has a `message_id`; duplicates within 24 hours are rejected.

---

## 6. Authorisation

Incoming message:

1. Verify TLS client cert against `Partner Site.fingerprint`.
2. Verify Ed25519 signature.
3. Look up Partner Site; status must be Active.
4. Check `intent` is in `allowed_intents` for this partner.
5. Check rate limit (rolling 60s window).
6. All pass → enqueue for processing.
7. Any fail → reject with appropriate code; log.

---

## 7. Processing

Incoming messages enqueue to a Frappe RQ queue. A worker:

1. Resolves the intent handler (`friday.acp.handlers.{intent_name}`).
2. Invokes the handler with the message.
3. Handler is intent-specific — `task_announce` creates a local work item from the incoming request data.
4. Handler emits an acknowledgment message back to the sender.

Intent handlers run in the same sandbox isolation as skills per `24-sandbox-architecture-implementation.md`. They are code Friday maintainers ship and review.

---

## 8. Rate limiting

Per-partner limits prevent a misbehaving or hostile partner from overwhelming a site:

- Default: 60 messages/minute per partner.
- Burst: 10 messages in 5 seconds allowed.
- Sustained excess: messages 429'd; partner notified.

Configurable per partner site.

---

## 9. Escalation handoff

The `escalation_handoff` intent — when agent A cannot resolve an issue and needs partner site B's human supervisor:

1. Agent A composes an escalation message with context.
2. Sends to partner B.
3. B's Friday creates an Agent Task with priority "External Escalation" in B's War Room.
4. B's supervisor responds via ACP message back.
5. Conversation continues async until resolved.

Formalises B2B human ↔ human ↔ agent collaboration.

---

## 10. Privacy

Outbound messages reviewed before leaving:

- Personal-data redaction policies applied (e.g. internal employee IDs replaced with opaque tokens).
- Sensitive memory entries blocked.
- Supervisor configures per-partner what fields are includable.

A data-sharing audit log records exactly what content went to whom and when. GDPR / DPDPA discovery cost is small because everything is queryable.

---

## 11. Trust levels

| Level | Behaviour |
|---|---|
| **Untrusted** | Friday only sends acknowledgments to messages; does not initiate. Useful for new partners during a verification period |
| **Verified** | Standard interaction. Most partners |
| **Trusted** | Reduced approval gates; certain autopilot actions can proceed without re-approval per message. Reserved for long-established partners |

Trust-level changes are supervisor decisions, logged.

---

## 12. Conflict resolution

When two sites disagree (e.g. one site says a task is done, the other says it never arrived):

1. Both agents flag the discrepancy.
2. Escalation handoff initiated.
3. Conversation continues until resolution.
4. Resolution recorded as Memory Entries (`Reflective`) in both sites.
5. Repeated pattern enters the learning loop (`22-hermes-learning-loop-deep-dive.md`) for future automation.

---

## 13. Topology

| Phase | Topology |
|---|---|
| 2 | Pairwise direct connections only. No relays, no brokers |
| 4 | Optional Friday Labs cloud relay for sites behind NAT or with intermittent connectivity. Messages queue at the relay, deliver when destination reachable. Relay never sees plaintext (end-to-end signed; payload may be additionally encrypted) |

---

## 14. Observability

Per partner connection:

- Messages sent / received per hour.
- Latency p50, p99.
- Error rate per intent.
- Last successful exchange timestamp.

Visible in the Framework Console operations view.

---

## 15. Failure modes

**Partner unreachable**
- Outbound messages retry with exponential backoff (5min, 15min, 1h, 6h, 24h).
- After 24h unreachability, partner marked `Status=Suspended`; supervisor notified.
- Conversation marked stalled; agent may pursue alternative paths.

**Partner sends malformed message**
- Reject with HTTP 400 + reason.
- Log for investigation.
- Repeated malformed messages → automatic `Status=Suspended`.

**Partner sends apparently malicious message** (impossible intent, oversized payload)
- Drop.
- Log with high priority.
- Notify supervisor.
- After 3 in 24h → automatic `Status=Revoked`; manual reinstatement required.

---

## 16. Phasing

| Phase | Scope |
|---|---|
| 1 (v0.1) | Not in scope per `42-phase-one-authority-contract.md` §4. Friday Phase 1 is single-site only |
| 2 | Partner Site DocType (manual entry); ACP protocol; 4 core intents (task announce, status notify, result announce, receipt confirm); mTLS + Ed25519 signature verification; rate limiting; basic escalation handoff |
| 3 | Well-known endpoint discovery; full intent catalogue; trust levels; data-sharing audit; failure-mode handling |
| 4 | Optional cloud relay; partner registry (Friday Labs hosted); multi-party conversations (3+ sites); inter-site analytics with consent |

---

## 17. Open questions

- Intent versioning — when a new intent version supersedes an old one, support both for 24 months minimum.
- Message size limit — 1MB payload Phase 2; larger needs alternative (file transfer with checksum and out-of-band signal).
- Inter-site identity beyond the Friday installation — when humans need to be addressable across sites, federate user IDs? Out of scope until at least Phase 4.
- Compliance with regional data residency (Indian DPDPA, EU GDPR) — each site enforces its own residency; ACP carries only what local policy permits.
