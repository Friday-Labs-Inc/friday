# Design 67 — MCP / outside-world tools (2026-06-13)

## The one-sentence version

Point Friday at a remote MCP server, click **Sync Tools**, and its tools become
governed Friday skills your agents can use — web search, GitHub, a browser,
any MCP server — permission-gated and audit-logged like everything else.

## What this PR ships

### 1. The MCP client — `mcp/client.py`

A minimal **streamable-HTTP** MCP client: JSON-RPC 2.0 over `requests` (no
asyncio, no new dependency — it fits Friday's synchronous RQ workers). It does
the `initialize → notifications/initialized → tools/list | tools/call` handshake
statelessly per operation, parses both JSON and SSE responses, captures the
`Mcp-Session-Id`, and raises `McpError` on transport/protocol/tool errors.
Refuses non-http URLs.

### 2. The `MCP Server` DocType

Operator config (mirrors LLM Provider): `server_name`, `base_url`, `transport`
(streamable-http), `enabled`, an encrypted `auth_token` (bearer) + `headers_json`
for extra static headers, `tool_include`/`tool_exclude` filters, and
`last_synced`/`last_sync_status`.

### 3. Sync = MCP tools become Skills — `mcp/sync.py`

The keystone. **Sync Tools** (`sync_server`, System-Manager-gated) connects to the
server, lists its tools, applies the filter, and writes one `Skill` per tool
named `mcp_<server>_<tool>` with the tool's `inputSchema` as its
`parameters_schema` and `mcp_server`/`mcp_tool_name` links (two new Skill fields).
Tools the server no longer advertises are **Archived** (never deleted —
preserves audit history + profile links). Because they're ordinary Skills, the
loader, the prompt's tool list, the permission matrix, the approval gate and the
Execution Log all work **unchanged**. A daily cron (`sync_all_due`) keeps them
fresh.

### 4. Dispatch — `skills/handlers_mcp.py` + a tiny dispatcher fallback

MCP skill names are dynamic, so they aren't in the static handler registry. The
dispatcher gains one fallback: if no handler is registered and the Skill row has
an `mcp_server`, route to `handlers_mcp.invoke`, which calls the server via the
client and returns `{"result": text}` (or raises `McpError`, scrubbed of secret
patterns, so the dispatcher's error path surfaces it). Everything *before*
dispatch — `matrix_check` (Permission Decision Log), approval, the Execution Log
— is the existing governed path, untouched. MCP runs in-process (outbound HTTP),
not the Docker sandbox.

## Compare with Hermes

Hermes' MCP client is broader (stdio + SSE + sampling + resources + a circuit
breaker) but its tools live in a flat registry with no per-agent gating. We port
the protocol + safety instincts (URL guard, secret scrubbing) and adapt to the
host — synchronous `requests`, and **MCP tools as governed Skills**. Per
[[feedback_hermes-floor-not-ceiling]] the surpass axis is governance: every MCP
call is permission-checked and audit-logged, and an agent can use an MCP tool
only when the operator grants it via `permitted_skills`.

## Security (the CRITICAL bar — [[feedback_v01-skills-first-party-trust]])

Opt-in per agent (sync grants nothing); `auth_token` encrypted + never logged;
URL scheme validated (no `file://`); server error text scrubbed of bearer/key/
secret patterns before reaching the model; operators can raise a synced skill's
`risk_level`/`requires_approval` to route it through the approval gate.

## Why we know it works

17 unit tests: `test_mcp_client` (handshake + session id, JSON & SSE parsing,
tool success, isError, JSON-RPC error, structuredContent fallback, non-http
guard) and `test_mcp_sync` (sanitize/name, include/exclude filter, header
building, upsert-new + archive-stale + status stamp, error-status + re-raise,
and the handler: success, disabled-server raise, resolve_handler). All green.

## Scoped out (named, deferred)

stdio transport (needs a subprocess manager RQ workers lack), SSE *streaming*
results, MCP sampling / resources / prompts, OAuth-authenticated MCP servers,
the circuit breaker / OSV scans, and auto-granting tools to agents.

## Operator note

`bench migrate` + `bench build --app frappe`. Create an **MCP Server** (base URL
+ optional bearer), **Sync Tools**, then add the resulting `mcp_<server>_*`
skills to an Agent Profile's **Permitted Skills**. The agent can now call them;
each call shows in the Permission Decision Log + Execution Log.
