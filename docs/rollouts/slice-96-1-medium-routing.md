# Design 96, Slice 1 — Medium-based model routing (multi-provider images)

## The problem, in one sentence

Every agent had exactly ONE model — its chat model — so an agent chatting on a
text-only provider (our brand agents run on Codex/gpt-5.5) could not generate
images at all, because `generate-image` hard-required the agent's own provider
to be MiniMax.

That check lived at `skills/handlers_visual.py` and failed with "generate-image
supports MiniMax providers only" — the exact capability gap the Friday Labs
E2E logged: a branding studio whose designers could write but not draw.

## What shipped

### 1. The Model Route table (new child DocType on Agent Settings)

Agent Settings now has a small routing table: one row per **medium** — image,
video, audio, doc-render (text exists too but is rarely needed) — naming the
LLM Provider that handles it. Think of it as "who does what kind of work":
everyone chats through their own model, but when anyone needs an *image*, the
site's image provider does it.

One admin surface, config-as-data, same pattern as `default_provider`.

### 2. `get_provider_for_medium` (llm/provider.py)

A resolution step ABOVE the existing `get_provider_for_profile` chain:

1. Is there a Model Route row for this medium? → use that provider.
2. No route? → fall through to the agent's own chain, unchanged.

Because no route rows exist until an admin adds one, **text behaviour cannot
regress** — the fall-through IS today's behaviour. Two deliberate rules,
mirroring the existing profile-link strictness:

- A route naming an **inactive** provider raises instead of silently
  re-routing (deactivating a provider means "stop", not "improvise").
- A route naming a **deleted** provider is a stale link and falls through.

The returned provider carries the same row identity stamps as every other
factory, so the **Design 94 failover chain of the routed provider applies** —
routing composes with failover for free.

### 3. `Skill.medium` (new Select field, default "text")

Every Skill now declares what kind of output it produces. It's carried through
`SkillDefinition` (and its cache round-trip) for observability and future
loader hints; cache entries written before this field default to "text".

### 4. `generate-image` goes multi-provider

The MiniMax-only credential helper is gone. The skill now resolves its
provider through the image medium route and dispatches on `provider_type`:

- **minimax** — the existing `/v1/image_generation` path, byte-for-byte the
  same behaviour (region host pick, URL download, magic-byte extension sniff).
- **openai** — NEW: `/v1/images/generations` (gpt-image models). OpenAI
  returns base64 instead of URLs, so we decode directly — no download
  round-trip. Aspect ratios map to the API's fixed sizes (square, landscape
  1536x1024, portrait 1024x1536; unparseable → "auto").

Image APIs differ too much for the LLMProvider class hierarchy (URL vs base64,
different error shapes), so the dispatch is a function-per-provider-type table
— the same shape as `_build_provider`'s if-chain. Adding the next provider is
one function plus one dict entry.

The provider row's existing `image_model` field names the model (`image-01`
for MiniMax, `gpt-image-1` for OpenAI).

## What this means on prod

The brand agents keep chatting on Codex. An admin adds one Model Route row —
medium `image` → an OpenAI provider row with an API key — and every visual
agent can produce actual logo drafts, mood boards, and mockups again. No
per-agent configuration, no code deploy for future provider swaps.

## Deploy notes

- `bench migrate` required: new `Model Route` DocType, the `model_routes`
  table field on Agent Settings, and `Skill.medium`.
- No route rows are created automatically — until an admin adds one, image
  generation resolves exactly as before (the agent's own provider).

## Tests

- `tests/test_medium_routing.py` (new): route-hit wins, un-routed falls
  through, inactive route raises, stale route falls through, Design-94
  identity stamped, `SkillDefinition.medium` round-trip + legacy-cache
  default.
- `tests/test_generate_image.py` (updated): both backends' payloads pinned
  (endpoint, auth, model, ratio→size mapping), error paths narrate instead of
  raising, unsupported provider types name the fix ("Agent Settings → Model
  Routes").
