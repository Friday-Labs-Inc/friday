# Design 95, Slice 4 — grounded research for the Strategist (Tavily MCP)

## The gap, from the capability audit

No agent could reach the web — so the Strategist's "competitive analysis" and
"trend analysis" were whatever the model half-remembered from training. Claims
about a client's market were ungrounded by construction.

## The scout (design Q3 — Brave vs Tavily vs Perplexity)

**Tavily** won: it is agent-native (returns LLM-ready extracted content, not
just links, so grounding needs no separate fetch skill), ships an official MCP
server (plugs into Friday's Design-67 MCP client — governance, permission
matrix, and audit come for free), and its free tier covers RandomPack's volume
many times over. Brave was runner-up (independent index, but raw links need a
second extraction step; free tier retired Feb 2026). Perplexity synthesizes
answers with its own LLM — a research assistant, not a grounding primitive.
Watch-item: Nebius announced acquiring Tavily (Feb 2026); the MCP seam means
swapping providers later is configuration, not code.

## What shipped (code — the key never touches the repo)

1. **Conditional grants** (`_ensure_research_grants` in the brand
   provisioner): the two research skills the MCP sync mints —
   `mcp_tavily_tavily_search` and `mcp_tavily_tavily_extract` — are granted to
   the Brand Strategist **only if their Skill rows exist**, i.e. only after an
   operator registers the Tavily MCP Server row and sync runs. A site without
   the registration is a clean no-op. A lockstep test pins the skill names to
   what `mcp/sync.py` actually mints (a naming drift would otherwise make the
   grant silently no-op forever).

2. **The strategy prompt gains a grounded-research step**: run 2–4 searches
   on competitors, category conventions, and current trends; cite source +
   takeaway in a RESEARCH section; extract a page only when load-bearing. And
   the honest fallback: with no research tools, say "research: ungrounded —
   no search tool" **instead of inventing market claims**.

   MCP skills declare no required_doctypes, so the permission matrix passes
   without extra roles — checked explicitly (the #190 lesson).

## The operator half (config, on the box)

Register once in Desk (or via bench):

- **MCP Server** row: name `Tavily`, base_url `https://mcp.tavily.com/mcp/`,
  transport streamable-http, auth_token = the Tavily API key,
  tool_include `tavily_search, tavily_extract` (UNDERSCORES — Tavily advertises
  underscore names; a hyphenated include matches nothing and sync mints 0
  skills, proven on prod), enabled.
- Run **sync** → the two Skill rows appear (`mcp_tavily_*`).
- Run **migrate** (or provision) → the conditional grant fires and the
  Strategist's tool menu gains both.

From then on, every new brief's Strategy phase opens with real searches.

## Tests

`tests/test_research_tooling.py` (6 DB-free): skill-name lockstep with the
sync minting rules, prompt names the exact tools + mandates the ungrounded
fallback, strategist owns the phase, grants are conditional (no rows → no-op,
missing profile → no-op, partial → only the missing one appended, no dupes).
