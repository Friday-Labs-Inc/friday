# Friday Slices — Visual Flowcharts
> **Slices 1–6 explained in plain terms, with data-flow diagrams**
> **Audience:** Anyone — engineer, product owner, or a non-technical person wondering what this codebase actually does

---

## How to Read These Diagrams

Each diagram shows:
- **Boxes** = data records (rows in Postgres)
- **Arrows** = code function calls or data reads
- **Bold labels** = the key function/decision point in that step
- **`DB`** suffix = data is stored or retrieved

---

## Slice 1 — Foundations & DocType Skeletons

### "In one sentence"
**Friday lays the groundwork: creates the filing cabinets (database tables) where all future features store their data.**

### Flowchart

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  ADMIN / OPERATOR          FRAPPE FRAMEWORK          DATABASE (Postgres)  │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│   Slice 1: Create 8 main DocTypes                                             │
│   + 3 child tables                                                          │
│                                                                             │
│   ┌──────────────┐    bench migrate    ┌─────────────────────────────────┐  │
│   │ Human Dev   │ ─────────────────►  │ Frappe reads JSON schemas       │  │
│   │ (writes the │                     │ and creates DB tables          │  │
│   │ .json files)│                     └─────────────────────────────────┘  │
│   └──────────────┘                                    │                     │
│                                                     ▼                     │
│                               ┌─────────────────────────────────────────┐  │
│                               │  Created tables:                        │  │
│                               │  • tabAgent Profile                     │  │
│                               │  • tabSkill                            │  │
│                               │  • tabAgent Project                    │  │
│                               │  • tabAgent Task                       │  │
│                               │  • tabChat Message                     │  │
│                               │  • tabChat Platform                    │  │
│                               │  • tabExecution Log (submittable)      │  │
│                               │  • tabPermission Decision Log (sub.)   │  │
│                               └─────────────────────────────────────────┘  │
│                                                     │                     │
│                                                     ▼                     │
│                               ┌─────────────────────────────────────────┐  │
│                               │  Admin opens Frappe Desk → creates      │  │
│                               │  one row of each type ✓                │  │
│                               └─────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Plain English Explanation

**Think of it like this:** Slice 1 is like building an office building's skeleton — the walls, floors, and rooms exist but nobody works there yet. The rooms are empty filing cabinets (database tables) sitting in a dark warehouse (Postgres).

Each "DocType" is a type of form. For example:
- **Agent Profile** = a form to describe one AI agent (its name, what it can do, which LLM it uses)
- **Skill** = a form to describe one tool the agent can use (like "create a Note")
- **Chat Message** = a form to record each message in a conversation
- **Permission Decision Log** = an immutable receipt book — once written, never erased

Nothing *works* yet. Nothing *checks* anything. The system just knows the forms exist and can save them to the database.

### Key Files

| File | What it is |
|------|-----------|
| `frappe/friday_core/doctype/agent_profile/agent_profile.json` | The "Agent Profile" form definition |
| `frappe/friday_core/doctype/skill/skill.json` | The "Skill" form definition |
| `frappe/friday_core/doctype/execution_log/execution_log.json` | The "Execution Log" form definition |
| `frappe/friday_core/doctype/permission_decision_log/permission_decision_log.json` | The audit receipt form |
| `frappe/friday_core/tests/test_doctypes_exist.py` | Test that all tables exist |

### Real-world analogy

It's like receiving a box of 8 different printed forms in the mail. They sit on a shelf. You can fill them in and put them in a filing cabinet. But nobody's going to read them, check them, or act on them. That starts in Slice 2.

---

## Slice 2 — Permission Engine (The Gatekeeper)

### "In one sentence"
**Before any agent can run a tool, a function CHECKS if it's allowed — and writes a permanent YES/NO receipt.**

### Flowchart

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  SLICE 2: THE GATEKEEPER                                                    │
│                                                                             │
│  ANY POINT IN THE CODE                                                      │
│  asks: "Can this agent run this skill?"                                     │
│                                    │                                       │
│                                    ▼                                       │
│                    ┌─────────────────────────────────┐                     │
│                    │  permissions.matrix.check(      │                     │
│                    │    agent_profile, skill_name     │                     │
│                    │  )                               │                     │
│                    └──────────────┬──────────────────┘                     │
│                                   │                                         │
│                    ┌──────────────▼──────────────┐                          │
│                    │   3 questions in sequence:  │                          │
│                    │                            │                          │
│                    │  1. Is agent Active?       │                          │
│                    │     (not Suspended?)       │                          │
│                    │                            │                          │
│                    │  2. Is skill Active?       │                          │
│                    │     (not Draft/Retired?)   │                          │
│                    │                            │                          │
│                    │  3. Does agent's role       │                          │
│                    │     cover the skill's      │                          │
│                    │     required DocType ops?  │                          │
│                    └──────────────┬──────────────┘                          │
│                                   │                                         │
│                         ┌─────────▼─────────┐                              │
│                         │                  │                              │
│                    ┌────▼────┐        ┌─────▼─────┐                         │
│                    │ ALLOWED │        │  DENIED   │                         │
│                    └────┬────┘        └─────┬─────┘                         │
│                         │                  │                                │
│                         ▼                  ▼                                │
│          ┌──────────────────────┐  ┌──────────────────┐                    │
│          │ Write Permission     │  │ Write Permission  │                    │
│          │ Decision Log row    │  │ Decision Log row  │                    │
│          │ decision='allowed' │  │ decision='denied'│                    │
│          │ + matrix snapshot  │  │ + reason why     │                    │
│          └──────────────────────┘  └──────────────────┘                    │
│                                   │                                         │
│                                   ▼                                         │
│                    ┌─────────────────────────────────┐                     │
│                    │  RETURN: Decision(allowed,       │                     │
│                    │  reason)                         │                     │
│                    └─────────────────────────────────┘                     │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Plain English Explanation

**Think of it like a security guard at a building entrance.** Before anyone can use the printer, the scanner, or the email system, the guard checks three things:

1. Is your employee badge active today? (Not suspended?)
2. Is the tool/equipment you're trying to use actually available for use? (Not under maintenance or retired?)
3. Does your job role cover that specific action? (One department can't use another department's system, even if their badges are active.)

If all three are "yes" → the guard waves you through and writes "allowed" in the logbook.
If any is "no" → the guard stops you and writes "denied: [reason]" in the logbook.

The logbook is a receipt book — once written, it can never be altered. A regulator or manager can look back at any decision weeks later and understand exactly why it was made.

### Key Code

```python
from frappe.friday_core.permissions.matrix import check

decision = check(agent_profile="My Agent", skill_name="create_note")
# decision.allowed  → True or False
# decision.reason   → "Allowed" or "Denied: no matching role for 'Note_create'"
```

### Key Files

| File | What it is |
|------|-----------|
| `frappe/friday_core/permissions/matrix.py` | The gatekeeper logic — checks all 3 questions |
| `frappe/friday_core/permissions/decisions.py` | Writes the permanent audit receipt |
| `frappe/friday_core/permissions/cache.py` | Redis cache so the same check is fast (<1ms) |
| `frappe/friday_core/tests/test_permissions.py` | 10 tests for every scenario |

### Real-world analogy

It's like a factory floor access system. Before a worker can operate lathe A, someone checks: is your shift badge active? Is lathe A switched on and not under repair? Does your training certification cover lathe A? All three yes = you get access. The system logs your attempt either way.

---

## Slice 3 — Skill Loader (The Menu)

### "In one sentence"
**The agent can now see WHICH tools it has access to, before it tries to use any of them.**

### Flowchart

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  SLICE 3: THE MENU — "Which tools can this agent see?"                      │
│                                                                             │
│  ANY CODE asks:                                                             │
│  "What tools does this agent have?"                                         │
│                        │                                                   │
│                        ▼                                                   │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  skills.loader.load_for_profile(profile_name)                       │   │
│  │                                                                      │   │
│  │  ┌──────────────────────────────────────────────────────────────┐   │   │
│  │  │  1. Load all Skills from DB that are linked to this agent   │   │   │
│  │  │     via the Agent Profile's "Permitted Skills" child table  │   │   │
│  │  └──────────────────────────────────────────────────────────────┘   │   │
│  │                              │                                        │   │
│  │                              ▼                                        │   │
│  │  ┌──────────────────────────────────────────────────────────────┐   │   │
│  │  │  2. Filter Step A: Keep only skills with status = 'Active'    │   │   │
│  │  │     (Drop Draft, Experimental, Retired, Archived)              │   │   │
│  │  └──────────────────────────────────────────────────────────────┘   │   │
│  │                              │                                        │   │
│  │                              ▼                                        │   │
│  │  ┌──────────────────────────────────────────────────────────────┐   │   │
│  │  │  3. Filter Step B: Keep only skills the permission engine     │   │   │
│  │  │     says this agent is ALLOWED to use                        │   │   │
│  │  │     (call matrix.check() for each skill)                     │   │   │
│  │  └──────────────────────────────────────────────────────────────┘   │   │
│  │                              │                                        │   │
│  │                              ▼                                        │   │
│  │  ┌──────────────────────────────────────────────────────────────┐   │   │
│  │  │  4. Convert each remaining skill into a "tool definition"      │   │   │
│  │  │     (OpenAI/Anthropic format: name, description, parameters)   │   │   │
│  │  └──────────────────────────────────────────────────────────────┘   │   │
│  │                              │                                        │   │
│  │                              ▼                                        │   │
│  │  ┌──────────────────────────────────────────────────────────────┐   │   │
│  │  │  5. Cache the result in Redis at friday:skills:<profile>      │   │   │
│  │  └──────────────────────────────────────────────────────────────┘   │   │
│  │                              │                                        │   │
│  │                              ▼                                        │   │
│  │  ┌──────────────────────────────────────────────────────────────┐   │   │
│  │  │  RETURN: list[SkillDefinition]                               │   │   │
│  │  │       → each has: name, description, parameters_schema        │   │   │
│  │  │       → ready to hand directly to an LLM as "tools" parameter│   │   │
│  │  └──────────────────────────────────────────────────────────────┘   │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Plain English Explanation

**Think of it like this:** Slice 2 built a security guard who checks people at the door. Slice 3 gives every agent their own *personalized menu* of what they're allowed to even ASK for.

Before, an agent could see every tool that existed — even ones they couldn't use. Now, the menu only shows them tools that:
1. Are published and safe to use (Active status)
2. The gatekeeper would say YES to for them specifically

The menu is cached for 5 minutes — so if you're checking "what can this agent do?" 100 times, you only hit the database once. The other 99 times it's a fast Redis lookup.

Importantly: **looking at the menu doesn't write any logs**. The audit log only gets written when someone actually TRIES to use a tool (Slice 2's gatekeeper). Reading the menu is silent.

### Why Two Layers?

```
BEFORE you ask (Menu — Slice 3):  "Here's what you can see"
WHEN  you act  (Gatekeeper — Slice 2): "Here's what you're allowed to do"
```

Two reasons for this:
1. **Speed** — looking up the menu once and reusing it is far cheaper than asking the gatekeeper 50 times per conversation
2. **Safety** — an agent can't even ASK to use a forbidden tool if it can't see it. This is "defense in depth" — two layers of "no" instead of one.

### Key Files

| File | What it is |
|------|-----------|
| `frappe/friday_core/skills/loader.py` | Builds the filtered menu |
| `frappe/friday_core/tests/test_skill_loader.py` | 8 tests |

### Real-world analogy

At a hotel, there are three master keys for three levels of rooms. Housekeeping gets a key card that opens level 1 rooms only. The front desk gets a key that opens all rooms. If the housekeeper's card were to somehow be used on the executive floor, the door would still say "denied."

---

## Slice 4 — Gateway & Chat Flow (The Hearing/Ear)

### "In one sentence"
**Friday now has ears — when you type in the CLI, it gets recorded as a message, and the system figures out how to reply.**

### Flowchart

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  SLICE 4: THE CHAT LOOP (CLI → Gateway → Reply)                              │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐      │
│  │ USER at terminal                                                     │      │
│  │                                                                      │      │
│  │  $ bench --site friday.localhost friday chat --profile "My Agent"  │      │
│  │  Friday chat — profile 'My Agent', session abc-...                │      │
│  │  > make me a note about the meeting                                 │      │
│  └─────────────────────────────────────────────────────────────────────┘      │
│                                    │                                          │
│                                    ▼  (writes DB row)                        │
│  ┌─────────────────────────────────────────────────────────────────────┐      │
│  │ Chat Message (direction=inbound, content="make me a note...")       │      │
│  │ ↳ session_id = abc-...                                               │      │
│  │ ↳ platform = "cli"                                                  │      │
│  │ ↳ sender_id = "user"                                               │      │
│  └─────────────────────────────────────────────────────────────────────┘      │
│                                    │                                          │
│                         Frappe after_insert hook fires                        │
│                                    │                                          │
│                                    ▼                                          │
│  ┌─────────────────────────────────────────────────────────────────────┐      │
│  │  gateway.service.handle_inbound()  ←──── the unified chokepoint     │      │
│  │                                                                      │      │
│  │  ┌────────────────────────────────────────────────────────────┐    │      │
│  │  │  1. Resolve which Agent Profile owns this session          │    │      │
│  │  │     (from platform's default OR from explicit --profile)   │    │      │
│  │  └────────────────────────────────────────────────────────────┘    │      │
│  │                              │                                        │      │
│  │                              ▼                                        │      │
│  │  ┌────────────────────────────────────────────────────────────┐    │      │
│  │  │  2. Acquire Redis SESSION LOCK for this session_id        │    │      │
│  │  │     (prevents two messages in same session racing)        │    │      │
│  │  └────────────────────────────────────────────────────────────┘    │      │
│  │                              │                                        │      │
│  │                              ▼                                        │      │
│  │  ┌────────────────────────────────────────────────────────────┐    │      │
│  │  │  3. Call agent_runner.run_turn(profile, session, content)  │    │      │
│  │  │     (in Slice 4 this is just an ECHO — it returns your     │    │      │
│  │  │     message back prefixed with "echo:")                   │    │      │
│  │  └────────────────────────────────────────────────────────────┘    │      │
│  │                              │                                        │      │
│  │                              ▼                                        │      │
│  │  ┌────────────────────────────────────────────────────────────┐    │      │
│  │  │  4. Write outbound Chat Message row                        │    │      │
│  │  │     (direction=outbound, content=<reply from agent)         │    │      │
│  │  │     session_id same as inbound                             │    │      │
│  │  └────────────────────────────────────────────────────────────┘    │      │
│  │                              │                                        │      │
│  │                              ▼                                        │      │
│  │  ┌────────────────────────────────────────────────────────────┐    │      │
│  │  │  5. Release Redis session lock                            │    │      │
│  │  └────────────────────────────────────────────────────────────┘    │      │
│  └─────────────────────────────────────────────────────────────────────┘      │
│                                    │                                          │
│                        (doc_events fires again, sees outbound, SKIPS)        │
│                                    │                                          │
│                                    ▼                                          │
│  ┌─────────────────────────────────────────────────────────────────────┐      │
│  │  REPL reads outbound row, prints:                                    │      │
│  │  echo: make me a note about the meeting                              │      │
│  └─────────────────────────────────────────────────────────────────────┘      │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Plain English Explanation

**Think of it like this:** Slice 4 makes Friday *hear* and *respond* through the CLI. It's the first working ear-to-mouth loop.

When you type into the CLI:
1. Your message gets written to a `Chat Message` inbox row in Postgres
2. Frappe's `after_insert` hook fires automatically (no polling, no separate process)
3. The **gateway** function picks up the new message — same gateway that任何 future surface (Telegram, Slack, Raven) will use
4. The gateway gets the agent to build a reply
5. The reply gets written to a `Chat Message` outbox row
6. The CLI prints it

All of this is the same code, regardless of whether the message came from CLI today or Telegram in Slice 7. That's the "unified gateway."

### Important Design: The Gateway Has a Loop Guard

The gateway fires on EVERY `Chat Message` insert — including the outbound row it just wrote. To stop it from replying to its own reply ad infinitum, it checks `direction`:
- `direction=inbound` → process normally
- `direction=outbound` → skip (return immediately)

### Key Files

| File | What it is |
|------|-----------|
| `frappe/friday_core/gateway/service.py` | The unified gateway function |
| `frappe/friday_core/cli/chat.py` | The REPL (reads/writes Chat Message rows) |
| `frappe/friday_core/agent_runner/runner.py` | `run_turn` — in Slice 4 this is an echo stub |
| `frappe/friday_core/tests/test_chat_flow.py` | 15 tests |

### Real-world analogy

It's like a telephone exchange operator. When you pick up and speak, your voice gets converted to a written note (inbound row). The exchange operator reads the note, handles it, writes a reply note (outbound row), and slides it back to you. The key is: every future communication channel — whether phone, email, or radio — goes through the same exchange operator and the same note-in/note-out process.

---

## Slice 5 — LLM Integration (The Brain)

### "In one sentence"
**The echo stub is replaced with a REAL LJM call. When you type a question, Friday THINKSP answers with Minimax M2.**

### Flowchart

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  SLICE 5: REPLACE THE ECHO WITH MINIMAX M2                                  │
│                                                                             │
│  (Everything from Slice 4 stays the same — only the body of run_turn()      │
│   is replaced)                                                              │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐  │
│  │  agent_runner.run_turn(profile, session, content)                     │  │
│  │                                                                      │  │
│  │  ┌───────────────────────────────────────────────────────────────┐  │  │
│  │  │  STEP 1: Load tool menu (from Slice 3)                        │  │  │
│  │  │  skills = load_for_profile(profile)                             │  │  │
│  │  │  → returns list of SkillDefinition objects                      │  │  │
│  │  │  → converted to OpenAI-style "tools" format for the LLM        │  │  │
│  │  └───────────────────────────────────────────────────────────────┘  │  │
│  │                              │                                        │  │
│  │                              ▼                                        │  │
│  │  ┌───────────────────────────────────────────────────────────────┐  │  │
│  │  │  STEP 2: Build the LLM prompt                                 │  │  │
│  │  │  prompt_builder.build(profile, session, current_msg, tools)    │  │  │
│  │  │    ↳ Reads Agent Profile's system_prompt field               │  │  │
│  │  │    ↳ Reads last 10 Chat Message rows for this session         │  │  │
│  │  │    ↳ Wraps everything into {messages, tools, model}          │  │  │
│  │  └───────────────────────────────────────────────────────────────┘  │  │
│  │                              │                                        │  │
│  │                              ▼                                        │  │
│  │  ┌───────────────────────────────────────────────────────────────┐  │  │
│  │  │  STEP 3: Resolve the LLM provider (per profile or default)   │  │  │
│  │  │  llm.get_provider_for_profile(profile)                        │  │  │
│  │  │    ↳ Reads Agent Profile's model_provider link              │  │  │
│  │  │    ↳ Looks up the LLM Provider DocType row                    │  │  │
│  │  │    ↳ Reads api_key via Frappe Password decryption            │  │  │
│  │  │    → returns a MinimaxProvider() instance                    │  │  │
│  │  └───────────────────────────────────────────────────────────────┘  │  │
│  │                              │                                        │  │
│  │                              ▼                                        │  │
│  │  ┌─────────────────────────────────────────────────────────    ┐  │  │
│  │  │  STEP 4: Make the API call                             ┐  │  │  │
│  │  │  provider.chat(messages, tools, model)                 │  │  │  │
│  │  │    ↳ POST https://api.minimax.io/v1/text/chat...      │  │  │  │
│  │  │    ↳ Bearer token = api_key (encrypted, never in logs) │  │  │  │
│  │  │    ↳ Retries on 429/5xx: 1s → 2s → 4s backoff         │  │  │  │
│  │  │    ↳ Redacts error details to avoid leaking secrets    │  │  │  │
│  │  │    → returns LLMResponse {content, finish_reason, usage}│  │  │  │
│  │  └──────────────────────────────────────────────────────────────┘  │  │
│  │                              │                                        │  │
│  │                              ▼                                        │  │
│  │  ┌───────────────────────────────────────────────────────────────┐  │  │
│  │  │  STEP 5: Return the reply text to the gateway                 │  │  │
│  │  │  → gateway writes outbound Chat Message row with this text  │  │  │
│  │  └───────────────────────────────────────────────────────────────┘  │  │
│  └─────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Plain English Explanation

**Slice 5 is the moment Friday becomes SMART.** Before, the CLI just echoed back your message. Now it calls a real AI brain (Minimax M2) and returns the AI's actual reply.

The key seam was exactly one function: `run_turn()`. We replaced the echo stub inside it with a real LLM call. Everything else — the CLI, the gateway, session locking, audit rows — is unchanged from Slice 4.

### Where does the system prompt come from?

The `Agent Profile.system_prompt` field. Operators write custom instructions like "You are a helpful research assistant. You specialize in summarizing documents." That text goes at the top of the LLM's context window.

### Does the LLM see the conversation history?

Yes — the last 10 back-and-forth turns are loaded from `Chat Message` rows and appended to the prompt. The older history is still in the DB for audit purposes, but the LLM only "sees" the last 10 turns to keep the context window manageable.

### Key Files

| File | What it is |
|------|-----------|
| `frappe/friday_core/llm/provider.py` | Minimax HTTP client with retry and error redaction |
| `frappe/friday_core/llm/prompt_builder.py` | Builds the {messages, tools, model} payload |
| `frappe/friday_core/agent_runner/runner.py` | Calls prompt_builder → provider → returns text |
| `frappe/friday_core/doctype/llm_provider/llm_provider.json` | The form where operators register API keys |
| `frappe/friday_core/doctype/agent_settings/agent_settings.json` | Holds the default provider link |
| `frappe/friday_core/tests/test_llm_provider.py` | 25 tests |
| `frappe/friday_core/tests/test_prompt_builder.py` | 20 tests |

### Real-world analogy

It's like swapping the answering machine's generic greeting with a real person who can actually understand what you said and respond intelligently. The phone line, the voicemail storage, and the recording mechanism all stay the same.

---

## Slice 6 — First Skill: `create_note` (The Hands)

### "In one sentence"
**Friday can now DO things, not just talk. When the AI decides to use a tool, it actually runs — with permission checks and a written receipt.**

### Flowchart

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  SLICE 6: THE COMPLETE AGENTIC LOOP                                         │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  USER: "make a note titled 'Meeting' about the board meeting"      │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                    │                                        │
│                                    ▼ (as before)                            │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │   Prompt sent to LLM (Minimax M2) — same as Slice 5                 │   │
│  │   BUT now includes tool definitions in the prompt:                   │   │
│  │                                                                      │   │
│  │   tools = [                                                           │   │
│  │     {                                                                 │   │
│  │       "name": "create_note",                                        │   │
│  │       "description": "Create a Note document with title and body", │   │
│  │       "parameters": {                                               │   │
│  │         "type": "object",                                          │   │
│  │         "properties": {"title": {...}, "content": {...}},          │   │
│  │         "required": ["title"]                                       │   │
│  │       }                                                              │   │
│  │     }                                                                │   │
│  │   ]                                                                  │   │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                    │                                        │
│                                    ▼ (LLM picks a tool)                    │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │   LLM RESPONSE — now includes a "tool_call":                      │   │
│  │   {                                                               │   │
│  │     "content": "",            ← empty text when tool is called    │   │
│  │     "tool_calls": [                                                │   │
│  │       {                                                           │   │
│  │         "name": "create_note",                                   │   │
│  │         "id": "call_abc123",                                     │   │
│  │         "arguments": "{\"title\":\"Meeting\",                       │   │
│  │                        \"content\":\"board meeting notes\"}"        │   │
│  │       }                                                           │   │
│  │     ]                                                             │   │
│  │   }                                                               │   │
│  └───────────────────────────┬─────────────────────────────────────┘   │
│                              │                                             │
│           ┌──────────────────▼──────────────────┐                         │
│           │  YES: tool_calls present?           │                         │
│           │  → route to dispatcher             │                         │
│           │  → DON'T return raw LLM text       │                         │
│           └───────────────────────────────────┘                         │
│                              │                                             │
│                              ▼                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐  │
│  │  dispatcher.dispatch(tool_call, profile, session, tokens)             │  │
│  │                                                                        │  │
│  │  ┌───────────────────────────────────────────────────────────────┐    │  │
│  │  │  STEP 1: Parse the tool call                                  │    │  │
│  │  │  name = "create_note"                                         │    │  │
│  │  │  args = JSON.parse("{\"title\":\"Meeting\",...}")             │    │  │
│  │  │  id = "call_abc123"                                          │    │  │
│  │  └───────────────────────────────────────────────────────────────┘    │  │
│  │                              │                                        │  │
│  │                              ▼                                        │  │
│  │  ┌───────────────────────────────────────────────────────────────┐    │  │
│  │  │  STEP 2: Ask the permission engine — ALLOWED?                │    │  │
│  │  │  matrix.check(profile, "create_note")                         │    │  │
│  │  │  → Decision(allowed=True/False, reason)                       │    │  │
│  │  └───────────────────────────────────────────────────────────────┘    │  │
│  │                              │                                        │  │
│  │              ┌──────────────┴──────────────┐                        │  │
│  │         ┌────▼────┐                    ┌───▼───┐                   │  │
│  │         │ ALLOWED │                    │ DENIED │                   │  │
│  │         └────┬────┘                    └───┬───┘                   │  │
│  │              │                            │                          │  │
│  │              ▼                            ▼                          │  │
│  │  ┌──────────────────────┐  ┌──────────────────────┐               │  │
│  │  │  STEP 3: Find the   │  │  STEP 3: Write log   │               │  │
│  │  │  registered handler│  │  status=REJECTED    │               │  │
│  │  │  for "create_note" │  │  Return error text   │               │  │
│  │  └──────────────────────┘  └──────────────────────┘               │  │
│  │              │                                                    │  │
│  │              ▼                                                    │  │
│  │  ┌──────────────────────┐                                         │  │
│  │  │  STEP 4: Call the   │                                          │  │
│  │  │  handler:          │                                          │  │
│  │  │  _handle_create_note│                                          │  │
│  │  │  (title, content)   │                                          │  │
│  │  │  → frappe.get_doc(   │                                          │  │
│  │  │    "Note", {...})    │                                          │  │
│  │  │    .insert()         │                                          │  │
│  │  └──────────┬──────────┘                                          │  │
│  │             │                                                       │  │
│  │             ▼                                                       │  │
│  │  ┌──────────────────────┐                                         │  │
│  │  │  STEP 5: Write       │                                          │  │
│  │  │  Execution Log       │                                          │  │
│  │  │  status=SUCCESS     │                                          │  │
│  │  │  + submit() it      │                                          │  │
│  │  │  (immutable audit)  │                                          │  │
│  │  └──────────────────────┘                                         │  │
│  │             │                                                       │  │
│  │             ▼                                                       │  │
│  │  ┌──────────────────────┐                                         │  │
│  │  │  RETURN DispatchResult│                                        │  │
│  │  │  (success, content,  │                                        │  │
│  │  │   execution_log_name)│                                        │  │
│  │  └──────────────────────┘                                         │  │
│  └─────────────────────────────────────────────────────────────────────┘ │
│                              │                                             │
│                              ▼                                             │
│  ┌────────────────────────────────────────────────────────────────────┐    │
│  │  Runner receives result.content: "Note 'Meeting' created ✓"       │    │
│  │  → Returns it to the gateway                                       │    │
│  │  → Gateway writes outbound Chat Message with this text             │    │
│  │  → CLI prints it                                                   │    │
│  └────────────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Plain English Explanation

**Slice 6 is the moment Friday can DO things, not just talk.** It's the difference between an AI that can describe what it would do, and one that actually does it.

The loop now works like this:
1. You ask Friday to "make a note titled 'Meeting' about the board meeting"
2. The LLM looks at your request and its tool menu (from Slice 3)
3. The LLM decides: "I should use the `create_note` tool"
4. The LLM sends back a special response telling the system WHICH tool to call and WHAT parameters to pass
5. Friday's **dispatcher** receives this instruction and asks the permission engine (Slice 2): "Is this agent ALLOWED to create notes?"
6. If YES → the handler actually runs, creating a `Note` document in the database
7. If NO → a rejection is logged, and Friday tells you "sorry, not allowed"
8. Either way, an **Execution Log** row is written as a permanent auditable receipt
9. Friday replies to you confirming what happened

### What's the "Dispatcher"?

The dispatcher is the **single chokepoint** that every skill call goes through. Think of it as the receptionist who:
1. Accepts the request (parses the tool call)
2. Checks with the gatekeeper (permission engine)
3. Routes to the right handler (or rejects)
4. Writes the receipt (Execution Log)
5. Reports back to the LLM

### What's `create_note` actually doing?

```python
def _handle_create_note(skill_name: str, parameters: dict) -> dict:
    title = parameters.get("title")
    content = parameters.get("content")
    doc = frappe.get_doc({
        "doctype": "Note",
        "title": title,
        "content": content,
    }).insert(ignore_permissions=True)
    return {"name": doc.name, "title": doc.title}
```

It just creates a `Note` document in the Frappe database. But now it's wrapped in the full permission-check + execution-log + LLM-routing machinery. That's what makes it a "real skill" and not just a code snippet.

### Single Chokepoint = Audit Trail Complete

Before Slice 6, there was no record of what a skill actually did — just whether it was allowed. Now:
- **Permission Decision Log** (from Slice 2) — permanent receipt for "can this agent run this skill?"
- **Execution Log** (new in Slice 6) — permanent receipt for "what happened when it ran?"

Together they answer: "On March 12th at 2 PM, agent X tried to create a note titled Y, was allowed (because their role grants Note/create), ran successfully, created Note Z."

### Key Files

| File | What it is |
|------|-----------|
| `frappe/friday_core/agent_runner/dispatcher.py` | The single chokepoint — parses, checks, routes, logs |
| `frappe/friday_core/agent_runner/runner.py` | Updated to detect tool calls and call dispatcher |
| `frappe/friday_core/llm/provider.py` | `tool_calls` field added to LLMResponse |
| `frappe/friday_core/doctype/execution_log/execution_log.json` | `error` status option added |
| `frappe/friday_core/tests/test_dispatcher.py` | 17 tests |
| `frappe/friday_core/tests/test_runner_tool_call.py` | 6 tests |

---

## How the Slices Build On Each Other

```
SLICE 1        SLICE 2            SLICE 3             SLICE 4           SLICE 5             SLICE 6
───────────────────────────────────────────────────────────────────────────────────────────────────────────────────
Filing cabinets  Gatekeeper         Skill menu        Chat loop +       Real AI brain        Real actions
(empty DB)  →  (check + log)   →  (filtered list) →  REPL + gateway →  (Minimax M2)    →  (create_note)
                                         ↑
                                         │
                              Slice 2's gatekeeper
                              is called HERE
```

Each slice:
- **Depends on** the previous slice's output
- **Does NOT modify** the previous slice's internals
- **Adds exactly one new capability** to the total system

The full end-to-end flow (after all 6 slices) is:

```
User types in CLI
  → Chat Message (inbound) row written
    → Gateway fires (after_insert hook)
      → Runner calls LLM (with tool menu from Slice 3)
        → LLM replies OR emits a tool call
        → If tool call: dispatcher checks (Slice 2) + executes (Slice 6) + logs (Slice 6)
      → Gateway writes Chat Message (outbound) row
    → CLI prints reply
  → User sees confirmation
```

---

## Summary Table

| Slice | Name | What it adds | Key New File |
|-------|------|-------------|-------------|
| 1 | Foundations | 8 DocType schemas exist in DB | `friday_core/doctype/*/` |
| 2 | Permission Engine | `check()` gatekeeper + audit log | `friday_core/permissions/matrix.py` |
| 3 | Skill Loader | `load_for_profile()` → tool menu | `friday_core/skills/loader.py` |
| 4 | Gateway + CLI | Chat flow with unified chokepoint | `friday_core/gateway/service.py` |
| 5 | LLM Integration | Real Minimax M2 calls (no tool call) | `friday_core/llm/provider.py` |
| 6 | First Skill | Tool execution loop (create_note) | `friday_core/agent_runner/dispatcher.py` |

**All 103 tests green across all slices. Branch `slice-6/first-skill` committed and pushed.**
