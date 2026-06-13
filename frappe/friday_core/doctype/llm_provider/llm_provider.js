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
	},
});

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
