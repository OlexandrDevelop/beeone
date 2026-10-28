// Desktop: greeting and widgets (docs/platform/SHELL.md §6). Data comes only from the server method
// frappe.beeone.shell.widget_data, which checks the permission on every call. No timers.
import { wins } from "./windows.js";
import { open_route } from "./panel.js";

const esc = (v) => frappe.utils.escape_html(v == null ? "" : String(v));
const icon = (n, c) => beeone.ui.icon(n, c);
const METHOD = "frappe.beeone.shell.widget_data";
const REFRESH_MS = 60000;
const MAX_WIDGETS = 16;

const CORE_TYPES = () => [
	{ type: "beeone.count", label: __("Shortcut"), sizes: ["s", "m"], icon: "list" },
	{ type: "beeone.number", label: __("Number"), sizes: ["m", "s"], icon: "trending" },
	{ type: "beeone.report", label: __("Mini report"), sizes: ["l"], icon: "chart" },
	{ type: "beeone.recent", label: __("Recent documents"), sizes: ["l"], icon: "history" },
];

let data = {}; // widget id -> server answer
let loaded_at = 0;
let loading = false;
let editing = false;
let was_visible = false;

export const desk = {
	widgets() {
		const st = beeone.shell.state;
		if (st.has_widgets) return st.widgets || [];
		const cat = (beeone.shell.catalog && beeone.shell.catalog.default) || [];
		return cat.map((w, i) => ({ id: `w${i + 1}`, size: "s", title: "", options: {}, ...w }));
	},

	render() {
		const host = document.getElementById("bo-desk-bg");
		if (!host) return;
		const list = this.widgets();
		const hour = new Date().getHours();
		const hello = hour < 5 ? __("Good night, {0}", [first_name()]) : hour < 12 ? __("Good morning, {0}", [first_name()]) : hour < 18 ? __("Good afternoon, {0}", [first_name()]) : __("Good evening, {0}", [first_name()]);
		host.innerHTML =
			`<div class="bo-desk-hello"><h1>${esc(hello)}</h1><p>${esc(__("Documents, lists and reports open as windows."))}</p></div>` +
			`<section class="bo-widgets" aria-label="${esc(__("Widgets"))}"><div class="bo-widgets-head"><h2>${esc(__("Widgets"))}</h2><div>` +
			`<button type="button" class="bo-btn bo-btn--sm bo-btn--ghost" data-w="add">${icon("plus", "bo-i-sm")}${esc(__("Add widget"))}</button>` +
			`<button type="button" class="bo-btn bo-btn--sm" data-w="edit">${esc(editing ? __("Done") : __("Customize"))}</button></div></div>` +
			`<div class="bo-widget-grid${editing ? " is-edit" : ""}">${list.map((w, i) => this.card(w, i, list.length)).join("")}</div>` +
			(list.length ? "" : `<div class="bo-widgets-empty">${icon("layout")}<p>${esc(__("Your widgets will be here"))}</p></div>`) +
			`</section>`;
		list.forEach((w) => this.fill(w));
	},

	card(w, i, n) {
		const size = ["s", "m", "l"].includes(w.size) ? w.size : "s";
		const tools = editing
			? `<div class="bo-w-tools"><button type="button" data-w="up" data-i="${i}" ${i ? "" : "disabled"} aria-label="${esc(__("Move up"))}">${icon("arrow-up")}</button>` +
			  `<button type="button" data-w="down" data-i="${i}" ${i < n - 1 ? "" : "disabled"} aria-label="${esc(__("Move down"))}">${icon("arrow-down")}</button>` +
			  `<button type="button" data-w="cfg" data-i="${i}" aria-label="${esc(__("Edit widget"))}">${icon("gear")}</button>` +
			  `<button type="button" data-w="del" data-i="${i}" aria-label="${esc(__("Remove widget"))}">${icon("x")}</button></div>`
			: "";
		return `<article class="bo-w bo-w--${size}" data-id="${esc(w.id)}" data-type="${esc(w.type)}">${tools}<div class="bo-w-body"></div></article>`;
	},

	fill(w) {
		const body = document.querySelector(`.bo-w[data-id="${CSS.escape(w.id)}"] .bo-w-body`);
		if (!body) return;
		const d = data[w.id];
		const src = source_of(w);
		const title = w.title || (src && src.label) || type_label(w.type);
		if (!d) {
			body.innerHTML = `<div class="bo-w-title">${esc(title)}</div><div class="bo-w-skel"><i></i><i></i></div>`;
			return;
		}
		if (d.denied || (src && src.denied)) {
			body.innerHTML = `<div class="bo-w-title">${esc(title)}</div><div class="bo-w-denied">${icon("lock")}<span>${esc(w.size === "s" ? __("No access") : __('You may not read "{0}". No data is shown.', [title]))}</span></div>`;
			return;
		}
		if (d.error) {
			body.innerHTML = `<div class="bo-w-title">${esc(title)}</div><div class="bo-w-error">${icon("alert")}<span>${esc(__("Could not load data"))}</span><button type="button" class="bo-btn bo-btn--sm" data-w="retry">${esc(__("Try again"))}</button></div>`;
			return;
		}
		body.innerHTML = `<div class="bo-w-title">${esc(title)}</div>` + view(w, d);
	},

	on_click(e) {
		const btn = e.target.closest("[data-w]");
		const card = e.target.closest(".bo-w");
		if (!btn) {
			if (card && !editing) open_source(card.dataset.id, e.target.closest("[data-route]"));
			return;
		}
		const act = btn.dataset.w;
		const list = this.widgets().slice();
		const i = +btn.dataset.i;
		if (act === "edit") {
			editing = !editing;
			return this.render();
		}
		if (act === "add") return this.dialog(null);
		if (act === "retry") return this.refresh(true);
		if (act === "cfg") return this.dialog(list[i]);
		if (act === "up" || act === "down") {
			const j = act === "up" ? i - 1 : i + 1;
			[list[i], list[j]] = [list[j], list[i]];
			return this.commit(list);
		}
		if (act === "del") {
			const [gone] = list.splice(i, 1);
			this.commit(list);
			beeone.ui.toast({
				title: __("Widget removed"),
				action: { label: __("Undo") },
				duration: 4000,
			});
			const undo = document.querySelector(".bo-toast:last-child .bo-toast-action button");
			if (undo)
				undo.addEventListener("click", () => {
					const now = this.widgets().slice();
					now.splice(i, 0, gone);
					this.commit(now);
				});
		}
	},

	commit(list) {
		const st = beeone.shell.state;
		st.widgets = list.slice(0, MAX_WIDGETS);
		st.has_widgets = true;
		beeone.shell.save_soon();
		this.render();
		this.refresh(true);
	},

	dialog(widget) {
		const cat = beeone.shell.catalog || { sources: [], types: [] };
		const own = (cat.types || []).filter((t) => !t.denied).map((t) => ({ type: t.type, label: t.label, sizes: t.sizes, icon: "layout", own: true }));
		const types = [...CORE_TYPES().filter((t) => cat.sources.some((s) => s.types.includes(t.type))), ...own];
		const cur = { type: widget ? widget.type : (types[0] || {}).type, source: widget ? widget.source : "", size: widget ? widget.size : "s", title: widget ? widget.title : "", period: widget && widget.options ? widget.options.period : "month" };
		const dlg = beeone.ui.dialog({
			title: widget ? __("Edit widget") : __("Add widget"),
			width: 520,
			html: `<div class="bo-dialog-head"><h3>${esc(widget ? __("Edit widget") : __("Add widget"))}</h3></div><div class="bo-dialog-body bo-wd"></div>` +
				`<div class="bo-dialog-foot"><button type="button" class="bo-btn" data-close>${esc(__("Cancel"))}</button><button type="button" class="bo-btn bo-btn--primary" data-ok>${esc(__("Done"))}</button></div>`,
		});
		const body = dlg.box.querySelector(".bo-wd");
		const paint = () => {
			const sources = cat.sources.filter((s) => s.types.includes(cur.type));
			const t = types.find((x) => x.type === cur.type) || {};
			const sizes = t.sizes || ["s", "m", "l"];
			if (!sizes.includes(cur.size)) cur.size = sizes[0];
			if (!t.own && !sources.some((s) => s.id === cur.source)) cur.source = (sources.find((s) => !s.denied) || sources[0] || {}).id || "";
			const size_label = { s: __("Small"), m: __("Wide"), l: __("Large") };
			body.innerHTML =
				`<div class="bo-wd-types">${types.map((x) => `<button type="button" class="bo-wd-type${x.type === cur.type ? " is-on" : ""}" data-type="${esc(x.type)}">${icon(x.icon)}<span>${esc(x.label)}</span></button>`).join("")}</div>` +
				(t.own ? "" : `<label class="bo-field"><span>${esc(__("Data"))}</span><select data-f="source">${sources.map((s) => `<option value="${esc(s.id)}"${s.denied ? " disabled" : ""}${s.id === cur.source ? " selected" : ""}>${esc(s.label)}${s.denied ? " — " + esc(__("no read permission")) : ""}</option>`).join("")}</select></label>`) +
				`<label class="bo-field"><span>${esc(__("Title"))}</span><input type="text" data-f="title" maxlength="60" value="${esc(cur.title)}"></label>` +
				`<label class="bo-field"><span>${esc(__("Size"))}</span><select data-f="size">${sizes.map((s) => `<option value="${s}"${s === cur.size ? " selected" : ""}>${esc(size_label[s])}</option>`).join("")}</select></label>` +
				(cur.type === "beeone.number" ? `<label class="bo-field"><span>${esc(__("Period"))}</span><select data-f="period">${["month", "quarter", "year"].map((p) => `<option value="${p}"${p === cur.period ? " selected" : ""}>${esc({ month: __("Month"), quarter: __("Quarter"), year: __("Year") }[p])}</option>`).join("")}</select></label>` : "");
		};
		body.addEventListener("click", (e) => {
			const t = e.target.closest("[data-type]");
			if (t) {
				cur.type = t.dataset.type;
				paint();
			}
		});
		body.addEventListener("change", (e) => {
			const f = e.target.dataset.f;
			if (f) cur[f] = e.target.value;
		});
		body.addEventListener("input", (e) => {
			if (e.target.dataset.f === "title") cur.title = e.target.value;
		});
		dlg.box.querySelector("[data-ok]").addEventListener("click", () => {
			const list = this.widgets().slice();
			const t = types.find((x) => x.type === cur.type) || {};
			if (!t.own && !cur.source) return;
			const item = { id: widget ? widget.id : "w" + Date.now().toString(36), type: cur.type, source: t.own ? "" : cur.source, size: cur.size, title: cur.title.trim(), options: cur.type === "beeone.number" ? { period: cur.period } : {} };
			if (widget) list[list.findIndex((x) => x.id === widget.id)] = item;
			else if (list.length >= MAX_WIDGETS) return;
			else list.push(item);
			dlg.close();
			this.commit(list);
		});
		paint();
	},

	// the data of the widgets: on start, when the desktop shows again (at most once a minute), after an edit
	refresh(force) {
		const list = this.widgets();
		if (!list.length || loading) return;
		const now = Date.now();
		if (!force && now - loaded_at < REFRESH_MS) return;
		loading = true;
		const request = list.map((w) => ({ id: w.id, type: w.type, source: w.source, options: w.options || {} }));
		frappe
			.xcall(METHOD, { widgets: JSON.stringify(request) })
			.then((res) => {
				data = res || {};
				loaded_at = Date.now();
			})
			.catch(() => {
				data = {};
				list.forEach((w) => (data[w.id] = { error: 1 }));
			})
			.finally(() => {
				loading = false;
				list.forEach((w) => this.fill(w));
			});
	},

	// called when a window changes: refresh only when the desktop becomes visible
	on_visibility() {
		const visible = ![...wins.map.values()].some((w) => w.state === "maximized") && !(document.body.classList.contains("bo-compact") && wins.active);
		if (visible && !was_visible) this.refresh(false);
		was_visible = visible;
	},
};

function first_name() {
	return (frappe.session.user_fullname || frappe.session.user || "").split(" ")[0];
}

function type_label(type) {
	const t = CORE_TYPES().find((x) => x.type === type);
	return t ? t.label : type;
}

function source_of(w) {
	const cat = beeone.shell.catalog;
	return cat && cat.sources.find((s) => s.id === w.source);
}

function open_source(id, link) {
	const w = desk.widgets().find((x) => x.id === id);
	if (!w) return;
	if (link && link.dataset.route) return open_route(JSON.parse(link.dataset.route));
	const src = source_of(w);
	if (src && src.report) frappe.set_route("query-report", src.report);
	else if (src && src.doctype) frappe.set_route("List", src.doctype);
}

function fmt(value, currency) {
	return beeone.ui.money(value, { digits: Math.abs(value) >= 1000 ? 0 : 2, cur: currency });
}

function view(w, d) {
	if (w.type === "beeone.count") return `<div class="bo-w-num">${esc(format_number(d.count, null, 0))}</div><div class="bo-w-sub">${esc(__("documents"))}</div>`;
	if (w.type === "beeone.number") {
		const up = d.change > 0;
		const delta = d.change == null ? "" : `<span class="bo-w-delta ${up ? "is-up" : "is-down"}">${up ? "▲" : "▼"} ${esc(Math.abs(d.change))}%</span>`;
		return `<div class="bo-w-num">${esc(fmt(d.value, d.currency))}</div><div class="bo-w-sub">${esc({ month: __("This month"), quarter: __("This quarter"), year: __("This year") }[d.period] || "")} ${delta}</div>`;
	}
	if (w.type === "beeone.recent") {
		if (!d.rows.length) return `<div class="bo-w-sub">${esc(__("No data for the period"))}</div>`;
		return `<ul class="bo-w-rows">${d.rows
			.map((r) => `<li><button type="button" data-route='${esc(JSON.stringify(["Form", d.doctype, r.name]))}'>${esc(r.title || r.name)}</button>${r.docstatus === 1 ? `<span class="bo-chip-dot is-ok">${esc(__("Submitted"))}</span>` : r.docstatus === 2 ? `<span class="bo-chip-dot is-bad">${esc(__("Cancelled"))}</span>` : ""}</li>`)
			.join("")}</ul>`;
	}
	if (w.type === "beeone.report") {
		if (!d.rows.length) return `<div class="bo-w-sub">${esc(__("No data for the period"))}</div>`;
		return `<table class="bo-w-table"><thead><tr>${d.columns.map((c) => `<th>${esc(c.label)}</th>`).join("")}</tr></thead><tbody>${d.rows
			.map((r) => `<tr>${r.map((v, i) => `<td${/Currency|Float|Int/.test(d.columns[i].fieldtype || "") ? ' class="num"' : ""}>${esc(typeof v === "number" ? format_number(v, null, 2) : v)}</td>`).join("")}</tr>`)
			.join("")}</tbody></table>`;
	}
	// a type of an app: its own render function
	const own = (beeone.shell.catalog.types || []).find((t) => t.type === w.type);
	const fn = own && own.render ? get_path(own.render) : null;
	if (fn) {
		const el = document.createElement("div");
		fn(el, d, w);
		return el.innerHTML;
	}
	return "";
}

function get_path(path) {
	return String(path)
		.split(".")
		.reduce((o, k) => (o ? o[k] : undefined), window);
}
