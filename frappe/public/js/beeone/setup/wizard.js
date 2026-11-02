// The page "Initial setup": the demo card and the setup wizard (steps come from the hook beeone_setup_steps).
frappe.provide("beeone.setup");

const esc = (v) => frappe.utils.escape_html(v == null ? "" : String(v));
const icon = (n, c) => beeone.ui.icon(n, c);
const call = (m, a) => beeone.setup.call(m, a);

beeone.setup.Page = class {
	constructor(page) {
		this.page = page;
		this.$body = $("<div class='bo-setup'></div>").appendTo(page.main);
		this.poll = null;
		beeone.setup.page = this;
		beeone.ui.inject_icons();
	}

	show(route) {
		this.stop_poll();
		if (route && route[1] === "wizard") this.wizard();
		else this.overview();
	}

	stop_poll() {
		clearInterval(this.poll);
		this.poll = null;
	}

	// ------------------------------------------------------------ overview: demo card and wizard card
	overview() {
		if (frappe.get_route()[1] === "wizard") return;
		this.$body.html(beeone.ui.skeleton_rows(3));
		Promise.all([call("demo_status"), call("get_wizard")]).then(([demo, wiz]) => {
			if (frappe.get_route()[1] === "wizard") return;
			this.render_overview(demo, wiz);
			if (demo.running) this.poll = this.poll || setInterval(() => this.overview(), 4000);
			else this.stop_poll();
		});
	}

	render_overview(demo, wiz) {
		const started = wiz.finished > 0;
		const wizard_action = wiz.done ? __("Open again") : started ? __("Continue") : __("Open");
		let demo_text = demo.running ? __("Demo data is being processed. Wait a few minutes.") : demo.loaded ? __("Demo data is loaded") : demo.allowed ? __("Sample records to look around") : demo.reason;
		if (demo.message && !demo.running) demo_text = demo.message;
		this.$body.html(
			`<div class="bo-setup-grid">` +
				`<section class="bo-card bo-setup-card"><div class="bo-card-body">${icon("package")}<h3>${esc(__("Demo data"))}</h3><p>${esc(demo_text)}</p>` +
				`<div class="bo-setup-actions">` +
				`<button type="button" class="bo-btn bo-btn--primary" data-a="load"${demo.allowed && !demo.running ? "" : " disabled"}>${esc(__("Fill with demo data"))}</button>` +
				`<button type="button" class="bo-btn" data-a="remove"${demo.loaded && !demo.running ? "" : " disabled"}>${esc(__("Remove demo data"))}</button>` +
				`</div></div></section>` +
				`<section class="bo-card bo-setup-card"><div class="bo-card-body">${icon("sliders")}<h3>${esc(__("Initial settings"))}</h3>` +
				`<p>${esc(wiz.done ? __("The initial settings are entered") : __("Step {0} of {1}", [wiz.finished, wiz.total]))}</p>` +
				`<div class="bo-setup-actions"><button type="button" class="bo-btn bo-btn--primary" data-a="wizard">${esc(wizard_action)}</button></div>` +
				`</div></section></div>`
		);
		this.$body.find("[data-a]").on("click", (e) => this.on_overview(e.currentTarget.dataset.a));
	}

	on_overview(act) {
		if (act === "wizard") return frappe.set_route("beeone-setup", "wizard");
		const load = act === "load";
		const dlg = beeone.ui.dialog({
			title: load ? __("Fill with demo data") : __("Remove demo data"),
			width: 460,
			html:
				`<div class="bo-dialog-head"><h3>${esc(load ? __("Fill with demo data") : __("Remove demo data"))}</h3></div>` +
				`<div class="bo-dialog-body"><p>${esc(load ? __("Sample records will be created. This takes a few minutes.") : __("Only the sample records are deleted. Your own data stays."))}</p></div>` +
				`<div class="bo-dialog-foot"><button type="button" class="bo-btn" data-close>${esc(__("Cancel"))}</button>` +
				`<button type="button" class="bo-btn bo-btn--primary" data-ok autofocus>${esc(load ? __("Fill with demo data") : __("Remove demo data"))}</button></div>`,
		});
		dlg.el.querySelector("[data-ok]").addEventListener("click", () => {
			dlg.close();
			call(load ? "load_demo" : "delete_demo").then(() => this.overview());
		});
	}

	// ------------------------------------------------------------ wizard
	wizard() {
		this.$body.html(beeone.ui.skeleton_rows(4));
		call("get_wizard").then((wiz) => {
			this.wiz = wiz;
			this.open_step(wiz.current);
		});
	}

	index_of(id) {
		return this.wiz.steps.findIndex((s) => s.id === id);
	}

	open_step(id) {
		call("get_step", { step_id: id }).then((step) => {
			this.step = step;
			this.wiz.current = id;
			this.render_step();
		});
	}

	render_step() {
		const wiz = this.wiz;
		const i = this.index_of(this.step.id);
		const last = i === wiz.steps.length - 1;
		const percent = Math.round((wiz.steps.filter((s) => s.done || s.skipped).length / Math.max(wiz.total, 1)) * 100);
		const list = wiz.steps
			.map(
				(s, n) =>
					`<li class="bo-setup-step${n === i ? " is-current" : ""}${s.done || s.skipped ? " is-done" : ""}">` +
					`<button type="button" data-step="${esc(s.id)}">${s.done ? icon("check") : `<span class="bo-setup-num">${n + 1}</span>`}${esc(s.title)}</button></li>`
			)
			.join("");
		this.$body.html(
			`<div class="bo-setup-wizard"><aside><ol class="bo-setup-steps">${list}</ol></aside>` +
				`<section class="bo-card"><div class="bo-card-body">` +
				`<div class="bo-setup-progress"><span>${esc(__("Step {0} of {1}", [i + 1, wiz.total]))}</span>` +
				`<div class="bo-setup-bar" role="progressbar" aria-valuenow="${percent}" aria-valuemin="0" aria-valuemax="100"><i style="width:${percent}%"></i></div></div>` +
				`<h3>${esc(this.step.title)}</h3><p class="bo-setup-desc">${esc(this.step.description)}</p>` +
				`<div class="bo-field-error bo-setup-error" hidden></div><div class="bo-setup-form"></div>` +
				`<div class="bo-setup-nav"><button type="button" class="bo-btn" data-nav="back"${i === 0 ? " disabled" : ""}>${icon("chev-l")}${esc(__("Back"))}</button><span class="bo-grow"></span>` +
				(this.step.optional ? `<button type="button" class="bo-btn bo-btn--ghost" data-nav="skip">${esc(__("Skip"))}</button>` : "") +
				`<button type="button" class="bo-btn bo-btn--primary" data-nav="next">${esc(last ? __("Save and finish") : __("Save and continue"))}</button></div>` +
				`</div></section></div>`
		);
		this.fg = new frappe.ui.FieldGroup({ fields: this.step.fields, body: this.$body.find(".bo-setup-form")[0] });
		this.fg.make();
		this.fg.set_values(this.step.values || {});
		this.$body.find("[data-step]").on("click", (e) => this.open_step(e.currentTarget.dataset.step));
		this.$body.find("[data-nav]").on("click", (e) => this.on_nav(e.currentTarget.dataset.nav));
	}

	show_errors(errors) {
		this.$body.find(".bo-setup-form .bo-field-error").remove();
		const banner = this.$body.find(".bo-setup-error")[0];
		banner.hidden = true;
		Object.entries(errors || {}).forEach(([name, text]) => {
			const field = name && this.fg.get_field(name);
			if (field) field.$wrapper.append(`<div class="bo-field-error">${esc(text)}</div>`);
			else {
				banner.textContent = text;
				banner.hidden = false;
			}
		});
	}

	on_nav(act) {
		const i = this.index_of(this.step.id);
		if (act === "back") return this.open_step(this.wiz.steps[i - 1].id);
		const buttons = this.$body.find("[data-nav]").prop("disabled", true);
		const done = (r) => this.after_save(r, i);
		const fail = () => buttons.prop("disabled", false);
		if (act === "skip") return call("skip_step", { step_id: this.step.id }).then(done, fail);
		call("save_step", { step_id: this.step.id, values: this.fg.get_values(true) || {} }).then((r) => {
			if (r.errors) {
				buttons.prop("disabled", false);
				return this.show_errors(r.errors);
			}
			done(r);
		}, fail);
	}

	after_save(result, i) {
		const last = i === this.wiz.steps.length - 1;
		if (result.next) return this.wizard_from(result.next);
		if (!last) return this.wizard_from(this.wiz.steps[i + 1].id);
		call("finish").then(
			() => {
				beeone.ui.toast({ title: __("The initial settings are entered") });
				frappe.set_route("beeone-setup");
			},
			() => this.wizard()
		);
	}

	wizard_from(id) {
		call("get_wizard").then((wiz) => {
			this.wiz = wiz;
			this.open_step(id);
		});
	}
};
