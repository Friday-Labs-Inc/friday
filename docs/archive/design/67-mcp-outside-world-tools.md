# Design 67 — MCP / Outside-World Tools

**Status:** LOCKED 2026-06-13. Transport fork answered by the user:
**HTTP / remote MCP only** (streamable-HTTP, hand-rolled JSON-RPC over
`requests` — no asyncio, no new dependency). stdio MCP is a deferred follow-up
(it needs subprocess-lifecycle management RQ workers aren't built for). One PR.
Tests-first per [[feedback_workflow-design-lock-before-roo-code]].

## Why this exists — the plain English

Friday's agents can read/write governed DocTypes (66) and run sandboxed skills,
but they can't reach the **outside world** — web search, a browser, GitHub, a
SaaS API. The Model Context Protocol (MCP) is the emerging universal way to
expose such tools. Design 67 lets an operator point Friday at a remote MCP
server and have its tools become first-class, **governed** agent tools.

## The principle that drives every Q below

> **An MCP tool is just another Skill.** Syncing a server writes one `Skill`
> row per tool (its `inputSchema` becomes the `parameters_schema`), so the
> *entire* existing pipeline — the loader, the prompt's tool list, the
> permission matrix, the approval gate, the Execution Log — works unchanged. The
> only new runtime piece is a dispatch handler that routes an `mcp_*` call to
> the server. Governance is unchanged: an agent can use an MCP tool only when
> the operator adds that Skill to the profile's `permitted_skills`.

## Compare with Hermes

Hermes' MCP client (`tools/mcp_tool.py`) supports stdio + streamable-http + SSE,
persistent asyncio connections, sampling callbacks, resources/prompts, a circuit
breaker, OSV malware scans. We port the **protocol + the safety instincts**
faithfully ([[feedback_true-1to1-ports]]) but adapt hard to the host: Friday's
RQ workers are synchronous and `requests`-based, so we implement the
**streamable-HTTP request/response subset** by hand (initialize → tools/list →
tools/call), and we make MCP tools *Skills* so they inherit Friday's governance
(which Hermes' flat registry doesn't have). The surpass-Hermes axis
([[feedback_hermes-floor-not-ceiling]]): **every MCP tool call is
permission-checked and audit-logged** like any other governed action — Hermes
has no per-agent MCP gating or decision log.

Deliberately scoped OUT of v1 (named, not silently dropped): stdio transport,
SSE streaming responses, MCP sampling (server-initiated LLM calls), MCP
resources/prompts, OAuth-authenticated MCP servers (static bearer/header only),
the circuit breaker, OSV scans (no subprocess to scan).

## Q1 — Transport *(LOCKED: streamable-HTTP, hand-rolled)*

`mcp/client.py` speaks MCP streamable-HTTP as JSON-RPC 2.0 over `requests`:
- `Accept: application/json, text/event-stream`; the response is parsed as
  plain JSON **or** SSE (a `data:` line carrying the JSON-RPC message) — both
  are valid per spec.
- Handshake per operation (stateless — RQ workers don't hold a session across
  jobs): `initialize` → capture any `Mcp-Session-Id` header → `notifications/
  initialized` → the real call (`tools/list` or `tools/call`). The latency cost
  (3 short POSTs per tool call) is accepted for v1 robustness; a per-turn
  session cache is a later optimization.
- Auth: a static `Authorization: Bearer <token>` (from an encrypted field) and/
  or extra static headers. OAuth-MCP is out of scope.
- Failures raise `McpError`; the handler turns it into a tool-result error the
  model can read (never a silent empty result).

## Q2 — Data model *(recommended)*

**New `MCP Server` DocType** (mirrors the LLM Provider / Chat Platform pattern):

| field | type | purpose |
|---|---|---|
| `server_name` | Data, unique, autoname | the `<server>` in `mcp_<server>_<tool>`; sanitized to `[a-z0-9_]` |
| `base_url` | Data, reqd | the MCP endpoint URL |
| `transport` | Select (`streamable-http`), default | future-proof; one option now |
| `enabled` | Check, default 1 | kill switch |
| `auth_token` | Password | optional bearer (encrypted) |
| `headers_json` | JSON | optional extra static headers |
| `tool_include` | Small Text | optional allowlist (newline/comma) |
| `tool_exclude` | Small Text | optional denylist |
| `last_synced` | Datetime, read_only | |
| `last_sync_status` | Small Text, read_only | ok / the error |

**Two fields added to `Skill`** (only set on MCP-sourced skills): `mcp_server`
(Link → MCP Server) + `mcp_tool_name` (Data, the *original* unprefixed tool
name). These make dispatch unambiguous (no fragile name-parsing) and let re-sync
find a server's skills for cleanup. The loader/matrix ignore them.

## Q3 — Sync *(recommended)*

`mcp/sync.py::sync_server(server_name)` (whitelisted, System-Manager-gated):
1. `client.list_tools(server)` → the server's tools.
2. Apply the server's include/exclude filter.
3. For each surviving tool, create/update a `Skill` named
   `mcp_<server>_<tool>` with `description`, `when_to_use` ("Provided by the
   <server> MCP server."), `parameters_schema = inputSchema`, `status=Active`,
   `mcp_server`, `mcp_tool_name`, `risk_level` defaulted (operator can raise it).
4. **Reconcile**: any existing `mcp_<server>_*` Skill no longer advertised is set
   `status=Disabled` (not deleted — preserves audit history + any profile links).
5. Stamp `last_synced` / `last_sync_status`.

Sync is **on-demand** (a "Sync Tools" button on the MCP Server form) plus a
daily cron backstop (`mcp/sync.sync_all_due` on `0 3 * * *`), failure-isolated
per server. It does NOT auto-grant tools to any agent — that stays the
operator's explicit opt-in (Q5).

## Q4 — Dispatch *(recommended)*

A generic in-process handler, not the Docker sandbox (MCP calls are outbound
HTTP, like the RandomPack client). Because MCP skill names are dynamic, the
`agent_runner/dispatcher` gains a tiny fallback: if no static handler is
registered for a skill AND the Skill row has `mcp_server` set, route to
`handlers_mcp.invoke`. That handler resolves the `MCP Server` + `mcp_tool_name`
from the Skill row, calls `client.call_tool`, and returns `{"result": ...}` (or
a structured error). Everything *before* dispatch — `matrix_check` (writes the
Permission Decision Log), the approval gate, the Execution Log — is the existing
path, unchanged. So an MCP call is governed and audited identically to a
first-party skill.

## Q5 — Governance & security *(per [[feedback_v01-skills-first-party-trust]])*

- **Opt-in per agent:** syncing creates Skills but grants nothing. An agent can
  call an MCP tool only when the operator adds it to `permitted_skills` — the
  same gate as every skill. `matrix_check` runs at dispatch.
- **Egress is real:** an MCP server reaches the network. v1 is single-tenant,
  first-party-trusted, and the operator chooses the server URL — but the handler
  still validates the URL scheme (https/http only, no `file://`) and the
  `auth_token` is encrypted + never logged. Error text from the server is
  scrubbed of obvious secret patterns before reaching the model (Hermes'
  `_sanitize_error` instinct).
- **Risk + approval:** operators can set a synced MCP Skill's `risk_level` and
  `requires_approval` — a high-risk MCP tool then routes through the existing
  Workflow approval gate before it runs.

## Q6 — UI *(recommended)*

`mcp_server.js`: a **Sync Tools** button (calls `sync_server`, shows the count +
status) and a hint listing the `mcp_<server>_*` Skills created. The synced
Skills then appear in the normal Agent Profile `permitted_skills` picker.

## Q7 — Implementation phasing (one PR)

1. `mcp/client.py` + `test_mcp_client.py` (the protocol core — JSON/SSE parse,
   handshake, list/call, error mapping).
2. `MCP Server` DocType; `Skill` gains `mcp_server` + `mcp_tool_name`.
3. `mcp/sync.py` + tests (create/update/reconcile Skills, filter, fail-loud).
4. `skills/handlers_mcp.py` + the dispatcher fallback + tests.
5. `mcp_server.js` Sync button; daily sync cron in hooks.
6. Rollout doc.

Verify: `bench migrate` clean; point at a real remote MCP server, Sync Tools →
`mcp_*` Skills appear; add one to a profile; an agent turn calls it and the
Permission Decision Log + Execution Log record it.

## What's explicitly NOT in Design 67

stdio transport (deferred — subprocess manager); SSE *streaming* tool results;
MCP sampling / resources / prompts; OAuth-authenticated MCP servers; a circuit
breaker / OSV scan; auto-granting tools to agents (governance opt-in stays).
