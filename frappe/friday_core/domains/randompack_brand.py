# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt

"""
The RandomPack brand identity domain, expressed purely as DATA (Design 75).

PLAIN ENGLISH
=============
This is the FIRST domain bundle. It does NOT contain pipeline logic — that lives
in the generic engine (friday_core/engine/). What it contains is the *data* that
teaches the engine one domain:

  - a Frappe Workflow on the Brand Brief work-item: the states a job moves
    through (Strategy -> Naming -> ... -> Delivered) and the role-gated
    transitions between them,
  - a Friday Workflow Transition Meta row for every AGENTIC transition: which
    role owns it, which skills it verifies, and the Jinja prompt the agent runs,
  - the brand specialist team as Agent Profiles, each tagged with the
    discriminator_role the engine routes to,
  - a gateway service account that holds ONLY the client-gate role, so the two
    client decision gates can be fired (by a human in Desk, or by the RandomPack
    webhook) without any agent being able to approve its own work,
  - the Domain Bundle manifest tying it all together.

Add a second domain (data centre ops, research) the same way: more data, no new
Python. This module is a "fixture generator" (Design 75 §6) — the old
hardcoded RANDOMPACK_PIPELINE list is reborn here as Workflow + meta rows.

Run once per site (idempotent):

    bench --site friday.localhost execute \\
        frappe.friday_core.domains.randompack_brand.provision

Phase 1 is sequential-only (Design 75 §8): the historical naming/directions
fan-out is linearised. A true parallel fan-out is Phase 2.

DESIGN 95 (the CD apprenticeship) reshaped the machine: the HUMAN Creative
Director creates the identity (the CD Creative stage — he uploads his direction
options + design system to the Project and fires "Creative Ready"), the AI
applies it (AI Production), and his CD Internal Gate approves or loops the
production back for rework before anything reaches the client gates. The old
AI-originates-directions states (Directions, Buildout) remain as LEGACY so
in-flight briefs finish; no new brief enters them.
"""

from __future__ import annotations

import json

import frappe

DOMAIN_DOCTYPE = "Brand Brief"
WORKFLOW_NAME = "RandomPack Brand Pipeline"
BUNDLE_NAME = "randompack-brand"
STATE_FIELD = "workflow_state"

# Design 81 — RandomPack is connector #1 (system modality). The Connector row is
# the registry entry; its secrets are carried over from the old RandomPack
# Settings by the 81b migration patch. This module is the connector's handler
# module (its HANDLERS dict is what connectors.core.process_event dispatches).
CONNECTOR_NAME = "randompack-system"
CONNECTOR_HANDLER_MODULE = "frappe.friday_core.surfaces.randompack"

# Generic engine skill (Design 75 Phase 1.1): lets a phase read the outputs of
# the earlier phases of the same work-item. Domain-agnostic — provisioned here
# because the brand bundle is the first to need it. Handler:
# friday_core/skills/handlers_engine.py.
ENGINE_SKILL = "get-phase-outputs"

# Visual-generation skill: the Creative Director produces real images (logos /
# key visuals) via the MiniMax image model. Handler:
# friday_core/skills/handlers_visual.py. Costs per call → risk_level medium.
VISUAL_SKILL = "generate-image"

# The existing brand Role (bootstrap_brand.py) carries the Frappe doctype perms
# the skills need: READ Brand Brief, CREATE Brand Direction, and WRITE Brand
# Brief (which apply_workflow's save needs). Every agent profile holds it.
PERM_ROLE = "Brand Agent"

# The client-decision-gate role. Held ONLY by the gateway account — no agent
# holds it, so no agent can fire a gate (Design 75 §3 governance).
GATE_ROLE = "Brand Client Reviewer"

# The HUMAN Creative Director's role (Design 95). Distinct from the client-gate
# role even while one person holds both today, and from the AI "Creative
# Director" profile (the apprentice seat): the human CREATES the identity (the
# CD Creative stage) and APPROVES the AI's production (the CD Internal Gate).
# No agent ever holds this role. Grant it to the human CD's user in Desk.
CD_ROLE = "Brand Creative Director"

# The no-login system user that fires the gates (the human in Desk acts through
# it, or the RandomPack webhook does). Holds GATE_ROLE and nothing else.
GATEWAY_USER = "gateway+brand@friday.local"

# ---------------------------------------------------------------------------
# The state machine — DATA. (state, allow_edit role). All doc_status = 0
# (Brand Brief is not submittable). allow_edit on a state is the role that
# *leaves* that state, because apply_workflow saves the doc as that actor.
# ---------------------------------------------------------------------------
STATES: list[tuple[str, str]] = [
	# Idle entry state: a brief sits here after payment.received until
	# project.created fires "Start Pipeline". It has NO agentic phase, so the
	# engine never dispatches from it — this is what lets us set rp_project
	# (known only at project.created) BEFORE the first phase runs.
	("Intake", "System Manager"),
	("Strategy", "Brand Strategist"),
	("Naming", "Brand Copywriter"),
	# Design 95 — the HUMAN Creative Director's stage: he creates the direction
	# options (logo concepts + design system) and uploads them to the Project.
	# No agentic phase; the engine waits for his "Creative Ready" transition.
	("CD Creative", CD_ROLE),
	("Gate 1 Prep", "Brand Strategist"),
	("Gate 1 Review", GATE_ROLE),
	# Design 95 — the AI applies the human's chosen system across the
	# deliverable set (the apprentice's production stage; replaces Buildout).
	("AI Production", "Creative Director"),
	# Design 95 — the human CD's internal QA gate: approve forwards the work;
	# refine loops it back to AI Production. Nothing reaches the client uninspected.
	("CD Internal Gate", CD_ROLE),
	("Gate 2 Prep", "Brand Strategist"),
	("Gate 2 Review", GATE_ROLE),
	("Guidelines", "Brand Copywriter"),
	("Delivered", "System Manager"),
	# LEGACY (pre-Design-95 machine) — kept ONLY so in-flight briefs already at
	# these states remain valid and can finish; no new brief ever enters them.
	("Directions", "Creative Director"),
	("Buildout", "Creative Director"),
]
INITIAL_STATE = "Intake"

# (from_state, action, next_state, allowed_role). "Start Pipeline" is the
# system transition project.created fires to leave the idle Intake state. The
# client gates are owned by GATE_ROLE, the two human-CD transitions by CD_ROLE;
# everything else by an agent role.
TRANSITIONS: list[tuple[str, str, str, str]] = [
	("Intake", "Start Pipeline", "Strategy", "System Manager"),
	("Strategy", "Complete Strategy", "Naming", "Brand Strategist"),
	("Naming", "Complete Naming", "CD Creative", "Brand Copywriter"),
	# The human CD signals "my directions + design system are on the Project".
	("CD Creative", "Creative Ready", "Gate 1 Prep", CD_ROLE),
	("Gate 1 Prep", "Complete Gate 1 Prep", "Gate 1 Review", "Brand Strategist"),
	("Gate 1 Review", "Approve Direction", "AI Production", GATE_ROLE),
	("AI Production", "Complete Production", "CD Internal Gate", "Creative Director"),
	# The internal gate: forward to the client track, or loop back for rework.
	("CD Internal Gate", "Approve Production", "Gate 2 Prep", CD_ROLE),
	("CD Internal Gate", "Request Refinement", "AI Production", CD_ROLE),
	("Gate 2 Prep", "Complete Gate 2 Prep", "Gate 2 Review", "Brand Strategist"),
	("Gate 2 Review", "Final Approval", "Guidelines", GATE_ROLE),
	("Guidelines", "Complete Guidelines", "Delivered", "Brand Copywriter"),
	# LEGACY exits — let in-flight briefs finish the old machine, then rejoin.
	("Directions", "Complete Directions", "Gate 1 Prep", "Creative Director"),
	("Buildout", "Complete Buildout", "Gate 2 Prep", "Creative Director"),
]

# Agentic transition metadata — one row per agent-owned transition. phase_key is
# the stable slug carried onto the Task; agent_role is BOTH the routing key
# (-> discriminator_role) and the Frappe transition's allowed role.
PHASES: list[dict] = [
	{
		"phase_key": "strategy",
		"from_state": "Strategy",
		"action": "Complete Strategy",
		"agent_role": "Brand Strategist",
		"skills": ["get-brand-brief", "attach-deliverable"],
		"prompt": (
			"You are the brand strategist for {{ business_name }} (industry: "
			"{{ industry or 'n/a' }}). Read the full brief first with get-brand-brief "
			"(brief id: {{ name }}). GROUND YOUR RESEARCH (design 95): if your tools "
			"include mcp_tavily_tavily_search / mcp_tavily_tavily_extract, run 2-4 "
			"searches on the client's competitors, category conventions, and current "
			"naming/visual trends in their industry — cite what you found (source + "
			"one-line takeaway) in a short RESEARCH section; extract a page only when "
			"a result is load-bearing. If you have no research tools, say so in one "
			"line ('research: ungrounded — no search tool') instead of inventing "
			"market claims. Then draft strategy & positioning: market "
			"position, the core audience insight, the ONE differentiating idea, and a "
			"crisp positioning statement. After the draft, call attach-deliverable "
			"with project_name=\"{{ project }}\" and file_name=\"strategy.md\" passing "
			"your draft as content, so the customer sees it on their project page. "
			"Reply with the full draft."
		),
	},
	{
		"phase_key": "naming",
		"from_state": "Naming",
		"action": "Complete Naming",
		"agent_role": "Brand Copywriter",
		"skills": ["get-brand-brief", "get-phase-outputs", "attach-deliverable"],
		"prompt": (
			"You are the brand namer/copywriter for {{ business_name }}. FIRST call "
			"get-phase-outputs to read the strategy phase's positioning, core insight, "
			"and differentiating idea — your names must reflect that positioning, not "
			"generic industry vibes. THEN read brief {{ name }} with get-brand-brief "
			"for the client's context. Produce 8-12 name candidates, each with a "
			"one-line rationale that ties back to the positioning and basic screening "
			"notes (pronunciation, obvious conflicts). After the list, call "
			"attach-deliverable with project_name=\"{{ project }}\" and "
			"file_name=\"naming-candidates.md\" passing the full list as content. "
			"Humans shortlist; trademark/domain checks are theirs."
		),
	},
	{
		"phase_key": "gate1_prep",
		"from_state": "Gate 1 Prep",
		"action": "Complete Gate 1 Prep",
		"agent_role": "Brand Strategist",
		"skills": [
			"get-brand-brief",
			"get-phase-outputs",
			"list-project-files",
			"get-project-file",
			"attach-deliverable",
		],
		"prompt": (
			"The human Creative Director has just uploaded their direction options "
			"(logo concepts + design system) to the project. FIRST call "
			"list-project-files with project_name=\"{{ project }}\" — this returns "
			"each attached File as {name, file_name, ...}. Then, for EACH file whose "
			"file_name looks like a Creative Director upload (typically a design "
			"system doc, direction options, logo concepts — NOT the earlier "
			"strategy*.md or naming-candidates*.md; you'll get those via "
			"get-phase-outputs below), call get-project-file with "
			"project_name=\"{{ project }}\" and file_name set to EITHER the file's "
			"`name` (docname) OR its `file_name` (human name) from the list — both "
			"work; do NOT invent a name. Read each file's `content` — those files "
			"ARE the directions; never invent or restyle them. Then call "
			"get-phase-outputs for the strategy draft and naming candidates for "
			"{{ business_name }}. THEN assemble the client-facing summary for "
			"decision gate 1 (brief {{ name }}): each direction the Creative "
			"Director prepared (one paragraph each, client-friendly, faithful to "
			"their files, citing colours/typography/mark from their system), "
			"naming shortlist context, and a recommendation with reasoning. After "
			"the summary, call attach-deliverable with "
			"project_name=\"{{ project }}\" and file_name=\"gate1-client-presentation.md\" "
			"passing the full presentation as content — this is what the client "
			"clicks at Gate 1. Reply with the full presentation text."
		),
	},
	{
		# Design 95 — the apprentice's production stage: apply the HUMAN Creative
		# Director's system, never originate one. Also re-entered on "Request
		# Refinement" from the CD Internal Gate.
		"phase_key": "production",
		"from_state": "AI Production",
		"action": "Complete Production",
		"agent_role": "Creative Director",
		"skills": [
			"get-brand-brief",
			"get-phase-outputs",
			"list-project-files",
			"get-project-file",
			"generate-image",
			"attach-deliverable",
		],
		"prompt": (
			"The client of {{ business_name }} chose the direction "
			"\"{{ chosen_direction or 'the approved direction' }}\" from the options "
			"the human Creative Director created. Their design system is LAW: FIRST "
			"call list-project-files with project_name=\"{{ project }}\" — this "
			"returns each attached File as {name, file_name, ...}. Then, for EACH "
			"Creative Director upload (design system doc, direction options, logo "
			"concepts — NOT strategy*.md / naming*.md / earlier deliverable-*.md), "
			"call get-project-file with project_name=\"{{ project }}\" and file_name "
			"set to EITHER the file's `name` (docname) OR `file_name` (human name) "
			"from the list — both work; do NOT invent a name. Follow their palette, "
			"typography, logo usage, and rules EXACTLY; never invent outside their "
			"system (where it is silent, extrapolate conservatively and note the "
			"gap). Also read get-phase-outputs for the strategy context — and if "
			"this task follows a refinement request, treat the Creative Director's "
			"refinement notes as corrections to apply first. Produce the production "
			"package applying their chosen system: palette values as specified, "
			"typography hierarchy, voice & tone rules, application copy (web hero, "
			"about, boilerplate), designer-ready specs for every core asset, and "
			"generate-image production visuals that follow the system. After the "
			"package, call attach-deliverable with project_name=\"{{ project }}\" "
			"and file_name=\"production-package.md\" passing the full package as "
			"content. Reply with the full package."
		),
	},
	{
		"phase_key": "gate2_prep",
		"from_state": "Gate 2 Prep",
		"action": "Complete Gate 2 Prep",
		"agent_role": "Brand Strategist",
		"skills": ["get-brand-brief", "get-phase-outputs", "list-project-files", "attach-deliverable"],
		"prompt": (
			"FIRST call list-project-files with project_name=\"{{ project }}\" to "
			"see what's already on the project, then get-phase-outputs to read the "
			"production package (or the legacy build-out package) and the earlier "
			"decisions for {{ business_name }}. "
			"THEN assemble the client-facing final-review summary (brief {{ name }}): "
			"what was built, the decisions made, and what delivery contains. After "
			"the summary, call attach-deliverable with project_name=\"{{ project }}\" "
			"and file_name=\"gate2-final-review.md\" passing the full summary as "
			"content — this is what the client clicks at Gate 2. Reply with the full "
			"presentation text."
		),
	},
	{
		"phase_key": "guidelines",
		"from_state": "Guidelines",
		"action": "Complete Guidelines",
		"agent_role": "Brand Copywriter",
		"skills": ["get-brand-brief", "get-phase-outputs", "list-project-files", "attach-deliverable"],
		"prompt": (
			"FIRST call list-project-files with project_name=\"{{ project }}\" to "
			"see what's already on the project, then get-phase-outputs to read the "
			"production package (or the legacy build-out package) and the strategy "
			"for {{ business_name }}. THEN draft "
			"the complete brand guidelines document (brief {{ name }}): strategy "
			"recap, logo usage rules, palette with values, typography, voice & tone "
			"with examples, and application do/don'ts. After the document, call "
			"attach-deliverable with project_name=\"{{ project }}\" and "
			"file_name=\"brand-guidelines.md\" passing the full document as content "
			"— this is the customer's primary deliverable. Reply with the full "
			"document in Markdown."
		),
	},
	# ------------------------------------------------------------------ LEGACY
	# Pre-Design-95 phases, kept ONLY so in-flight briefs already at these states
	# can finish. No new brief reaches them (the flow was re-routed above).
	{
		"phase_key": "directions",
		"from_state": "Directions",
		"action": "Complete Directions",
		"agent_role": "Creative Director",
		"skills": ["get-brand-brief", "create-brand-direction", "generate-image"],
		"prompt": (
			"You are the creative director for {{ business_name }}. Read brief "
			"{{ name }} with get-brand-brief, then generate THREE genuinely distinct "
			"brand directions. For EACH direction: (1) call generate-image with a "
			"vivid prompt capturing its logo concept, palette, and mood to produce a "
			"real sample visual (it attaches to the brief automatically); (2) persist "
			"the direction with create-brand-direction (palette, typography, "
			"designer-ready logo concept, taglines). Reply with a one-paragraph "
			"summary of each direction, noting its generated visual."
		),
	},
	{
		"phase_key": "buildout",
		"from_state": "Buildout",
		"action": "Complete Buildout",
		"agent_role": "Creative Director",
		"skills": ["get-brand-brief", "get-phase-outputs", "list-project-files", "generate-image", "attach-deliverable"],
		"prompt": (
			"The client of {{ business_name }} chose the direction "
			"\"{{ chosen_direction or 'the approved direction' }}\". FIRST call "
			"list-project-files with project_name=\"{{ project }}\" to see what's "
			"already on the project, then get-phase-outputs to read the strategy and "
			"the three directions — build on the chosen direction's ACTUAL palette, "
			"typography, and logo concept rather than inventing a fresh take. Call "
			"generate-image to produce the refined hero/key visual for the chosen "
			"direction. Produce the build-out package: refined palette system, "
			"typography hierarchy, voice & tone rules, application copy (web hero, "
			"about, boilerplate), and designer-ready specs for every core asset. "
			"After the package, call attach-deliverable with "
			"project_name=\"{{ project }}\" and file_name=\"buildout-package.md\" "
			"passing the full package as content. Reply with the full package."
		),
	},
]

# The brand specialist team — Agent Profiles. discriminator_role is the routing
# key the engine matches a transition's agent_role against; it is ALSO the role
# the profile's system user holds (so the user is authorised to fire its own
# transitions). PERM_ROLE is added for the skill/doctype permissions.
PROFILES: list[dict] = [
	{
		"profile_name": "Brand Strategist",
		"discriminator_role": "Brand Strategist",
		"skills": [
			"get-brand-brief",
			"get-phase-outputs",
			"list-project-files",
			"get-project-file",
			"attach-deliverable",
		],
		"system_prompt": (
			"You are a senior brand strategist. You think in positioning, audience "
			"insight, and the single differentiating idea. You are concise, "
			"evidence-led, and never decorative."
		),
	},
	{
		"profile_name": "Brand Copywriter",
		"discriminator_role": "Brand Copywriter",
		"skills": ["get-brand-brief", "get-phase-outputs", "list-project-files", "attach-deliverable"],
		"system_prompt": (
			"You are a brand namer and copywriter. You generate distinctive names "
			"and write brand voice with rhythm and restraint. You screen names for "
			"obvious problems but leave legal checks to humans."
		),
	},
	{
		# Design 95 — the apprentice seat. The HUMAN Creative Director creates the
		# identity; this agent PRODUCES around it, faithfully. (create-brand-direction
		# + generate-image stay granted for the LEGACY directions/buildout phases of
		# in-flight briefs, and generate-image serves production visuals.)
		"profile_name": "Creative Director",
		"discriminator_role": "Creative Director",
		"skills": [
			"get-brand-brief",
			"create-brand-direction",
			"get-phase-outputs",
			"generate-image",
			"list-project-files",
			"get-project-file",
			"attach-deliverable",
			# Design 95 slice 2 — the observe task stores lessons via remember.
			"remember",
		],
		# remember is matrix-checked (create on Agent Memory) at MENU BUILD time;
		# without this role the loader silently drops the tool even though it is
		# allow-listed above. Memory Agent = the same role the Friday profile uses.
		"extra_roles": ["Memory Agent"],
		"system_prompt": (
			"You are the studio's production designer — the apprentice seat of the "
			"human Creative Director. Their logo and design system are law: read their "
			"files first, and apply their palette, typography, and rules exactly, at "
			"production quality, across every deliverable. You never originate a new "
			"identity direction; where their system is silent, extrapolate "
			"conservatively from it and flag the gap. Treat every correction and "
			"refinement note from the Creative Director as a lesson to follow."
		),
	},
]

AGENT_ROLES = [p["discriminator_role"] for p in PROFILES]

# Design 95 slice 4 — grounded research for the Strategist. These are the Skill
# rows the Tavily MCP sync mints (mcp/sync.py naming: mcp_<server-slug>_<tool>;
# server "Tavily" + tools "tavily-search"/"tavily-extract"). They exist only
# AFTER an operator registers the MCP Server row (it holds the API key — config,
# never repo) and sync runs; the grant below is therefore CONDITIONAL, so the
# provisioner is a no-op on sites without the registration.
RESEARCH_PROFILE = "Brand Strategist"
RESEARCH_SKILLS = ("mcp_tavily_tavily_search", "mcp_tavily_tavily_extract")


# ---------------------------------------------------------------------------
# Provisioning (idempotent; safe to re-run).
# ---------------------------------------------------------------------------
def after_migrate() -> None:
	"""after_migrate entry — ensure the bundle exists on every site (Legion, CI,
	fresh installs). Failure-isolated: a provisioning hiccup is logged loudly but
	must NEVER abort the migrate (mirrors agent_identity.provision_all_agent_users).
	"""
	try:
		provision()
	except Exception:
		frappe.log_error(
			title="randompack_brand: provision failed in after_migrate",
			message=frappe.get_traceback(),
		)


def provision() -> dict:
	"""Provision the whole bundle. Order matters: roles -> masters -> workflow ->
	meta -> profiles (which auto-provision their users) -> gateway -> perms ->
	bundle manifest."""
	_ensure_roles()
	# The get-phase-outputs Skill must exist before ANYTHING that Links to it —
	# the transition-meta required_skills AND the profiles' permitted_skills both
	# reference it. Its Task:read grant needs PERM_ROLE, created by _ensure_roles.
	_ensure_engine_skill()
	_ensure_visual_skill()
	_ensure_file_skills()
	_ensure_workflow_masters()
	_ensure_workflow()
	_ensure_transition_meta()
	# The Domain Bundle must exist before the profiles, because each profile
	# Links to it (domain_bundle). Its own links (work-item doctype, workflow)
	# already exist by this point.
	_ensure_bundle()
	_ensure_profiles()
	_ensure_research_grants()
	_ensure_gateway_account()
	_ensure_work_item_perms()
	_ensure_connector()

	frappe.db.commit()  # nosemgrep: frappe-semgrep-rules.rules.frappe-manual-commit
	summary = {
		"bundle": BUNDLE_NAME,
		"workflow": WORKFLOW_NAME,
		"work_item": DOMAIN_DOCTYPE,
		"agentic_phases": [p["phase_key"] for p in PHASES],
		"profiles": [p["profile_name"] for p in PROFILES],
		"gateway": GATEWAY_USER,
	}
	print(f"✓ RandomPack brand bundle provisioned: {summary}")
	return summary


def _ensure_connector() -> None:
	"""Ensure the randompack-system Connector registry row exists (Design 81b).

	Idempotent + secret-safe: on a fresh site this creates a DISABLED stub (an
	operator fills in the secrets + flips enabled); on an existing site it only
	repairs the modality/direction/handler_module pointer and NEVER touches the
	secrets or the enabled flag (those were migrated from RandomPack Settings by
	the 81b patch, or set by an operator).
	"""
	if frappe.db.exists("Connector", CONNECTOR_NAME):
		frappe.db.set_value(
			"Connector",
			CONNECTOR_NAME,
			{"modality": "system", "handler_module": CONNECTOR_HANDLER_MODULE},
			update_modified=False,
		)
		return
	frappe.get_doc(
		{
			"doctype": "Connector",
			"connector_name": CONNECTOR_NAME,
			"modality": "system",
			"direction": "Both",
			"enabled": 0,
			"handler_module": CONNECTOR_HANDLER_MODULE,
			"signature_tolerance_seconds": 300,
			"description": "RandomPack ops backend — connector #1 (Design 81). "
			"Fill in the API base URL, token key/secret, and webhook secret, then enable.",
		}
	).insert(ignore_permissions=True)


def _ensure_roles() -> None:
	"""Create the agent (discriminator) roles + the gate role + the human CD role.
	PERM_ROLE is owned by bootstrap_brand; create it too if a site hasn't run that
	yet."""
	for role in [*AGENT_ROLES, GATE_ROLE, CD_ROLE, PERM_ROLE]:
		if not frappe.db.exists("Role", role):
			frappe.get_doc({"doctype": "Role", "role_name": role, "desk_access": 1}).insert(
				ignore_permissions=True
			)


def _ensure_file_skills() -> None:
	"""Make the file-tool skills (list-project-files, get-project-file, attach-deliverable)
	actually USABLE by the brand team (Design 66b). TWO gates had to be opened — both found
	by a real agent-turn E2E where the Creative Director couldn't read the human CD's
	uploaded design system:

	  1. **Status.** `bootstrap_files._ensure_skill_row` creates the Skill row with the
	     DEFAULT status "Draft", and the skills loader HARD-excludes non-Active skills — so
	     the tool never even appeared in the agent's toolset. We flip them Active.
	  2. **Runtime perms.** The handlers gate on `has_permission("Project"/"File", …)` as the
	     AGENT'S user. The brand profiles' roles don't grant Project/File read, so even once
	     the tool loaded the call returned "denied / no files". The `Friday File Author`
	     role grants exactly File-create + Project/Task-read; we ensure it here and
	     `_ensure_profiles` assigns it to each brand profile.

	bootstrap_files is not in after_migrate, so both could be missing on a fresh site.
	Same ordering pattern as _ensure_engine_skill.
	"""
	from frappe.friday_core.skills.bootstrap_files import _ensure_role_and_perms, _ensure_skill_row

	_ensure_role_and_perms()  # the Friday File Author role + File-create / Project+Task-read
	for skill_name in ("list-project-files", "get-project-file", "attach-deliverable"):
		if not frappe.db.exists("Skill", skill_name):
			_ensure_skill_row(skill_name)
		if frappe.db.get_value("Skill", skill_name, "status") != "Active":
			frappe.db.set_value("Skill", skill_name, "status", "Active")


def _ensure_engine_skill() -> None:
	"""Create the generic `get-phase-outputs` Skill row and grant PERM_ROLE READ
	on Task, so the permission matrix admits agents reading their work-item's
	earlier phase outputs. Idempotent."""
	if frappe.db.exists("Skill", ENGINE_SKILL):
		skill = frappe.get_doc("Skill", ENGINE_SKILL)
	else:
		skill = frappe.new_doc("Skill")
		skill.skill_name = ENGINE_SKILL
	skill.description = (
		"Read the outputs the EARLIER phases of this work item already produced "
		"(strategy, naming, directions, build-out, ...). Returns each completed "
		"phase's result so you build on real prior work instead of just the brief."
	)
	skill.when_to_use = (
		"Call this FIRST in any phase that summarises or builds on earlier work — "
		"gate preps, build-out, guidelines. Inside a pipeline task it needs no "
		"arguments; it reads the current work item automatically."
	)
	skill.parameters_schema = json.dumps(
		{
			"type": "object",
			"properties": {
				"work_item": {
					"type": "string",
					"description": "Optional — the work-item id (e.g. a brief id). Defaults to the current task's work item.",
				}
			},
			"required": [],
		}
	)
	skill.risk_level = "low"
	skill.requires_approval = 0
	skill.status = "Active"
	skill.required_doctypes = []
	skill.append("required_doctypes", {"target_doctype": "Task", "operation": "read"})
	skill.save(ignore_permissions=True)

	# PERM_ROLE (held by every specialist) needs READ on Task for the matrix to
	# admit get-phase-outputs. Mirrors bootstrap_brand's Custom DocPerm idiom.
	if not frappe.db.exists("Custom DocPerm", {"parent": "Task", "role": PERM_ROLE}):
		frappe.get_doc(
			{
				"doctype": "Custom DocPerm",
				"parent": "Task",
				"parenttype": "DocType",
				"parentfield": "permissions",
				"role": PERM_ROLE,
				"permlevel": 0,
				"read": 1,
			}
		).insert(ignore_permissions=True)
	frappe.clear_cache(doctype="Task")


def _ensure_visual_skill() -> None:
	"""Create the generate-image Skill row (idempotent). It creates Frappe Files
	via the file manager, so it declares no required_doctypes (generative, not a
	domain CRUD); it is gated only by being in a profile's permitted_skills."""
	if frappe.db.exists("Skill", VISUAL_SKILL):
		skill = frappe.get_doc("Skill", VISUAL_SKILL)
	else:
		skill = frappe.new_doc("Skill")
		skill.skill_name = VISUAL_SKILL
	skill.description = (
		"Generate an actual image from a text prompt (via the MiniMax image "
		"model) and save it as a file attached to the current work item. Use it "
		"to produce a logo or key visual, not just describe one. Returns the "
		"file URL(s)."
	)
	skill.when_to_use = (
		"When you need a REAL image — a sample logo, a key visual, a moodboard "
		"frame. Give a vivid prompt capturing subject, style, palette, and mood. "
		"Optional: aspect_ratio (default 1:1), n (1-9). It attaches to the work "
		"item automatically."
	)
	skill.parameters_schema = json.dumps(
		{
			"type": "object",
			"properties": {
				"prompt": {"type": "string", "description": "Vivid description of the image to generate."},
				"aspect_ratio": {
					"type": "string",
					"description": "1:1, 16:9, 4:3, 3:2, 2:3, 3:4, 9:16, or 21:9. Default 1:1.",
				},
				"n": {"type": "integer", "description": "How many images (1-9). Default 1."},
			},
			"required": ["prompt"],
		}
	)
	skill.risk_level = "medium"  # external generative call with per-image cost
	skill.requires_approval = 0  # first-party trusted pipeline (v0.1 posture)
	skill.status = "Active"
	skill.required_doctypes = []
	skill.save(ignore_permissions=True)


def _ensure_workflow_masters() -> None:
	"""Workflow State + Workflow Action Master records are link targets the
	Workflow references; they must exist first."""
	for state, _allow_edit in STATES:
		if not frappe.db.exists("Workflow State", state):
			frappe.get_doc(
				{"doctype": "Workflow State", "workflow_state_name": state, "style": ""}
			).insert(ignore_permissions=True)
	for _from, action, _next, _allowed in TRANSITIONS:
		if not frappe.db.exists("Workflow Action Master", action):
			frappe.get_doc(
				{"doctype": "Workflow Action Master", "workflow_action_name": action}
			).insert(ignore_permissions=True)


def _ensure_workflow() -> None:
	"""Upsert the Frappe Workflow on Brand Brief. Rebuilds states + transitions
	from STATES/TRANSITIONS each run so code changes (e.g. the Intake state)
	reach an already-provisioned site. Existing briefs keep their current state."""
	states = [
		{"state": state, "doc_status": "0", "allow_edit": allow_edit}
		for state, allow_edit in STATES
	]
	transitions = [
		{"state": frm, "action": action, "next_state": nxt, "allowed": allowed, "allow_self_approval": 1}
		for frm, action, nxt, allowed in TRANSITIONS
	]
	if frappe.db.exists("Workflow", WORKFLOW_NAME):
		wf = frappe.get_doc("Workflow", WORKFLOW_NAME)
		wf.is_active = 1
		wf.workflow_state_field = STATE_FIELD
		wf.send_email_alert = 0
		wf.set("states", [])
		for s in states:
			wf.append("states", s)
		wf.set("transitions", [])
		for t in transitions:
			wf.append("transitions", t)
		wf.save(ignore_permissions=True)
		return
	frappe.get_doc(
		{
			"doctype": "Workflow",
			"workflow_name": WORKFLOW_NAME,
			"document_type": DOMAIN_DOCTYPE,
			"is_active": 1,
			"workflow_state_field": STATE_FIELD,
			"send_email_alert": 0,
			"states": states,
			"transitions": transitions,
		}
	).insert(ignore_permissions=True)


def _ensure_transition_meta() -> None:
	"""One Friday Workflow Transition Meta per agentic transition (upsert)."""
	for phase in PHASES:
		existing = frappe.db.get_value(
			"Friday Workflow Transition Meta",
			{"workflow": WORKFLOW_NAME, "from_state": phase["from_state"], "action": phase["action"]},
			"name",
		)
		doc = (
			frappe.get_doc("Friday Workflow Transition Meta", existing)
			if existing
			else frappe.new_doc("Friday Workflow Transition Meta")
		)
		doc.workflow = WORKFLOW_NAME
		doc.from_state = phase["from_state"]
		doc.action = phase["action"]
		doc.phase_key = phase["phase_key"]
		doc.execution_mode = "agentic"
		doc.agent_role = phase["agent_role"]
		doc.prompt_template = phase["prompt"]
		doc.timeout_seconds = 1800
		doc.max_retries = 2
		doc.required_skills = []
		for skill in phase["skills"]:
			doc.append("required_skills", {"skill": skill})
		doc.save(ignore_permissions=True)


def _ensure_profiles() -> None:
	"""Create/refresh the three specialist profiles. assigned_roles =
	[discriminator_role, PERM_ROLE]; inserting fires after_insert which
	provisions the agent's system user with those roles."""
	from frappe.friday_core.skills.bootstrap_files import FILE_ROLE
	from frappe.friday_core.skills.bootstrap_memory import ensure_memory_role

	# Memory Agent (+ its create-on-Agent-Memory perm) must exist before any
	# spec below references it — fresh sites may not have run the memory
	# bootstrap yet. Idempotent.
	ensure_memory_role()

	provider, model = _model_config()
	for spec in PROFILES:
		name = spec["profile_name"]
		if frappe.db.exists("Agent Profile", name):
			profile = frappe.get_doc("Agent Profile", name)
		else:
			profile = frappe.new_doc("Agent Profile")
			profile.profile_name = name
		profile.agent_role = "Specialist"
		profile.status = "Active"
		profile.discriminator_role = spec["discriminator_role"]
		profile.domain_bundle = BUNDLE_NAME
		profile.system_prompt = spec["system_prompt"]
		if provider:
			profile.model_provider = provider
		if model:
			profile.model_name = model

		# FILE_ROLE (Friday File Author) grants the Project/File perms the file-skill handlers
		# check at RUNTIME — without it get-project-file / list-project-files return "denied".
		_append_missing(
			profile,
			"assigned_roles",
			"role",
			[spec["discriminator_role"], PERM_ROLE, FILE_ROLE, *spec.get("extra_roles", ())],
		)
		_append_missing(profile, "permitted_skills", "skill", spec["skills"])
		profile.save(ignore_permissions=True)

		# Reconcile the system user's roles in case the profile already existed
		# (after_insert only fires on first creation).
		from frappe.friday_core.identity.agent_identity import provision_agent_user

		provision_agent_user(profile)
		from frappe.friday_core.skills.loader import invalidate_for_profile

		invalidate_for_profile(name)


def _ensure_research_grants() -> None:
	"""Grant the Tavily research skills to the Strategist — ONLY those whose
	Skill rows exist (minted by the MCP sync after the operator registers the
	server). Idempotent; a site without the Tavily registration is a no-op.
	MCP skills declare no required_doctypes, so the permission matrix passes
	without extra roles (unlike remember — the #190 lesson checked)."""
	if not frappe.db.exists("Agent Profile", RESEARCH_PROFILE):
		return
	present = [s for s in RESEARCH_SKILLS if frappe.db.exists("Skill", s)]
	if not present:
		return
	profile = frappe.get_doc("Agent Profile", RESEARCH_PROFILE)
	_append_missing(profile, "permitted_skills", "skill", present)
	profile.save(ignore_permissions=True)


def _ensure_gateway_account() -> None:
	"""A no-login System User holding ONLY the gate role. The human (or webhook)
	fires the client gates through it; no agent holds GATE_ROLE."""
	if not frappe.db.exists("User", GATEWAY_USER):
		frappe.get_doc(
			{
				"doctype": "User",
				"email": GATEWAY_USER,
				"first_name": "Brand Gate",
				"full_name": "Brand Gateway",
				"enabled": 1,
				"user_type": "System User",
				"send_welcome_email": 0,
				"roles": [{"role": GATE_ROLE}],
			}
		).insert(ignore_permissions=True)
	else:
		user = frappe.get_doc("User", GATEWAY_USER)
		if GATE_ROLE not in {r.role for r in (user.roles or [])}:
			user.append("roles", {"role": GATE_ROLE})
			user.save(ignore_permissions=True)


def _ensure_work_item_perms() -> None:
	"""The gate role + the human CD role need WRITE on Brand Brief so
	apply_workflow's save succeeds when they fire their transitions. (Agent roles
	already get this via PERM_ROLE.)"""
	for role in [GATE_ROLE, CD_ROLE]:
		if frappe.db.exists("Custom DocPerm", {"parent": DOMAIN_DOCTYPE, "role": role}):
			continue
		frappe.get_doc(
			{
				"doctype": "Custom DocPerm",
				"parent": DOMAIN_DOCTYPE,
				"parenttype": "DocType",
				"parentfield": "permissions",
				"role": role,
				"permlevel": 0,
				"read": 1,
				"write": 1,
			}
		).insert(ignore_permissions=True)
	frappe.clear_cache(doctype=DOMAIN_DOCTYPE)


def _ensure_bundle() -> None:
	"""The Domain Bundle manifest tying the work-item to its workflow."""
	if frappe.db.exists("Domain Bundle", BUNDLE_NAME):
		bundle = frappe.get_doc("Domain Bundle", BUNDLE_NAME)
	else:
		bundle = frappe.new_doc("Domain Bundle")
		bundle.bundle_name = BUNDLE_NAME
	bundle.description = "RandomPack brand identity pipeline (the first Design 75 domain)."
	bundle.domain_doctype = DOMAIN_DOCTYPE
	bundle.workflow_name = WORKFLOW_NAME
	bundle.version = "1.0"
	bundle.is_active = 1
	bundle.tags = "brand, randompack"
	bundle.save(ignore_permissions=True)


# --- helpers ----------------------------------------------------------------
def _append_missing(doc, table_field: str, key: str, values: list[str]) -> None:
	"""Append child rows for any `values` not already present (never duplicates)."""
	have = {row.get(key) for row in (doc.get(table_field) or [])}
	for value in values:
		if value not in have:
			doc.append(table_field, {key: value})


def _model_config() -> tuple[str | None, str | None]:
	"""Reuse whatever model the main 'Friday' profile runs on, so the specialists
	work wherever Friday works. Falls back to the first Active LLM Provider."""
	row = frappe.db.get_value(
		"Agent Profile", "Friday", ["model_provider", "model_name"], as_dict=True
	)
	if row and row.get("model_provider"):
		return row.model_provider, row.model_name
	provider = frappe.db.get_value("LLM Provider", {"is_active": 1}, "name")
	return provider, None
