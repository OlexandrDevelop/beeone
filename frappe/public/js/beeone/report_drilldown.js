// Report drill-down (user 2026-11-20): a double click on a report cell opens a menu of the reports that show what is
// behind the cell — always a menu, even with one item. The chosen report opens with the filters of the cell (the Link
// values of the clicked row: counterparty, item, account, ...; the Link filters of the source report: organization, ...)
// and the period of the source report. A report's own double-click drill-down (bound by the report script) becomes the
// first item of the menu; a Link cell adds «Open ...». The candidates come from frappe.beeone.api.report_drilldown.
frappe.provide("beeone.drill");

(function () {
	const D = beeone.drill;
	const API = "frappe.beeone.api.report_drilldown.targets";
	const esc = (v) => frappe.utils.escape_html(v == null ? "" : String(v));
	const PERIOD = {
		from: ["from_date", "date_from", "period_from", "start_date", "start"],
		to: ["to_date", "date_to", "period_to", "end_date", "end"],
		at: ["date", "report_date", "as_of_date", "on_date", "at", "balance_date"],
	};
	const OWN = "beeone-own-drill"; // marks the re-dispatched event of the report's own handler

	// the period of the source report: {from, to, at}
	D.period = function (values) {
		const out = {};
		Object.entries(PERIOD).forEach(([kind, names]) => {
			const name = names.find((n) => values[n]);
			if (name) out[kind] = values[name];
		});
		return out;
	};

	// the Link values of a row: [{doctype, value, fieldname, label}]; a report whose cells are text (an account shown as
	// "281 Goods") gives the values in the row as `_links: {DocType: value}`
	D.row_links = function (report, row) {
		const out = [];
		Object.entries((row && row._links) || {}).forEach(([doctype, value]) => {
			if (value) out.push({ doctype, value: String(value), fieldname: null, label: __(doctype) });
		});
		// a row that stands for a document (a group «Документ-реєстратор»): `bo_document: {doctype, name, title}`; a double
		// click on its group cell offers «Open: <the document>»
		const d = row && row.bo_document;
		if (d && d.doctype && d.name) {
			out.push({ doctype: d.doctype, value: String(d.name), title: d.title, fieldname: d.field || "group", label: __(d.doctype) });
		}
		(report.columns || []).forEach((c) => {
			const value = row && row[c.fieldname];
			if (!value || typeof value !== "string") return;
			let doctype = null;
			if (c.fieldtype === "Link") doctype = c.options;
			else if (c.fieldtype === "Dynamic Link") doctype = row[c.options];
			if (doctype) out.push({ doctype, value, fieldname: c.fieldname, label: c.label });
		});
		return out;
	};

	D.filter_links = function (report) {
		const out = [];
		(report.filters || []).forEach((f) => {
			const df = f.df || {};
			const value = f.get_value && f.get_value();
			if (df.fieldtype === "Link" && df.options && value && typeof value === "string") {
				out.push({ doctype: df.options, value, fieldname: df.fieldname, label: df.label });
			}
		});
		return out;
	};

	// the report's own dblclick handlers on the datatable or on the page (not ours)
	D.own_handlers = function (report, cell) {
		const holders = [report.datatable && report.datatable.wrapper, report.page && report.page.wrapper && report.page.wrapper[0]];
		return holders.some((el) => {
			const events = el && $._data(el, "events");
			return events && events.dblclick && events.dblclick.length;
		});
	};

	// the filters of the target report from the cell and the source report
	D.target_filters = function (target, ctx) {
		const filters = {};
		Object.entries(target.links || {}).forEach(([fieldname, doctype]) => {
			const pick =
				(ctx.clicked && ctx.clicked.doctype === doctype && ctx.clicked) ||
				ctx.row.find((l) => l.doctype === doctype) ||
				ctx.filters.find((l) => l.doctype === doctype);
			if (pick) filters[fieldname] = pick.value;
		});
		const src = ctx.period;
		const p = target.period || {};
		if (p.from && p.to) {
			const to = src.to || src.at;
			const from = src.from || (to ? frappe.datetime.month_start(to) : null);
			if (from) filters[p.from] = from;
			if (to) filters[p.to] = to;
		} else if (p.at && (src.to || src.at)) {
			filters[p.at] = src.to || src.at;
		} else if (p.to && (src.to || src.at)) {
			filters[p.to] = src.to || src.at;
		}
		return filters;
	};

	D.open_report = function (report, target, ctx) {
		const filters = D.target_filters(target, ctx);
		if (target.report === report.report_name) {
			// the same report: the cell's values become its filters
			Object.entries(filters).forEach(([k, v]) => report.get_filter(k) && report.set_filter_value(k, v));
			return;
		}
		frappe.route_options = filters;
		frappe.set_route("query-report", target.report);
	};

	D.close = function () {
		$(".bo-drill-menu").remove();
		$(document).off(".bodrill");
	};

	D.menu = function (x, y, title, items) {
		D.close();
		const $m = $(
			`<div class="bo-drill-menu" role="menu"><div class="bo-drill-title">${esc(title)}</div><div class="bo-drill-items"></div></div>`
		).appendTo(document.body);
		const $list = $m.find(".bo-drill-items");
		if (!items.length) {
			$list.append(`<div class="bo-drill-empty">${esc(__("No reports to drill down into"))}</div>`);
		}
		items.forEach((item, i) => {
			const $b = $(
				`<button type="button" class="bo-drill-item${item.kind ? " is-" + item.kind : ""}" role="menuitem">` +
					`<span class="bo-drill-ico">${frappe.utils.icon(item.icon || "file", "sm")}</span>` +
					`<span class="bo-drill-text"><span class="bo-drill-label">${esc(item.label)}</span>` +
					(item.hint ? `<span class="bo-drill-hint">${esc(item.hint)}</span>` : "") +
					`</span></button>`
			).appendTo($list);
			$b.on("click", () => {
				D.close();
				item.run();
			});
			if (!i) setTimeout(() => $b.trigger("focus"), 0);
		});
		const w = $m.outerWidth();
		const h = $m.outerHeight();
		$m.css({
			left: Math.max(8, Math.min(x, window.innerWidth - w - 8)),
			top: Math.max(8, y + h > window.innerHeight - 8 ? y - h : y),
		});
		setTimeout(() => {
			$(document).on("mousedown.bodrill", (e) => {
				if (!$(e.target).closest(".bo-drill-menu").length) D.close();
			});
			$(document).on("keydown.bodrill", (e) => {
				const $items = $m.find(".bo-drill-item");
				const i = $items.index(document.activeElement);
				if (e.key === "Escape") D.close();
				else if (e.key === "ArrowDown") $items.eq((i + 1) % $items.length).trigger("focus"), e.preventDefault();
				else if (e.key === "ArrowUp") $items.eq((i - 1 + $items.length) % $items.length).trigger("focus"), e.preventDefault();
			});
		}, 0);
		return $m;
	};

	D.on_dblclick = function (e) {
		if (e[OWN]) return;
		const cell = e.target.closest && e.target.closest(".dt-cell");
		if (!cell || cell.closest(".dt-header") || cell.dataset.rowIndex == null) return;
		const report = frappe.query_report;
		const wrapper = report && report.datatable && report.datatable.wrapper;
		if (!wrapper || !wrapper.contains(cell)) return;
		const row_index = cint(cell.dataset.rowIndex);
		const col_index = cint(cell.dataset.colIndex);
		const row = (report.data || [])[row_index];
		if (!row) return;
		e.preventDefault();
		e.stopPropagation(); // the report's own handlers run from the menu

		const column = report.datatable.getColumn ? report.datatable.getColumn(col_index) : null;
		const fieldname = column && ((column.docfield && column.docfield.fieldname) || column.fieldname || column.id);
		// a report's own menu: `drill_menu(report, row, fieldname)` of its script gives the items ({label, hint, icon, run})
		const own_menu = report.report_settings && report.report_settings.drill_menu;
		const own_items = own_menu && own_menu(report, row, fieldname);
		if (own_items) {
			const [mx, my] = [e.clientX, e.clientY];
			Promise.resolve(own_items).then((items) => D.menu(mx, my, __("Drill down"), items || []));
			return;
		}
		const row_links = D.row_links(report, row);
		const ctx = {
			row: row_links,
			filters: D.filter_links(report),
			clicked: row_links.find((l) => l.fieldname === fieldname) || null,
			period: D.period(report.get_filter_values ? report.get_filter_values() : {}),
		};
		const doctypes = [...new Set([...ctx.row, ...ctx.filters].map((l) => l.doctype))];
		const row_doctypes = [...new Set(ctx.row.map((l) => l.doctype))];
		const x = e.clientX;
		const y = e.clientY;
		const own = D.own_handlers(report, cell);

		frappe.xcall(API, { report: report.report_name, doctypes, row_doctypes }).then((targets) => {
			const items = [];
			if (own) {
				items.push({
					kind: "own",
					icon: "search",
					label: __("Drill down in this report"),
					run: () => {
						const ev = $.Event("dblclick");
						ev[OWN] = true;
						$(cell).trigger(ev);
					},
				});
			}
			// the reports that filter by the clicked column's value go first, in the server's order otherwise
			const clicked_dt = ctx.clicked && ctx.clicked.doctype;
			targets = (targets || [])
				.map((t, i) => ({ t, i, hit: clicked_dt && Object.values(t.links || {}).includes(clicked_dt) ? 0 : 1 }))
				.sort((a, b) => a.hit - b.hit || a.i - b.i)
				.map((x) => x.t);
			targets.forEach((t) => {
				const filters = D.target_filters(t, ctx);
				const hint = Object.entries(t.links || {})
					.filter(([f]) => filters[f])
					.map(([f, dt]) => {
						return `${__(dt)}: ${frappe.utils.get_link_title(dt, filters[f]) || filters[f]}`;
					})
					.join(" · ");
				items.push({ icon: "file-text", label: __(t.report), hint, run: () => D.open_report(report, t, ctx) });
			});
			if (ctx.clicked && frappe.model.can_read(ctx.clicked.doctype)) {
				const l = ctx.clicked;
				items.push({
					kind: "open",
					icon: "external-link",
					label: `${__("Open")}: ${l.title || frappe.utils.get_link_title(l.doctype, l.value) || l.value}`,
					hint: __(l.doctype),
					run: () => frappe.set_route("Form", l.doctype, l.value),
				});
			}
			D.menu(x, y, __("Drill down"), items);
		});
	};

	// capture phase: before the report's own (delegated, bubbling) handlers
	document.addEventListener("dblclick", (e) => D.on_dblclick(e), true);
})();
