// Copyright (c) 2026, Friday Labs and contributors
// For license information, please see license.txt
//
// MCP Server form (design 67). A "Sync Tools" button discovers the server's
// tools and writes them as governed mcp_<server>_* Skill rows. The synced
// skills then show up in the normal Agent Profile "Permitted Skills" picker —
// granting a tool to an agent stays an explicit operator opt-in.

frappe.ui.form.on("MCP Server", {
	refresh: function (frm) {
		if (frm.is_new()) {
			frm.dashboard.add_comment(
				__(
					"Save the server first, then click <b>Sync Tools</b> to import its tools as skills."
				),
				"yellow",
				true
			);
			return;
		}

		frm.add_custom_button(__("Sync Tools"), function () {
			frappe.call({
				method: "friday.friday_core.mcp.sync.sync_server",
				args: { server_name: frm.doc.name },
				freeze: true,
				freeze_message: __("Discovering tools from {0}…", [frm.doc.server_name]),
				callback: function (r) {
					const m = r && r.message;
					if (m && m.count != null) {
						frappe.show_alert({
							message: __(
								"Synced {0} tool(s) — find them in Agent Profile → Permitted Skills",
								[m.count]
							),
							indicator: "green",
						});
						frm.reload_doc();
					} else {
						frappe.msgprint(
							__("Sync returned no tools — check the Base URL and auth.")
						);
					}
				},
			});
		});

		if (frm.doc.last_sync_status) {
			const ok = frm.doc.last_sync_status.startsWith("ok");
			frm.dashboard.add_comment(
				__("Last sync: {0}", [frm.doc.last_sync_status]),
				ok ? "green" : "red",
				true
			);
		}
	},
});
