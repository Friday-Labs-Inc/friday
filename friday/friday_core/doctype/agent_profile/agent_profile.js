// Copyright (c) 2026, Friday Labs and contributors
// For license information, please see license.txt
//
// Agent Profile form (design 68).
//
// When the operator picks an Agent Role, show a recommended model tier next to
// the model picker (Heavy / Standard / Light). It's a hint only — never an
// enforcement (Q2). An orchestrator pinned to a Light model still saves; the
// hint just makes the trade-off visible.

const FRIDAY_ROLE_TIERS = {
	Orchestrator: {
		tier: "Heavy",
		hint: __(
			"Recommended: a heavy reasoning model (e.g. Opus, GPT-5, Sonnet) — orchestrators plan, delegate, and synthesise."
		),
	},
	Specialist: {
		tier: "Standard",
		hint: __(
			"Recommended: a standard model (e.g. Haiku, GPT-4o, Gemini Pro) — specialists go deep in one domain."
		),
	},
	Worker: {
		tier: "Light",
		hint: __(
			"Recommended: a light fast model (e.g. MiniMax, Haiku 3.5, Gemini Flash) — workers run narrow tasks in bulk."
		),
	},
};

frappe.ui.form.on("Agent Profile", {
	refresh: function (frm) {
		render_role_hint(frm);
	},
	agent_role: function (frm) {
		render_role_hint(frm);
	},
});

function render_role_hint(frm) {
	const role = frm.doc.agent_role;
	const meta = FRIDAY_ROLE_TIERS[role];
	if (!meta) {
		frm.set_df_property("model_provider", "description", "");
		return;
	}
	frm.set_df_property(
		"model_provider",
		"description",
		`<b>${meta.tier} tier</b> — ${meta.hint}`
	);
}
