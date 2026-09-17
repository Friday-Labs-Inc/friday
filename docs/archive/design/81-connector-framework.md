# Design 81 — the Friday Connector framework (ecosystem integration as a core pillar)

_Opened 2026-06-23. Track: `integration` (a first-class Friday Core pillar, per
the governing dev-structure directive). Design-lock in progress — forks at the
bottom await the user. Companion: [[friday-labs-charter]], Design 75 (domains as
data), Design 67 (MCP), Design 47 (gateway)._

## Plain English

Friday must talk to other systems as a **built-in capability**, not a bolt-on.
Today each integration is bespoke: chat surfaces are wired one way, the
RandomPack webhook seam another, MCP another. This design unifies them under ONE
generic abstraction — a **Connector** — so adding a new ecosystem is *data + a
thin adapter*, never core surgery. RandomPack's existing HMAC seam becomes
**connector #1**, proving the framework rather than being a special case.

## The problem

Integration logic is scattered and per-system:
- Inbound chat (CLI/Raven/A2A) → `gateway/service.py` surfaces.
- Outbound to RandomPack → `surfaces/randompack.py` (inbound events) +
  `integrations/randompack_bridge.py` / `randompack_client.py` (outbound API).
- Outbound tools → `mcp/` (Design 67).
There's no single contract, no registry, no uniform governance/audit across them.
"Integration is core" can't be true while each one is hand-built.

## The model — a Connector

A **Connector** is a governed, registered integration with an external
ecosystem. It is DATA (a `Connector` record + config) plus a thin typed adapter,
mirroring Design 75's "a domain is data." Each connector declares a **direction**
and a **modality**:

| Modality (locked: all four) | Direction | What it is | Today → unified |
|---|---|---|---|
| **chat** | inbound + outbound | a chat platform (Slack/Telegram/Teams/WhatsApp) as a gateway surface | gateway surfaces → a `chat` connector type |
| **system** | inbound (signed events) + outbound (API) | an external business system (CRM/ERP/RandomPack) over a signed contract | the RandomPack HMAC seam → connector #1 |
| **mcp** | outbound (tools) | an MCP server exposing tools the agent can call | Design 67 `MCP Server` → an `mcp` connector type |
| **a2a** | inbound + outbound | another agent system / Friday deployment over an agent protocol | new |

### Shared spine (what makes it generic + governed)
Every connector, whatever its modality, goes through the same spine:
- **Identity & registry:** a `Connector` DocType (name, modality, direction,
  enabled, config JSON, encrypted secrets, status). The registry is the single
  place that lists "what Friday integrates with."
- **Inbound contract:** signed-event intake (HMAC over RAW bytes — the #1
  integration bug guard from the charter) → persist UUID-unique → 200 fast →
  process on the `friday` queue. Generalises `surfaces/randompack.receive_event`.
- **Outbound contract:** a typed client (auth from the connector's encrypted
  secrets) with retry/backoff; for `system` connectors, an outbox.
- **Governance (the surpass-Hermes line):** every inbound event and outbound
  call is permission-scoped (which Agent Profile/role may use this connector)
  and **audited** (a `Connector Event` row — like Dispatcher Event). Hermes has
  per-adapter config but no unified permissioned/audited integration surface.
- **Surfaces stay thin:** a connector adapter only translates to/from the
  ecosystem's wire format; it never calls the agent runner directly (the
  unified-gateway law, [[feedback_unified-gateway-service]]).

## Generalise NOW — RandomPack as connector #1

Per the user's "generalise now" decision: refactor the RandomPack seam into a
`system` connector instance.
- The `RandomPack Settings` single → a `Connector` row (modality=system,
  direction=both, config = api_base_url + the HMAC secret).
- `surfaces/randompack.receive_event` → the generic signed-event intake keyed by
  connector; the RandomPack-specific event→engine mapping stays in the
  RandomPack domain (Track B), NOT in the connector core.
- `randompack_client` → a `system` outbound client built from the connector row.
- **The law holds:** the *connector framework* is `core`/`integration` (generic);
  the *RandomPack event semantics* (project.created→engine, gate.decided→workflow)
  stay in `domain:randompack`. The seam is generic; the meaning is domain data.

## Hermes comparison (required)

Hermes: gateway has a `platform_registry` of chat adapters (poll/webhook/ws) +
MCP + Honcho-style external memory. Each is configured independently; no unified
governance. Friday **surpasses**: one `Connector` registry across all four
modalities, each permission-scoped + audited, secrets encrypted, single-tenant.
We port Hermes' adapter patterns (poll loop / webhook / ws for chat) faithfully
into the `chat` connector type; the registry + governance spine is the Friday
addition.

## Slice plan (proposed)

1. **81a — the spine:** `Connector` DocType + registry + `Connector Event` audit
   + the generic signed-event intake + permission scoping. No new ecosystem yet.
2. **81b — connector #1:** refactor the RandomPack seam onto the spine (system
   connector); RandomPack domain mapping unchanged. Prove parity on the existing
   round-trip.
3. **81c — MCP as a connector:** fold Design 67's `MCP Server` under the registry
   (mcp modality) — mostly a re-home + governance unification.
4. **81d — chat connectors:** Slack/Telegram as `chat` connectors (Hermes adapter
   ports) into the unified gateway.
5. **81e — A2A:** agent-to-agent connector (protocol TBD).

Runs in parallel with the remaining Core/Hermes-port gaps (interrupt/steer).

## Locked decisions (2026-06-23)

- **F1 — registry granularity: ONE `Connector` DocType** + a `modality` field +
  a `config` JSON (+ encrypted secret fields). Simplest single registry;
  modality-typed behaviour in code, not schema.
- **F2 — connector #1: refactor the LIVE RandomPack seam directly onto the
  spine** (true "generalise now"). Parity guarded by the existing round-trip
  tests; RandomPack's event *meaning* stays in `domain:randompack`.
- **F3 — A2A protocol: DEFERRED** to slice 81e (decide adopt-standard vs
  Friday-native signed-message then).
- **F4 — sequencing: spine → system(RandomPack) → MCP → chat → A2A.** Ground the
  framework in the real use case (the live seam) first, then re-home MCP, then
  chat, then A2A.

## Locked slice plan

1. **81a — the spine:** ✅ **SHIPPED 2026-06-24.** `Connector` DocType + registry
   + `Connector Event` audit + generic signed-event intake (`connectors/core.py`)
   + generic outbound client (`connectors/client.py`). Permission scoping deferred
   to 81c/81d (see note below). (No new ecosystem yet.)
2. **81b — connector #1:** ✅ **SHIPPED 2026-06-24.** Refactored the LIVE
   RandomPack seam onto the spine (`randompack-system` system connector);
   RandomPack domain mapping unchanged (`surfaces/randompack.HANDLERS` +
   `randompack_client` thin adapter). Parity proven: 60/60 tests + clean migrate.
   `RandomPack Settings` → Connector row + `RandomPack Event` → Connector Event
   (renamed, history preserved) via two idempotent patches. See
   [[connector-framework-81ab-2026-06-24]].
3. **81c — MCP** folded under the registry (mcp modality).
4. **81d — chat** connectors (Slack/Telegram, Hermes adapter ports) into the
   unified gateway. **Permission scoping gets its teeth here** (an agent actually
   invokes the connector mid-turn).
5. **81e — A2A** (protocol decided then).

Runs in parallel with the remaining Core/Hermes-port gap (interrupt/steer).

### Permission-scoping note (81a/81b divergence, justified)

The spine calls for per-connector permission scoping. For the `system` modality
that has no teeth yet: inbound is HMAC-authenticated (no agent), outbound is
system-triggered (workflow/bridge, not an agent turn). So enforcement is deferred
to `mcp`/`chat` (81c/81d), where an agent picks up and uses a connector during a
turn. The **audit** half (Connector Event) shipped in 81a.
