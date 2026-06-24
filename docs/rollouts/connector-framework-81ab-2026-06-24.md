# Connector framework — RandomPack becomes connector #1 (Design 81a + 81b)

_Shipped 2026-06-24. Track: `integration` (a first-class Friday Core pillar)._

## In one sentence

Friday used to talk to the RandomPack backend through bespoke, brand-named code;
now it talks through a **generic, reusable "Connector"**, and RandomPack is simply
the first one — proving the framework instead of being a special case.

## Why this matters (plain English)

"Integration is a core capability" can't be true if every integration is
hand-built. Before today, the RandomPack seam was wired one way, chat surfaces
another, MCP another — no shared contract, no single registry, no uniform audit.

This change introduces the **Connector**: one governed, registered way to
integrate with an outside system. Adding the *next* ecosystem becomes "create a
Connector row + a thin handler module," never core surgery. RandomPack — the
live, money-making seam — is the first connector, so the framework is proven on
something real, not a toy.

## What a Connector is

A `Connector` is DATA (a registry row) + a thin adapter:

- **modality** — what kind of system: `system` (signed-event business backend
  like RandomPack), and later `chat` / `mcp` / `a2a`.
- **direction** — inbound, outbound, or both.
- **secrets** — the HMAC webhook secret + the API token, encrypted at rest on
  the row (no more brand-named Settings singleton).
- **handler_module** — for `system` connectors, the dotted Python module whose
  `HANDLERS` dict turns each event into an action.

Two doctypes back it:
- **Connector** — the registry ("what Friday integrates with").
- **Connector Event** — the unified audit row for every inbound signed event
  (the surpass-Hermes line: Hermes has per-adapter config but no single audited
  integration surface).

## What moved where (the two-track law in action)

The **seam** is now generic core; the **meaning** stays in the RandomPack domain.

| Concern | Before (brand-named) | After |
|---|---|---|
| HMAC verify + intake + dispatch | `surfaces/randompack.py` | `connectors/core.py` (generic) |
| Outbound HTTP transport + auth | `randompack_client.send` | `connectors/client.py` (generic) |
| Event meaning (project.created → engine, gate.decided → workflow) | `surfaces/randompack.py` | **stays** in `surfaces/randompack.py` as the `HANDLERS` registry |
| The 5 contract calls (update_task_progress, attach_deliverable, …) | `randompack_client.py` | **stays** as a thin domain adapter resolving endpoint paths |
| Config + secrets | `RandomPack Settings` (single) | a `Connector` row (`randompack-system`) |
| Inbound event ledger | `RandomPack Event` | `Connector Event` (renamed, history preserved) |
| Reconciler durability sweep | `_reconcile_randompack_events` over `RandomPack Event` | `_reconcile_connector_events` over `Connector Event` |
| Health block | `randompack` | `connectors` |

The back-compat URL is untouched: the RandomPack backend still POSTs to
`…surfaces.randompack.receive_event`, which now just delegates to the generic
spine. **Zero RandomPack-side changes required.**

## How the live data was migrated (no loss)

Two ordered patches, both idempotent:

1. **pre-model-sync** `rename_randompack_event_to_connector_event` — renames the
   table `tabRandomPack Event` → `tabConnector Event` *before* the schema sync,
   so the live event history is preserved (not dropped + recreated).
2. **post-model-sync** `migrate_randompack_settings_to_connector` — copies the
   old singleton's URL/key + the encrypted `api_secret`/`webhook_secret` into the
   `randompack-system` Connector row, backfills `connector` on the renamed event
   rows, then retires the `RandomPack Settings` DocType for good.

Fresh sites (no old Settings) instead get a disabled Connector **stub** from the
domain's `after_migrate` (`_ensure_connector`), ready for an operator to fill in
and enable.

## A scoping note (justified divergence)

Design 81's spine calls for "every connector permission-scoped (which Agent
Profile/role may use it)." For a `system` connector that enforcement has no
teeth yet: inbound is authenticated by the HMAC signature (no agent involved),
and outbound is system-triggered (by workflow transitions / the bridge), not
invoked by an agent during a turn. So **role-scoping is deferred to the `mcp`
and `chat` modalities (81c/81d)**, where an agent actually picks up and uses a
connector mid-turn. The audit half of governance (Connector Event) ships now.

## Verification (on the Mac, stack-down)

- `bench migrate` clean, twice (idempotency proven): rename + secret migration +
  backfill (11 event rows → `randompack-system`) + after_migrate provisioning.
- Secrets confirmed carried over (`webhook_secret` decrypts on the new row);
  `RandomPack Settings` DocType gone.
- **60/60 tests pass:** `test_connector_core` 16 (new generic spine),
  `test_randompack_surface` 9 (domain handlers + adapter), and the unchanged
  parity suites `test_randompack_integration` 14, `test_task_reconciler` 12,
  `test_pipeline_health` 9.

## What's next on the integration track

- **81c** — fold Design 67's `MCP Server` under the registry (`mcp` modality).
- **81d** — Slack/Telegram as `chat` connectors (Hermes adapter ports) into the
  unified gateway; permission-scoping gets its teeth here.
- **81e** — A2A (protocol decided then).
