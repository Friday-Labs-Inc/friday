# Proposal: Slice 6 — First Skill: `create_note`

## Status
- **Author:** `fridaylabs` (L0 Visitor)
- **Sponsor:** `iamfriday86`
- **Created At:** 2026-05-28
- **Status:** Draft

---

## 1. Problem & Context

Slice 5 gave the agent a voice — it can now receive a message and produce a real LLM reply. But the agent is still mute: it can analyze and respond but not **act**. Every real-world AI agent use case requires the agent to touch state: create a record, update a field, post a message.

**Slice 6 completes the minimal demo loop**: user asks → LLM analyzes → LLM emits a tool call → dispatcher validates permission → skill executes → result returned → user sees confirmation.

This is not yet a sandbox (Slice 7), not yet a task queue (Slice 8). This is one skill — `create_note` — running in-process, fully permission-gated, fully logged.

---

## 2. Proposed Changes & Architecture

### The Loop

```
User message → run_turn() → LLM → tool_call → dispatcher.check()
  → allowed? execute skill → write Execution Log → reply to user
  → denied?  write rejection → Execution Log → error reply to user
```

### 2.1 Dispatcher (`friday/friday_core/agent_runner/dispatcher.py`)

The dispatcher is the bridge between the LLM's tool call intent and actual skill execution.

```python
from dataclasses import dataclass

@dataclass
class DispatchResult:
    success: bool
    content: str          # human-readable result or error message
    execution_log_name: str | None
    tokens_used: int | None

def dispatch(
    skill_name: str,
    parameters: dict,
    agent_profile: str,
    session_id: str,
) -> DispatchResult:
    """Resolve, validate, and execute one tool call from the LLM.
    
    Returns a DispatchResult with the outcome. Writes exactly one
    Execution Log row (submitted on success, rejected on denial).
    Never raises — all errors are captured in the result.
    """
```

**Dispatch flow:**
1. Resolve the `Skill` DocType row by name.
2. Call `permissions.matrix.check(agent_profile, skill_name)` — writes a `Permission Decision Log` row.
3. If denied → write `Execution Log` with `status='rejected'`, return `DispatchResult(success=False, ...)`.
4. If allowed → execute the skill via `_execute_skill()`.
5. Write `Execution Log` with `status='success'`, return result.

**Error handling:** Any exception during execution is caught, written to `Execution Log` as `status='error'`, and returned as a `DispatchResult` with the error message. The gateway never crashes.

### 2.2 Skill Executor (`_execute_skill()`)

In-process execution. Acceptable for Slice 6 because:
- Only one skill (`create_note`) exists.
- The skill is `risk_level=low` and operates on a single DocType.
- Slice 7 moves all execution into Docker with network isolation and resource caps.

```python
def _execute_skill(skill_name: str, parameters: dict) -> dict:
    """Execute the named skill with parameters.
    
    Maps skill_name → handler function. Each handler is a small,
    auditable function that calls Frappe's ORM.
    
    Handler for `create_note`:
      - Creates a Note DocType row with title + content.
      - Returns {"name": note.name, "title": note.title}
    """
```

**Handler registry pattern** — future skills (Slice 8+) add entries here without changing the dispatcher:

```python
_SKILL_HANDLERS = {
    "create_note": _handle_create_note,
    # "update_note": _handle_update_note,  # future
    # "send_message": _handle_send_message, # future
}
```

### 2.3 Runner Update (`friday/friday_core/agent_runner/runner.py`)

The `run_turn()` function is updated to:

1. Call the LLM with tool definitions (already done in Slice 5).
2. **Detect** whether the LLM response contains a tool call.
3. **Parse** the tool call: skill name + parameters from the LLM's JSON arguments.
4. **Dispatch** to the dispatcher.
5. **Loop** or **respond**: if the skill result should be fed back to the LLM (for multi-step reasoning), re-call the LLM with the result as a new user message. For Slice 6, a single dispatch → reply is sufficient.

**Tool call detection:**
Minimax returns tool calls in `response["choices"][0]["message"]["tool_calls"]`. Each entry has `{"name": "...", "arguments": "{...}"}`. The `arguments` field is a JSON string to be parsed.

### 2.4 Execution Log DocType (`friday/friday_core/doctype/execution_log/`)

Already exists from Slice 1. Slice 6 populates it correctly:

| Field | Value |
|-------|-------|
| `status` | `success` / `rejected` / `error` |
| `skill` | skill name |
| `agent_profile` | profile name |
| `session_id` | session UUID |
| `parameters` | JSON — the arguments passed |
| `result` | JSON — what happened (created note name, or error string) |
| `duration_ms` | elapsed time |
| `tokens_used` | from LLM response usage |
| `permission_decision` | Link → Permission Decision Log (on rejection) |

### 2.5 Test Skill `create_note`

A pre-existing `Skill` DocType row that the test profile uses:

| Field | Value |
|-------|-------|
| `skill_name` | `create_note` |
| `description` | `Create a note with a title and content` |
| `parameters_schema` | `{"title": {"type": "string"}, "content": {"type": "string"}}` |
| `required_doctypes` | `[Note(create)]` |
| `risk_level` | `low` |
| `status` | `Active` |

---

## 3. Files to Create or Modify

| File | Action | Notes |
|------|--------|-------|
| `friday/friday_core/agent_runner/dispatcher.py` | Create | `dispatch()` + `_execute_skill()` + `_SKILL_HANDLERS` |
| `friday/friday_core/agent_runner/runner.py` | Modify | Detect tool calls; call dispatcher; handle result |
| `friday/friday_core/doctype/execution_log/execution_log.json` | Inspect | Verify fields for Slice 6 population needs |
| `friday/friday_core/tests/test_dispatcher.py` | Create | Allowed flow, denied flow, error flow |
| `friday/friday_core/tests/test_runner_tool_call.py` | Create | Runner parses tool calls, dispatches, returns result |
| `docs/contributing/proposals/slice-6-first-skill.md` | Create | This proposal |

---

## 4. Testing & Coverage Plan

### Test Cases

- `[ ]` **Happy path:** LLM returns tool call `create_note` → dispatcher allows → Note row created → Execution Log submitted → user reply contains note title.
- `[ ]` **Permission denied:** LLM returns tool call → permission matrix says no → Execution Log submitted with `status='rejected'` → user reply contains denial message.
- `[ ]` **Execution error:** Skill handler raises → `Execution Log` with `status='error'` and error message → user reply contains error.
- `[ ]` **Invalid tool name:** LLM returns unknown skill → dispatcher returns error → no DB side effects.
- `[ ]` **Malformed tool arguments:** LLM returns tool call with unparseable JSON → dispatcher catches → `Execution Log` with `status='error'` → user reply contains error.
- `[ ]` **No tool call:** LLM returns plain text reply (no tool_calls) → runner returns content directly (existing behavior).
- `[ ]` **Regression:** existing Slice 5 tests (45/45) still green.

### Coverage Targets

- `dispatcher.py`: 90% line coverage; 100% branch on allowed/denied/error paths.
- `runner.py` tool-call branch: 85% coverage.

---

## 5. Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| In-process skill execution is unsafe for high-risk skills | Medium | Slice 6 uses only `risk_level=low` skills. Risk classification is on the Skill DocType — higher risk skills are blocked by the permission matrix before the dispatcher runs. |
| LLM tool-call format varies across providers | Low | Tool call format is provider-specific. Minimax returns `tool_calls` in the message. The runner uses a `_parse_tool_calls()` helper that can be updated per provider without changing the dispatcher. OpenAI-compatible providers likely share the same format. |
| Malformed tool arguments crash the gateway | Medium | `dispatch()` wraps all skill execution in try/except. Never propagates exceptions to the gateway. All errors captured in `Execution Log`. |
| No loop detection (LLM calls same tool repeatedly) | Low | Slice 6 is single-dispatch (one tool call → reply). Loop detection is deferred to Slice 8 when multi-step task dispatch lands. |

---

## 6. Exit Gate

Per [`11-agent-validation-checklist.md`](docs/design/11-agent-validation-checklist.md) §Slice 6:

- `friday chat --profile note_taker` → "create a note titled X about Y" → Note row created, user sees confirmation.
- Profile without Note-create permission → clean denial message, no Note created.
- `Execution Log` has exactly one row per skill attempt (success/rejected/error).
- All 45 Slice 5 regression tests still pass.
- `bench --site friday.localhost migrate` runs clean.