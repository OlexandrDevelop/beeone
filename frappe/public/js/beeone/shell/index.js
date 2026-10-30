// Desktop shell of beeone: start, layout storage, favourites, history (docs/platform/SHELL.md).
import * as W from "./windows.js";
import * as P from "./panel.js";
import { desk } from "./desk.js";

frappe.provide("beeone.shell");

const SAVE_METHOD = "frappe.beeone.shell.save_layout";
const MAX_RECENT = 20;
const MAX_FAV = 40;
let save_timer = null;
let dirty = false;

function state_to_layout() {
	const st = beeone.shell.state;
	return { v: 1, ...W.snapshot(), widgets: st.widgets || [], has_widgets: !!st.has_widgets, favorites: st.favorites || [], recent: st.recent || [], accent: st.accent || "cobalt" };
}

function flush(keep) {
	if (!dirty) return;
	dirty = false;
	clearTimeout(save_timer);
	save_timer = null;
	const layout = JSON.stringify(state_to_layout());
	if (keep) {
		// the page is going away: fetch with keepalive finishes after it
		fetch("/api/method/" + SAVE_METHOD, {
			method: "POST",
			keepalive: true,
			headers: { "Content-Type": "application/x-www-form-urlencoded", "X-Frappe-CSRF-Token": frappe.csrf_token, Accept: "application/json" },
			body: "layout=" + encodeURIComponent(layout),
		}).catch(() => {});
		return;
	}
	frappe.xcall(SAVE_METHOD, { layout }).catch(() => {
		dirty = true;
	});
}

Object.assign(beeone.shell, {
	active: false,
	sections: [],
	catalog: null,
	state: { widgets: [], has_widgets: false, favorites: [], recent: [], accent: "cobalt" },
	windows: W,
	desktop_routes: W.desktop_routes,
	taskbar: P.taskbar,
	desk,
	host: W.host,
	adopt_renamed: W.adopt_renamed,
	scroll_parent: W.scroll_parent,
	add_context_chip: P.add_context_chip,
	open_search: P.open_search,
	close_panel: P.close_panel,

	// open a route as a window: beeone.shell.open(["List", "Item"]) or beeone.shell.open("Form/Item/ITEM-1")
	open(route) {
		route = typeof route === "string" ? route.replace(/^\/?(desk\/)?/, "").split("/").filter(Boolean) : route;
		P.open_route(route);
	},

	save_soon() {
		dirty = true;
		if (save_timer) return;
		save_timer = setTimeout(() => {
			save_timer = null;
			flush(false);
		}, 1000);
	},

	announce(text) {
		const live = document.getElementById("bo-live");
		if (live) live.textContent = text;
	},

	// history: the last windows opened by the user
	track(win) {
		if (win.parked) return;
		const st = beeone.shell.state;
		const route = win.route.map(String);
		const key = route.join("/");
		st.recent = [{ route, label: win.title }, ...(st.recent || []).filter((r) => r.route.join("/") !== key)].slice(0, MAX_RECENT);
	},

	is_fav(route) {
		const key = Array.isArray(route) ? route.join("/") : String(route);
		return (beeone.shell.state.favorites || []).some((f) => f.route.join("/") === key);
	},

	// returns true when the route is a favourite after the call
	toggle_fav(entry) {
		const st = beeone.shell.state;
		const key = entry.route.join("/");
		const had = beeone.shell.is_fav(entry.route);
		st.favorites = (st.favorites || []).filter((f) => f.route.join("/") !== key);
		if (!had) st.favorites.unshift({ route: entry.route.map(String), label: entry.label || key });
		st.favorites = st.favorites.slice(0, MAX_FAV);
		beeone.shell.save_soon();
		return !had;
	},

	set_accent(accent) {
		beeone.shell.state.accent = accent === "teal" ? "teal" : "cobalt";
		document.body.dataset.boAccent = beeone.shell.state.accent;
		beeone.shell.save_soon();
	},

	reset_layout() {
		frappe.xcall("frappe.beeone.shell.reset_layout").then((layout) => {
			const st = beeone.shell.state;
			st.widgets = layout.widgets;
			st.has_widgets = true;
			st.accent = "cobalt";
			document.body.dataset.boAccent = "cobalt";
			[...beeone.shell.windows.wins.keys()].forEach((k) => W.close(k, true));
			desk.render();
			desk.refresh(true);
		});
	},

	// can the user open this saved route? Doctypes by permission, reports and pages by the sections
	readable(route) {
		const head = route[0];
		if (head === "Form" || head === "List" || head === "Tree") return frappe.model.can_read(route[1]);
		const ok = (beeone.shell.sections || []).some((s) =>
			s.commands.some((c) => (c.type === "report" && head === "query-report" && c.target === route[1]) || (c.type === "page" && c.target === head) || (c.type === "route" && String(c.target).split("/")[0] === head))
		);
		return ok;
	},

	init() {
		const boot = frappe.boot.beeone_shell;
		if (!boot || !boot.enabled || beeone.shell.active) return;
		// `boot.setup_complete` is the authoritative site-level flag. The legacy
		// sysdefaults copy can remain 0 after automated/demo provisioning and
		// must not disable the desktop shell when the desk is already usable.
		if (frappe.boot.setup_complete === false) return;
		const sh = beeone.shell;
		sh.active = true;
		sh.sections = boot.sections;
		sh.catalog = boot.widgets;
		const layout = boot.layout || {};
		sh.state = {
			widgets: layout.widgets || [],
			has_widgets: !!(layout.has_widgets || (layout.widgets || []).length),
			favorites: layout.favorites || [],
			recent: layout.recent || [],
			accent: layout.accent || "cobalt",
		};
		document.body.classList.add("bo-shell");
		document.body.dataset.boAccent = sh.state.accent;
		beeone.ui.inject_icons();
		P.build();
		P.init_taskbar();
		P.init_keys();
		P.paint_theme_icon();
		W.init_pointer();
		const small = () => document.body.classList.toggle("bo-compact", window.innerWidth < 900 || window.innerHeight < 560);
		small();
		desk.render();
		desk.on_visibility();
		desk.refresh(true);
		document.getElementById("bo-desk-bg").addEventListener("click", (e) => desk.on_click(e));
		window.addEventListener("pagehide", () => flush(true));
		document.addEventListener("visibilitychange", () => document.visibilityState === "hidden" && flush(true));
		// a desktop route (no window) clears the active window
		frappe.router.on("change", () => {
			if (!W.is_window_route(frappe.get_route())) W.blur();
		});
		// restore the saved windows: only the active one loads, the others wait parked
		const active = W.restore(layout, sh.readable);
		frappe.realtime && frappe.realtime.on("notification", refresh_bell);
		refresh_bell();
		// beeone: use get_sub_path() before router sets current_route (which is null at startup)
		const path = frappe.router.get_sub_path().split("/").filter(Boolean);
		const landing = path.length === 0 || (path[0] === "desk" && path.length === 1) || (path[0] === "app" && path.length === 1);
		// return active route for desk.js to set, or null if not landing
		return landing ? (active?.route || null) : null;
	},
});

function refresh_bell() {
	frappe
		.xcall("frappe.client.get_count", { doctype: "Notification Log", filters: { for_user: frappe.session.user, read: 0 } })
		.then((count) => {
			const dot = document.querySelector("#bo-top .bo-dot-badge");
			if (dot) dot.hidden = !count;
		})
		.catch(() => {});
}
