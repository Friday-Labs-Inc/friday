// Copyright (c) 2026, Friday Labs and contributors
// For license information, please see license.txt
//
// The Studio Workspace — "The Bench" (design 96, Pillar 3).
//
// The human Creative Director's craft station. One page that answers "what is
// waiting on ME?" — every Brand Brief parked at a CD state as a queue card,
// the production package rendered for review (refine rounds side by side),
// and the three verbs as one-click actions:
//
//   CD Creative      → Creative Ready
//   CD Internal Gate → Approve Production / Request Refinement (notes required)
//
// Refinement notes are the design-95 apprenticeship training signal: the API
// writes them to the project as cd-refinement-notes-r<N>.md before the
// transition fires, so the production agent reads the correction the moment
// its phase starts.
//
// Poll-refresh only (60s + after every action) — realtime badges are the
// deferred follow-up per the design's Q4 lock. Same page pattern as
// project_console: make_app_page + whitelisted snapshot endpoints.

frappe.pages["studio"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Studio"),
		single_column: true,
	});

	const bench = new StudioBench(page);
	wrapper.studio_bench = bench;
};

frappe.pages["studio"].on_page_show = function (wrapper) {
	if (wrapper.studio_bench) {
		wrapper.studio_bench.refresh();
	}
};

class StudioBench {
	constructor(page) {
		this.page = page;
		this.POLL_MS = 60000;
		this._build_layout();
		this._start_poll();
		this.refresh();
	}

	_build_layout() {
		this.$body = $(`
			<div class="friday-studio">
				<div class="fs-intro">${__("Work waiting on the Creative Director")}</div>
				<div class="fs-queue" data-zone="queue"></div>
				<div class="fs-ledger-title">${__("Apprentice ledger")}</div>
				<div class="fs-ledger" data-zone="ledger"></div>
			</div>
		`).appendTo(this.page.body);
		this.$queue = this.$body.find('[data-zone="queue"]');
		this.$ledger = this.$body.find('[data-zone="ledger"]');
	}

	refresh() {
		frappe.call({
			method: "frappe.friday_core.console.studio_api.studio_snapshot",
			callback: (r) => {
				if (!r || !r.message) return;
				this._render(r.message);
			},
		});
		frappe.call({
			method: "frappe.friday_core.console.studio_api.apprentice_ledger",
			callback: (r) => {
				if (!r || !r.message) return;
				this._render_ledger(r.message);
			},
		});
	}

	_render_ledger(snap) {
		const esc = frappe.utils.escape_html;
		if (snap.error || !snap.ledger) {
			this.$ledger.html(
				`<div class="fs-empty fs-error">${__("Ledger error")}: ${esc(snap.error || "no data")}</div>`
			);
			return;
		}
		const L = snap.ledger;
		const rate =
			L.gates.approve_rate === null ? __("no gates yet") : `${L.gates.approve_rate}%`;
		const drafting = L.flags.may_draft_directions;
		const stat = (label, value) => `
			<div class="fs-stat">
				<div class="fs-stat-value">${value}</div>
				<div class="fs-stat-label">${label}</div>
			</div>`;
		const dims = Object.entries(L.dimensions || {})
			.map(([d, n]) => `${esc(d)} <b>${n}</b>`)
			.join(" · ");
		const briefs = (L.briefs || [])
			.map(
				(b) => `
			<div class="fs-brief-row">
				<span>${esc(b.business_name || b.brief)}</span>
				<span>${__("{0} refinement(s)", [b.refinements])} — ${
					b.approved ? __("approved") : __("in refinement")
				}</span>
			</div>`
			)
			.join("");

		this.$ledger.html(`
			<div class="fs-stats">
				${stat(__("lessons stored"), L.lessons_stored)}
				${stat(__("observations"), L.observations.completed)}
				${stat(__("gate approve rate"), rate)}
				${stat(__("productions"), L.productions_attempted)}
				${stat(
					__("drafting"),
					drafting ? `<span class="fs-flag-on">${__("ON")}</span>` : __("off")
				)}
			</div>
			${dims ? `<div class="fs-dims">${__("evidence by dimension")}: ${dims}</div>` : ""}
			${briefs ? `<div class="fs-briefs">${briefs}</div>` : ""}
			<div class="fs-ledger-note">${__(
				"Graduation is an operator decision — the flag lives on the Creative Director agent profile."
			)}</div>
		`);
	}

	_render(snap) {
		if (snap.error) {
			this.$queue.html(
				`<div class="fs-empty fs-error">${__("Studio error")}: ${frappe.utils.escape_html(snap.error)}</div>`
			);
			return;
		}
		const queue = snap.queue || [];
		if (!queue.length) {
			this.$queue.html(`<div class="fs-empty">${__("The bench is clear. Nothing waits on you.")}</div>`);
			return;
		}
		this.$queue.empty();
		queue.forEach((b) => this.$queue.append(this._card(b)));
	}

	_card(b) {
		const esc = frappe.utils.escape_html;
		const waiting =
			b.days_waiting > 0
				? __("waiting {0} day(s)", [b.days_waiting])
				: __("arrived today");
		const round = b.refine_round ? ` · ${__("round {0}", [b.refine_round + 1])}` : "";
		const state_cls = b.workflow_state === "CD Internal Gate" ? "fs-state-gate" : "fs-state-creative";

		const $card = $(`
			<div class="fs-card">
				<div class="fs-card-top">
					<span class="fs-brand">${esc(b.business_name || b.name)}</span>
					<span class="fs-state ${state_cls}">${__(b.workflow_state)}</span>
				</div>
				<div class="fs-card-meta">
					<span>${waiting}${round}</span>
					<a class="fs-brief-link">${esc(b.name)}</a>
				</div>
				<div class="fs-notes-wrap" hidden>
					<textarea class="fs-notes" rows="4"
						placeholder="${__("What must change? The production agent applies these corrections verbatim — and learns from them.")}"></textarea>
				</div>
				<div class="fs-card-actions"></div>
			</div>
		`);

		$card.find(".fs-brief-link").on("click", () => frappe.set_route("Form", "Brand Brief", b.name));

		const $actions = $card.find(".fs-card-actions");

		// The review material: only meaningful once a package exists.
		if (b.package_count > 0) {
			$(`<button class="btn btn-sm fs-btn fs-btn-review">${__("Review package")}</button>`)
				.on("click", () => this._open_preview(b))
				.appendTo($actions);
		}

		(b.actions || []).forEach((action) => {
			const primary = action !== "Request Refinement";
			const $btn = $(
				`<button class="btn btn-sm fs-btn ${primary ? "fs-btn-primary" : "fs-btn-refine"}">${__(action)}</button>`
			);
			$btn.on("click", () => {
				if (action === "Request Refinement") {
					const $wrap = $card.find(".fs-notes-wrap");
					if ($wrap.attr("hidden") !== undefined) {
						// First click reveals the notes box; second click submits.
						$wrap.removeAttr("hidden");
						$card.find(".fs-notes").trigger("focus");
						return;
					}
					const notes = ($card.find(".fs-notes").val() || "").trim();
					if (!notes) {
						frappe.show_alert({
							message: __("Refinement needs notes — say what must change."),
							indicator: "orange",
						});
						return;
					}
					this._act(b, action, notes, $btn);
					return;
				}
				this._act(b, action, null, $btn);
			});
			$btn.appendTo($actions);
		});

		return $card;
	}

	_act(b, action, notes, $btn) {
		$btn.prop("disabled", true);
		frappe.call({
			method: "frappe.friday_core.console.studio_api.studio_action",
			args: { brief: b.name, action: action, notes: notes },
			callback: (r) => {
				const m = (r && r.message) || {};
				frappe.show_alert({
					message: __("{0} → {1}", [
						frappe.utils.escape_html(b.business_name || b.name),
						frappe.utils.escape_html(m.new_state || action),
					]),
					indicator: "green",
				});
				this.refresh();
			},
			error: () => $btn.prop("disabled", false),
		});
	}

	_open_preview(b) {
		frappe.call({
			method: "frappe.friday_core.console.studio_api.package_preview",
			args: { brief: b.name },
			callback: (r) => {
				const versions = ((r && r.message) || {}).versions || [];
				if (!versions.length) {
					frappe.show_alert({ message: __("No production package on the project yet."), indicator: "orange" });
					return;
				}
				const esc = frappe.utils.escape_html;
				const body = versions
					.map(
						(v, i) => `
					<details class="fs-version" ${i === 0 ? "open" : ""}>
						<summary>${esc(v.file_name)} <span class="fs-version-when">${comment_when(v.creation)}</span>
							${i === 0 ? `<span class="fs-version-latest">${__("latest")}</span>` : ""}</summary>
						<div class="fs-version-body">${v.html}</div>
					</details>`
					)
					.join("");
				const d = new frappe.ui.Dialog({
					title: __("{0} — production package", [b.business_name || b.name]),
					size: "extra-large",
				});
				$(d.body).addClass("fs-preview").html(body);
				d.show();
			},
		});
	}

	_start_poll() {
		this._poll = setInterval(() => this.refresh(), this.POLL_MS);
		$(this.page.wrapper).on("remove", () => clearInterval(this._poll));
	}
}
