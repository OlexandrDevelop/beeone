// Movement viewer of documents and the read-only register lists (Balance and Turnover commands).
// Country neutral: every text goes through __(), the translations come from the apps.

frappe.provide("beeone.registers");

const esc = (text) => frappe.utils.escape_html(String(text ?? ""));
const API = "frappe.beeone.api.registers.";
const NUMERIC = ["Currency", "Float", "Int", "Long Int", "Percent"];

// Only numbers, dates and times go through frappe.format (it returns markup for them).
// Every other value is text of a register row and is escaped, so it can never become HTML.
const FORMATTED = [...NUMERIC, "Date", "Datetime", "Time", "Duration", "Check"];

// Link cells show the title of the record (frappe._link_titles is filled by the register API)
// and stay an anchor that opens it. The anchor is built here with escaping: frappe.format would
// return unescaped text for some Link paths.
beeone.registers.link = function (value, column, row) {
	const doctype = column.fieldtype === "Link" ? column.options : row && row[column.options];
	if (!doctype) return esc(value);
	const title = frappe.utils.get_link_title(doctype, value) || value;
	if (!frappe.model.can_read(doctype)) return esc(title);
	return (
		`<a href="${esc(frappe.utils.get_form_link(doctype, value))}" ` +
		`data-doctype="${esc(doctype)}" data-name="${esc(value)}">${esc(title)}</a>`
	);
};

beeone.registers.format = function (value, column, row) {
	if (value === null || value === undefined || value === "") return "";
	if (["Link", "Dynamic Link"].includes(column.fieldtype)) return beeone.registers.link(value, column, row);
	if (!FORMATTED.includes(column.fieldtype)) return esc(value);
	const df = { fieldtype: column.fieldtype, options: column.options, fieldname: column.fieldname };
	return frappe.format(value, df, { inline: true }, row);
};

beeone.registers.table = function (columns, rows, { sums = true } = {}) {
	const numeric = (c) => NUMERIC.includes(c.fieldtype);
	const head = columns
		.map((c) => `<th class="${numeric(c) ? "beeone-r" : ""}">${esc(c.label)}</th>`)
		.join("");
	const body = rows
		.map(
			(row) =>
				`<tr>` +
				columns
					.map(
						(c) =>
							`<td class="${numeric(c) ? "beeone-r beeone-num" : ""}">${beeone.registers.format(
								row[c.fieldname],
								c,
								row
							)}</td>`
					)
					.join("") +
				`</tr>`
		)
		.join("");
	let foot = "";
	if (sums && rows.length && columns.some((c) => c.role === "Resource")) {
		foot =
			`<tfoot><tr>` +
			columns
				.map((c, i) => {
					if (c.role !== "Resource") return `<td>${i ? "" : esc(__("Total"))}</td>`;
					const total = rows.reduce((sum, row) => sum + flt(row[c.fieldname]), 0);
					return `<td class="beeone-r beeone-num">${beeone.registers.format(total, c, {})}</td>`;
				})
				.join("") +
			`</tr></tfoot>`;
	}
	return (
		`<div class="beeone-table-wrap"><table class="beeone-table"><thead><tr>${head}</tr></thead>` +
		`<tbody>${body}</tbody>${foot}</table></div>`
	);
};

// ------------------------------------------------------------ Document Movements

beeone.registers.show_movements = function (frm) {
	frappe.call({
		method: API + "document_movements",
		args: { doctype: frm.doctype, name: frm.doc.name },
		callback: (r) => beeone.registers.movements_dialog(frm, r.message || []),
	});
};

// the kind of a register gives the colour of its tab and table (accounting, balance, turnover, information)
const KIND_TONE = {
	Accounting: "acc",
	"Accumulation: Balance": "bal",
	"Accumulation: Turnover": "turn",
	"Information: Periodic": "info",
	"Information: Plain": "info",
};
const tone_of = (set) => KIND_TONE[set.kind] || "info";

// Receipt / expense of a balance register: a coloured badge, not the raw value
beeone.registers.direction = function (value) {
	if (!value) return "";
	const receipt = ["receipt", "Receipt", "income", "in", "+"].includes(String(value));
	return (
		`<span class="beeone-dir ${receipt ? "is-in" : "is-out"}">` +
		`${receipt ? "+" : "−"} ${esc(__(receipt ? "Receipt" : "Expense"))}</span>`
	);
};

// A register table with the receipt/expense rows tinted (balance registers)
beeone.registers.movement_table = function (set) {
	const direction = set.columns.find((c) => c.role === "System" && /direction|record_type|movement_type/.test(c.fieldname));
	const columns = set.columns.map((c) =>
		c === direction ? Object.assign({}, c, { render: (v) => beeone.registers.direction(v) }) : c
	);
	const numeric = (c) => NUMERIC.includes(c.fieldtype);
	const head = columns
		.map((c) => `<th class="${numeric(c) ? "beeone-r" : ""}${c.role === "Resource" ? " beeone-res" : ""}">${esc(c.label)}</th>`)
		.join("");
	const body = set.rows
		.map((row) => {
			const dir = direction ? row[direction.fieldname] : "";
			const cls = dir ? (["receipt", "Receipt", "income", "in", "+"].includes(String(dir)) ? "is-in" : "is-out") : "";
			return (
				`<tr class="${cls}">` +
				columns
					.map((c) => {
						const html = c.render ? c.render(row[c.fieldname]) : beeone.registers.format(row[c.fieldname], c, row);
						const klass = [numeric(c) ? "beeone-r beeone-num" : "", c.role === "Resource" ? "beeone-res" : ""].join(" ");
						return `<td class="${klass}">${html}</td>`;
					})
					.join("") +
				`</tr>`
			);
		})
		.join("");
	let foot = "";
	if (set.rows.length > 1 && columns.some((c) => c.role === "Resource")) {
		foot =
			`<tfoot><tr>` +
			columns
				.map((c, i) => {
					if (c.role !== "Resource") return `<td>${i ? "" : esc(__("Total"))}</td>`;
					const total = set.rows.reduce((sum, row) => sum + flt(row[c.fieldname]), 0);
					return `<td class="beeone-r beeone-num beeone-res">${beeone.registers.format(total, c, {})}</td>`;
				})
				.join("") +
			`</tr></tfoot>`;
	}
	return (
		`<div class="beeone-table-wrap"><table class="beeone-table beeone-mv-table"><thead><tr>${head}</tr></thead>` +
		`<tbody>${body}</tbody>${foot}</table></div>`
	);
};

// Accounting entries like 1C: one row per entry, the debit side tinted blue, the credit side tinted green,
// the subaccounts under the account (kind: value), the amount and the content at the end
beeone.registers.entries_table = function (entries) {
	const money = (v) => (v ? frappe.format(v, { fieldtype: "Currency" }, { inline: true }) : "");
	const qty = (v) => (v ? frappe.format(v, { fieldtype: "Float" }, { inline: true }) : "");
	const any = (fn) => entries.some((e) => fn(e.debit) || fn(e.credit));
	const has_qty = any((s) => flt(s.quantity));
	const has_cur = any((s) => s.currency || flt(s.currency_amount));
	const has_content = entries.some((e) => e.content);
	const link = (doctype, value, title) =>
		doctype && value && frappe.model.can_read(doctype)
			? `<a href="${esc(frappe.utils.get_form_link(doctype, value))}">${esc(title || value)}</a>`
			: esc(title || value);
	// the title of an account often repeats its code ("902 Cost of sales"): the code is shown once
	const acc_name = (s) => {
		const title = String(s.title || "");
		return s.account && title.startsWith(s.account) ? title.slice(s.account.length).trim() : title;
	};
	const side = (s, cls) => {
		const sub = s.subconto
			.map(
				(x) =>
					`<div class="beeone-sub"><span class="beeone-sub-kind">${esc(x.kind)}</span>` +
					`<span class="beeone-sub-val">${x.value ? link(x.doctype, x.value, x.title) : "<i>—</i>"}</span></div>`
			)
			.join("");
		let cells =
			`<td class="beeone-acc ${cls}"><b class="beeone-acc-code">${esc(s.account || "")}</b>` +
			`<span class="beeone-acc-title">${esc(acc_name(s))}</span></td>` +
			`<td class="beeone-subs ${cls}">${sub}</td>`;
		if (has_qty) cells += `<td class="beeone-r beeone-num ${cls}">${qty(s.quantity)}</td>`;
		if (has_cur)
			cells +=
				`<td class="beeone-r beeone-num ${cls}">${s.currency ? esc(s.currency) + " " : ""}` +
				`${flt(s.currency_amount) ? qty(s.currency_amount) : ""}</td>`;
		return cells;
	};
	const side_head = (label, cls) =>
		`<th class="${cls}">${esc(__("Account"))} ${esc(label)}</th><th class="${cls}">${esc(__("Subaccounts"))} ${esc(label)}</th>` +
		(has_qty ? `<th class="beeone-r ${cls}">${esc(__("Quantity"))} ${esc(label)}</th>` : "") +
		(has_cur ? `<th class="beeone-r ${cls}">${esc(__("Currency"))} ${esc(label)}</th>` : "");
	const dr = __("Dr");
	const cr = __("Cr");
	const head =
		`<tr class="beeone-band"><th rowspan="2" class="beeone-r">№</th>` +
		`<th colspan="${2 + has_qty + has_cur}" class="beeone-dr">${esc(__("Debit"))}</th>` +
		`<th colspan="${2 + has_qty + has_cur}" class="beeone-cr">${esc(__("Credit"))}</th>` +
		`<th rowspan="2" class="beeone-r beeone-amt">${esc(__("Amount"))}</th>` +
		(has_content ? `<th rowspan="2">${esc(__("Content"))}</th>` : "") +
		`</tr><tr>${side_head(dr, "beeone-dr")}${side_head(cr, "beeone-cr")}</tr>`;
	const body = entries
		.map(
			(e, i) =>
				`<tr><td class="beeone-r beeone-num beeone-ln">${esc(e.line_no || i + 1)}</td>` +
				side(e.debit, "beeone-dr") +
				side(e.credit, "beeone-cr") +
				`<td class="beeone-r beeone-num beeone-amt">${money(e.amount)}</td>` +
				(has_content ? `<td class="beeone-content">${esc(e.content)}</td>` : "") +
				`</tr>`
		)
		.join("");
	const total = entries.reduce((sum, e) => sum + flt(e.amount), 0);
	const span = 1 + 2 * (2 + has_qty + has_cur);
	const foot =
		`<tfoot><tr><td colspan="${span}">${esc(__("Total"))}</td>` +
		`<td class="beeone-r beeone-num beeone-amt">${money(total)}</td>${has_content ? "<td></td>" : ""}</tr></tfoot>`;
	return (
		`<div class="beeone-table-wrap"><table class="beeone-table beeone-entries"><thead>${head}</thead>` +
		`<tbody>${body}</tbody>${foot}</table></div>`
	);
};

beeone.registers.movements_dialog = function (frm, sets) {
	const dialog = new frappe.ui.Dialog({
		title: __("Document Movements") + ": " + __(frm.doctype) + " " + frm.doc.name,
		size: "extra-large",
		fields: [{ fieldtype: "HTML", fieldname: "body" }],
	});
	dialog.$wrapper.addClass("beeone-mv-dialog");
	// the accounting entries come first, like the «Проводки» tab of 1C
	sets = [...sets].sort((a, b) => (a.entries ? 0 : 1) - (b.entries ? 0 : 1));
	const tabs = sets
		.map(
			(set, i) =>
				`<button type="button" class="beeone-tab tone-${tone_of(set)}${i ? "" : " is-active"}" data-register="${esc(set.register)}">` +
				`<span class="beeone-dot"></span>${esc(__(set.register))} <span class="beeone-count">${set.rows.length}</span></button>`
		)
		.join("");
	const panels = sets
		.map(
			(set, i) =>
				`<div class="beeone-panel tone-${tone_of(set)}" data-register="${esc(set.register)}"${i ? " hidden" : ""}>` +
				(set.entries ? beeone.registers.entries_table(set.entries) : beeone.registers.movement_table(set)) +
				`<div class="beeone-note">${esc(__("Rows"))}: <b class="beeone-num">${set.rows.length}</b>` +
				(set.truncated ? ` · ${esc(__("Only the first rows are shown"))}` : "") +
				`<span class="beeone-kind">${esc(__(set.kind))}</span></div></div>`
		)
		.join("");
	const empty = `<div class="beeone-empty">${esc(__("This document has no movements"))}</div>`;
	dialog.fields_dict.body.$wrapper.html(
		`<div class="beeone-viewer beeone-mv">${sets.length ? `<div class="beeone-tabs">${tabs}</div>${panels}` : empty}</div>`
	);
	dialog.$wrapper.on("click", ".beeone-tab", function () {
		const register = $(this).attr("data-register");
		dialog.$wrapper.find(".beeone-tab").removeClass("is-active");
		$(this).addClass("is-active");
		dialog.$wrapper.find(".beeone-panel").each(function () {
			$(this).prop("hidden", $(this).attr("data-register") !== register);
		});
	});
	dialog.show();
};

$(document).on("form-refresh", (e, frm) => {
	// a row of a register is written by posting a document only
	if ((frappe.boot.beeone_registers || {})[frm.doctype]) {
		frm.disable_form();
		frm.disable_save();
		return;
	}
	const registers = (frappe.boot.beeone_movements || {})[frm.doctype];
	if (!registers || frm.doc.docstatus !== 1 || frm.is_new()) return;
	frm.add_custom_button(__("Document Movements"), () => beeone.registers.show_movements(frm));
});

// ------------------------------------------------------------ Register lists

// A register list is read only (the boot data holds no write permission for it)
// and offers the Balance and Turnover commands.
const setup_view = frappe.views.ListView.prototype.setup_view;
frappe.views.ListView.prototype.setup_view = async function () {
	await setup_view.apply(this, arguments);
	const info = (frappe.boot.beeone_registers || {})[this.doctype];
	if (!info) return;
	if (info.balance) {
		this.page.add_inner_button(__("Balance"), () => beeone.registers.report(this.doctype, "balance"));
	}
	if (info.turnover) {
		this.page.add_inner_button(__("Turnovers"), () => beeone.registers.report(this.doctype, "turnover"));
	}
};

beeone.registers.report = function (doctype, command) {
	frappe.call({
		method: API + "register_info",
		args: { doctype },
		callback: (r) => beeone.registers.report_dialog(r.message, command),
	});
};

beeone.registers.report_dialog = function (info, command) {
	const is_balance = command === "balance";
	const today = frappe.datetime.get_today();
	const month_start = frappe.datetime.month_start();
	const dimension_field = (c) => ({
		fieldtype: c.fieldtype === "Link" ? "Link" : "Data",
		options: c.fieldtype === "Link" ? c.options : undefined,
		fieldname: "filter_" + c.fieldname,
		label: c.label,
	});
	const fields = [
		...(is_balance
			? [{ fieldtype: "Date", fieldname: "at", label: __("On Date"), default: today, reqd: 1 }]
			: [
					{ fieldtype: "Date", fieldname: "start", label: __("From"), default: month_start, reqd: 1 },
					{ fieldtype: "Column Break" },
					{ fieldtype: "Date", fieldname: "end", label: __("To"), default: today, reqd: 1 },
			  ]),
		{ fieldtype: "Section Break", label: __("Group by") },
		{
			fieldtype: "MultiCheck",
			fieldname: "group_by",
			label: __("Dimensions"),
			columns: 3,
			options: info.dimensions.map((c) => ({ label: c.label, value: c.fieldname, checked: 1 })),
		},
		...(info.dimensions.length
			? [{ fieldtype: "Section Break", label: __("Filters"), collapsible: 1 }]
			: []),
		...info.dimensions.flatMap((c, i) => [
			...(i && i % 2 === 0 ? [{ fieldtype: "Section Break" }] : []),
			...(i % 2 ? [{ fieldtype: "Column Break" }] : []),
			dimension_field(c),
		]),
		{ fieldtype: "Section Break" },
		{ fieldtype: "HTML", fieldname: "result" },
	];
	const title = (is_balance ? __("Balance") : __("Turnovers")) + ": " + __(info.register);
	const dialog = new frappe.ui.Dialog({
		title,
		size: "extra-large",
		fields,
		primary_action_label: __("Generate"),
		primary_action: (values) => {
			const group_by = (values.group_by || []).filter(Boolean);
			const filters = {};
			info.dimensions.forEach((c) => {
				if (values["filter_" + c.fieldname]) filters[c.fieldname] = values["filter_" + c.fieldname];
			});
			const args = { register: info.register, filters, group_by };
			if (is_balance) args.at = values.at;
			else Object.assign(args, { start: values.start, end: values.end });
			frappe.call({
				method: API + (is_balance ? "balance" : "turnover"),
				args,
				freeze: true,
				callback: (r) => {
					const columns = [
						...info.dimensions.filter((c) => group_by.includes(c.fieldname)),
						...info.resources.map((c) => Object.assign({}, c, { role: "Resource" })),
					];
					const rows = r.message || [];
					dialog.fields_dict.result.$wrapper.html(
						`<div class="beeone-viewer">` +
							(rows.length
								? beeone.registers.table(columns, rows) +
								  `<div class="beeone-note">${esc(__("Rows"))}: <b class="beeone-num">${rows.length}</b></div>`
								: `<div class="beeone-empty">${esc(__("No data for the selected period and filters"))}</div>`) +
							`</div>`
					);
				},
			});
		},
	});
	beeone.registers.report_form = dialog; // the open command dialog, for tests
	dialog.show();
	const defaults = is_balance ? { at: today } : { start: month_start, end: today };
	dialog.set_values(defaults).then(() => dialog.get_primary_btn().trigger("click"));
};
