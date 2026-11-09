// Rail, function panel, search, task bar, top bar and hotkeys (docs/platform/SHELL.md §2, §3.4, §3.5).
import { wins, focus, minimize, toggle_max, toggle_min, close, show_desktop, list, kind_of } from "./windows.js";

const esc = (v) => frappe.utils.escape_html(v == null ? "" : String(v));
const icon = (n, c) => beeone.ui.icon(n, c);
const RM = window.matchMedia("(prefers-reduced-motion: reduce)");
const COLUMNS = [
	{ key: "docs", title: () => __("Documents"), icon: "file" },
	{ key: "refs", title: () => __("Catalogs"), icon: "book" },
	{ key: "reps", title: () => __("Reports"), icon: "chart" },
	{ key: "svc", title: () => __("Service"), icon: "gear" },
];

// ------------------------------------------------------------------ commands

export function command_route(cmd) {
	const t = cmd.target;
	switch (cmd.type) {
		case "doctype":
			return ["List", t];
		case "tree":
			return ["Tree", t];
		case "single":
			return ["Form", t, t];
		case "report":
			return ["query-report", t];
		case "route":
			return String(t).split("/");
		case "new":
			return ["Form", t, "new"];
		default:
			return [t];
	}
}

export function open_command(cmd) {
	if (cmd.type === "new") return frappe.new_doc(cmd.target);
	frappe.set_route(...command_route(cmd));
}

export function open_route(route) {
	if (route[0] === "Form" && route[2] === "new") return frappe.new_doc(route[1]);
	frappe.set_route(...route);
}

function all_commands() {
	const out = [];
	(beeone.shell.sections || []).forEach((s) => s.commands.forEach((c) => out.push({ ...c, section: s })));
	return out;
}

// ------------------------------------------------------------------ build the DOM

export function build() {
	const user = frappe.session.user_fullname || frappe.session.user;
	const app = document.createElement("div");
	app.id = "bo-app";
	app.innerHTML =
		`<nav id="bo-rail" aria-label="${esc(__("Sections"))}"><div class="bo-rail-top"><span class="bo-logo" aria-hidden="true">${icon("hexagon")}</span></div>` +
		`<div class="bo-rail-list" id="bo-rail-list"></div>` +
		`<div class="bo-rail-bottom"><button type="button" class="bo-rail-btn" data-act="user" title="${esc(user)}" aria-label="${esc(user)}">` +
		`<span class="bo-avatar">${esc(initials(user))}</span></button></div></nav>` +
		`<header id="bo-top"><div class="bo-top-chips" id="bo-chips"></div>` +
		`<button type="button" class="bo-search" data-act="search">${icon("search")}<span>${esc(__("Find a command, report or open window…"))}</span><kbd>Ctrl K</kbd></button>` +
		`<div class="bo-top-end"><button type="button" class="bo-top-btn" data-act="theme" title="${esc(__("Theme"))}" aria-label="${esc(__("Theme"))}">${icon("sun")}</button>` +
		`<button type="button" class="bo-top-btn" data-act="bell" title="${esc(__("Notifications"))}" aria-label="${esc(__("Notifications"))}">${icon("bell")}<i class="bo-dot-badge" hidden></i></button></div></header>` +
		`<main id="bo-desk"><div id="bo-desk-bg"></div><div id="bo-wins"></div></main>` +
		`<footer id="bo-task" role="toolbar" aria-label="${esc(__("Open windows"))}">` +
		`<button type="button" class="bo-task-menu" data-act="sections" aria-label="${esc(__("Sections"))}" aria-expanded="false" aria-controls="bo-panel">${icon("menu")}</button>` +
		`<button type="button" class="bo-task-desk" data-act="desktop" title="${esc(__("Show desktop"))} (Alt D)" aria-label="${esc(__("Show desktop"))}">${icon("layout")}</button>` +
		`<div class="bo-task-list" id="bo-task-list"></div><span class="bo-task-count" id="bo-task-count"></span></footer>` +
		`<div id="bo-panel" role="dialog" aria-modal="false" aria-labelledby="bo-fp-title" hidden></div><div id="bo-live" class="bo-sr" aria-live="polite"></div>`;
	document.body.appendChild(app);
	render_rail();
	app.addEventListener("click", on_click);
	document.getElementById("bo-rail-list").addEventListener("keydown", rail_keys);
	document.addEventListener("mousedown", (e) => {
		const panel = document.getElementById("bo-panel");
		if (!panel.hidden && !e.target.closest("#bo-panel, #bo-rail, .bo-task-menu")) close_panel();
	});
}

function initials(name) {
	return (
		String(name || "")
			.split(/\s+/)
			.filter(Boolean)
			.slice(0, 2)
			.map((w) => w[0])
			.join("")
			.toUpperCase() || "?"
	);
}

function render_rail() {
	const list_el = document.getElementById("bo-rail-list");
	list_el.innerHTML = (beeone.shell.sections || [])
		.map(
			(s) =>
				`<button type="button" class="bo-rail-btn" data-section="${esc(s.id)}" title="${esc(s.label)}" aria-label="${esc(s.label)}" aria-expanded="false" aria-controls="bo-panel">${icon(s.icon)}<span class="bo-rail-label">${esc(s.label)}</span></button>`
		)
		.join("");
}

function on_click(e) {
	const sec = e.target.closest("[data-section]");
	if (sec && sec.closest("#bo-rail")) return toggle_panel(sec.dataset.section);
	const act = e.target.closest("[data-act]");
	if (!act || act.closest(".bo-win")) return;
	const what = act.dataset.act;
	if (what === "search") open_search();
	else if (what === "theme") toggle_theme();
	else if (what === "bell") frappe.set_route("List", "Notification Log");
	else if (what === "desktop") show_desktop();
	else if (what === "sections") toggle_panel(null);
	else if (what === "user") user_menu(act);
}

// ------------------------------------------------------------------ function panel

let panel_section = null;
let panel_opener = null;

const route_key = (route) => route.map(String).join("/");
const norm = (v) => String(v).toLowerCase().replace(/[’ʼ`]/g, "'");

function sync_expanded(open) {
	document.querySelectorAll("#bo-rail [data-section], .bo-task-menu").forEach((b) => {
		const on = open && (b.classList.contains("bo-task-menu") ? panel_section === "*" : b.dataset.section === panel_section);
		b.setAttribute("aria-expanded", on ? "true" : "false");
	});
}

export function close_panel(return_focus) {
	const panel = document.getElementById("bo-panel");
	if (!panel) return;
	const was = panel.hidden ? null : panel_section;
	panel.hidden = true;
	panel_section = null;
	document.querySelectorAll("#bo-rail .is-active").forEach((b) => b.classList.remove("is-active"));
	sync_expanded(false);
	if (return_focus === true && was) {
		const back = panel_opener && document.body.contains(panel_opener) ? panel_opener : document.querySelector(was === "*" ? ".bo-task-menu" : `#bo-rail [data-section="${was}"]`);
		if (back) back.focus();
	}
}

export function open_section(id) {
	const panel = document.getElementById("bo-panel");
	if (panel && !panel.hidden && panel_section === id) return;
	toggle_panel(id);
}

function rail_keys(e) {
	if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
	const btns = [...document.querySelectorAll("#bo-rail-list .bo-rail-btn")];
	const at = btns.indexOf(document.activeElement);
	if (at < 0) return;
	e.preventDefault();
	const to = btns[Math.max(0, Math.min(btns.length - 1, at + (e.key === "ArrowDown" ? 1 : -1)))];
	if (to) to.focus();
}

function animate_open(panel) {
	if (RM.matches || !panel.animate) return;
	panel.animate([{ opacity: 0, transform: "translateX(-8px)" }, { opacity: 1, transform: "none" }], {
		duration: 160,
		easing: "cubic-bezier(.16,1,.3,1)",
	});
}

// order inside a column: main commands, commands without a group, then the groups as they first appear
function column_blocks(items) {
	const mains = items.filter((x) => x.main);
	const rest = items.filter((x) => !x.main);
	const loose = [...mains, ...rest.filter((x) => !x.group)];
	const named = [];
	rest.forEach((x) => {
		if (!x.group) return;
		let g = named.find((n) => n.name === x.group);
		if (!g) named.push((g = { name: x.group, items: [] }));
		g.items.push(x);
	});
	const heads = named.length >= 2 || (named.length === 1 && loose.length > 0);
	const blocks = [];
	if (loose.length) blocks.push({ name: "", items: loose });
	named.forEach((g) => blocks.push({ name: heads ? g.name : "", items: g.items }));
	return blocks;
}

function star_label(cmd, on) {
	return `${on ? __("Remove from favorites") : __("Add to favorites")}: ${cmd.label}`;
}

function row_html(section, x) {
	const i = section.commands.indexOf(x);
	const on = beeone.shell.is_fav(command_route(x));
	return (
		`<div class="bo-fp-row" data-i="${i}"><button type="button" class="bo-fp-cmd${x.main ? " is-main" : ""}" data-i="${i}" title="${esc(x.label)}" tabindex="-1"><span class="bo-fp-lab">${esc(x.label)}</span></button>` +
		`<button type="button" class="bo-fp-star" data-star="${i}" tabindex="-1" aria-pressed="${on}" aria-label="${esc(star_label(x, on))}">${icon("star")}</button></div>`
	);
}

// favourites and recent of this section only: a strip is not drawn when it is empty
function links_html(section) {
	const own = new Set(section.commands.map((c) => route_key(command_route(c))));
	const strip = (key, label, ic, rows) => {
		const picked = rows.filter((r) => own.has(route_key(r.route))).slice(0, 6);
		if (!picked.length) return "";
		return (
			`<div class="bo-fp-strip"><span class="bo-fp-strip-t">${icon(ic, "bo-i-sm")}${esc(label)}:</span>` +
			picked.map((r) => `<button type="button" class="bo-fp-chip" data-link="${key}:${rows.indexOf(r)}">${esc(r.label)}</button>`).join("") +
			"</div>"
		);
	};
	return strip("f", __("Favorites"), "star", beeone.shell.state.favorites || []) + strip("r", __("Recent"), "clock", beeone.shell.state.recent || []);
}

function toggle_panel(id) {
	const panel = document.getElementById("bo-panel");
	const was_open = !panel.hidden;
	if (!id) {
		// compact screens: all sections as a list
		if (was_open && panel_section === "*") return close_panel();
		panel_opener = document.activeElement;
		panel_section = "*";
		panel.hidden = false;
		panel.innerHTML =
			`<h2 id="bo-fp-title" class="bo-sr">${esc(__("Sections"))}</h2><div class="bo-fp-all">${(beeone.shell.sections || [])
				.map((s) => `<button type="button" class="bo-fp-sec" data-section="${esc(s.id)}">${icon(s.icon)}<span>${esc(s.label)}</span></button>`)
				.join("")}</div>`;
		panel.querySelectorAll("[data-section]").forEach((b) => b.addEventListener("click", () => toggle_panel(b.dataset.section)));
		panel.onclick = null;
		panel.oninput = null;
		panel.onkeydown = (e) => {
			if (e.key === "Escape") {
				e.preventDefault();
				e.stopPropagation();
				close_panel(true);
			} else if (e.key === "ArrowDown" || e.key === "ArrowUp") {
				const btns = [...panel.querySelectorAll(".bo-fp-sec")];
				const at = btns.indexOf(document.activeElement);
				e.preventDefault();
				const to = btns[Math.max(0, Math.min(btns.length - 1, at + (e.key === "ArrowDown" ? 1 : -1)))];
				if (to) to.focus();
			}
		};
		sync_expanded(true);
		animate_open(panel);
		const first = panel.querySelector(".bo-fp-sec");
		if (first) first.focus();
		return;
	}
	if (was_open && panel_section === id) return close_panel();
	const section = (beeone.shell.sections || []).find((s) => s.id === id);
	if (!section) return;
	if (!was_open || panel_section === "*") panel_opener = document.activeElement;
	panel_section = id;
	document.querySelectorAll("#bo-rail [data-section]").forEach((b) => b.classList.toggle("is-active", b.dataset.section === id));
	const cols = COLUMNS.map((c, ci) => {
		const items = section.commands.filter((x) => x.column === c.key);
		if (!items.length) return "";
		const body = column_blocks(items)
			.map((g, gi) => {
				const gid = `bo-fp-g${ci}-${gi}`;
				return (
					`<div class="bo-fp-grp"${g.name ? ` role="group" aria-labelledby="${gid}"` : ""}>` +
					(g.name ? `<h4 class="bo-fp-group" id="${gid}">${esc(g.name)}</h4>` : "") +
					g.items.map((x) => row_html(section, x)).join("") +
					"</div>"
				);
			})
			.join("");
		return (
			`<div class="bo-fp-col" role="group" aria-label="${esc(c.title())}, ${items.length}"><h3>${icon(c.icon)}${esc(c.title())}</h3>` +
			`<span class="bo-fp-n" aria-hidden="true">${items.length}</span>${body}</div>`
		);
	}).join("");
	const create = (section.create || [])
		.map((c) => `<button type="button" class="bo-btn bo-btn--sm" data-new="${esc(c.doctype)}">${icon("plus", "bo-i-sm")}${esc(__(c.doctype))}</button>`)
		.join("");
	panel.hidden = false;
	panel.innerHTML =
		`<div class="bo-fp-head"><div><h2 id="bo-fp-title">${esc(section.label)}</h2><p>${esc(section.description)}</p></div>` +
		`<div class="bo-fp-find"><label class="bo-fp-qbox">${icon("search")}<input type="search" class="bo-fp-q" autocomplete="off" spellcheck="false" aria-controls="bo-fp-cols" ` +
		`aria-label="${esc(__("Find in section"))}" placeholder="${esc(__("Find in section…"))}"><kbd>Esc</kbd></label>` +
		`<button type="button" class="bo-fp-all-btn" data-all>${esc(__("Search all sections"))}<kbd>Ctrl K</kbd></button></div></div>` +
		(create ? `<div class="bo-fp-create"><span>${esc(__("Create"))}:</span>${create}</div>` : "") +
		`<div class="bo-fp-links" id="bo-fp-links">${links_html(section)}</div>` +
		`<div class="bo-fp-cols" id="bo-fp-cols">${cols}</div>` +
		`<div class="bo-fp-none" hidden>${esc(__("Nothing found"))}</div>`;
	set_stop(first_visible(panel));
	panel.onclick = (e) => {
		const star = e.target.closest("[data-star]");
		if (star) return toggle_star(panel, section, +star.dataset.star);
		if (e.target.closest("[data-all]")) {
			const q = panel.querySelector(".bo-fp-q").value;
			return open_search(q);
		}
		const link = e.target.closest("[data-link]");
		const cmd = e.target.closest(".bo-fp-cmd");
		const nw = e.target.closest("[data-new]");
		if (link) {
			const [kind, at] = link.dataset.link.split(":");
			const row = (kind === "f" ? beeone.shell.state.favorites : beeone.shell.state.recent)[+at];
			if (row) open_route(row.route);
		} else if (cmd) open_command(section.commands[+cmd.dataset.i]);
		else if (nw) frappe.new_doc(nw.dataset.new);
		else return;
		if (!(e.ctrlKey || e.metaKey)) close_panel();
	};
	panel.oninput = (e) => {
		if (e.target.classList.contains("bo-fp-q")) filter_panel(panel, section, e.target.value);
	};
	panel.onfocusin = (e) => {
		if (e.target.classList.contains("bo-fp-cmd")) set_stop(e.target);
	};
	panel.onkeydown = (e) => panel_keys(e, panel, section);
	sync_expanded(true);
	if (!was_open) animate_open(panel);
	panel.querySelector(".bo-fp-q").focus({ preventScroll: true });
}

function visible_cols(panel) {
	return [...panel.querySelectorAll(".bo-fp-col:not([hidden])")].map((c) => [...c.querySelectorAll(".bo-fp-row:not([hidden]) .bo-fp-cmd")]);
}

function first_visible(panel) {
	return panel.querySelector(".bo-fp-row:not([hidden]) .bo-fp-cmd");
}

// roving tabindex: the grid of commands is one tab stop
function set_stop(btn) {
	const panel = document.getElementById("bo-panel");
	panel.querySelectorAll(".bo-fp-cmd").forEach((b) => b.setAttribute("tabindex", b === btn ? "0" : "-1"));
}

function go(btn) {
	if (!btn) return;
	set_stop(btn);
	btn.focus({ preventScroll: true });
	if (btn.scrollIntoView) btn.scrollIntoView({ block: "nearest" });
}

function run_cmd(section, btn, keep) {
	open_command(section.commands[+btn.dataset.i]);
	if (!keep) close_panel();
}

function toggle_star(panel, section, i) {
	const cmd = section.commands[i];
	if (!cmd) return;
	const on = beeone.shell.toggle_fav({ route: command_route(cmd), label: cmd.label });
	const star = panel.querySelector(`[data-star="${i}"]`);
	if (star) {
		star.setAttribute("aria-pressed", on ? "true" : "false");
		star.setAttribute("aria-label", star_label(cmd, on));
	}
	panel.querySelector("#bo-fp-links").innerHTML = links_html(section);
	beeone.shell.announce(on ? __("Added to favorites") : __("Removed from favorites"));
}

function paint_label(row, label, words) {
	const el = row.querySelector(".bo-fp-lab");
	const low = norm(label);
	if (!words.length || low.length !== label.length) {
		el.textContent = label;
		return;
	}
	const marks = [];
	words.forEach((w) => {
		const at = low.indexOf(w);
		if (at >= 0) marks.push([at, at + w.length]);
	});
	marks.sort((a, b) => a[0] - b[0]);
	const merged = [];
	marks.forEach((m) => {
		const last = merged[merged.length - 1];
		if (last && m[0] <= last[1]) last[1] = Math.max(last[1], m[1]);
		else merged.push([...m]);
	});
	let out = "";
	let pos = 0;
	merged.forEach(([a, b]) => {
		out += esc(label.slice(pos, a)) + `<mark class="bo-fp-hit">${esc(label.slice(a, b))}</mark>`;
		pos = b;
	});
	el.innerHTML = out + esc(label.slice(pos));
}

// every word of the query must be a part of the label
function filter_panel(panel, section, q) {
	const words = norm(q).split(/\s+/).filter(Boolean);
	let shown = 0;
	panel.querySelectorAll(".bo-fp-row").forEach((row) => {
		const cmd = section.commands[+row.dataset.i];
		const low = norm(cmd.label);
		const ok = words.every((w) => low.includes(w));
		row.hidden = !ok;
		if (ok) shown++;
		paint_label(row, cmd.label, ok ? words : []);
	});
	panel.querySelectorAll(".bo-fp-grp").forEach((g) => (g.hidden = !g.querySelector(".bo-fp-row:not([hidden])")));
	panel.querySelectorAll(".bo-fp-col").forEach((c) => (c.hidden = !c.querySelector(".bo-fp-row:not([hidden])")));
	panel.querySelector(".bo-fp-none").hidden = shown > 0;
	panel.querySelector("#bo-fp-links").hidden = words.length > 0;
	set_stop(first_visible(panel));
	beeone.shell.announce(shown ? __("{0} commands", [shown]) : __("Nothing found"));
}

function panel_keys(e, panel, section) {
	const q = panel.querySelector(".bo-fp-q");
	const t = e.target;
	if (e.key === "Escape") {
		e.preventDefault();
		e.stopPropagation();
		if (q.value) {
			q.value = "";
			filter_panel(panel, section, "");
			q.focus();
		} else close_panel(true);
		return;
	}
	if (t === q) {
		if (e.key === "ArrowDown") {
			e.preventDefault();
			go(first_visible(panel));
		} else if (e.key === "Enter") {
			e.preventDefault();
			const first = first_visible(panel);
			if (first) run_cmd(section, first, e.ctrlKey || e.metaKey);
		}
		return;
	}
	const btn = t.closest && t.closest(".bo-fp-cmd");
	if (!btn) return;
	const cols = visible_cols(panel);
	const ci = cols.findIndex((c) => c.includes(btn));
	const ri = ci < 0 ? 0 : cols[ci].indexOf(btn);
	const mod = e.ctrlKey || e.metaKey;
	const key = e.key;
	let handled = true;
	if (key === "ArrowDown") go(cols[ci][ri + 1] || btn);
	else if (key === "ArrowUp") {
		if (ri > 0) go(cols[ci][ri - 1]);
		else q.focus();
	} else if (key === "ArrowRight" || key === "ArrowLeft") {
		const next = cols[ci + (key === "ArrowRight" ? 1 : -1)];
		go(next ? next[Math.min(ri, next.length - 1)] : btn);
	} else if (key === "Home") go(mod ? cols[0][0] : cols[ci][0]);
	else if (key === "End") {
		const last = cols[cols.length - 1];
		go(mod ? last[last.length - 1] : cols[ci][cols[ci].length - 1]);
	} else if (key === "Enter") run_cmd(section, btn, mod);
	else if (key === "*") toggle_star(panel, section, +btn.dataset.i);
	else if (key.length === 1 && key !== " " && !mod && !e.altKey) {
		// typing on a command goes to the search field
		q.focus();
		q.value += key;
		filter_panel(panel, section, q.value);
	} else handled = false;
	if (handled) e.preventDefault();
}

// ------------------------------------------------------------------ task bar

let task_dirty = false;
export const taskbar = {
	render() {
		if (task_dirty) return;
		task_dirty = true;
		// one render per task: many state changes in a row make one DOM update
		Promise.resolve().then(() => {
			task_dirty = false;
			paint_taskbar();
		});
	},
};

const task_btns = new Map(); // key -> {el, sig}

// buttons are kept and only the ones that changed are written (no innerHTML of the whole bar on every change)
function paint_taskbar() {
	const host = document.getElementById("bo-task-list");
	if (!host) return;
	const items = list();
	const keep = new Set(items.map((w) => w.key));
	task_btns.forEach((b, key) => {
		if (!keep.has(key)) {
			b.el.remove();
			task_btns.delete(key);
		}
	});
	items.forEach((w, i) => {
		let b = task_btns.get(w.key);
		if (!b) {
			const el = document.createElement("button");
			el.type = "button";
			el.dataset.key = w.key;
			b = { el, sig: "" };
			task_btns.set(w.key, b);
		}
		const sig = [w.key === wins.active, w.state === "minimized", w.parked, w.dirty, w.title, i, w.kind].join("|");
		if (b.sig !== sig) {
			b.sig = sig;
			const cls = ["bo-task-btn"];
			if (w.key === wins.active) cls.push("is-active");
			if (w.state === "minimized") cls.push("is-min");
			if (w.parked) cls.push("is-parked");
			b.el.className = cls.join(" ");
			b.el.title = (w.parked ? __("Unloaded from memory, will open again") : w.title) + (i < 9 ? ` (Alt ${i + 1})` : "");
			b.el.setAttribute("aria-pressed", w.key === wins.active);
			b.el.innerHTML =
				icon(w.kind === "form" ? "file" : w.kind === "list" ? "book" : w.kind === "report" ? "chart" : "layout") +
				`<span>${esc(w.title)}</span>${w.dirty ? '<i class="bo-task-dirty"></i>' : ""}`;
		}
		if (host.children[i] !== b.el) host.insertBefore(b.el, host.children[i] || null);
	});
	const n = items.length;
	document.getElementById("bo-task-count").textContent = n ? (n === 1 ? __("1 window") : __("{0} windows", [n])) : "";
	// the active button comes into view once the animations are over: scrolling reads the layout of the whole page
	clearTimeout(task_scroll);
	task_scroll = setTimeout(() => {
		const on = host.querySelector(".is-active");
		if (on && on.scrollIntoView) on.scrollIntoView({ block: "nearest", inline: "nearest" });
	}, 400);
}
let task_scroll = null;

export function init_taskbar() {
	document.getElementById("bo-task-list").addEventListener("click", (e) => {
		const btn = e.target.closest("[data-key]");
		if (btn) toggle_min(btn.dataset.key);
	});
	document.getElementById("bo-task-list").addEventListener("auxclick", (e) => {
		const btn = e.target.closest("[data-key]");
		if (btn && e.button === 1) close(btn.dataset.key);
	});
}

// ------------------------------------------------------------------ search (Ctrl K)

export function open_search(query = "") {
	close_panel();
	if (document.querySelector(".bo-dialog-backdrop .bo-ks")) return;
	const dlg = beeone.ui.dialog({
		title: __("Search"),
		html:
			`<div class="bo-ks"><div class="bo-ks-in">${icon("search")}<input type="text" autofocus autocomplete="off" spellcheck="false" ` +
			`placeholder="${esc(__("Find a command, report or open window…"))}" aria-label="${esc(__("Search"))}"></div><div class="bo-ks-list" role="listbox"></div></div>`,
		width: 620,
	});
	const input = dlg.box.querySelector("input");
	const out = dlg.box.querySelector(".bo-ks-list");
	let rows = [];
	let at = 0;
	const render = () => {
		const q = input.value.trim().toLowerCase();
		const match = (s) => !q || String(s).toLowerCase().includes(q);
		rows = [];
		list()
			.filter((w) => match(w.title))
			.forEach((w) => rows.push({ group: __("Open windows"), label: w.title, sub: w.kind, icon: "layout", run: () => focus(w.key) }));
		all_commands()
			.filter((c) => match(c.label))
			.slice(0, q ? 40 : 12)
			.forEach((c) => rows.push({ group: __("Commands"), label: c.label, sub: c.section.label, icon: "file", run: () => open_command(c) }));
		(beeone.shell.state.favorites || [])
			.filter((f) => match(f.label))
			.forEach((f) => rows.push({ group: __("Favorites"), label: f.label, sub: f.route.join(" / "), icon: "star", run: () => open_route(f.route) }));
		(beeone.shell.state.recent || [])
			.filter((f) => match(f.label))
			.slice(0, 8)
			.forEach((f) => rows.push({ group: __("Recent"), label: f.label, sub: f.route.join(" / "), icon: "clock", run: () => open_route(f.route) }));
		(beeone.shell.sections || []).forEach((s) =>
			(s.create || [])
				.filter((c) => q && match(c.doctype))
				.forEach((c) => rows.push({ group: __("Create"), label: __(c.doctype), sub: s.label, icon: "plus", run: () => frappe.new_doc(c.doctype) }))
		);
		at = Math.min(at, Math.max(0, rows.length - 1));
		let last = "";
		out.innerHTML = rows.length
			? rows
					.map((r, i) => {
						const head = r.group !== last ? `<div class="bo-ks-group">${esc(r.group)}</div>` : "";
						last = r.group;
						return `${head}<button type="button" role="option" class="bo-ks-row${i === at ? " is-on" : ""}" data-i="${i}">${icon(r.icon)}<span>${esc(r.label)}</span><small>${esc(r.sub)}</small></button>`;
					})
					.join("")
			: `<div class="bo-ks-empty">${esc(__("Nothing found"))}</div>`;
		const on = out.querySelector(".is-on");
		if (on && on.scrollIntoView) on.scrollIntoView({ block: "nearest" });
	};
	const run = (i) => {
		const r = rows[i];
		if (!r) return;
		dlg.close();
		r.run();
	};
	input.addEventListener("input", () => {
		at = 0;
		render();
	});
	input.addEventListener("keydown", (e) => {
		if (e.key === "ArrowDown" || e.key === "ArrowUp") {
			e.preventDefault();
			at = Math.max(0, Math.min(rows.length - 1, at + (e.key === "ArrowDown" ? 1 : -1)));
			render();
		} else if (e.key === "Enter") {
			e.preventDefault();
			run(at);
		}
	});
	out.addEventListener("click", (e) => {
		const row = e.target.closest("[data-i]");
		if (row) run(+row.dataset.i);
	});
	input.value = query;
	render();
}

// ------------------------------------------------------------------ top bar: theme, chips, user menu

export function toggle_theme() {
	const next = document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark";
	document.documentElement.setAttribute("data-theme", next);
	document.documentElement.setAttribute("data-theme-mode", next);
	frappe.xcall("frappe.core.doctype.user.user.switch_theme", { theme: next[0].toUpperCase() + next.slice(1) }).catch(() => {});
	paint_theme_icon();
}

export function paint_theme_icon() {
	const dark = document.documentElement.getAttribute("data-theme") === "dark";
	const btn = document.querySelector('#bo-top [data-act="theme"]');
	if (btn) btn.innerHTML = icon(dark ? "moon" : "sun");
}

export function add_context_chip(chip) {
	const host = document.getElementById("bo-chips");
	if (!host) return null;
	let el = host.querySelector(`[data-chip="${chip.id}"]`);
	if (!el) {
		el = document.createElement("button");
		el.type = "button";
		el.className = "bo-chip";
		el.dataset.chip = chip.id;
		el.addEventListener("click", () => chip.menu && chip.menu(el));
		host.appendChild(el);
	}
	const html = chip.render ? chip.render() : null;
	el.hidden = !html;
	if (html) el.innerHTML = html;
	return el;
}

function user_menu(trigger) {
	const accent = beeone.shell.state.accent;
	const items =
		`<div class="bo-menu-label">${esc(frappe.session.user_fullname || frappe.session.user)}</div>` +
		`<button class="bo-menu-item" data-a="accent-cobalt">${icon("check", accent === "cobalt" ? "" : "bo-i-hide")}${esc(__("Accent: cobalt"))}</button>` +
		`<button class="bo-menu-item" data-a="accent-teal">${icon("check", accent === "teal" ? "" : "bo-i-hide")}${esc(__("Accent: teal"))}</button>` +
		`<div class="bo-menu-sep"></div>` +
		`<button class="bo-menu-item" data-a="reset">${icon("undo")}${esc(__("Reset layout"))}</button>` +
		`<button class="bo-menu-item" data-a="keys">${icon("book")}${esc(__("Keyboard shortcuts"))}</button>` +
		`<button class="bo-menu-item" data-a="settings">${icon("gear")}${esc(__("My Settings"))}</button>` +
		(frappe.user.has_role("System Manager") ? `<button class="bo-menu-item" data-a="setup">${icon("sliders")}${esc(__("Initial setup"))}</button>` : "") +
		`<button class="bo-menu-item" data-a="logout">${icon("logout")}${esc(__("Log out"))}</button>`;
	beeone.ui.menu(
		trigger,
		items,
		(item) => {
			const a = item.dataset.a;
			if (a === "accent-cobalt" || a === "accent-teal") beeone.shell.set_accent(a.slice(7));
			else if (a === "reset") beeone.shell.reset_layout();
			else if (a === "keys") help();
			else if (a === "settings") frappe.set_route("Form", "User", frappe.session.user);
			else if (a === "setup") frappe.set_route("beeone-setup");
			else if (a === "logout") frappe.app.logout();
		},
		{ cls: "bo-user-pop", side: "right" }
	);
}

export function help() {
	const rows = [
		["Ctrl K", __("Search")],
		["\u2191 \u2193 \u2190 \u2192", __("Move between commands in a section panel")],
		["Ctrl Enter", __("Open a command and keep the panel")],
		["*", __("Add the command to favorites or remove it")],
		["Alt 1 … Alt 9", __("Window N on the task bar")],
		["Alt `", __("Next window")],
		["Alt M", __("Minimize")],
		["Alt ↑", __("Maximize")],
		["Alt Q", __("Close")],
		["Alt D", __("Show desktop")],
		["Ctrl S", __("Save")],
	];
	beeone.ui.dialog({
		title: __("Keyboard shortcuts"),
		html:
			`<div class="bo-dialog-head"><h3>${esc(__("Keyboard shortcuts"))}</h3></div><div class="bo-dialog-body"><table class="bo-keys">` +
			rows.map((r) => `<tr><td><kbd>${esc(r[0])}</kbd></td><td>${esc(r[1])}</td></tr>`).join("") +
			`</table></div>`,
		width: 440,
	});
}

// ------------------------------------------------------------------ hotkeys (physical keys, same in uk and en)

export function init_keys() {
	// Frappe binds Ctrl K to its own search: use ours only
	try {
		frappe.ui.keys.handlers["ctrl+k"] = [];
	} catch (e) {
		// keys are not ready: the capture handler below still wins
	}
	window.addEventListener(
		"keydown",
		(e) => {
			const code = e.code;
			if (e.ctrlKey && !e.altKey && !e.metaKey && !e.shiftKey && code === "KeyK") {
				e.preventDefault();
				e.stopImmediatePropagation();
				return open_search();
			}
			if (!e.altKey || e.ctrlKey || e.metaKey) {
				if (e.key === "?" && !/^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName) && !e.target.isContentEditable) help();
				return;
			}
			const items = list();
			let handled = true;
			const digit = /^Digit([1-9])$/.exec(code);
			if (digit) {
				const w = items[+digit[1] - 1];
				if (w) focus(w.key);
			} else if (code === "Backquote") {
				const open = items;
				if (open.length) {
					const at = open.findIndex((w) => w.key === wins.active);
					const step = e.shiftKey ? -1 : 1;
					focus(open[(at + step + open.length) % open.length].key);
				}
			} else if (code === "KeyM") wins.active && minimize(wins.active);
			else if (code === "ArrowUp") wins.active && toggle_max(wins.active);
			else if (code === "KeyQ") wins.active && close(wins.active);
			else if (code === "KeyD") show_desktop();
			else handled = false;
			if (handled) {
				e.preventDefault();
				e.stopImmediatePropagation();
			}
		},
		true
	);
	document.addEventListener("keydown", (e) => {
		if (e.key === "Escape") close_panel();
	});
}

export { kind_of };
