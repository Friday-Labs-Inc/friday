# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt

"""
The Friday agent runner — the brain that takes a user message and produces a reply.

PLAIN ENGLISH
=============

This package is where the agent's *thinking* happens. Given an Agent
Profile and an inbound message, it produces an outbound reply.

In Slice 4 the runner is a **stub**: it loads the agent's tool menu
(via Slice 3) and echoes the message back with a count of available
tools. This proves the pipeline end-to-end without dragging in an LLM
dependency yet.

In Slice 5 the body of `run_turn` gets replaced with a real LLM call —
the function signature stays the same, the seam is at the function
boundary on purpose. The gateway, the chat-flow tests, and the Chat
Message writer don't need to change.

When batching activates (per §4 Q4-C in the design-decisions doc), the
signature evolves to accept `messages: list[str]` — but until then it
stays `content: str` and the gateway joins any batched messages with
'\\n' before calling.

DESIGN NOTE: WHY A PACKAGE, NOT JUST A FUNCTION
================================================

A bare module would work today. A package gives us room to grow:
provider adapters, system-prompt builders, tool-dispatch helpers, the
ReAct loop. All of those will live here when they exist.

The Hermes equivalent is `run_agent.py:AIAgent.run_conversation` — a
single class with many helpers. We'll mirror that structure when we
need it; for now there's one stub function.

CONTRACT WITH THE GATEWAY
=========================

`run_turn` is called BY the gateway, INSIDE the per-session lock. It
must not write Chat Message rows of its own (the gateway does that).
It must not write Permission Decision Log rows (that's the per-skill
permission check in later slices). It just returns the reply text.
"""
