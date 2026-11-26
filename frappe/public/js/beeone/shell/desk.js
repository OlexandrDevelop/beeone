// Desktop: greeting and widgets (docs/platform/SHELL.md §6). Data comes only from the server method
// frappe.beeone.shell.widget_data, which checks the permission on every call. No timers.
import { wins } from "./windows.js";
import { open_route, open_section, open_command } from "./panel.js";
import { render_chart, chart_table } from "./chart.js";

const esc = (v) => frappe.utils.escape_html(v == null ? "" : String(v));
const icon = (n, c) => beeone.ui.icon(n, c);
const METHOD = "frappe.beeone.shell.widget_data";
const REFRESH_MS = 60000;
const MAX_WIDGETS = 16;
// the free desktop (user 2026-11-26): a widget stands where the user put it; the sizes on a grid of 12 px
const STEP = 12;
const CELL = { w: 174, h: 108 };
const SIZE_PX = {
	s: [CELL.w, CELL.h],
	m: [2 * CELL.w + STEP, CELL.h],
	l: [2 * CELL.w + STEP, 2 * CELL.h + STEP],
	xl: [4 * CELL.w + 3 * STEP, 4 * CELL.h + 3 * STEP],
};
const TOP = 44; // below the bar «Віджети» of the desktop

const CORE_TYPES = () => [
	{ type: "beeone.count", label: __("Shortcut"), sizes: ["s", "m"], icon: "list" },
	{ type: "beeone.number", label: __("Period total"), sizes: ["m", "s"], icon: "trending" },
	{ type: "beeone.chart", label: __("Chart for the period"), sizes: ["l", "xl"], icon: "linechart" },
	{ type: "beeone.report", label: __("Mini report"), sizes: ["l"], icon: "chart" },
	{ type: "beeone.recent", label: __("Recent documents"), sizes: ["l"], icon: "history" },
];

let data = {}; // widget id -> server answer
let loaded_at = 0;
let loading = false;
let editing = false;
let was_visible = false;
let placed_on_resize = false;

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
			`<div class="bo-desk-hello"><div class="bo-desk-title">${esc(hello)}</div><p>${esc(__("Documents, lists and reports open as windows."))}</p>${this.tiles()}</div>` +
			`<section class="bo-widgets${editing ? " is-edit" : ""}" aria-label="${esc(__("Widgets"))}"><div class="bo-widgets-head"><h2>${esc(__("Widgets"))}</h2><div>` +
			`<button type="button" class="bo-btn bo-btn--sm bo-btn--ghost" data-w="add">${icon("plus", "bo-i-sm")}${esc(__("Add widget"))}</button>` +
			`<button type="button" class="bo-btn bo-btn--sm" data-w="edit">${esc(editing ? __("Done") : __("Customize"))}</button></div></div>` +
			(editing && list.length ? `<p class="bo-widgets-hint">${esc(__("Drag a widget to any place of the desktop"))}</p>` : "") +
			(list.length ? "" : `<div class="bo-widgets-empty">${icon("layout")}<p>${esc(__("Your widgets will be here"))}</p></div>`) +
			`</section>` +
			`<div class="bo-widget-grid${editing ? " is-edit" : ""}">${list.map((w, i) => this.card(w, i, list.length)).join("")}</div>`;
		this.place(host, list);
		list.forEach((w) => this.fill(w));
		if (!placed_on_resize) {
			// a narrower desktop keeps every widget inside it
			placed_on_resize = true;
			let timer = null;
			window.addEventListener("resize", () => {
				clearTimeout(timer);
				timer = setTimeout(() => {
					const bg = document.getElementById("bo-desk-bg");
					if (bg && !bg.hidden) this.place(bg, this.widgets());
				}, 150);
			});
		}
	},

	// the places of the widgets on the desktop: the saved one, else the first free place in the column of the widgets at
	// the right edge (where the widgets stood before they could be moved); a place is kept inside the desktop
	places(host, list) {
		const width = Math.max(host.clientWidth - 2 * 28, SIZE_PX.l[0]);
		const wide = list.some((w) => w.size === "xl" && w.x == null);
		const column = Math.max(0, width - (wide ? SIZE_PX.xl[0] : SIZE_PX.l[0]));
		const taken = [];
		const free = (r) => !taken.some((t) => r.x < t.x + t.w + STEP && t.x < r.x + r.w + STEP && r.y < t.y + t.h + STEP && t.y < r.y + r.h + STEP);
		const out = {};
		const size = (w) => SIZE_PX[w.size] || SIZE_PX.s;
		list.forEach((w) => {
			if (w.x == null || w.y == null) return;
			const [ww, hh] = size(w);
			const r = { x: Math.max(0, Math.min(w.x, width - ww)), y: Math.max(0, w.y), w: ww, h: hh };
			taken.push(r);
			out[w.id] = r;
		});
		list.forEach((w) => {
			if (out[w.id]) return;
			const [ww, hh] = size(w);
			for (let y = TOP; ; y += STEP) {
				const x = [column, column + CELL.w + STEP].find((x0) => x0 + ww <= width + 0.5 && free({ x: x0, y, w: ww, h: hh }));
				if (x != null) {
					out[w.id] = { x, y, w: ww, h: hh };
					taken.push(out[w.id]);
					break;
				}
			}
		});
		return out;
	},

	place(host, list) {
		const grid = host.querySelector(".bo-widget-grid");
		if (!grid || document.body.classList.contains("bo-compact")) return; // a small screen: one column, as it was
		const at = this.places(host, list);
		let bottom = 0;
		grid.querySelectorAll(".bo-w").forEach((el) => {
			const r = at[el.dataset.id];
			if (!r) return;
			Object.assign(el.style, { left: r.x + "px", top: r.y + "px", width: r.w + "px", height: r.h + "px" });
			bottom = Math.max(bottom, r.y + r.h);
		});
		grid.style.height = bottom + 24 + "px";
		if (editing) this.drag(host, grid, list);
	},

	// «Налаштувати»: a widget is dragged to any place of the desktop; the place is snapped to the grid and saved
	drag(host, grid, list) {
		grid.querySelectorAll(".bo-w").forEach((el) => {
			el.addEventListener("pointerdown", (e) => {
				if (e.button !== 0 || e.target.closest("button")) return;
				e.preventDefault();
				const start = { x: e.clientX, y: e.clientY, left: el.offsetLeft, top: el.offsetTop };
				const max_x = Math.max(0, host.clientWidth - 2 * 28 - el.offsetWidth);
				let moved = false;
				el.setPointerCapture(e.pointerId);
				el.classList.add("is-drag");
				const pos = (ev) => ({
					x: Math.max(0, Math.min(max_x, Math.round((start.left + ev.clientX - start.x) / STEP) * STEP)),
					y: Math.max(0, Math.round((start.top + ev.clientY - start.y) / STEP) * STEP),
				});
				const move = (ev) => {
					const p = pos(ev);
					moved = moved || Math.abs(ev.clientX - start.x) + Math.abs(ev.clientY - start.y) > 3;
					el.style.left = p.x + "px";
					el.style.top = p.y + "px";
				};
				const up = (ev) => {
					el.removeEventListener("pointermove", move);
					el.removeEventListener("pointerup", up);
					el.removeEventListener("pointercancel", up);
					el.classList.remove("is-drag");
					if (!moved) return;
					// every widget keeps the place it has now (the ones placed automatically too), the dragged one its new one
					const at = this.places(host, list);
					const p = pos(ev);
					const next = list.map((w) => (w.id === el.dataset.id ? { ...w, ...p } : { ...w, x: at[w.id].x, y: at[w.id].y }));
					this.commit(next, false);
				};
				el.addEventListener("pointermove", move);
				el.addEventListener("pointerup", up);
				el.addEventListener("pointercancel", up);
			});
		});
	},

	// the home page of the role: tiles of its sections and commands (the role desk, SHELL.md §6.6)
	tiles() {
		const list = beeone.shell.tiles || [];
		if (!list.length) return "";
		return (
			`<section class="bo-tiles" aria-label="${esc(__("Role desk"))}">` +
			list
				.map(
					(t, i) =>
						`<button type="button" class="bo-tile" data-tile="${i}">${icon(t.icon)}<span class="bo-tile-label">${esc(t.label)}</span>` +
						(t.description ? `<span class="bo-tile-sub">${esc(t.description)}</span>` : "") +
						`</button>`
				)
				.join("") +
			`</section>`
		);
	},

	card(w, i, n) {
		const size = ["s", "m", "l", "xl"].includes(w.size) ? w.size : "s";
		const tools = editing
			? `<div class="bo-w-tools">${icon("grip", "bo-w-grip")}` +
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
		if (w.type === "beeone.chart") {
			const host = body.querySelector(".bo-chart-host");
			if (host) {
				host.__bo_w = w;
				host.__bo_d = d;
				render_chart(host, d, w.options || {});
				chart_resize().observe(host);
			}
		}
	},

	// "Chart for the period" opened large: the chart over the whole window and the table of every value
	expand(w) {
		const d = data[w.id];
		if (!d || d.error || d.denied) return;
		const src = source_of(w);
		const title = w.title || (src && src.label) || type_label(w.type);
		const dlg = beeone.ui.dialog({
			title,
			width: 1100,
			className: "bo-chart-dialog",
			html:
				`<div class="bo-dialog-head"><h3>${esc(title)}</h3></div>` +
				`<div class="bo-dialog-body"><div class="bo-chart-host bo-chart-host--big"></div>` +
				`<details class="bo-chart-data"><summary>${esc(__("Data as a table"))}</summary>${chart_table(d)}</details></div>` +
				`<div class="bo-dialog-foot"><button type="button" class="bo-btn" data-close>${esc(__("Close"))}</button>` +
				(d.doctype ? `<button type="button" class="bo-btn bo-btn--primary" data-open>${esc(__("Open the list"))}</button>` : "") +
				`</div>`,
		});
		const host = dlg.box.querySelector(".bo-chart-host");
		setTimeout(() => render_chart(host, d, w.options || {}), 0);
		const open = dlg.box.querySelector("[data-open]");
		if (open)
			open.addEventListener("click", () => {
				dlg.close();
				frappe.set_route("List", d.doctype);
			});
	},

	on_click(e) {
		const tile = e.target.closest("[data-tile]");
		if (tile) {
			const t = (beeone.shell.tiles || [])[+tile.dataset.tile];
			if (t) t.section ? open_section(t.section) : open_command(t);
			return;
		}
		const btn = e.target.closest("[data-w]");
		const card = e.target.closest(".bo-w");
		if (!btn) {
			if (card && !editing) {
				const w = this.widgets().find((x) => x.id === card.dataset.id);
				if (w && w.type === "beeone.chart") return this.expand(w);
				open_source(card.dataset.id, e.target.closest("[data-route]"));
			}
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
		if (act === "del") {
			const [gone] = list.splice(i, 1);
			this.commit(list);
			beeone.ui.toast({
				title: __("Widget removed"),
				type: "info",
				action: {
					label: __("Undo"),
					on_click: () => {
						const now = this.widgets().slice();
						now.splice(i, 0, gone);
						this.commit(now);
					},
				},
				duration: 4000,
			});
		}
	},

	commit(list, reload = true) {
		const st = beeone.shell.state;
		st.widgets = list.slice(0, MAX_WIDGETS);
		st.has_widgets = true;
		beeone.shell.save_soon("widgets");
		this.render();
		if (reload) this.refresh(true);
		else st.widgets.forEach((w) => this.fill(w)); // a move: the data the widgets have
	},

	dialog(widget) {
		const cat = beeone.shell.catalog || { sources: [], types: [] };
		const own = (cat.types || []).filter((t) => !t.denied).map((t) => ({ type: t.type, label: t.label, sizes: t.sizes, icon: "layout", own: true }));
		const types = [...CORE_TYPES().filter((t) => cat.sources.some((s) => s.types.includes(t.type))), ...own];
		const cur = { type: widget ? widget.type : (types[0] || {}).type, source: widget ? widget.source : "", size: widget ? widget.size : "s", title: widget ? widget.title : "", period: widget && widget.options ? widget.options.period : "month" };
		// "Chart for the period": what splits the series, the period, the look
		const opt = (widget && widget.options) || {};
		const chart = { group: opt.group ?? "organization", cperiod: opt.period || "12m", style: opt.style || "area" };
		const dlg = beeone.ui.dialog({
			title: widget ? __("Edit widget") : __("Add widget"),
			width: 520,
			html: `<div class="bo-dialog-head"><h3>${esc(widget ? __("Edit widget") : __("Add widget"))}</h3></div><div class="bo-dialog-body bo-wd"></div>` +
				`<div class="bo-dialog-foot"><button type="button" class="bo-btn" data-close>${esc(__("Cancel"))}</button><button type="button" class="bo-btn bo-btn--primary" data-ok>${esc(__("Done"))}</button></div>`,
		});
		const body = dlg.box.querySelector(".bo-wd");
		const paint = () => {
			if (!types.length) {
				// no app declares a widget source and the sections of the user have no document lists
				body.innerHTML = `<p class="bo-wd-empty">${esc(__("There is no data for widgets yet: no document list is available to you."))}</p>`;
				return;
			}
			const sources = cat.sources.filter((s) => s.types.includes(cur.type));
			const t = types.find((x) => x.type === cur.type) || {};
			const sizes = t.sizes || ["s", "m", "l"];
			if (!sizes.includes(cur.size)) cur.size = sizes[0];
			if (!t.own && !sources.some((s) => s.id === cur.source)) cur.source = (sources.find((s) => !s.denied) || sources[0] || {}).id || "";
			const size_label = { s: __("Small"), m: __("Wide"), l: __("Large"), xl: __("Full panel") };
			const src = sources.find((s) => s.id === cur.source) || {};
			const groups = src.groups || [];
			if (chart.group && !groups.some((g) => g.field === chart.group)) chart.group = "";
			const choice = (f, value, list) =>
				`<select data-f="${f}">${list.map(([v, l]) => `<option value="${esc(v)}"${v === value ? " selected" : ""}>${esc(l)}</option>`).join("")}</select>`;
			const chart_fields =
				cur.type === "beeone.chart"
					? `<label class="bo-field"><span>${esc(__("Split by"))}</span>${choice("group", chart.group, [["", __("Do not split")], ...groups.map((g) => [g.field, g.label])])}</label>` +
					  `<div class="bo-field-row"><label class="bo-field"><span>${esc(__("Period"))}</span>${choice("cperiod", chart.cperiod, [["12m", __("Last 12 months")], ["ytd", __("This year")], ["90d", __("Last 90 days")], ["30d", __("Last 30 days")]])}</label>` +
					  `<label class="bo-field"><span>${esc(__("Look"))}</span>${choice("style", chart.style, [["area", __("Areas")], ["line", __("Lines")], ["bar", __("Bars")]])}</label></div>`
					: "";
			body.innerHTML =
				`<div class="bo-wd-types">${types.map((x) => `<button type="button" class="bo-wd-type${x.type === cur.type ? " is-on" : ""}" data-type="${esc(x.type)}">${icon(x.icon)}<span>${esc(x.label)}</span></button>`).join("")}</div>` +
				(t.own ? "" : `<label class="bo-field"><span>${esc(__("Data"))}</span><select data-f="source">${sources.map((s) => `<option value="${esc(s.id)}"${s.denied ? " disabled" : ""}${s.id === cur.source ? " selected" : ""}>${esc(s.label)}${s.denied ? " — " + esc(__("no read permission")) : ""}</option>`).join("")}</select></label>`) +
				chart_fields +
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
			if (["group", "cperiod", "style"].includes(f)) chart[f] = e.target.value;
			else if (f) cur[f] = e.target.value;
			if (f === "source") paint(); // the fields to split by belong to the source
		});
		body.addEventListener("input", (e) => {
			if (e.target.dataset.f === "title") cur.title = e.target.value;
		});
		dlg.box.querySelector("[data-ok]").addEventListener("click", () => {
			const list = this.widgets().slice();
			const t = types.find((x) => x.type === cur.type) || {};
			if (!t.own && !cur.source) return;
			const item = { id: widget ? widget.id : "w" + Date.now().toString(36), type: cur.type, source: t.own ? "" : cur.source, size: cur.size, title: cur.title.trim(), options: cur.type === "beeone.number" ? { period: cur.period } : cur.type === "beeone.chart" ? { period: chart.cperiod, group: chart.group, style: chart.style } : {} };
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
		const host = document.getElementById("bo-desk-bg");
		// beeone: hide desktop only when a window is maximized (covers it completely)
		if (host) host.hidden = [...wins.map.values()].some((w) => w.state === "maximized");
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

let resize_observer = null;
function chart_resize() {
	if (!resize_observer)
		resize_observer = new ResizeObserver((entries) => {
			for (const e of entries) {
				const host = e.target;
				if (!host.isConnected) {
					resize_observer.unobserve(host);
					continue;
				}
				const width = Math.round(e.contentRect.width);
				if (host.__bo_width === width) continue;
				host.__bo_width = width;
				if (host.__bo_d) render_chart(host, host.__bo_d, (host.__bo_w && host.__bo_w.options) || {});
			}
		});
	return resize_observer;
}

function view(w, d) {
	if (w.type === "beeone.chart") return `<div class="bo-chart-host"></div>`;
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
