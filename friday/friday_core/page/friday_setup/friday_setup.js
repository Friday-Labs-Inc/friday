// Copyright (c) 2026, Friday Labs and contributors
// For license information, please see license.txt
//
// The Friday Setup wizard (design 64) — Hermes' `hermes setup`, Desk-native.
//
// A re-runnable, state-aware 5-step stepper that DOES the work:
//   1. Provider & model   2. Agent   3. Surfaces (Raven)   4. Tools   5. Verify
//
// It renders entirely from one `setup_status()` read, so every step shows what
// is already configured (regardless of whether it was done here, by the CLI, or
// by hand) and lets you fill the gap. Each step calls a System-Manager-gated
// endpoint that delegates to the same plumbing the CLI uses. The final step
// runs a LIVE provider probe + pipeline health before declaring Friday ready —
// so "complete" means "actually works".

frappe.pages["friday-setup"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Friday Setup"),
		single_column: true,
	});
	wrapper.friday_setup = new FridaySetup(page);
};

frappe.pages["friday-setup"].on_page_show = function (wrapper) {
	if (wrapper.friday_setup) wrapper.friday_setup.refresh();
};

const B = "friday.friday_core.setup.wizard"; // endpoint namespace

class FridaySetup {
	constructor(page) {
		this.page = page;
		this.status = null;
		this.$body = $('<div class="friday-setup"></div>').appendTo(page.body);
		this.refresh();
	}

	call(method, args) {
		return new Promise((resolve) => {
			frappe.call({
				method: `${B}.${method}`,
				args: args || {},
				freeze: true,
				callback: (r) => resolve(r ? r.message : null),
			});
		});
	}

	async refresh() {
		this.status = await this.call("setup_status");
		this.render();
	}

	render() {
		const s = this.status || {};
		const done = (ok) =>
			ok
				? '<span class="fs-badge fs-ok">✓ done</span>'
				: '<span class="fs-badge fs-todo">○ to do</span>';

		this.$body.empty();

		if (s.setup_complete) {
			this.$body.append(
				`<div class="fs-banner fs-ok-banner">✅ ${__(
					"Friday is set up and verified."
				)} ${__("You can re-run any step below to change configuration.")}</div>`
			);
		} else {
			this.$body.append(
				`<div class="fs-banner">${__(
					"Walk these five steps to get Friday running. Each is re-runnable; green steps are already configured."
				)}</div>`
			);
		}

		// ---- Step 1: Provider & model ----
		const p = s.provider || {};
		this._step(1, __("Provider & Model"), done(p.configured), (body) => {
			body.html(`
				<div class="fs-grid">
					<label>${__(
						"Provider name"
					)}<input class="form-control" data-f="provider_name" value="${frappe.utils.escape_html(
				(p.providers && p.providers[0]) || ""
			)}"></label>
					<label>${__("Type")}
						<select class="form-control" data-f="provider_type">
							${["minimax", "openai", "anthropic", "openrouter"]
								.map((t) => `<option value="${t}">${t}</option>`)
								.join("")}
						</select>
					</label>
					<label>${__(
						"API key"
					)}<input type="password" class="form-control" data-f="api_key" placeholder="sk-…"></label>
					<label>${__("Base URL (optional)")}<input class="form-control" data-f="base_url"></label>
					<label>${__("Default model")}<input class="form-control" data-f="default_model" placeholder="${__(
				"pick via Discover Models"
			)}"></label>
					<label>${__(
						"Input $/M (optional)"
					)}<input class="form-control" data-f="input_cost_per_million"></label>
					<label>${__(
						"Output $/M (optional)"
					)}<input class="form-control" data-f="output_cost_per_million"></label>
				</div>
				<div class="fs-actions">
					<button class="btn btn-default btn-sm" data-act="discover">${__("Discover Models")}</button>
					<button class="btn btn-primary btn-sm" data-act="save-provider">${__("Save provider")}</button>
				</div>
				<div class="fs-note">${
					p.default_provider
						? __("Default provider: {0}", [p.default_provider])
						: __("No default provider set yet.")
				}<br><span class="fs-muted">${__(
				"OAuth login — coming in a later release; use an API key for now."
			)}</span></div>
				<div class="fs-models"></div>`);

			body.find('[data-act="discover"]').on("click", () => this.discover(body));
			body.find('[data-act="save-provider"]').on("click", () => this.saveProvider(body));
		});

		// ---- Step 2: Agent ----
		const a = s.agent || {};
		this._step(2, __("Agent"), done(a.configured && a.active), (body) => {
			body.html(`
				<div class="fs-grid">
					<label>${__(
						"Profile name"
					)}<input class="form-control" data-f="profile_name" value="${frappe.utils.escape_html(
				a.profile || "Friday"
			)}"></label>
					<label>${__(
						"Provider"
					)}<input class="form-control" data-f="provider_name" value="${frappe.utils.escape_html(
				p.default_provider || (p.providers && p.providers[0]) || ""
			)}"></label>
					<label>${__("Model (optional)")}<input class="form-control" data-f="model_name"></label>
				</div>
				<label class="fs-block">${__("System prompt (optional — a default 'soul' is seeded if blank)")}
					<textarea class="form-control" rows="3" data-f="system_prompt"></textarea></label>
				<div class="fs-actions">
					<button class="btn btn-primary btn-sm" data-act="save-agent">${__("Save agent")}</button>
				</div>`);
			body.find('[data-act="save-agent"]').on("click", () => this.saveAgent(body));
		});

		// ---- Step 3: Surfaces ----
		const su = s.surfaces || {};
		this._step(3, __("Surfaces — War Room"), done(su.war_room), (body) => {
			const txt = !su.raven_installed
				? __(
						"Raven is not installed on this site — install it to enable the War Room, then re-run."
				  )
				: su.war_room
				? __("The FRIDAY_WAR_ROOM channel exists.")
				: __("Raven is installed; provision the War Room channel + Friday bot.");
			body.html(`<div class="fs-note">${txt}</div>
				<div class="fs-actions">
					<button class="btn btn-primary btn-sm" data-act="surfaces" ${
						su.raven_installed ? "" : "disabled"
					}>${__("Provision War Room")}</button>
				</div>`);
			body.find('[data-act="surfaces"]').on("click", async () => {
				await this.call("provision_surfaces");
				this.refresh();
			});
		});

		// ---- Step 4: Tools ----
		const t = s.tools || {};
		this._step(4, __("Tools"), done(t.read && t.files), (body) => {
			body.html(`<div class="fs-note">${__(
				"Provision the agent's read tools (read-record, list-records) and file tools (attach-deliverable, …)."
			)}</div>
				<div class="fs-actions">
					<button class="btn btn-primary btn-sm" data-act="tools">${__("Provision tools")}</button>
				</div>`);
			body.find('[data-act="tools"]').on("click", async () => {
				await this.call("provision_tools");
				this.refresh();
			});
		});

		// ---- Step 5: Verify ----
		const h = s.health || {};
		this._step(5, __("Verify & Finish"), done(s.setup_complete), (body) => {
			const worker = h.friday_worker
				? `<span class="fs-ok">✓ ${__("friday worker up")}</span>`
				: `<span class="fs-todo">✗ ${__("friday worker absent")} — ${__(
						"run: bench worker --queue friday"
				  )}</span>`;
			body.html(`<div class="fs-note">${__(
				"Runs a live provider probe and a pipeline health check, then marks setup complete."
			)}<br>${__("Health verdict")}: <b>${frappe.utils.escape_html(
				h.verdict || "?"
			)}</b> · ${worker}</div>
				<div class="fs-actions">
					<button class="btn btn-primary btn-sm" data-act="verify">${__("Verify & complete")}</button>
				</div>
				<div class="fs-verify-result"></div>`);
			body.find('[data-act="verify"]').on("click", () => this.verify(body));
		});
	}

	_step(n, title, badge, build) {
		const card = $(`
			<div class="fs-step">
				<div class="fs-step-head"><span class="fs-step-n">${n}</span>
					<span class="fs-step-title">${title}</span> ${badge}</div>
				<div class="fs-step-body"></div>
			</div>`);
		build(card.find(".fs-step-body"));
		this.$body.append(card);
	}

	_collect(body) {
		const out = {};
		body.find("[data-f]").each(function () {
			const v = $(this).val();
			if (v !== "" && v != null) out[$(this).data("f")] = v;
		});
		return out;
	}

	async discover(body) {
		const f = this._collect(body);
		if (!f.provider_name) {
			frappe.msgprint(
				__("Save the provider first (it needs the name + key), then Discover Models.")
			);
			return;
		}
		const models = await new Promise((resolve) => {
			frappe.call({
				method: "friday.friday_core.llm.model_discovery.list_models",
				args: { provider_name: f.provider_name },
				callback: (x) => resolve(x ? x.message : null),
			});
		});
		const box = body.find(".fs-models");
		if (!models || !(models.models || []).length) {
			box.html(
				`<div class="fs-todo">${__("No models returned. Check the key/base URL.")}</div>`
			);
			return;
		}
		const src =
			models.source === "live"
				? `<span class="fs-ok">● ${__("live")}</span>`
				: `<span class="fs-todo">● ${__("catalog (key not verified)")}</span>`;
		box.html(
			`<div class="fs-note">${src}</div>` +
				models.models
					.map(
						(m) =>
							`<button class="btn btn-xs btn-default fs-model" data-m="${frappe.utils.escape_html(
								m
							)}">${frappe.utils.escape_html(m)}</button>`
					)
					.join(" ")
		);
		box.find(".fs-model").on("click", function () {
			body.find('[data-f="default_model"]').val($(this).data("m"));
		});
	}

	async saveProvider(body) {
		const f = this._collect(body);
		if (!f.provider_name || !f.api_key) {
			frappe.msgprint(__("Provider name and API key are required."));
			return;
		}
		f.make_default = 1;
		await this.call("save_provider", f);
		frappe.show_alert({ message: __("Provider saved"), indicator: "green" });
		this.refresh();
	}

	async saveAgent(body) {
		const f = this._collect(body);
		if (!f.provider_name) {
			frappe.msgprint(__("Choose a provider for the agent."));
			return;
		}
		await this.call("save_agent", f);
		frappe.show_alert({ message: __("Agent saved"), indicator: "green" });
		this.refresh();
	}

	async verify(body) {
		const r = await this.call("verify_and_complete");
		const box = body.find(".fs-verify-result");
		if (r && r.ready) {
			box.html(`<div class="fs-ok-banner">✅ ${__("Verified — Friday is ready.")}</div>`);
			this.refresh();
		} else {
			const why =
				r && r.provider_source !== "live"
					? __("Provider not verified live (source: {0}). Check the API key.", [
							(r && r.provider_source) || "?",
					  ])
					: __("Pipeline health is down — start the friday worker / scheduler.");
			box.html(`<div class="fs-todo">⚠ ${frappe.utils.escape_html(why)}</div>`);
		}
	}
}
