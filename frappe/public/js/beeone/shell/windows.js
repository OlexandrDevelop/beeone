// Window manager of the desktop shell (docs/platform/SHELL.md §3, §4).
// Frappe builds its pages as usual; the core moves the page element into a window body.
// Animations: element.animate with transform and opacity only. No timers, no animation frames.
// The loader skeleton moves its light with a CSS animation (transform only).

const MIN_W = 380;
const MIN_H = 260;
const MAX_LIVE = 10;
const MAX_RESTORE = 12;
const RM = window.matchMedia("(prefers-reduced-motion: reduce)");
const EASE = "cubic-bezier(.16,1,.3,1)";
const esc = (v) => frappe.utils.escape_html(v == null ? "" : String(v));
const icon = (n, c) => beeone.ui.icon(n, c);

const SIZES = { Form: [860, 600], List: [900, 560], Tree: [900, 560], "query-report": [980, 600], page: [980, 600] };

export const wins = {
	map: new Map(), // key -> window
	order: [], // keys in order of opening (task bar order)
	z: [], // keys, the last is on top
	active: null,
	cascade: 0,
	desktop_hidden: null, // keys hidden by "show desktop"
	syncing: false,
};

// ------------------------------------------------------------------ keys

export function kind_of(route) {
	const head = route[0];
	if (head === "Form") return "form";
	if (head === "List" || head === "Tree" || head === "Report") return "list";
	if (head === "query-report") return "report";
	return "page";
}

export function route_key(route) {
	route = route.map(String);
	if (route[0] === "Form") return ["Form", route[1], route.length > 2 ? route.slice(2).join("/") : route[1]].join("/");
	if (route[0] === "query-report") return "query-report/" + route.slice(1).join("/");
	return route.join("/");
}

// routes that show the desktop and open no window; apps add the routes of their former home pages
export const desktop_routes = ["", "desk", "home", "workspaces", "beeone-desktop", "ua-home", "ut-home"];
// pages that should show desktop, not open as windows
const desktop_pages = ["home", "ua-home", "workspaces", "beeone-desktop"];
export function is_window_route(route) {
	if (!route || !route.length) return false;
	const head = String(route[0]).toLowerCase();
	// beeone: /desk/something - check if it's a known desktop page or a window route type
	if (head === "desk" && route.length > 1) {
		const second = String(route[1]).toLowerCase();
		// Explicit window route types
		if (["form", "list", "tree", "query-report"].includes(second)) return true;
		// Shell prefixes: /desk/ua-core/ua-sales-invoice/... is a form in the ua-core shell
		if (route.length > 2) {
			const third = String(route[2]).toLowerCase();
			if (["form", "list", "tree"].includes(third)) return true;
		}
		// Known desktop pages
		if (desktop_pages.includes(second)) return false;
		// Unknown /desk/* routes are treated as custom pages = window routes (e.g., /desk/ua-osv, /desk/ua-account-card)
		return true;
	}
	return !desktop_routes.includes(head);
}

const desk_el = () => document.getElementById("bo-wins");
const compact = () => document.body.classList.contains("bo-compact");

function desk_size() {
	const el = desk_el();
	return { w: el.clientWidth, h: el.clientHeight };
}

// ------------------------------------------------------------------ animation helper

function anim(el, frames, ms, done) {
	if (RM.matches || !el.animate) {
		done && done();
		return;
	}
	el.classList.add("is-moving");
	const a = el.animate(frames, { duration: ms, easing: EASE });
	const end = () => {
		el.classList.remove("is-moving");
		done && done();
	};
	a.onfinish = end;
	a.oncancel = end;
}

const tf = (x, y, s) => `translate(${x}px, ${y}px)` + (s === undefined ? "" : ` scale(${s})`);

// ------------------------------------------------------------------ geometry

function geometry(win) {
	if (win.state === "maximized") {
		const { w, h } = desk_size();
		return { x: 0, y: 0, w, h };
	}
	return { x: win.x, y: win.y, w: win.w, h: win.h };
}

function place(win) {
	const g = geometry(win);
	const s = win.el.style;
	s.width = g.w + "px";
	s.height = g.h + "px";
	s.transform = tf(g.x, g.y);
	tell_size(win, g);
}

// The page layout follows the WINDOW width, not the viewport (SHELL.md §13): `data-bw` on .bo-win lists the thresholds the body
// is narrower than ("lt560 lt720 ..."), `--bo-body-h` is the body height. No ResizeObserver and no CSS container: both made every
// window animation of the T-539 budget slower. The size is known here, so nothing is measured.
const BW = [560, 720, 900, 1024, 1440, 1600];

function tell_size(win, g) {
	if (!win.body) return;
	const compact = document.body.classList.contains("bo-compact");
	const full = compact || win.state === "maximized";
	const dw = compact ? desk_size().w : g.w;
	const dh = compact ? desk_size().h : g.h;
	const w = dw - (full ? 0 : 2);
	const h = dh - 44 - (full ? 0 : 2);
	const set = () => {
		const tokens = BW.filter((n) => w < n).map((n) => "lt" + n).join(" ");
		if (win.el.dataset.bw !== tokens) win.el.dataset.bw = tokens;
		if (win.body_h !== h) {
			win.body_h = h;
			win.body.style.setProperty("--bo-body-h", h + "px");
			// a list sizes its scrollbox from the window; no resize event fires for a maximize/restore
			const l = window.cur_list;
			if (l?.view === "List" && l.$result?.[0] && win.body.contains(l.$result[0])) {
				l.set_result_height();
				l.render_virtual_rows?.(true, 0, l.get_virtual_restore_scroll_top?.() ?? null);
			}
		}
	};
	// the first size at once; a later one when the window has settled: restyling the whole page of a window in the middle of
	// its maximize/restore animation, or on every step of a drag, costs frames (T-539 B6)
	if (!win.size_set) {
		win.size_set = true;
		return set();
	}
	clearTimeout(win.size_timer);
	win.size_timer = setTimeout(set, 280);
}

function clamp(win) {
	const { w, h } = desk_size();
	win.w = Math.max(MIN_W, Math.min(win.w, w));
	win.h = Math.max(MIN_H, Math.min(win.h, h));
	win.x = Math.max(80 - win.w, Math.min(win.x, w - 80));
	win.y = Math.max(0, Math.min(win.y, Math.max(0, h - 44)));
}

// a newly opened window lies wholly inside the desk, so its buttons are never cut off (clamp lets a dragged one hang out)
function fit(win) {
	const { w, h } = desk_size();
	win.x = Math.max(0, Math.min(win.x, w - win.w));
	win.y = Math.max(0, Math.min(win.y, h - win.h));
}

// ------------------------------------------------------------------ create

// the title of a command as the app named it (a catalog "Items"), else the translated DocType name
export function label_of(route) {
	const head = route[0];
	for (const section of beeone.shell.sections || []) {
		for (const c of section.commands) {
			if ((head === "List" || head === "Tree" || head === "Form") && ["doctype", "tree", "single"].includes(c.type) && c.target === route[1]) return c.label;
			if (head === "query-report" && c.type === "report" && c.target === route[1]) return c.label;
			if (c.type === "page" && c.target === head) return c.label;
		}
	}
	return "";
}

function title_of(route, kind) {
	if (kind === "form") {
		const name = route.slice(2).join("/");
		if (/^new-/.test(name)) return __("New {0}", [__(route[1])]);
		return name === route[1] ? label_of(route) || __(name) : name; // a single document is titled by its type
	}
	if (kind === "report") return label_of(route) || __(route[1] || "");
	if (kind === "list") return label_of(route) || __(route[1]);
	const doc = (window.locals && locals.Page && locals.Page[route[0]]) || null;
	return label_of(route) || (doc && __(doc.title)) || route[0];
}

function sub_of(route, kind) {
	if (kind === "form") return label_of(["List", route[1]]) || __(route[1]);
	if (kind === "list") return route[0] === "Tree" ? __("Tree") : route[2] && route[2] !== "List" ? __(route[2]) : __("List");
	if (kind === "report") return __("Report");
	return "";
}

const ICONS = { form: "file", list: "book", report: "chart", page: "layout" };

function make_el(win) {
	const el = document.createElement("section");
	el.className = "bo-win";
	el.setAttribute("role", "dialog");
	el.setAttribute("aria-modal", "false");
	el.dataset.key = win.key;
	el.innerHTML =
		`<header class="bo-win-bar"><span class="bo-win-ico">${icon(ICONS[win.kind])}</span>` +
		`<div class="bo-win-t"><b class="bo-win-title"></b><small class="bo-win-sub"></small></div><i class="bo-win-dirty" hidden></i>` +
		`<div class="bo-win-btns">` +
		`<button type="button" data-act="min" title="${esc(__("Minimize"))} (Alt M)" aria-label="${esc(__("Minimize"))}">${icon("minus")}</button>` +
		`<button type="button" data-act="max" title="${esc(__("Maximize"))} (Alt ↑)" aria-label="${esc(__("Maximize"))}">${icon("square")}</button>` +
		`<button type="button" data-act="close" class="is-close" title="${esc(__("Close"))} (Alt Q)" aria-label="${esc(__("Window: close"))}">${icon("x")}</button>` +
		`</div></header><div class="bo-win-body"></div>` +
		["n", "s", "e", "w", "ne", "nw", "se", "sw"].map((d) => `<i class="bo-rz bo-rz-${d}" data-d="${d}"></i>`).join("");
	win.el = el;
	win.body = el.querySelector(".bo-win-body");
	win.title_el = el.querySelector(".bo-win-title");
	el.querySelector(".bo-win-title").id = "bo-wt-" + (wins.map.size + 1) + "-" + Math.random().toString(36).slice(2, 6);
	el.setAttribute("aria-labelledby", win.title_el.id);
	set_title(win, win.title || title_of(win.route, win.kind), sub_of(win.route, win.kind));
	desk_el().appendChild(el);
}

function set_title(win, title, sub) {
	win.title = title;
	win.title_el.textContent = title;
	win.el.querySelector(".bo-win-sub").textContent = sub || "";
	win.el.querySelector(".bo-win-sub").hidden = !sub;
}

export function create(route, opts = {}) {
	const kind = kind_of(route);
	const key = opts.key || route_key(route);
	const size = SIZES[kind === "list" ? route[0] === "Tree" ? "Tree" : "List" : kind === "form" ? "Form" : kind === "report" ? "query-report" : "page"];
	const { w: dw, h: dh } = desk_size();
	const step = (wins.cascade++ % 6) * 32;
	const win = {
		key,
		route,
		kind,
		state: opts.state || "normal",
		prev: opts.prev || null,
		x: opts.x != null ? opts.x : 24 + step,
		y: opts.y != null ? opts.y : 20 + step,
		w: opts.w || Math.min(size[0], dw),
		h: opts.h || Math.min(size[1], dh),
		page: null,
		parked: !!opts.parked,
		dirty: false,
		last: Date.now(),
		title: opts.title || "",
	};
	make_el(win);
	clamp(win);
	if (opts.x == null && opts.y == null) fit(win);
	place(win);
	wins.map.set(key, win);
	wins.order.push(key);
	wins.z.push(key);
	if (win.parked) {
		win.el.classList.add("is-parked");
		win.el.classList.remove("is-chromeless");
		show_placeholder(win);
	}
	if (win.state === "minimized") win.el.classList.add("is-min");
	beeone.shell.taskbar.render();
	return win;
}

// ------------------------------------------------------------------ hosting a Frappe page

function show_placeholder(win) {
	win.body.innerHTML = `<div class="bo-win-parked"><p>${esc(__("Unloaded from memory, will open again"))}</p>` +
		`<button type="button" class="bo-btn bo-btn--primary" data-act="load">${esc(__("Open"))}</button></div>`;
}

// ------------------------------------------------------------------ loading

// What a window shows from the click until Frappe hands it the page: a skeleton of the kind of window
// (form: head, fields, table; list and others: rows) under a moving light, and a thin running bar on top.
function loader_html(kind) {
	const line = (w, cls = "") => `<i class="bo-sk ${cls}" style="--w:${w}"></i>`;
	let body;
	if (kind === "form") {
		const field = (w) => `<div class="bo-sk-field">${line("38%", "is-label")}${line(w, "is-input")}</div>`;
		body =
			`<div class="bo-sk-head">${line("34%", "is-title")}<span class="bo-sk-btns">${line("120px", "is-btn")}${line("28px", "is-btn")}${line("28px", "is-btn")}</span></div>` +
			`<div class="bo-sk-card"><div class="bo-sk-tabs">${line("64px")}${line("80px")}${line("72px")}</div>` +
			`<div class="bo-sk-grid">${["100%", "100%", "100%", "100%", "100%", "100%"].map(field).join("")}</div></div>` +
			`<div class="bo-sk-card">${line("90px", "is-tab")}${[0, 1, 2, 3].map(() => `<div class="bo-sk-row">${line("6%")}${line("40%")}${line("12%")}${line("14%")}${line("16%")}</div>`).join("")}</div>`;
	} else {
		body =
			`<div class="bo-sk-head">${line("28%", "is-title")}<span class="bo-sk-btns">${line("96px", "is-btn")}</span></div>` +
			`<div class="bo-sk-card">${[0, 1, 2, 3, 4, 5, 6].map(() => `<div class="bo-sk-row">${line("4%")}${line("36%")}${line("18%")}${line("14%")}${line("16%")}</div>`).join("")}</div>`;
	}
	return (
		`<div class="bo-win-loader" role="status" aria-live="polite"><span class="bo-sr">${esc(__("Loading..."))}</span>` +
		`<span class="bo-load-bar" aria-hidden="true"></span><div class="bo-sk-wrap" aria-hidden="true">${body}</div></div>`
	);
}

function show_loader(win) {
	win.loading = true;
	win.el.classList.add("is-loading");
	win.el.classList.remove("is-chromeless");
	win.body.innerHTML = loader_html(win.kind);
}

// the page has arrived: the skeleton fades out over it and removes itself
function end_loader(win) {
	if (!win.loading) return;
	win.loading = false;
	win.el.classList.remove("is-loading");
	const el = win.body.querySelector(":scope > .bo-win-loader");
	if (!el) return;
	if (RM.matches) return el.remove();
	const a = el.animate([{ opacity: 1 }, { opacity: 0 }], { duration: 160, easing: "ease-out", fill: "forwards" });
	a.onfinish = () => el.remove();
}

// called on every route change: a window route whose page is not built yet gets its window at once,
// with the loader, so the click answers immediately; host() puts the page into this same window
export function pending(route) {
	if (!is_window_route(route)) return;
	const key = route_key(route);
	let win = wins.map.get(key);
	if (win && win.page) return;
	const fresh = !win;
	if (!win) win = create(route, { state: "normal" });
	show_loader(win);
	wins.syncing = true;
	focus(key, { route: false });
	wins.syncing = false;
	if (fresh && !RM.matches) open_anim(win);
}

// called by frappe.container.change_to for every page; the current route says which window it is
export function host(page) {
	const route = frappe.get_route();
	if (!is_window_route(route)) {
		$(page).hide();
		blur();
		return;
	}
	const key = route_key(route);
	let win = wins.map.get(key);
	const fresh = !win;
	if (!win) win = create(route, { state: "normal" });
	if (win.page !== page) {
		if (win.page) destroy_page(win, true);
		// the loader stays on top of the arriving page and fades out once the page is in
		const loader = win.loading ? win.body.querySelector(":scope > .bo-win-loader") : null;
		win.body.textContent = "";
		if (loader) win.body.appendChild(loader);
		// beeone: ensure page is visible before appending to window, as Frappe may need visibility for initialization
		$(page).show();
		win.body.appendChild(page);
		win.page = page;
		win.parked = false;
		win.el.classList.remove("is-parked");
		if (win.kind === "form" || win.kind === "list") page.dataset.boKey = key;
	}
	// a form window has no title bar of its own: the page head of the form is its drag handle
	win.el.classList.toggle("is-chromeless", win.kind === "form");
	$(page).show();
	win.route = route;
	win.el.dataset.key = key;
	refresh_title(win);
	wins.syncing = true;
	focus(key, { route: false, animate: fresh });
	wins.syncing = false;
	end_loader(win);
	enforce_limit();
}

// the element that scrolls in a window: the page body under the fixed page head, else the window body
function scroller(body) {
	return (body && body.querySelector(":scope > .page-container > .page-body")) || body;
}

export function scroll_parent(element) {
	const node = element && element.nodeType ? element : null;
	const own = node && node.closest && node.closest(".bo-win-body");
	if (own) return scroller(own);
	const win = wins.map.get(wins.active);
	return win ? scroller(win.body) : null;
}

// a new document got its real name: the page and the window keep living, only the key changes
export function adopt_renamed(key, route) {
	const name = route.slice(2).join("/");
	const news = frappe.model.new_names || {};
	const old = Object.keys(news).find((o) => news[o] === name);
	if (!old) return;
	const old_key = `Form/${route[1]}/${old}`;
	const win = wins.map.get(old_key);
	if (!win || wins.map.has(key)) return;
	const page = frappe.views.formview[old_key];
	if (page) {
		delete frappe.views.formview[old_key];
		delete frappe.pages[old_key];
		frappe.views.formview[key] = page;
		frappe.pages[key] = page;
		page.label = key;
	}
	rekey(old_key, key, route);
}

function rekey(old_key, key, route) {
	const win = wins.map.get(old_key);
	wins.map.delete(old_key);
	wins.map.set(key, win);
	const swap = (list) => {
		const i = list.indexOf(old_key);
		if (i >= 0) list[i] = key;
	};
	swap(wins.order);
	swap(wins.z);
	if (wins.active === old_key) wins.active = key;
	win.key = key;
	win.route = route;
	win.el.dataset.key = key;
	if (win.page) win.page.dataset.boKey = key;
	beeone.shell.taskbar.render();
	beeone.shell.save_soon();
}

export function refresh_title(win) {
	if (!win.page) return;
	if (win.kind === "form") {
		const frm = win.page.frm;
		if (frm && frm.doc) {
			let title = frm.doc.name;
			const meta = frappe.get_meta(frm.doctype);
			if (meta && meta.issingle) title = label_of(["Form", frm.doctype]) || __(frm.doctype);
			else if (frm.is_new()) title = __("New {0}", [__(frm.doctype)]);
			else if (meta && meta.title_field && meta.title_field !== "name" && frm.doc[meta.title_field] && (!meta.is_submittable || meta.opaque_name))
				title = frm.doc[meta.title_field];
			set_title(win, title, meta && meta.issingle ? "" : label_of(["List", frm.doctype]) || __(frm.doctype));
		}
		set_dirty(win, !!(frm && frm.doc && frm.doc.__unsaved));
	} else if (win.kind === "page" || win.kind === "report") {
		const t = $(win.page).find(".page-title .title-text").first().text().trim();
		if (t && win.kind === "page") set_title(win, t, "");
	}
}

function set_dirty(win, on) {
	if (win.dirty === on) return;
	win.dirty = on;
	win.el.querySelector(".bo-win-dirty").hidden = !on;
	beeone.shell.taskbar.render();
}

// ------------------------------------------------------------------ memory: park and close

function destroy_page(win, keep_window) {
	const page = win.page;
	if (!page) return;
	const label = page.label;
	if (page.frm && window.cur_frm === page.frm) window.cur_frm = null;
	if (frappe.container.page === page) frappe.container.page = null;
	try {
		$(page).trigger("hide");
	} catch (e) {
		// a page script may fail on hide: the window closes anyway
	}
	delete frappe.pages[label];
	["formview"].forEach((reg) => frappe.views[reg] && delete frappe.views[reg][label]);
	if (frappe.views.list_view) delete frappe.views.list_view[label];
	if (cur_list && cur_list.page === page.page) window.cur_list = null;
	$(page).remove();
	win.page = null;
	if (!keep_window) win.body.textContent = "";
}

export function park(key) {
	const win = wins.map.get(key);
	if (!win || win.parked || win.dirty) return false;
	destroy_page(win);
	win.parked = true;
	win.el.classList.add("is-parked");
	win.el.classList.remove("is-chromeless");
	show_placeholder(win);
	beeone.shell.taskbar.render();
	return true;
}

function enforce_limit() {
	const live = [...wins.map.values()].filter((w) => !w.parked && w.page);
	if (live.length <= MAX_LIVE) return;
	const pick = (list) => list.filter((w) => !w.dirty && w.key !== wins.active).sort((a, b) => a.last - b.last)[0];
	const victim = pick(live.filter((w) => w.state === "minimized")) || pick(live);
	if (victim) park(victim.key);
}

// ------------------------------------------------------------------ focus and states

function visible_top() {
	for (let i = wins.z.length - 1; i >= 0; i--) {
		const w = wins.map.get(wins.z[i]);
		if (w && w.state !== "minimized") return w;
	}
	return null;
}

function apply_z() {
	wins.z.forEach((k, i) => {
		const w = wins.map.get(k);
		if (w.zi !== i) {
			w.zi = i;
			w.el.style.zIndex = 10 + i;
		}
	});
}

function paint_state() {
	// only what changed is written: a class on one window is cheap, a class on the body is not
	wins.map.forEach((w) => {
		const sig = (w.key === wins.active ? "a" : "") + w.state;
		if (w.sig === sig) return;
		w.sig = sig;
		w.el.classList.toggle("is-active", w.key === wins.active);
		w.el.classList.toggle("is-max", w.state === "maximized");
		w.el.classList.toggle("is-min", w.state === "minimized");
		const max_btn = w.el.querySelector('[data-act="max"]');
		const label = w.state === "maximized" ? __("Restore size") : __("Maximize");
		max_btn.setAttribute("aria-label", label);
		max_btn.title = label + " (Alt ↑)";
		max_btn.firstElementChild.firstElementChild.setAttribute("href", w.state === "maximized" ? "#bo-i-restore" : "#bo-i-square");
	});
	apply_z();
	beeone.shell.taskbar.render();
}

export function focus(key, opts = {}) {
	const win = wins.map.get(key);
	if (!win) return;
	const was_min = win.state === "minimized";
	// Frappe refreshes the page of a route: that work waits until the animation is over
	const sync = () => {
		if (opts.route !== false && wins.map.get(key) === win && wins.active === key) route_to(win);
	};
	if (was_min) {
		win.state = win.prev === "maximized" ? "maximized" : "normal";
		win.prev = null;
		place(win);
		win.el.classList.remove("is-min");
	}
	wins.z = wins.z.filter((k) => k !== key).concat(key);
	const changed = wins.active !== key;
	wins.active = key;
	win.last = Date.now();
	wins.desktop_hidden = null;
	paint_state();
	if (changed || was_min) beeone.shell.announce(__("Window opened: {0}", [win.title]));
	if (was_min) restore_anim(win, sync);
	else if (opts.animate === true && win.page) open_anim(win);
	if (!was_min) sync();
	beeone.shell.track(win);
	beeone.shell.save_soon();
	if (changed) beeone.shell.desk.on_visibility();
}

function route_to(win) {
	const now = frappe.get_route();
	const same = is_window_route(now) && route_key(now) === win.key;
	if (win.parked || !win.page) {
		wins.syncing = true;
		frappe.set_route(...win.route);
		wins.syncing = false;
		return;
	}
	if (!same) {
		wins.syncing = true;
		frappe.set_route(...win.route);
		wins.syncing = false;
	}
}

export function blur() {
	wins.active = null;
	paint_state();
	beeone.shell.desk.on_visibility();
}

function task_rect(key) {
	const btn = document.querySelector(`#bo-task [data-key="${CSS.escape(key)}"]`);
	return btn ? btn.getBoundingClientRect() : null;
}

function open_anim(win) {
	const g = geometry(win);
	anim(win.el, [{ transform: tf(g.x, g.y, 0.96), opacity: 0 }, { transform: tf(g.x, g.y, 1), opacity: 1 }], 180);
}

function restore_anim(win, done) {
	const g = geometry(win);
	const r = task_rect(win.key);
	const base = desk_el().getBoundingClientRect();
	if (!r) return anim(win.el, [{ transform: tf(g.x, g.y, 0.96), opacity: 0 }, { transform: tf(g.x, g.y, 1), opacity: 1 }], 180, done);
	const fx = r.left + r.width / 2 - base.left - (g.x + g.w / 2);
	const fy = r.top - base.top - (g.y + g.h / 2);
	anim(win.el, [{ transform: tf(g.x + fx, g.y + fy, 0.2), opacity: 0 }, { transform: tf(g.x, g.y, 1), opacity: 1 }], 240, done);
}

export function minimize(key) {
	const win = wins.map.get(key);
	if (!win || win.state === "minimized") return;
	const g = geometry(win);
	const r = task_rect(key);
	const base = desk_el().getBoundingClientRect();
	win.prev = win.state === "maximized" ? "maximized" : null;
	const fx = r ? r.left + r.width / 2 - base.left - (g.x + g.w / 2) : 0;
	const fy = r ? r.top - base.top - (g.y + g.h / 2) : 40;
	const done = () => {
		win.state = "minimized";
		win.el.classList.add("is-min");
		if (wins.active === key) {
			const next = visible_top();
			wins.active = next ? next.key : null;
			if (next) route_to(next);
		}
		paint_state();
		beeone.shell.save_soon();
		beeone.shell.desk.on_visibility();
		beeone.shell.announce(__("Window minimized: {0}", [win.title]));
	};
	anim(win.el, [{ transform: tf(g.x, g.y, 1), opacity: 1 }, { transform: tf(g.x + fx, g.y + fy, 0.2), opacity: 0 }], 260, done);
}

export function toggle_max(key) {
	const win = wins.map.get(key);
	if (!win || compact()) return;
	const from = geometry(win);
	win.state = win.state === "maximized" ? "normal" : "maximized";
	const to = geometry(win);
	place(win);
	paint_state();
	// FLIP from the old frame: the centre of the old frame, scaled to its size (transform only)
	const dx = from.x + from.w / 2 - (to.x + to.w / 2);
	const dy = from.y + from.h / 2 - (to.y + to.h / 2);
	anim(
		win.el,
		[
			{ transform: tf(to.x + dx, to.y + dy) + ` scale(${from.w / to.w}, ${from.h / to.h})` },
			{ transform: tf(to.x, to.y) + " scale(1, 1)" },
		],
		220
	);
	beeone.shell.save_soon();
	beeone.shell.desk.on_visibility();
}

export function toggle_min(key) {
	const win = wins.map.get(key);
	if (!win) return;
	if (win.state === "minimized") focus(key);
	else if (wins.active === key) minimize(key);
	else focus(key);
}

export function show_desktop() {
	if (wins.desktop_hidden) {
		const keys = wins.desktop_hidden;
		wins.desktop_hidden = null;
		keys.forEach((k) => {
			const w = wins.map.get(k);
			if (w && w.state === "minimized") {
				w.state = w.prev === "maximized" ? "maximized" : "normal";
				w.prev = null;
				w.el.classList.remove("is-min");
				place(w);
				restore_anim(w);
			}
		});
		const top = keys.map((k) => wins.map.get(k)).filter(Boolean).pop();
		paint_state();
		if (top) focus(top.key);
		return;
	}
	const open = [...wins.map.values()].filter((w) => w.state !== "minimized");
	if (!open.length) return;
	open.forEach((w) => minimize(w.key));
	wins.desktop_hidden = open.map((w) => w.key);
	blur();
	if (is_window_route(frappe.get_route())) {
		wins.syncing = true;
		frappe.set_route("beeone-desktop");
		wins.syncing = false;
	}
}

// ------------------------------------------------------------------ close

export function close(key, force) {
	const win = wins.map.get(key);
	if (!win) return;
	refresh_title(win);
	if (win.dirty && !force) return confirm_close(win);
	const finish = () => {
		destroy_page(win);
		clearTimeout(win.size_timer);
		win.el.remove();
		wins.map.delete(key);
		wins.order = wins.order.filter((k) => k !== key);
		wins.z = wins.z.filter((k) => k !== key);
		const was_active = wins.active === key;
		if (was_active) {
			const next = visible_top();
			wins.active = next ? next.key : null;
			if (next) route_to(next);
			else if (is_window_route(frappe.get_route())) {
				wins.syncing = true;
				frappe.set_route("beeone-desktop");
				wins.syncing = false;
			}
		}
		paint_state();
		beeone.shell.save_soon();
		beeone.shell.desk.on_visibility();
		beeone.shell.announce(__("Window closed: {0}", [win.title]));
	};
	const g = geometry(win);
	if (win.state === "minimized") return finish();
	anim(win.el, [{ transform: tf(g.x, g.y, 1), opacity: 1 }, { transform: tf(g.x, g.y, 0.96), opacity: 0 }], 140, finish);
}

function confirm_close(win) {
	focus(win.key);
	if (win.sheet) return;
	// a screen-level dialog on <body>: a window is transformed, so nothing inside it can cover the viewport
	const dlg = beeone.ui.dialog({
		className: "bo-sheet",
		role: "alertdialog",
		title: __("Save changes?"),
		width: 440,
		html:
			`<div class="bo-dialog-head"><h3>${esc(__("Save changes?"))}</h3></div>` +
			`<div class="bo-dialog-body"><p>${esc(__('"{0}" has changes. If you close it without saving, the changes will be lost.', [win.title]))}</p></div>` +
			`<div class="bo-dialog-foot"><button type="button" class="bo-btn bo-btn--ghost" data-s="cancel" data-close>${esc(__("Cancel"))}</button>` +
			`<button type="button" class="bo-btn" data-s="drop">${esc(__("Don't save"))}</button>` +
			`<button type="button" class="bo-btn bo-btn--primary" data-s="save" autofocus>${esc(__("Save and close"))}</button></div>`,
		on_close: () => {
			win.sheet = null;
		},
	});
	win.sheet = dlg;
	dlg.el.addEventListener("click", (e) => {
		const act = e.target.closest("[data-s]");
		if (!act) return;
		const what = act.dataset.s;
		dlg.close();
		if (what === "drop") close(win.key, true);
		if (what === "save" && win.page && win.page.frm) {
			win.page.frm.save(null, () => close(win.key, true));
		}
	});
}

// ------------------------------------------------------------------ pointer: focus, drag, resize

const INTERACTIVE = "button, a, input, select, textarea, label, [role=button], [role=menuitem], [role=tab], .dropdown-menu, [contenteditable=true], [data-act]";

// the window bar, or (chromeless form window) the free area of the form page head
function is_drag_handle(target, el) {
	if (target.closest("[data-act]")) return false;
	if (target.closest(".bo-win-bar")) return true;
	return el.classList.contains("is-chromeless") && !!target.closest(".bo-win-body .page-head") && !target.closest(INTERACTIVE);
}

export function init_pointer() {
	const layer = desk_el();
	layer.addEventListener(
		"pointerdown",
		(e) => {
			const el = e.target.closest(".bo-win");
			if (!el) return;
			const win = wins.map.get(el.dataset.key);
			if (!win) return;
			if (wins.active !== win.key) focus(win.key);
			const btn = e.target.closest("[data-act]");
			if (btn) return;
			const rz = e.target.closest(".bo-rz");
			if (rz && !compact() && win.state === "normal") return start_drag(e, win, rz.dataset.d);
			if (is_drag_handle(e.target, el) && !compact() && win.state === "normal") start_drag(e, win, "move");
		},
		true
	);
	layer.addEventListener("click", (e) => {
		const btn = e.target.closest("[data-act]");
		if (!btn) return;
		// only the window's own buttons (a page may use data-act and re-render, which detaches its button)
		const own = btn.closest(".bo-win-bar, .bo-win-parked");
		const host = own && own.closest(".bo-win");
		const win = host && wins.map.get(host.dataset.key);
		if (!win) return;
		const act = btn.dataset.act;
		if (act === "min") minimize(win.key);
		else if (act === "max") toggle_max(win.key);
		else if (act === "close") close(win.key);
		else if (act === "load") focus(win.key);
	});
	layer.addEventListener("dblclick", (e) => {
		const el = e.target.closest(".bo-win");
		if (el && is_drag_handle(e.target, el)) toggle_max(el.dataset.key);
	});
	// the dirty mark follows the form of the window
	layer.addEventListener("input", mark_dirty, true);
	layer.addEventListener("change", mark_dirty, true);
	$(document).on("form-refresh form-load", (e, frm) => {
		const win = frm && wins.map.get(`Form/${frm.doctype}/${frm.docname}`);
		if (win) refresh_title(win);
	});
	window.addEventListener("resize", () => {
		wins.map.forEach((w) => {
			clamp(w);
			place(w);
		});
		document.body.classList.toggle("bo-compact", window.innerWidth < 900 || window.innerHeight < 560);
	});
}

function mark_dirty(e) {
	const el = e.target.closest && e.target.closest(".bo-win");
	const win = el && wins.map.get(el.dataset.key);
	if (win && win.kind === "form") setTimeout(() => refresh_title(win), 0);
}

function start_drag(e, win, dir) {
	e.preventDefault();
	const start = { x: e.clientX, y: e.clientY, wx: win.x, wy: win.y, ww: win.w, wh: win.h };
	const { w: dw, h: dh } = desk_size();
	win.el.classList.add("is-moving", "is-drag");
	win.el.setPointerCapture && win.el.setPointerCapture(e.pointerId);
	const move = (ev) => {
		const dx = ev.clientX - start.x;
		const dy = ev.clientY - start.y;
		let { wx: x, wy: y, ww: w, wh: h } = start;
		if (dir === "move") {
			x = Math.max(80 - w, Math.min(start.wx + dx, dw - 80));
			y = Math.max(0, Math.min(start.wy + dy, dh - 44));
		} else {
			if (dir.includes("e")) w = Math.max(MIN_W, Math.min(start.ww + dx, dw - x));
			if (dir.includes("s")) h = Math.max(MIN_H, Math.min(start.wh + dy, dh - y));
			if (dir.includes("w")) {
				w = Math.max(MIN_W, start.ww - dx);
				x = start.wx + start.ww - w;
			}
			if (dir.includes("n")) {
				h = Math.max(MIN_H, start.wh - dy);
				y = Math.max(0, start.wy + start.wh - h);
				h = start.wy + start.wh - y;
			}
		}
		win.x = x;
		win.y = y;
		win.w = w;
		win.h = h;
		place(win);
	};
	const up = () => {
		win.el.classList.remove("is-moving", "is-drag");
		win.el.removeEventListener("pointermove", move);
		win.el.removeEventListener("pointerup", up);
		win.el.removeEventListener("pointercancel", up);
		beeone.shell.save_soon();
	};
	win.el.addEventListener("pointermove", move);
	win.el.addEventListener("pointerup", up);
	win.el.addEventListener("pointercancel", up);
}

// ------------------------------------------------------------------ layout in and out

export function snapshot() {
	const windows = wins.order
		.map((k) => wins.map.get(k))
		.filter((w) => w && !/\/new-/.test(w.key))
		.slice(0, MAX_RESTORE)
		.map((w) => {
			const item = { key: w.key, route: w.route.map(String), x: w.x, y: w.y, w: w.w, h: w.h, state: w.state };
			if (w.prev) item.prev = w.prev;
			if (w.title) item.title = w.title;
			return item;
		});
	const keys = new Set(windows.map((w) => w.key));
	return {
		windows,
		z: wins.z.filter((k) => keys.has(k)),
		active: keys.has(wins.active) ? wins.active : null,
	};
}

export function restore(layout, readable) {
	const items = (layout.windows || []).filter((w) => readable(w.route)).slice(0, MAX_RESTORE);
	const order = layout.z || [];
	items.forEach((w) => {
		if (wins.map.has(w.key)) return;
		create(w.route, { ...w, parked: true });
	});
	wins.z = [...order.filter((k) => wins.map.has(k)), ...wins.z.filter((k) => !order.includes(k))];
	paint_state();
	return layout.active && wins.map.has(layout.active) ? wins.map.get(layout.active) : null;
}

export function list() {
	return wins.order.map((k) => wins.map.get(k)).filter(Boolean);
}
