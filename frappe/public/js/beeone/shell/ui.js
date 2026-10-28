// Small runtime of the shared components (components.css): icons, menus, dialogs, tabs,
// toasts, empty and skeleton states. The shell, lists, forms and reports use only these helpers.
frappe.provide("beeone.ui");

(function () {
	const esc = (v) => frappe.utils.escape_html(v == null ? "" : String(v));

	// ---------------------------------------------------------------- icons (one inline sprite)
	const ICONS = {
		home: '<path d="M3 10.5 12 3l9 7.5"/><path d="M5 9.5V20a1 1 0 0 0 1 1h4v-6h4v6h4a1 1 0 0 0 1-1V9.5"/>',
		cart: '<circle cx="9" cy="20" r="1.4"/><circle cx="18" cy="20" r="1.4"/><path d="M2.5 3h2.6l2.4 12.2a1.5 1.5 0 0 0 1.5 1.2h8.9a1.5 1.5 0 0 0 1.5-1.2L21 7H6"/>',
		trending: '<path d="m3 17 6-6 4 4 8-8"/><path d="M15 7h6v6"/>',
		package: '<path d="M21 8 12 3 3 8v8l9 5 9-5Z"/><path d="m3 8 9 5 9-5"/><path d="M12 13v8"/><path d="m7.5 5.5 9 5"/>',
		landmark: '<path d="M3 21h18"/><path d="M5 18h14"/><path d="M6 18v-7M10 18v-7M14 18v-7M18 18v-7"/><path d="M12 3 3 8.5h18Z"/>',
		building: '<rect x="4" y="3" width="16" height="18" rx="1.5"/><path d="M9 7h1M14 7h1M9 11h1M14 11h1M9 15h1M14 15h1"/><path d="M10 21v-3h4v3"/>',
		chart: '<path d="M3 3v16a2 2 0 0 0 2 2h16"/><path d="M8 17v-5M13 17V8M18 17v-9"/>',
		book: '<path d="M5 19.5v-15A1.5 1.5 0 0 1 6.5 3H19v14H6.5A1.5 1.5 0 0 0 5 18.5 1.5 1.5 0 0 0 6.5 20H19"/><path d="M9 7.5h6"/>',
		sliders: '<path d="M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12M20 18h0"/><circle cx="16" cy="6" r="2"/><circle cx="10" cy="12" r="2"/><circle cx="18" cy="18" r="2"/>',
		search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
		star: '<path d="m12 3 2.8 5.7 6.2.9-4.5 4.4 1.1 6.2L12 17.3l-5.6 2.9 1.1-6.2L3 9.6l6.2-.9Z"/>',
		plus: '<path d="M12 5v14M5 12h14"/>',
		"chev-r": '<path d="m9 6 6 6-6 6"/>',
		"chev-d": '<path d="m6 9 6 6 6-6"/>',
		"chev-l": '<path d="m15 6-6 6 6 6"/>',
		"chev-u": '<path d="m6 15 6-6 6 6"/>',
		updown: '<path d="m7 15 5 5 5-5M7 9l5-5 5 5"/>',
		x: '<path d="M18 6 6 18M6 6l12 12"/>',
		check: '<path d="m5 12.5 4.5 4.5L19 7.5"/>',
		checks: '<path d="m2 12.5 4.5 4.5L15 8.5"/><path d="M11 16l1 1 9.5-9.5"/>',
		filter: '<path d="M3 6h18M7 12h10M10 18h4"/>',
		more: '<circle cx="5" cy="12" r="1.2" fill="currentColor"/><circle cx="12" cy="12" r="1.2" fill="currentColor"/><circle cx="19" cy="12" r="1.2" fill="currentColor"/>',
		printer: '<path d="M6 9V3h12v6"/><rect x="3" y="9" width="18" height="8" rx="2"/><path d="M6 14h12v7H6Z"/>',
		file: '<path d="M14 3H6.5A1.5 1.5 0 0 0 5 4.5v15A1.5 1.5 0 0 0 6.5 21h11a1.5 1.5 0 0 0 1.5-1.5V8Z"/><path d="M14 3v5h5"/><path d="M9 13h6M9 17h6"/>',
		"file-plus": '<path d="M14 3H6.5A1.5 1.5 0 0 0 5 4.5v15A1.5 1.5 0 0 0 6.5 21h11a1.5 1.5 0 0 0 1.5-1.5V8Z"/><path d="M14 3v5h5"/><path d="M12 11v6M9 14h6"/>',
		dtkt: '<path d="M4 8h15l-3.5-3.5"/><path d="M20 16H5l3.5 3.5"/>',
		branch: '<path d="M6 3v12"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="6" r="3"/><path d="M18 9a9 9 0 0 1-9 9"/>',
		copy: '<rect x="8" y="8" width="13" height="13" rx="2"/><path d="M16 8V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h3"/>',
		trash: '<path d="M3 6h18M8 6V4h8v2M6 6l1 14a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1l1-14"/><path d="M10 11v6M14 11v6"/>',
		"arrow-up": '<path d="M12 19V5M6 11l6-6 6 6"/>',
		"arrow-down": '<path d="M12 5v14M6 13l6 6 6-6"/>',
		"arrow-right": '<path d="M5 12h14M13 6l6 6-6 6"/>',
		grip: '<circle cx="9" cy="6" r="1.2" fill="currentColor"/><circle cx="15" cy="6" r="1.2" fill="currentColor"/><circle cx="9" cy="12" r="1.2" fill="currentColor"/><circle cx="15" cy="12" r="1.2" fill="currentColor"/><circle cx="9" cy="18" r="1.2" fill="currentColor"/><circle cx="15" cy="18" r="1.2" fill="currentColor"/>',
		calendar: '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/>',
		sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
		moon: '<path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5Z"/>',
		bell: '<path d="M6 8a6 6 0 1 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a1.9 1.9 0 0 0 3.4 0"/>',
		help: '<circle cx="12" cy="12" r="9"/><path d="M9.5 9a2.5 2.5 0 1 1 3.5 2.3c-.6.3-1 .9-1 1.6v.6"/><path d="M12 17h.01"/>',
		panel: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M9 4v16"/>',
		folder: '<path d="M3 7.5A1.5 1.5 0 0 1 4.5 6H9l2 2h8.5A1.5 1.5 0 0 1 21 9.5v8a1.5 1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 17.5Z"/>',
		"folder-open": '<path d="M3 17.5v-10A1.5 1.5 0 0 1 4.5 6H9l2 2h7.5A1.5 1.5 0 0 1 20 9.5V11"/><path d="M3 17.5 5.5 12h16L19 18.2a1.5 1.5 0 0 1-1.4.8H4.5A1.5 1.5 0 0 1 3 17.5Z"/>',
		"folder-plus": '<path d="M3 7.5A1.5 1.5 0 0 1 4.5 6H9l2 2h8.5A1.5 1.5 0 0 1 21 9.5v8a1.5 1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 17.5Z"/><path d="M12 11v5M9.5 13.5h5"/>',
		sheet: '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18M3 15h18M9 3v18"/>',
		refresh: '<path d="M20 11a8 8 0 0 0-14.6-4.5L4 8"/><path d="M4 3v5h5"/><path d="M4 13a8 8 0 0 0 14.6 4.5L20 16"/><path d="M20 21v-5h-5"/>',
		user: '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',
		info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/>',
		alert: '<path d="M10.3 3.9 2 18a2 2 0 0 0 1.7 3h16.6a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z"/><path d="M12 9v4M12 17h.01"/>',
		"check-circle": '<circle cx="12" cy="12" r="9"/><path d="m8 12.5 3 3 5-6"/>',
		history: '<path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/><path d="M12 7v5l3 2"/>',
		list: '<path d="M8 6h13M8 12h13M8 18h13M3.5 6h.01M3.5 12h.01M3.5 18h.01"/>',
		tree: '<path d="M4 4v14a2 2 0 0 0 2 2h4M4 10h6"/><rect x="12" y="7" width="8" height="6" rx="1.5"/><rect x="12" y="16" width="8" height="6" rx="1.5"/>',
		external: '<path d="M14 4h6v6M20 4l-9 9"/><path d="M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/>',
		pencil: '<path d="M4 20h4L19 9a2.8 2.8 0 0 0-4-4L4 16Z"/><path d="m13.5 6.5 4 4"/>',
		save: '<path d="M5 3h11l5 5v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2Z"/><path d="M7 3v5h8V3M7 21v-7h10v7"/>',
		undo: '<path d="M9 14 4 9l5-5"/><path d="M4 9h11a5 5 0 0 1 0 10h-3"/>',
		wallet: '<path d="M19 7V5.5A1.5 1.5 0 0 0 17.5 4H5a2 2 0 0 0 0 4h14a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H5a2 2 0 0 1-2-2V6"/><path d="M16 14h.01"/>',
		cash: '<rect x="2" y="6" width="20" height="12" rx="2"/><circle cx="12" cy="12" r="2.5"/><path d="M6 12h.01M18 12h.01"/>',
		inbox: '<path d="M22 12h-6l-2 3h-4l-2-3H2"/><path d="M5.5 5h13l3.5 7v6a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2v-6Z"/>',
		gear: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1Z"/>',
		link: '<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1"/><path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/>',
		lock: '<rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>',
		hexagon: '<path d="M12 2.5 20.5 7.4v9.2L12 21.5l-8.5-4.9V7.4Z"/><path d="M12 8.5v7M8.5 10.5 12 12.5l3.5-2"/>',
		menu: '<path d="M4 6h16M4 12h16M4 18h16"/>',
		layout: '<rect x="3" y="4" width="18" height="16" rx="2.5"/><path d="M3 9h18M9 9v11"/>',
		minus: '<path d="M5 12h14"/>',
		square: '<rect x="5" y="5" width="14" height="14" rx="2"/>',
		restore: '<rect x="4" y="8" width="12" height="12" rx="2"/><path d="M8 8V6a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-2"/>',
		clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
		logout: '<path d="M15 4h3a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-3"/><path d="M10 17l-5-5 5-5M5 12h11"/>',
	};

	beeone.ui.inject_icons = function () {
		if (document.getElementById("bo-icons")) return;
		let s = '<svg id="bo-icons" xmlns="http://www.w3.org/2000/svg" style="display:none">';
		Object.keys(ICONS).forEach((k) => {
			s += `<symbol id="bo-i-${k}" viewBox="0 0 24 24">${ICONS[k]}</symbol>`;
		});
		document.body.insertAdjacentHTML("afterbegin", s + "</svg>");
	};

	// icon("star") or icon("star", "bo-i-sm")
	beeone.ui.icon = function (name, cls) {
		const extra = typeof cls === "string" && cls ? " " + cls : "";
		return `<svg class="bo-i${extra}" aria-hidden="true"><use href="#bo-i-${name}"/></svg>`;
	};

	// ---------------------------------------------------------------- numbers (uk: 1 234,56)
	beeone.ui.money = function (value, opts) {
		opts = opts || {};
		if (value === null || value === undefined || value === "") return "";
		const out = format_number(value, null, opts.digits === undefined ? 2 : opts.digits);
		if (!opts.cur) return out;
		const symbol = typeof opts.cur === "string" ? opts.cur : get_currency_symbol(frappe.boot.sysdefaults.currency || "");
		return symbol ? `${out} ${symbol}` : out;
	};

	// ---------------------------------------------------------------- menus (.bo-pop)
	let open_menu = null;

	beeone.ui.close_menu = function () {
		if (!open_menu) return;
		const m = open_menu;
		open_menu = null;
		if (m.trigger) m.trigger.setAttribute("aria-expanded", "false");
		// on_close can take back parts it lent to the menu (live controls) before the menu goes
		if (m.on_close) m.on_close(m.el);
		m.el.remove();
	};

	// Shows a menu under the trigger. html: inner HTML of .bo-pop; on_click(item_el, event).
	// opts: cls, side, align, on_open(el) (before it is placed), on_close(el).
	beeone.ui.menu = function (trigger, html, on_click, opts) {
		opts = opts || {};
		const same = open_menu && open_menu.trigger === trigger;
		beeone.ui.close_menu();
		if (same) return null;
		const el = document.createElement("div");
		el.className = "bo-pop" + (opts.cls ? " " + opts.cls : "");
		el.setAttribute("role", opts.role || "menu");
		el.innerHTML = html;
		document.body.appendChild(el);
		if (opts.on_open) opts.on_open(el);
		const r = trigger.getBoundingClientRect();
		el.style.position = "fixed";
		el.style.zIndex = 1060;
		if (opts.side === "right") {
			el.style.left = r.right + 8 + "px";
			el.style.top = r.top + "px";
		} else {
			el.style.top = r.bottom + 6 + "px";
			const w = el.offsetWidth;
			if (opts.align === "right" || r.left + w > innerWidth - 12) {
				el.classList.add("bo-pop--right");
				el.style.left = Math.max(12, r.right - w) + "px";
			} else {
				el.style.left = r.left + "px";
			}
		}
		const h = el.offsetHeight;
		const top = parseFloat(el.style.top);
		if (top + h > innerHeight - 12) el.style.top = Math.max(12, innerHeight - 12 - h) + "px";
		trigger.setAttribute("aria-expanded", "true");
		open_menu = { el, trigger, on_close: opts.on_close };
		el.addEventListener("click", (e) => {
			const item = e.target.closest(".bo-menu-item, [data-act], [data-pick]");
			if (!item || !on_click) return;
			const keep = on_click(item, e);
			if (keep !== true) beeone.ui.close_menu();
		});
		const first = el.querySelector("input, .bo-menu-item");
		if (first) setTimeout(() => first.focus({ preventScroll: true }), 0);
		return el;
	};

	document.addEventListener(
		"mousedown",
		(e) => {
			if (!open_menu) return;
			if (open_menu.el.contains(e.target) || open_menu.trigger.contains(e.target)) return;
			// Frappe puts the date picker into <body>: a click there belongs to the menu
			if (e.target.closest && e.target.closest(".datepickers-container, .datepicker")) return;
			beeone.ui.close_menu();
		},
		true
	);
	window.addEventListener("resize", () => beeone.ui.close_menu());

	beeone.ui.menu_open = () => !!open_menu;

	// ---------------------------------------------------------------- own dialogs (.bo-dialog)
	// Frappe dialogs are restyled in the app CSS; this one is for the shell (search, shortcuts).
	beeone.ui.dialog = function (opts) {
		const back = document.createElement("div");
		back.className = "bo-dialog-backdrop";
		back.innerHTML =
			`<div class="bo-dialog${opts.wide ? " bo-dialog--wide" : ""}" role="dialog" aria-modal="true" ` +
			`aria-label="${esc(opts.title || "")}" tabindex="-1"${opts.width ? ` style="width:min(${opts.width}px,100%)"` : ""}>` +
			opts.html +
			"</div>";
		document.body.appendChild(back);
		const box = back.querySelector(".bo-dialog");
		const last = document.activeElement;
		const close = () => {
			if (back.classList.contains("leaving")) return;
			back.classList.add("leaving");
			const ms = parseFloat(getComputedStyle(back).animationDuration) * 1000 || 0;
			setTimeout(() => back.remove(), ms + 10);
			document.removeEventListener("keydown", on_key, true);
			if (last && last.focus) last.focus({ preventScroll: true });
			if (opts.on_close) opts.on_close();
		};
		const on_key = (e) => {
			if (e.key === "Escape") {
				e.stopPropagation();
				e.preventDefault();
				close();
			}
		};
		document.addEventListener("keydown", on_key, true);
		back.addEventListener("mousedown", (e) => {
			if (e.target === back) close();
		});
		back.addEventListener("click", (e) => {
			if (e.target.closest("[data-close]")) close();
		});
		const focus = box.querySelector("[autofocus]") || box;
		setTimeout(() => focus.focus({ preventScroll: true }), 30);
		return { el: back, box, close };
	};

	// ---------------------------------------------------------------- tabs with moving ink
	beeone.ui.place_ink = function (tabs) {
		let ink = tabs.querySelector(".bo-tabs-ink");
		if (!ink) {
			tabs.insertAdjacentHTML("beforeend", '<span class="bo-tabs-ink"></span>');
			ink = tabs.querySelector(".bo-tabs-ink");
		}
		const on = tabs.querySelector(".bo-tab.is-on");
		if (!on) {
			ink.style.width = "0";
			return;
		}
		ink.style.width = on.offsetWidth + "px";
		ink.style.transform = `translateX(${on.offsetLeft}px)`;
	};

	// ---------------------------------------------------------------- toasts
	beeone.ui.toast = function (o) {
		o = typeof o === "string" ? { title: o } : o;
		let box = document.querySelector(".bo-toasts");
		if (!box) {
			box = document.createElement("div");
			box.className = "bo-toasts";
			box.setAttribute("role", "status");
			box.setAttribute("aria-live", "polite");
			document.body.appendChild(box);
		}
		const type = o.type || "success";
		const dur = o.duration || 4000;
		const ic = type === "error" ? "x" : type === "info" ? "info" : type === "warning" ? "alert" : "check";
		const t = document.createElement("div");
		t.className = "bo-toast bo-toast--" + type;
		t.innerHTML =
			`<span class="bo-toast-icon">${beeone.ui.icon(ic)}</span><div class="bo-toast-body">` +
			`<div class="bo-toast-title">${o.title_html || esc(o.title)}</div>` +
			(o.text ? `<div class="bo-toast-text">${esc(o.text)}</div>` : "") +
			(o.action ? `<div class="bo-toast-action"><button class="bo-btn bo-btn--sm">${esc(o.action.label)}</button></div>` : "") +
			`</div><button class="bo-btn bo-btn--ghost bo-btn--icon bo-btn--sm bo-toast-close" aria-label="${esc(
				__("Close")
			)}">${beeone.ui.icon("x")}</button>` +
			`<span class="bo-toast-bar" style="animation-duration:${dur}ms"></span>`;
		box.appendChild(t);
		let timer = setTimeout(close, dur);
		function close() {
			clearTimeout(timer);
			if (t.classList.contains("leaving")) return;
			t.classList.add("leaving");
			const ms = parseFloat(getComputedStyle(t).animationDuration) * 1000 || 0;
			setTimeout(() => t.remove(), ms + 20);
		}
		t.addEventListener("mouseenter", () => {
			clearTimeout(timer);
			t.querySelector(".bo-toast-bar").style.animationPlayState = "paused";
		});
		t.addEventListener("mouseleave", () => {
			timer = setTimeout(close, 1600);
		});
		t.querySelector(".bo-toast-close").addEventListener("click", close);
		if (o.action) {
			t.querySelector(".bo-toast-action .bo-btn").addEventListener("click", () => {
				o.action.on_click();
				close();
			});
		}
		return t;
	};

	// ---------------------------------------------------------------- states: empty, error, skeleton
	// art: icon name; actions: [{label, primary, icon, act}]
	beeone.ui.empty_html = function (o) {
		const actions = (o.actions || [])
			.map(
				(a) =>
					`<button class="bo-btn${a.primary ? " bo-btn--primary" : ""}" data-act="${esc(a.act)}">` +
					`${a.icon ? beeone.ui.icon(a.icon) : ""}${esc(a.label)}</button>`
			)
			.join("");
		return (
			`<div class="bo-empty${o.cls ? " " + o.cls : ""}"><div class="bo-empty-art${o.error ? " bo-empty-art--error" : ""}">` +
			`${beeone.ui.icon(o.art || (o.error ? "alert" : "inbox"))}</div>` +
			`<div class="bo-empty-title">${esc(o.title)}</div>` +
			(o.text ? `<div class="bo-empty-text">${esc(o.text)}</div>` : "") +
			(actions ? `<div class="bo-empty-actions">${actions}</div>` : "") +
			"</div>"
		);
	};

	// rows of shimmer bars; widths in % per column
	beeone.ui.skeleton_rows = function (count, widths) {
		const w = widths || [14, 12, 30, 16, 12];
		let out = "";
		for (let i = 0; i < count; i++) {
			out +=
				'<div class="bo-skel-row">' +
				w.map((p, j) => `<span class="bo-skel" style="width:${Math.max(6, p - ((i + j) % 3) * 2)}%"></span>`).join("") +
				"</div>";
		}
		return `<div class="bo-skel-list" aria-busy="true" aria-label="${esc(__("Loading"))}">${out}</div>`;
	};

	beeone.ui.esc = esc;
})();
