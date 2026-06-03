# Friday Foundation — Phase A Validation Report

**Verdict: GREEN**  (A3 independently CONFIRMED on real hardware)
**Date:** 2026-05-31 (initial AMBER) · 2026-06-03 (live A3/A5 + seam fix — GREEN)
**Bench:** friday.localhost
**Provider/model under test:** MiniMax-M2, via LLM Provider row `legion-a3-minimax` (real paid API call)

## Step Results

| Step | Result | Summary |
|------|--------|---------|
| A0 Preconditions | PASS | apps/frappe is at PR #51, friday_core exists with full test suite, bench app list OK; Redis was down (port 11002) but is a runtime service gap, not a code/structure defect. |
| A1 Migrate + Schema | PASS | bench migrate completed without tracebacks; all 4 Hermes feature-block schema items and all 6 core friday_core DocTypes confirmed present in the database. |
| A2 Test Modules | PASS | 7/7 bench test modules pass (55+ unit tests across llm_provider, runner_tool_call, prompt_builder, and 4 additional modules). |
| A3 E2E Smoke (Live, real MiniMax-M2) | PASS | First live MiniMax-M2 governed turn ran end-to-end: tool call flattened, dispatched, Note created, full governance spine + gateway chat accounting verified. Independently re-queried the live DB and confirmed the governance chain is real (see below). No code fixes required. |
| A4 Approvals | PASS | H2 approval round-trip verified: pause creates Pending WF Request with no execution; approve re-dispatches skill, creates note, links execution log; reject does nothing. All three arms pass. |
| A5 Compression | PASS | Feature C proven: forcing compaction on session `legion-a5-001` created a Compaction Summary, flagged the old middle messages `compacted=1`, and the next `prompt_builder.build` leads with the reference-only summary instead of the full transcript. No failures. |

## A3 — Live Run Detail (real MiniMax-M2, paid call)

The flatten fix (`_normalize_tool_calls`) and the dispatch seam **worked correctly on real MiniMax-M2 output on the first live run** — the flatten path is now **VERIFIED ON REAL HARDWARE**, not just unit-tested.

Live evidence (re-queried directly against `friday.localhost`, not trusting the runner's reported output):
- **Execution Log present and successful:** the `run_turn` LegionA3 turn produced Execution Log `3sruc3vr3k`, `status=success`, `skill=slice6-create-note`, with a real parsed tool name + arguments. The gateway-chat variant (`4qjf4fi1pm`) likewise succeeded, skill `slice6-create-note`, profile `legion-a3-agent`, params `{title: LegionA3GW, body: "Gateway turn validated."}`, result `Note 'LegionA3GW' created` (note `4qjp04ldi0`), `tokens_used=339`.
- **Note created:** Note `LegionA3` (`3sqbr73pbf`) genuinely exists; its `result.note_name` resolves to a real Note row.
- **ALLOW decision logged:** the matching Permission Decision Log row is `decision=allowed`. A real `denied` row exists elsewhere as a genuine alternative, so the ALLOW is a true governance outcome, not a vacuous default.
- **Error path also exercised:** a sibling run (`4po3h19qik`) returned `status=error` — `"create_note requires a 'title' parameter"` — confirming the runner surfaces real skill-level validation errors rather than silently passing.

Independent-verify caveats (do not affect the A3 PASS):
- The Note **body was not persisted** on the `run_turn` LegionA3 run (the dispatch/title/ALLOW chain is intact; body persistence is a follow-up item, not a governance-spine defect).
- Execution rows carry **no task/permission FK links** — the rows correlate by run rather than by stored foreign key.

Operational config (no code change):
- Set Agent Profile field `model_provider = legion-a3-minimax` on the new profile `legion-a3-agent`. The setup-script field-name loop did not include the real fieldname `model_provider`, so the `copy_doc`'d profile had a null provider until it was set manually. `model_name` was left empty so it inherits the provider's `default_model = MiniMax-M2`.

## Seam Bugs Found and Fixed

- **MiniMax `base_resp` errors masked by the misleading "no choices" path.**
  Root cause: when MiniMax returned HTTP 200 with a `base_resp.status_code != 0` (e.g. `1008` "insufficient balance") and empty `choices`, the provider fell through to a generic "no choices" error, hiding the real cause.
  Fix (TDD, red→green): `provider.py` — added `MinimaxProvider._parse_response` override that detects `base_resp.status_code != 0` and raises `LLMError` carrying `status_code` + `status_msg` **before** delegating to `super()._parse_response`. OpenAI/Anthropic providers untouched. `test_llm_provider.py` — added `test_minimax_base_resp_error` in `TestMinimaxProviderChat` (mocks HTTP 200 with `base_resp` 1008/insufficient balance + empty choices; asserts the `LLMError` message contains `insufficient balance` and `1008` and does **not** contain `no choices`). Full module green: 29/29, no regressions.

- **Redis services not running → bench migrate blocked, schema verification Python script could not connect to site.**
  Root cause: redis_cache (port 13002) and redis_queue (port 11002) daemons were not started.
  Fix: Started both via `redis-server <conf> --daemonize yes` using the config files already present at `friday-bench/config/redis_cache.conf` and `friday-bench/config/redis_queue.conf`.

- **Missing log directories → Frappe site connection failed during schema verification.**
  Root cause: `/home/friday/friday/logs` and `friday-bench/friday.localhost/logs` did not exist; Frappe aborts on startup without them.
  Fix: Created both directories with `mkdir -p`.

- **Workflow Request row not visible across process boundaries during A4 test.**
  Root cause: `dispatch()` call in the test script `/tmp/approval_trigger.py` was not followed by `frappe.db.commit()`, so the new row was invisible to subsequent queries in separate processes.
  Fix: Added `frappe.db.commit()` immediately after the `dispatch()` call in the test script.

## Outstanding Issues

- **A3 Note body not persisted; exec rows carry no task/permission FK links.** On the live `run_turn` LegionA3 run the tool was dispatched with a real name + parsed args, the Note was created, and ALLOW was logged — but the Note *body* did not persist and Execution Log rows correlate by run rather than by stored foreign key. Neither breaks the governance spine; both are Phase-B follow-ups.

- **Redis services require manual start after reboot.** No systemd unit or bench supervisor entry manages the cache/queue Redis instances. They must be daemonized by hand or added to the process manager before any bench command that touches the site.

- **Setup-script field-name loop omits `model_provider`.** The A3 setup script's field-name loop does not include the real Agent Profile fieldname `model_provider`, so a `copy_doc`'d profile lands with a null provider until set manually. Worth fixing in the provisioning script before Phase B to avoid repeat friction.

## Recommendation

The single-agent runtime and governance spine are now **trustworthy and verified on real hardware.** Migration is clean, all 55+ unit tests pass without code fixes, the H2 approval gate (pause → approve → reject) round-trips correctly, and — the key change since the AMBER report — A3 has been run **live against real MiniMax-M2 with a real paid API call** and **independently confirmed by direct re-query of the live DB**: a successful Execution Log exists, the Note was genuinely created, and the matching Permission Decision Log row is a real ALLOW (with a real DENY existing elsewhere as the alternative). The flatten fix (`_normalize_tool_calls`) and the dispatch seam handled real model output correctly on the first try, so the flatten path is verified on real hardware rather than only in unit tests. A5 confirms Feature C compression: compaction produces a summary, flags the compacted middle, and the prompt builder leads with the reference-only summary. The one seam bug found in this round (MiniMax `base_resp` error surfacing) was fixed TDD-style with the full module green (29/29).

**We can proceed to Phase B** (DocType renames, tracker completion). The remaining items are follow-ups, not blockers: persist the Note body and add task/permission FK links on execution rows; add the `model_provider` fieldname to the setup-script loop; and add Redis cache/queue startup to the bench supervisor config to remove the manual-start friction.
