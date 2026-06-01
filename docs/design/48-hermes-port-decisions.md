# 48 — Hermes Port Decisions

> **Status:** Authoritative. The contract every PR in the Hermes-port sprint implements against.
> **Scope:** Single-tenant Friday deployment. NOT multi-tenant SaaS. Sized for one customer's Frappe site.
> **Sprint:** Hermes → Friday core-feature port, ~5 working days.
> **Audience:** Roo Code (implementer), the auditing reviewer, the product head, anyone reading the code in six months wondering "why did we do it this way?"
> **Related docs:** `41-porting-strategy-hermes-erpnext-raven.md` (what to port vs not), `47-gateway-design-decisions.md` (gateway contract).

---

## 1. Scope of this document

Friday today has the storage, permission, audit, and dispatch layers but is missing several Hermes capabilities that turn a tool-call wrapper into a real agent. This sprint ports the critical ones, Frappe-natively.

**Sprint features in priority order:**

| § | Feature | Status |
|---|---|---|
| 1 | Feature A — ReAct loop in `agent_runner.runner` | **LOCKED ↓** |
| 2 | Feature B1 — OpenAI provider adapter | **LOCKED → [doc 51 §4.B1](51-hermes-core-port-roadmap.md)** |
| 3 | Feature B2 — Anthropic provider adapter | **LOCKED → [doc 51 §4.B2](51-hermes-core-port-roadmap.md)** |
| 4 | Feature C — Conversation history compression | **LOCKED → [doc 51 §4.C](51-hermes-core-port-roadmap.md)** |
| 5 | Feature D — Per-tool idempotency wiring | **LOCKED → [doc 51 §4.D](51-hermes-core-port-roadmap.md)** |
| 6 | Feature F — LLM error classification | **LOCKED → [doc 51 §4.F](51-hermes-core-port-roadmap.md)** |

Each section answers Q-by-Q the calls the implementer would otherwise make alone (and get wrong — see Slice 5's 10 audit findings).

**Out of this sprint** (deferred to follow-ups, with reasoning in the relevant sections):

- Feature E — Parallel tool dispatch (lands after D)
- Feature G — Provider fallback chain (lands after B + F)
- Feature H — Tool auto-registration (Friday-vs-Hermes design call, deferred)
- Memory hierarchy (SOUL/MEMORY/USER analog) — architectural, deserves its own sprint
- Skill drafting / self-improvement loop — Phase 2 explicitly deferred per doc 22

---

## 2. Sprint precondition

**[PR #35](https://github.com/Friday-Labs-Inc/friday/pull/35) must be merged before Feature A starts.** It restores main to green by adding the missing `Skill Credential` DocType and fixing 5 other production bugs. Without it, the port is building on broken ground.

> **Status (2026-05-30): satisfied.** PR #35 is merged (`main @ 0f2cdd9`). Also note the
> workflow change recorded in [doc 51 §0](51-hermes-core-port-roadmap.md): the Roo Code
> hand-off is discontinued — this Claude now writes the production code directly. References
> to "Roo Code" elsewhere in this doc are historical.

---

# §1 — Feature A: ReAct loop

## 1.A Plain English

Today, when an LLM responds with a tool call, Friday dispatches it once and returns the tool result text to the user. That is **not** what an agent does. An agent **observes** the tool's result, **thinks** about what to do next, possibly **calls another tool**, and only ends when it has a final answer for the user.

This feature replaces single-cycle dispatch with a proper loop. Roughly:

```
while iterations < 15:
    response = llm.chat(messages)
    if response has tool_calls:
        for each tool_call (sequential, not parallel):
            result = dispatcher.dispatch(tool_call, ...)
            if result was a permission denial:  break the loop
            else: append result as a tool message and continue iterating
        continue                            # let LLM observe and decide next step
    else:
        return response.content              # plain text reply → we're done
return last_assistant_text + "\n\n[loop budget exhausted]"
```

This is what makes Friday "agentic": multi-step reasoning, with full audit and governance.

## 1.B Hermes comparison (per the project memory rule)

| Concern | Hermes does | Friday will do | Justification |
|---|---|---|---|
| Where the loop lives | `run_agent.py:AIAgent.run_conversation()` in-process | `agent_runner/runner.py:run_turn()`, called by gateway | **Same intent.** Frappe-fit. |
| Max iterations | `max_iterations: int = 90` | **15** | **Different.** Single-tenant v0.1 sized for cost safety, not for long-running daemon use. 15 covers genuine multi-step (3–4 chained tools with retries). |
| Tool result message format | `{role: "tool", tool_call_id: ..., content: ...}` (OpenAI shape) | **Same.** Provider adapter normalises Anthropic's `tool_result` block shape into this canonical form before append. | **Same as Hermes.** |
| Tool errors | Fed back to LLM as tool result; LLM decides next step | **Same — fed back.** | **Same as Hermes.** Lets LLM adapt. |
| Permission denials | N/A — Hermes has no permission engine | **Break the loop.** Return denial text to user. | **Friday-only.** Governance signal: if an agent tries something it can't do, that's an event the operator wants visible, not an event the LLM should silently route around. |
| Multi-tool-call iterations | Parallel via `concurrent.futures` | **Sequential, in order.** | **Different.** Parallel = Feature E (future sprint). Sequential is correct for v0.1 single-tenant. |
| Token-budget pressure handling | `trajectory_compressor.py` mid-loop | Handled by Feature C separately; loop just calls compression hook | **Same intent**, different placement. |
| Streaming token delivery | Yes | No (per doc 47 §6, deferred) | **Different.** No real-time surface needs it in v0.1. |
| Loop-exit on max iterations | Returns trajectory with `truncated=True` flag | Returns last assistant text with `[loop budget exhausted]` suffix | **Equivalent.** Same effect; Frappe-fit phrasing. |

## 1.C Decision log (locked)

### A.1 — Max iterations cap

**LOCKED: 15.**

Configurable in code as `MAX_REACT_ITERATIONS = 15`. Not a per-profile field for v0.1 (avoid premature config surface). If a profile genuinely needs more, lift to a field in a future PR.

### A.2 — Behavior at max-iterations

**LOCKED: return last assistant text with `[loop budget exhausted]` suffix.**

Specifically: if the loop hits iteration 15 and the last LLM response had tool_calls (meaning we never got a clean plain-text reply), return the most recent `assistant.content` (or "I'm unable to complete this in the time allotted." if it's empty) appended with `\n\n[loop budget exhausted after 15 iterations]`.

The Execution Log row for the **last attempted tool call** is left with `status="error"` and a `result.note = "max_iterations reached before reply"` field so admins can spot the cap-hit case in queries.

### A.3 — Tool errors during a loop iteration

**LOCKED: feed back to LLM as a tool result message, loop continues.**

When a tool dispatch returns `DispatchResult(success=False, content="...")` with a non-permission reason (skill execution error, unknown skill, malformed args, etc.):

- Append a tool message: `{role: "tool", tool_call_id: <call_id>, content: <result.content>}`.
- The content **must include the error message verbatim** so the LLM can read it and adapt.
- Continue to next iteration.

The dispatcher already writes an Execution Log row with `status="error"` for this case — the loop does NOT write an additional row.

### A.4 — Permission-denied tool call during a loop iteration

**LOCKED: BREAK the loop. Return denial text to the user.**

When `DispatchResult.success == False` AND the underlying reason is a permission denial (we know because `dispatcher.dispatch` distinguishes via `_get_latest_permission_decision`):

- Stop the loop immediately. Do **not** call the LLM again.
- Return reply text: `"I don't have permission to do that: <decision.reason>"`.
- The dispatcher already wrote an Execution Log row with `status="rejected"` and linked the Permission Decision Log — those exist; the loop does NOT write more rows.

**Why this is different from A.3:** a tool error is a "thing that went wrong" — the agent can retry differently. A permission denial is a "thing the operator said NO to" — letting the LLM route around it silently is a governance hole. The operator must see that the agent tried something it shouldn't have; surfacing it directly to the user (and writing the denial to the audit trail) is the right shape.

**Implementation hint:** the `DispatchResult` already carries enough information. The loop detects denial by: `result.success == False AND result.execution_log_name != None AND the linked log row's status == "rejected"`. A helper `_is_permission_denial(result: DispatchResult) -> bool` keeps the runner code clean.

### A.5 — Chat Message audit pattern

**LOCKED: one inbound + one outbound Chat Message row per *turn* (= per `run_turn` call), regardless of how many loop iterations happen.**

What gets written:
- **1 inbound row** — the user's message (already written by the surface adapter before the gateway fires).
- **N Execution Log rows** — one per `dispatcher.dispatch` call within the loop. Per Slice 6's contract.
- **N Permission Decision Log rows** — one per `matrix.check` call, also per Slice 6.
- **1 outbound row** — the final reply text the gateway writes after `run_turn` returns.

What is NOT written:
- No outbound rows for intermediate LLM responses with tool_calls. Those exist in Execution Log only.
- No "internal" / "system" Chat Message rows for tool results. The Execution Log row IS the audit row.

**Rationale:** Chat Message is the user-facing surface. The LLM's internal mid-loop reasoning belongs in the technical audit trail (Execution Log + Permission Decision Log), not the conversation history. The conversation history loaded by `prompt_builder.build()` should NOT include mid-loop assistant-with-tool-calls turns from prior conversations — only finished user/assistant pairs. This keeps the LLM's context clean across sessions.

### A.6 — Sub-decisions (locked by default; flag if you disagree)

- **Tool result message format:** OpenAI canonical — `{role: "tool", tool_call_id: <id>, content: <str>}`. Provider adapters normalise from Anthropic's `tool_result` block format into this shape before the runner sees it. Runner code is provider-agnostic.
- **Sequential tool dispatch only** — if an LLM response has 3 tool_calls, dispatcher is called 3 times in order, results appended in order. Parallel = Feature E (deferred).
- **Streaming: off** — per doc 47 §6.
- **Per-iteration Execution Log row:** every `dispatcher.dispatch` call writes one row (already the case). The loop does NOT write its own "iteration boundary" rows.
- **Token-budget awareness:** runner does NOT track tokens. Feature C handles compression. If the LLM call fails due to context overflow, that surfaces as a provider error → Feature F classifies it → for now (sprint v1) the loop catches and feeds back the error.
- **Loop-break sentinel for tests:** add module constant `MAX_REACT_ITERATIONS` so tests can patch it. No env-var override needed.
- **Telemetry:** runner emits one `frappe.logger("friday.runner").info(...)` line per iteration boundary with `{session_id, iteration, had_tool_calls}` so post-hoc grep on the Friday log shows the loop trajectory cheaply.

## 1.D Concrete contract for Roo Code

**File to modify:** `frappe/friday_core/agent_runner/runner.py`.

**New module constant:**
```python
MAX_REACT_ITERATIONS = 15
```

**Public function unchanged signature:**
```python
def run_turn(profile_name: str, session_id: str, inbound_content: str) -> str:
    ...
```

**New behavior (pseudocode):**
```python
def run_turn(profile_name, session_id, inbound_content):
    skill_definitions = load_for_profile(profile_name)
    prompt = build(profile_name, session_id, inbound_content, tools=skill_definitions)
    provider = get_provider_for_profile(profile_name)
    
    messages = prompt["messages"]
    last_assistant_text = ""
    
    for iteration in range(MAX_REACT_ITERATIONS):
        response = provider.chat(messages=messages, tools=prompt["tools"], model=prompt["model"])
        last_assistant_text = response.get("content", "") or last_assistant_text
        
        tool_calls = response.get("tool_calls")
        if not tool_calls:
            return response["content"]                              # ← plain reply → done
        
        # Append the assistant turn that requested tool calls
        messages.append({
            "role": "assistant",
            "content": response.get("content", ""),
            "tool_calls": tool_calls,
        })
        
        # Sequentially dispatch each tool call
        for tool_call in tool_calls:
            result = dispatch(tool_call=tool_call, agent_profile=profile_name, session_id=session_id,
                              tokens_used=response.get("usage", {}).get("total_tokens"))
            
            if _is_permission_denial(result):
                # A.4 — BREAK loop; surface denial to user
                return f"I don't have permission to do that: {_extract_denial_reason(result)}"
            
            # A.3 — Append tool result and continue
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.get("id", ""),
                "content": result.content,
            })
    
    # A.2 — Loop budget exhausted
    suffix = "\n\n[loop budget exhausted after 15 iterations]"
    return (last_assistant_text or "I'm unable to complete this in the time allotted.") + suffix


def _is_permission_denial(result: DispatchResult) -> bool:
    """Return True iff DispatchResult is for a permission-rejected dispatch."""
    if result.success or not result.execution_log_name:
        return False
    status = frappe.db.get_value("Execution Log", result.execution_log_name, "status")
    return status == "rejected"


def _extract_denial_reason(result: DispatchResult) -> str:
    """Best-effort: pull the denial reason out of the linked Execution Log row."""
    if not result.execution_log_name:
        return result.content
    row = frappe.db.get_value("Execution Log", result.execution_log_name, "result", as_dict=False)
    try:
        import json as _json
        return _json.loads(row).get("reason", result.content) if row else result.content
    except Exception:
        return result.content
```

## 1.E Tests Roo Code must include

`frappe/friday_core/tests/test_react_loop.py` — new file.

Required cases:

1. **`test_single_cycle_plain_text` — backwards compat:** LLM returns plain text on iteration 1 → runner returns that text. (Same as Slice 5 baseline; protects against regression.)
2. **`test_two_step_tool_chain`:** LLM returns tool_call on iteration 1; tool succeeds; LLM returns plain text on iteration 2 → runner returns iteration-2 text. **Assert messages list grew to 5 entries** (system, user, assistant-with-tool_calls, tool-result, assistant-final).
3. **`test_three_step_chain`:** LLM returns tool_call → tool_call → plain text. Assert two Execution Log rows written.
4. **`test_tool_error_feeds_back`:** LLM calls a tool that raises; iteration 2 LLM gets the error in a tool message and tries a different approach; final reply returned. Assert the failing dispatch wrote an Execution Log row with `status="error"`.
5. **`test_permission_denial_breaks_loop`:** LLM calls a tool the profile can't use; runner returns `"I don't have permission to do that: ..."` without further LLM calls. Assert only ONE Execution Log row written (the denied one with `status="rejected"`).
6. **`test_max_iterations_returns_with_suffix`:** Mock provider to always return a tool_call; assert runner returns last assistant content + `[loop budget exhausted after 15 iterations]`. Assert loop performed exactly 15 LLM calls.
7. **`test_iteration_boundary_log_lines`:** Assert `frappe.logger("friday.runner").info` was called at each iteration boundary with the expected fields.
8. **`test_sequential_multi_tool_call_in_one_iteration`:** LLM returns 3 tool_calls in iteration 1; dispatcher called 3 times in order; assert dispatch order matches tool_calls order; assert 3 Execution Log rows.
9. **Coverage target:** 90% line coverage on `runner.py`; 100% branch on `_is_permission_denial` and the loop's break vs continue branches.

Existing tests that must still pass: every test in `test_chat_flow`, `test_dispatcher`, `test_runner_tool_call`, `test_prompt_builder`, `test_llm_provider`.

## 1.F What this does NOT do (deferred, explicitly)

- **Parallel tool dispatch within one iteration** — Feature E. Sequential is the v0.1 contract.
- **Token-aware iteration budget** — Feature C handles via compression; A doesn't measure tokens.
- **Provider fallback on LLM call failure** — Feature G, future. For sprint v1, an LLM error propagates and the gateway writes system-error outbound (same as today).
- **Streaming** — out of scope per doc 47 §6.
- **Per-profile max iterations** — fixed at 15 in code. Add as a field later only if a customer asks.
- **Idempotency on tool re-invocations within the loop** — Feature D handles via Skill flags. For sprint v1, if the LLM re-calls the same tool with the same args within a loop, both calls execute. D fixes this.

## 1.G Hermes-equivalent files for Roo Code to read

If Roo Code wants to ground the implementation against the Hermes reference:

- `run_agent.py:run_conversation` — Hermes's full ReAct loop (very long; ~500 lines).
- `run_agent.py:_continue_loop_after_tool_result` — tool-result append shape.
- `chat_completion_helpers.py` — non-streaming completion code path Hermes uses; matches what Friday needs.

The Hermes implementation is much richer (parallel, streaming, compression, fallback, vision); for sprint A we want only the loop shape, not the orchestration around it.

---

# §2 — Feature B1: OpenAI provider adapter

**Status: LOCKED — see [doc 51 §4.B1](51-hermes-core-port-roadmap.md).** Build order: slice S6.

---

# §3 — Feature B2: Anthropic provider adapter

**Status: LOCKED — see [doc 51 §4.B2](51-hermes-core-port-roadmap.md).** Build order: slice S7.

---

# §4 — Feature C: Conversation history compression

**Status: LOCKED — see [doc 51 §4.C](51-hermes-core-port-roadmap.md).** Build order: slice S8. (Storage model is an open fork — doc 51 §5 Fork 3.)

---

# §5 — Feature D: Per-tool idempotency wiring

**Status: LOCKED — see [doc 51 §4.D](51-hermes-core-port-roadmap.md).** Build order: slice S5. Note: Hermes-core's actual mechanism is *within-turn dedup*, not a cross-turn idempotency key — doc 51 §4.D scopes it accordingly.

---

# §6 — Feature F: LLM error classification

**Status: LOCKED — see [doc 51 §4.F](51-hermes-core-port-roadmap.md).** Build order: slice S4 (precedes the provider adapters, which consume the classifier).

---

## Appendix — How each section becomes a PR

For every locked feature (`§N` becomes "FINAL"):

1. **I** (architect/reviewer in this chat) write §N as a complete contract above.
2. **You** (`@Fridaylabsinc`) hand the design doc to Roo Code with: *"Implement §N exactly. PR title `feat(friday-core): Feature X — <name>`. Pass all the tests required in §N.E."*
3. **Roo Code** implements + opens PR.
4. **I** audit the PR against §N. Findings posted as PR comments.
5. **Roo Code** addresses findings.
6. **You** merge.
7. **I** write the rollout doc `docs/rollouts/feature-X-<name>.md` in a follow-up small PR (or bundled with the merge).

Single chokepoint, like Slice 4's gateway. No drift.
