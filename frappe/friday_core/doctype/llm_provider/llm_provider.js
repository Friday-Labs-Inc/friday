// Copyright (c) 2026, Friday Labs and contributors
// For license information, please see license.txt
//
// LLM Provider Desk form script (design 63b — model picker UI).
//
// Adds a "Discover Models" button next to default_model. The button calls
// `llm.model_discovery.list_models` for the saved provider row and shows
// the live model list (or the curated fallback) in a click-to-fill picker.
//
// Why a button and not a Select: the model list is provider-specific AND
// changes over time. A static Select would drift; live discovery against
// the provider's own /v1/models keeps it current. The data layer landed
// in PR #89 (design 63); this is the visual binding that closes the loop.

frappe.ui.form.on("LLM Provider", {
	refresh: function (frm) {
		if (frm.is_new()) {
			frm.dashboard.add_comment(
				__(
					"Save the provider first, then click <b>Discover Models</b> to see its real model list."
				),
				"yellow",
				true
			);
			return;
		}

		frm.add_custom_button(__("Discover Models"), function () {
			frappe.call({
				method: "frappe.friday_core.llm.model_discovery.list_models",
				args: { provider_name: frm.doc.name },
				freeze: true,
				freeze_message: __("Asking {0}…", [frm.doc.provider_type || "the provider"]),
				callback: function (r) {
					if (!r.message) {
						frappe.msgprint(__("No response from model discovery."));
						return;
					}
					show_model_picker(frm, r.message);
				},
			});
		});

		// OAuth subscription login (design 63b-OAuth). Claude is the manual-paste
		// PKCE flow: open the URL, approve, paste the code#state back.
		frm.add_custom_button(
			__("Login with Claude"),
			function () {
				start_claude_login(frm);
			},
			__("OAuth Login")
		);

		frm.add_custom_button(
			__("Login with Codex"),
			function () {
				start_codex_login(frm);
			},
			__("OAuth Login")
		);

		// Show the current OAuth status when this is an OAuth provider.
		if (frm.doc.auth_mode === "oauth") {
			frappe.call({
				method: "frappe.friday_core.llm.oauth.endpoints.oauth_status",
				args: { provider_name: frm.doc.name },
				callback: function (r) {
					const s = r && r.message;
					if (!s) return;
					const msg = s.logged_in
						? __("OAuth: logged in ({0}), token valid until {1}.", [
								s.oauth_flavor || "?",
								s.expires_at || "?",
						  ])
						: __("OAuth provider — not logged in yet. Use OAuth Login.");
					frm.dashboard.add_comment(msg, s.logged_in ? "green" : "orange", true);
				},
			});
		}
	},
});

// Claude OAuth: ask the server for the authorize URL, open it, then collect the
// pasted code#state and exchange it. No callback route — Anthropic shows the
// code on its own page and the operator pastes it here.
function start_claude_login(frm) {
	frappe.call({
		method: "frappe.friday_core.llm.oauth.endpoints.start_claude_login",
		args: { provider_name: frm.doc.name },
		freeze: true,
		freeze_message: __("Preparing Claude login…"),
		callback: function (r) {
			const url = r && r.message && r.message.authorize_url;
			if (!url) {
				frappe.msgprint(__("Could not start the Claude login."));
				return;
			}
			window.open(url, "_blank");
			const d = new frappe.ui.Dialog({
				title: __("Log in with Claude"),
				fields: [
					{
						fieldtype: "HTML",
						options: `<p>${__(
							"A Claude login tab was opened. Approve access, then copy the code shown (it looks like <code>code#state</code>) and paste it below."
						)}</p>`,
					},
					{
						fieldtype: "Data",
						fieldname: "pasted",
						label: __("Pasted code"),
						reqd: 1,
					},
				],
				primary_action_label: __("Complete login"),
				primary_action: function (values) {
					frappe.call({
						method: "frappe.friday_core.llm.oauth.endpoints.complete_claude_login",
						args: { provider_name: frm.doc.name, pasted: values.pasted },
						freeze: true,
						freeze_message: __("Exchanging code…"),
						callback: function (res) {
							const s = res && res.message;
							if (s && s.logged_in) {
								frappe.show_alert({
									message: __("Logged in with Claude"),
									indicator: "green",
								});
								d.hide();
								frm.reload_doc();
							} else {
								frappe.msgprint(
									__("Login did not complete — check the pasted code.")
								);
							}
						},
					});
				},
			});
			d.show();
		},
	});
}

// Codex OAuth: device-code. Show the user code + verification link, then poll
// the server (one poll per call) until the operator approves in the browser.
function start_codex_login(frm) {
	frappe.call({
		method: "frappe.friday_core.llm.oauth.endpoints.start_codex_login",
		args: { provider_name: frm.doc.name },
		freeze: true,
		freeze_message: __("Preparing Codex login…"),
		callback: function (r) {
			const m = r && r.message;
			if (!m || !m.user_code) {
				frappe.msgprint(__("Could not start the Codex login."));
				return;
			}
			window.open(m.verification_url, "_blank");
			const d = new frappe.ui.Dialog({
				title: __("Log in with Codex"),
				fields: [
					{
						fieldtype: "HTML",
						options: `<p>${__("In the opened tab, enter this code:")}</p>
							<h3 style="font-family:var(--font-stack-monospace,monospace);letter-spacing:2px;">${frappe.utils.escape_html(
								m.user_code
							)}</h3>
							<p class="text-muted">${__("Waiting for approval…")}</p>`,
					},
				],
			});
			d.show();

			const interval_ms = Math.max(3, m.interval || 5) * 1000;
			const poll = () => {
				frappe.call({
					method: "frappe.friday_core.llm.oauth.endpoints.poll_codex_login",
					args: { provider_name: frm.doc.name },
					callback: function (res) {
						const s = res && res.message;
						if (s && s.logged_in) {
							frappe.show_alert({
								message: __("Logged in with Codex"),
								indicator: "green",
							});
							d.hide();
							frm.reload_doc();
						} else if (s && s.pending && d.$wrapper.is(":visible")) {
							setTimeout(poll, interval_ms);
						}
					},
					error: function () {
						d.hide();
						frappe.msgprint(__("Codex login failed — please try again."));
					},
				});
			};
			setTimeout(poll, interval_ms);
		},
	});
}

// Render the live (or catalog) list as a click-to-fill dialog. Clicking a
// row writes it into default_model and closes — no manual typing of model
// strings, which was the user's exact pain ("can't see Minimax's models").
function show_model_picker(frm, result) {
	const models = result.models || [];
	const source = result.source || "catalog";
	const error = result.error || "";

	if (!models.length) {
		frappe.msgprint({
			title: __("No models found"),
			indicator: "red",
			message: error || __("The provider returned an empty list."),
		});
		return;
	}

	// Highlight whether this is the live list from the provider's own API
	// or the curated fallback (e.g. the key isn't set yet). Operator
	// confidence depends on knowing which.
	const source_label =
		source === "live"
			? `<span style="color:#2d8a4f;font-weight:600;">● live from ${frappe.utils.escape_html(
					result.provider_type || ""
			  )} /v1/models</span>`
			: `<span style="color:#b06900;font-weight:600;">● built-in catalog (fallback)</span>`;

	const subtitle = error
		? `<div style="margin-top:4px;color:#888;font-size:12px;">${frappe.utils.escape_html(
				error
		  )}</div>`
		: "";

	const rows = models
		.map(
			(m) => `
		<button type="button" class="friday-model-pick"
			data-model="${frappe.utils.escape_html(m)}"
			style="display:block;width:100%;text-align:left;padding:6px 10px;margin:2px 0;
			       border:1px solid #ddd;background:#fafafa;border-radius:4px;cursor:pointer;
			       font-family:var(--font-stack-monospace,monospace);">
			${frappe.utils.escape_html(m)}
		</button>`
		)
		.join("");

	const d = new frappe.ui.Dialog({
		title: __("Available models for {0}", [frm.doc.name]),
		fields: [
			{
				fieldtype: "HTML",
				fieldname: "picker_body",
				options: `
					<div style="margin-bottom:8px;">${source_label}${subtitle}</div>
					<div style="max-height:50vh;overflow-y:auto;">${rows}</div>
					<div style="margin-top:10px;color:#888;font-size:12px;">
						${__("Click a model to set it as <b>Default Model</b> and save.")}
					</div>
				`,
			},
		],
	});

	d.show();

	d.$wrapper.on("click", ".friday-model-pick", function () {
		const picked = $(this).data("model");
		frm.set_value("default_model", picked);
		d.hide();
		frm.save().then(() => {
			frappe.show_alert({
				message: __("Default model set to {0}", [picked]),
				indicator: "green",
			});
		});
	});
}
