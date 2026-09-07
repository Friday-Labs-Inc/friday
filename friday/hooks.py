"""Friday — a governed agent kernel for Frappe.

Agents act as THEMSELVES: each Agent Profile has its own Frappe User, its roles
are its job description, every skill call is permission-checked before it runs
and written to an immutable Execution Log after. Long work runs on a durable
task pipeline that survives restarts.

This file is the whole seam between Friday and Frappe. Everything Friday does
is registered here as an ordinary app hook — there is no patched framework.
"""

# Upstream Frappe fixes Friday still carries (currently one). hooks.py is
# imported early in every request and job, which makes it the reliable place to
# apply them. See friday_core/compat.py for the audited list and the rationale.
from friday.friday_core import compat as _compat

_compat.apply()

app_name = "friday"
app_title = "Friday"
app_publisher = "Friday Labs"
app_description = "A governed agent kernel for Frappe — permission-checked, audited, sandboxed AI agents."
app_email = "hello@fridaylabs.in"
app_license = "gpl-3.0"

# Raven is Friday's chat front door — the bot you DM, per-project channels, the
# war room (design 58). Not an optional surface: the platform assumes it.
required_apps = ["frappe", "raven"]

# ---------------------------------------------------------------------------
# Document events
# ---------------------------------------------------------------------------
doc_events = {
	"*": {
		# Design 75 — the generic workflow interpreter. Runs on every save but
		# returns immediately unless an active Domain Bundle governs the doctype
		# (cached lookup), so a domain app adds a pipeline as DATA rather than by
		# registering its DocType in a hooks file.
		"on_update": "friday.friday_core.engine.workflow_engine.on_work_item_update",
	},
	"Agent Profile": {
		"after_insert": "friday.friday_core.identity.agent_identity.on_agent_profile_after_insert",
		"on_update": [
			"friday.friday_core.permissions.cache.invalidate_for_profile",
			"friday.friday_core.skills.loader.invalidate_for_profile",
		],
	},
	"Role": {
		"on_update": [
			"friday.friday_core.permissions.cache.invalidate_all",
			"friday.friday_core.skills.loader.invalidate_all",
		],
	},
	"Skill": {
		"on_update": "friday.friday_core.skills.loader.invalidate_for_skill",
	},
	# Design 73 — each project gets a dedicated Raven conversation channel,
	# provisioned on creation and archived when the project closes. Both handlers
	# are savepoint-guarded so a Raven hiccup never blocks a Project save.
	"Agent Project": {
		"after_insert": "friday.friday_core.conversation.project_channel.on_project_after_insert",
		"on_update": [
			"friday.friday_core.conversation.project_channel.on_project_update",
			# Design 73 slice 5 — assemble the deliverable package on completion.
			"friday.friday_core.deliverables.materialize.on_project_doc_update",
		],
	},
	"Chat Message": {
		# The gateway chokepoint — every inbound message from every surface
		# (CLI, Slack, Raven, A2A) passes through here. Design 47.
		"after_insert": [
			"friday.friday_core.gateway.service.handle_inbound",
			"friday.friday_core.surfaces.raven_adapter.handle_outbound_to_raven",
			"friday.friday_core.surfaces.slack_adapter.handle_outbound_to_slack",
		],
	},
	"Raven Message": {
		# Design 58 — a human DM / @mention becomes an inbound Chat Message.
		"after_insert": "friday.friday_core.surfaces.raven_adapter.handle_raven_message",
	},
	"Agent Task": {
		# Order matters: on_state_change settles the row (dispatchable, timestamps,
		# executing_token), then advance enqueues the work-item's next phase after
		# commit.
		"on_update": [
			"friday.friday_core.tasks.workflow.on_state_change",
			"friday.friday_core.engine.advance.on_task_update",
		],
	},
}

# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------
scheduler_events = {
	"cron": {
		# Every 60s — the durable pipeline's heartbeat. The dispatcher moves
		# Pending → Assigned; the reconciler heals every other seam (lost
		# enqueues, stale executors, transient blocks, stuck connector events);
		# the cron scheduler fires due Cron Jobs. State is the source of truth,
		# the scheduler is the heartbeat, events are an optimisation.
		"*/1 * * * *": [
			"friday.friday_core.tasks.dispatcher.tick",
			"friday.friday_core.tasks.reconciler.tick",
			"friday.friday_core.cron.scheduler.tick",
		],
		# Design 63b — backstop refresh of expiring provider OAuth tokens, so a
		# long-idle login stays warm and a broken refresh surfaces before an agent
		# needs it. On-use refresh is the primary path.
		"*/30 * * * *": [
			"friday.friday_core.llm.oauth_token_refresh.tick",
		],
		# Design 67 — daily re-sync of every enabled MCP server's tools into Skill
		# rows. Failure-isolated per server.
		"0 3 * * *": [
			"friday.friday_core.mcp.sync.sync_all_due",
		],
	},
	# Design 47 §4 Q5 — sweep inbound Chat Messages whose worker died before
	# writing an outbound row. No-op on pure-sync deployments.
	"all": [
		"friday.friday_core.gateway.recovery.sweep_orphans",
	],
	# Design 72 — Dispatcher Event 30-day retention sweep.
	"daily": [
		"friday.friday_core.observability.retention.purge_old_events",
	],
}

# ---------------------------------------------------------------------------
# Provisioning — re-applied idempotently on every migrate, so a deployed site
# never drifts from what this repo says it is.
# ---------------------------------------------------------------------------
after_migrate = [
	# Settings + schema
	"friday.friday_core.llm.after_migrate.ensure_agent_settings",
	# Postgres-only, best-effort: FTS + pgvector for memory recall. Absent them,
	# recall degrades to recency (no regression).
	"friday.friday_core.llm.after_migrate.ensure_memory_search_schema",
	"friday.friday_core.llm.after_migrate.ensure_memory_embedding_schema",
	"friday.friday_core.llm.after_migrate.ensure_chatmessage_search_schema",
	# Register the dedicated `friday` queue so enqueues don't die on an unknown
	# queue name. (Starting the WORKER is an operator step — see the runbook.)
	"friday.friday_core.health.after_migrate.register_friday_queue",
	"friday.friday_core.tasks.runner.register_task_runner",
	# Identity: a no-login Frappe User per Agent Profile, so an agent is a
	# first-class, assignable, @-mentionable actor.
	"friday.friday_core.identity.agent_identity.provision_all_agent_users",
	# Desk surfaces
	"friday.friday_core.console.provision_console.provision_console",
	# Roles
	"friday.friday_core.gateway.after_migrate.ensure_command_roles",
	"friday.friday_core.cron.after_migrate.ensure_cron_role",
	# Skill definitions — the #19 class-killer: every bootstrap's definition is
	# refreshed from code on every migrate, so a deployed skill never drifts.
	"friday.friday_core.skills.bootstrap_memory.ensure_memory_provisioned",
	"friday.friday_core.skills.bootstrap_registry.ensure_all_skill_definitions",
	"friday.friday_core.skills.bootstrap_cron.provision",
	"friday.friday_core.skills.bootstrap_session_search.provision",
	"friday.friday_core.skills.bootstrap_project.provision_if_ready",
	# Surfaces + the customer-facing file boundary
	"friday.friday_core.surfaces.bootstrap_slack.provision",
	"friday.friday_core.deliverables.materialize.ensure_customer_facing_field",
]

# ---------------------------------------------------------------------------
# Friday kernel seams — how a DOMAIN app plugs in without touching this kernel.
# Any installed app may extend each list. See design 75 and 81.
# ---------------------------------------------------------------------------

# Modules whose import registers skill handlers (friday_core/skills/registry.py).
friday_skill_handlers = [
	"friday.friday_core.skills.handlers_cron",
	"friday.friday_core.skills.handlers_delegate",
	"friday.friday_core.skills.handlers_deliverables",
	"friday.friday_core.skills.handlers_engine",
	"friday.friday_core.skills.handlers_files",
	"friday.friday_core.skills.handlers_memory",
	"friday.friday_core.skills.handlers_project",
	"friday.friday_core.skills.handlers_propose_skill",
	"friday.friday_core.skills.handlers_read",
	"friday.friday_core.skills.handlers_session_search",
	"friday.friday_core.skills.handlers_visual",
]

# `ensure_definitions()` callables refreshed on every migrate.
friday_skill_definitions = []

# Called as fn(doc, state) after every Task transition.
friday_task_transition_hooks = []

# Dotted paths to {"@PREFIX-": (doctype, content_fields)} dicts, merged into the
# @-reference registry.
friday_reference_registry = []
