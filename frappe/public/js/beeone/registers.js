// Movement viewer of documents and the read-only register lists (Balance and Turnover commands).
// Country neutral: every text goes through __(), the translations come from the apps.

frappe.provide("beeone.registers");

const esc = (text) => frappe.utils.escape_html(String(text ?? ""));
const API = "frappe.beeone.api.registers.";
const NUMERIC = ["Currency", "Float", "Int", "Long Int", "Percent"];

beeone.registers.format = function (value, column, row) {
	if (value === null || value === undefined || value === "") return "";
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

beeone.registers.movements_dialog = function (frm, sets) {
	const dialog = new frappe.ui.Dialog({
		title: __("Document Movements") + ": " + __(frm.doctype) + " " + frm.doc.name,
		size: "extra-large",
		fields: [{ fieldtype: "HTML", fieldname: "body" }],
	});
	const tabs = sets
		.map(
			(set, i) =>
				`<button type="button" class="beeone-tab${i ? "" : " is-active"}" data-register="${esc(set.register)}">` +
				`${esc(__(set.register))} <span class="beeone-count">${set.rows.length}</span></button>`
		)
		.join("");
	const panels = sets
		.map(
			(set, i) =>
				`<div class="beeone-panel" data-register="${esc(set.register)}"${i ? " hidden" : ""}>` +
				beeone.registers.table(set.columns, set.rows) +
				`<div class="beeone-note">${esc(__("Rows"))}: <b class="beeone-num">${set.rows.length}</b>` +
				(set.truncated ? ` · ${esc(__("Only the first rows are shown"))}` : "") +
				`</div></div>`
		)
		.join("");
	const empty = `<div class="beeone-empty">${esc(__("This document has no movements"))}</div>`;
	dialog.fields_dict.body.$wrapper.html(
		`<div class="beeone-viewer">${sets.length ? `<div class="beeone-tabs">${tabs}</div>${panels}` : empty}</div>`
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
	dialog.show();
	dialog.get_primary_btn().trigger("click");
};
