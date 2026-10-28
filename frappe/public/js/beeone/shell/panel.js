// Rail, function panel, search, task bar, top bar and hotkeys (docs/platform/SHELL.md §2, §3.4, §3.5).
import { wins, focus, minimize, toggle_max, toggle_min, close, show_desktop, list, kind_of } from "./windows.js";

const esc = (v) => frappe.utils.escape_html(v == null ? "" : String(v));
const icon = (n, c) => beeone.ui.icon(n, c);
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
		`<button type="button" class="bo-task-menu" data-act="sections" aria-label="${esc(__("Sections"))}">${icon("menu")}</button>` +
		`<button type="button" class="bo-task-desk" data-act="desktop" title="${esc(__("Show desktop"))} (Alt D)" aria-label="${esc(__("Show desktop"))}">${icon("layout")}</button>` +
		`<div class="bo-task-list" id="bo-task-list"></div><span class="bo-task-count" id="bo-task-count"></span></footer>` +
		`<div id="bo-panel" hidden></div><div id="bo-live" class="bo-sr" aria-live="polite"></div>`;
	document.body.appendChild(app);
	render_rail();
	app.addEventListener("click", on_click);
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
				`<button type="button" class="bo-rail-btn" data-section="${esc(s.id)}" title="${esc(s.label)}" aria-label="${esc(s.label)}">${icon(s.icon)}</button>`
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

export function close_panel() {
	const panel = document.getElementById("bo-panel");
	if (!panel) return;
	panel.hidden = true;
	panel_section = null;
	document.querySelectorAll("#bo-rail .is-active").forEach((b) => b.classList.remove("is-active"));
}

function toggle_panel(id) {
	const panel = document.getElementById("bo-panel");
	if (!id) {
		// compact screens: all sections as a list
		if (!panel.hidden && panel_section === "*") return close_panel();
		panel_section = "*";
		panel.hidden = false;
		panel.innerHTML = `<div class="bo-fp-all">${(beeone.shell.sections || [])
			.map((s) => `<button type="button" class="bo-fp-sec" data-section="${esc(s.id)}">${icon(s.icon)}<span>${esc(s.label)}</span></button>`)
			.join("")}</div>`;
		panel.querySelectorAll("[data-section]").forEach((b) => b.addEventListener("click", () => toggle_panel(b.dataset.section)));
		return;
	}
	if (!panel.hidden && panel_section === id) return close_panel();
	const section = (beeone.shell.sections || []).find((s) => s.id === id);
	if (!section) return;
	panel_section = id;
	document.querySelectorAll("#bo-rail [data-section]").forEach((b) => b.classList.toggle("is-active", b.dataset.section === id));
	const cols = COLUMNS.map((c) => {
		const items = section.commands.filter((x) => x.column === c.key);
		if (!items.length) return "";
		return (
			`<div class="bo-fp-col"><h3>${icon(c.icon)}${esc(c.title())}</h3>` +
			items
				.map((x, i) => `<button type="button" class="bo-fp-cmd" data-i="${section.commands.indexOf(x)}">${esc(x.label)}</button>`)
				.join("") +
			"</div>"
		);
	}).join("");
	const create = (section.create || [])
		.map((c) => `<button type="button" class="bo-btn bo-btn--sm" data-new="${esc(c.doctype)}">${icon("plus", "bo-i-sm")}${esc(__(c.doctype))}</button>`)
		.join("");
	panel.hidden = false;
	panel.innerHTML =
		`<div class="bo-fp-head"><div><h2>${esc(section.label)}</h2><p>${esc(section.description)}</p></div></div>` +
		(create ? `<div class="bo-fp-create"><span>${esc(__("Create"))}:</span>${create}</div>` : "") +
		`<div class="bo-fp-cols">${cols}</div>`;
	panel.onclick = (e) => {
		const cmd = e.target.closest("[data-i]");
		const nw = e.target.closest("[data-new]");
		if (cmd) open_command(section.commands[+cmd.dataset.i]);
		else if (nw) frappe.new_doc(nw.dataset.new);
		else return;
		if (!(e.ctrlKey || e.metaKey)) close_panel();
	};
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

function paint_taskbar() {
	const host = document.getElementById("bo-task-list");
	if (!host) return;
	const items = list();
	host.innerHTML = items
		.map((w, i) => {
			const cls = ["bo-task-btn"];
			if (w.key === wins.active) cls.push("is-active");
			if (w.state === "minimized") cls.push("is-min");
			if (w.parked) cls.push("is-parked");
			const tip = w.parked ? __("Unloaded from memory, will open again") : w.title;
			return (
				`<button type="button" class="${cls.join(" ")}" data-key="${esc(w.key)}" title="${esc(tip)}${i < 9 ? ` (Alt ${i + 1})` : ""}" ` +
				`aria-pressed="${w.key === wins.active}">${icon(w.kind === "form" ? "file" : w.kind === "list" ? "book" : w.kind === "report" ? "chart" : "layout")}` +
				`<span>${esc(w.title)}</span>${w.dirty ? '<i class="bo-task-dirty"></i>' : ""}</button>`
			);
		})
		.join("");
	const n = items.length;
	document.getElementById("bo-task-count").textContent = n ? (n === 1 ? __("1 window") : __("{0} windows", [n])) : "";
	const on = host.querySelector(".is-active");
	if (on && on.scrollIntoView) on.scrollIntoView({ block: "nearest", inline: "nearest" });
}

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

export function open_search() {
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
			else if (a === "logout") frappe.app.logout();
		},
		{ cls: "bo-user-pop", side: "right" }
	);
}

export function help() {
	const rows = [
		["Ctrl K", __("Search")],
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
