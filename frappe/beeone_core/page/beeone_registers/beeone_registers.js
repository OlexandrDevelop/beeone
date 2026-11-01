// Platform Register Explorer: one place to open every readable register and its movements.
frappe.pages["beeone-registers"].on_page_load = function (wrapper) {
	new beeone.registers.Explorer(wrapper);
};

frappe.provide("beeone.registers");

beeone.registers.Explorer = class {
	constructor(wrapper) {
		this.page = frappe.ui.make_app_page({ parent: wrapper, title: __("Registers"), single_column: true });
		this.$body = $("<div class='beeone-register-explorer'></div>").appendTo(this.page.main);
		this.load();
	}

	load() {
		this.$body.html(`<div class="beeone-register-loading">${frappe.utils.escape_html(__("Loading registers…"))}</div>`);
		frappe.call({ method: "frappe.beeone.api.registers.catalog" }).then((r) => this.render(r.message || []));
	}

	render(registers) {
		const esc = (v) => frappe.utils.escape_html(String(v ?? ""));
		const kind = (value) => __(value).replace("Accumulation: ", "").replace("Information: ", "");
		if (!registers.length) {
			this.$body.html(`<div class="beeone-register-empty">${esc(__("No registers available"))}</div>`);
			return;
		}
		this.$body.html(
			`<div class="beeone-register-intro"><h2>${esc(__("Registers"))}</h2><p>${esc(__("Open a register to inspect its movements. Use filters and the seamless list scroll to explore large volumes."))}</p></div>` +
			`<div class="beeone-register-grid">${registers.map((r) => this.card(r, esc, kind)).join("")}</div>`
		);
		this.$body.on("click", "[data-register-open]", (event) => {
			frappe.set_route("List", $(event.currentTarget).data("register-open"));
		});
		this.$body.on("click", "[data-register-balance]", (event) =>
			beeone.registers.report($(event.currentTarget).data("register-balance"), "balance")
		);
		this.$body.on("click", "[data-register-turnover]", (event) =>
			beeone.registers.report($(event.currentTarget).data("register-turnover"), "turnover")
		);
	}

	card(register, esc, kind) {
		const columns = register.columns.slice(0, 5).map((c) => esc(c.label)).join(" · ");
		return `<article class="beeone-register-card"><div class="beeone-register-card-head"><div><h3>${esc(__(register.register))}</h3><span>${esc(kind(register.kind))}</span></div><span class="beeone-register-mark">${esc(register.doctype)}</span></div>` +
			`<p class="beeone-register-fields">${columns}</p><div class="beeone-register-actions"><button class="btn btn-primary btn-sm" data-register-open="${esc(register.doctype)}">${esc(__("Open movements"))}</button>` +
			(register.balance ? `<button class="btn btn-default btn-sm" data-register-balance="${esc(register.doctype)}">${esc(__("Balance"))}</button>` : "") +
			(register.turnover ? `<button class="btn btn-default btn-sm" data-register-turnover="${esc(register.doctype)}">${esc(__("Turnovers"))}</button>` : "") +
			`</div></article>`;
	}
};
