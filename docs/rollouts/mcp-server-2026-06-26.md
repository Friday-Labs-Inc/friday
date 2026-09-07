# Friday as a governed MCP server (2026-06-26)

> A major new enterprise capability: Friday now **serves** MCP, not just consumes it.
> Any MCP client — Claude Code, Claude Desktop, another agent framework — can drive
> Friday's skills as tools, and **every call is governed**: permission matrix + audit
> log + human approval gate. An ordinary MCP server hands out *raw* tools; Friday hands
> out *governed* ones. That's the enterprise difference.

## What it is

Friday already spoke MCP as a **client** (`mcp/client.py` — discover + call tools on
remote servers). This adds the inverse: a **server** endpoint that exposes Friday's own
skills as MCP tools over the same streamable-HTTP JSON-RPC 2.0 subset.

- **Endpoint:** `POST /api/method/friday.friday_core.mcp.server.handle`
- **Auth:** `Authorization: Bearer <token>` (the MCP transport-level auth).
- **Methods:** `initialize` · `notifications/initialized` · `tools/list` · `tools/call`.

## The governance — the whole point

| Step | What happens |
|---|---|
| `tools/list` | Returns the skills the configured **Exposed Agent Profile** is allowed to see — role + permission-matrix scoped (via the real skill loader). The client never gets more than that profile has. |
| `tools/call` | Routes the call through the **real dispatcher** as that profile → the permission matrix decides, an **Execution Log** row is written, and a `requires_approval` skill **pauses for a human** (the client is told "needs approval"). |

So an external AI client gets a **least-privilege, fully-audited** slice of Friday — and
a gated action it calls is *enforced*, surfaced back as a normal tool result
(`isError:false`, "needs human approval"), not silently run.

## Configure (Desk)

`MCP Server Settings` (a Single doctype, System Manager only):
- **Enabled** — off → the endpoint returns 404.
- **Exposed Agent Profile** — whose governed skills are exposed + which profile every
  call runs as.
- **Bearer Token** — a long random secret (encrypted). Clients present it as
  `Authorization: Bearer <token>`.

Point an MCP client at the endpoint with that token and it will see Friday's skills as
tools.

## Design notes

- `handle_jsonrpc(...)` is a **pure** protocol+governance core (injectable `list_fn` /
  `dispatch_fn`) — unit-testable with no Frappe, no DB, no LLM. `handle()` is a thin
  whitelisted endpoint that does auth + body I/O and returns a **raw JSON-RPC body**
  (verified against Frappe's `handler.py`: a returned `werkzeug.Response` is passed
  through, bypassing the `{"message": …}` wrapper an MCP client wouldn't expect).
- **MCP error convention honored:** a permission denial / failure / pending-approval is a
  normal result with `isError`, not a JSON-RPC protocol error (those are reserved for
  malformed requests / unknown methods).
- **Scoped out (v1):** resources, prompts, sampling, SSE partial-result streaming,
  per-session state, OAuth — symmetric with the client's v1 scope (design 67).

## Validation

- **11 DB-free unit tests** (`test_mcp_server.py`): initialize, the no-response
  notification, tools/list mapping, governed tools/call (routes through the dispatcher
  as the profile), denial → `isError`, pending-approval surfaced, dispatch exception →
  tool error, malformed/unknown → JSON-RPC error. ruff clean.
- **Live real-path check** (`bench execute …mcp.server.handle_jsonrpc`): `tools/list`
  against the real `Friday` profile returned all 12 of its skills as valid MCP tool
  defs with JSON-Schema `inputSchema`. `bench migrate` clean.
- **Pending:** a full HTTP round-trip (curl with the bearer token + an MCP client
  handshake) needs the web stack up — to be exercised on deploy.
