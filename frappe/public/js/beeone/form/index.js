// One form template for the catalogs and the documents, at platform level.
// Frappe's Form stays the engine. We rebuild the layout from a spec (beeone.form.LAYOUTS[doctype], or an automatic one):
// head (title, status, "Unsaved changes"), the command bar, a card with the groups "Main | ... | Additional"
// in a dense grid (1 / 2 / 3 columns by the window width, see scss/beeone/_form.scss), the card of the table parts with
// its commands and the totals footer.
//
// A configuration (an app) uses it through hooks.py (read at boot, see frappe/boot.py: bootinfo.beeone_form):
//   beeone_form_apps = ["app"]            # the template is on for every DocType of the app's modules
//   beeone_form_doctypes = ["DocType"]    # ... and for single DocTypes of other apps
//   beeone_form_exclude = ["DocType"]     # the template is off for these DocTypes
// and, from the app's JS, with
//   beeone.form.LAYOUTS["DocType"] = {kind, head, groups, tables, totals, go}   // replaces the automatic layout
//   header_fields stays above tabs; optional groups[].tables places table parts inside that tab.
//   beeone.form.COMMANDS["DocType"] = [{name, label, icon, menu, run(frm, el)}] // extra buttons of the command bar
//   beeone.form.enable("DocType") / beeone.form.disable("DocType")
//   beeone.form.DETAILS["*" | "DocType"] = {label, icon, fields}  // T-2309: fields kept out of the head, edited in a dialog
//                                                                // opened by a button of the command bar (e.g. "Prices and currency")
//   beeone.form.PAIRS = [[date_field, time_field, label]]          // two fields shown as one compact "Date and time" control
// A DocType that no app enabled is never touched, so an app that has its own form template is not affected.
frappe.provide("beeone.form");

(function () {
	const F = beeone.form;
	F.LAYOUTS = F.LAYOUTS || {};
	F.COMMANDS = F.COMMANDS || {};
	// the names the automatic layout and the title look for (a configuration may change the lists)
	F.AUTO = F.AUTO || {
		head: ["posting_date", "posting_time", "organization", "operation_kind", "counterparty", "contract", "warehouse"],
		totals: ["document_amount", "vat_amount", "total", "vat_total", "amount"],
		number: ["document_number", "onec_number"],
	};
	// T-2309: a date and a time field of one group are one compact control (both stay real fields of the form)
	F.PAIRS = F.PAIRS || [["posting_date", "posting_time", "Date and time"]];
	// T-2309: the fields a configuration moves from the head into the details dialog; "*" is for every DocType,
	// a DocType key replaces it. Absent fields are ignored, a DocType with none of them has no button.
	F.DETAILS = F.DETAILS || {};
	// "*" applies to the submittable DocTypes (documents) only; a catalog is given the dialog by its own key
	F.details_cfg = (doctype) => F.DETAILS[doctype] || (frappe.get_meta(doctype).is_submittable && F.DETAILS["*"]) || null;
	// the groups of custom buttons (frm.add_custom_button(label, fn, group)) that fill the «Fill» and «Status» menus
	F.GROUPS = F.GROUPS || { fill: ["Actions"], status: ["Status"] };
	const enabled = (F._on = F._on || new Set());
	const disabled = (F._off = F._off || new Set());
	F.enable = (doctype) => (disabled.delete(doctype), enabled.add(doctype));
	F.disable = (doctype) => (enabled.delete(doctype), disabled.add(doctype));

	// the apps/doctypes the hooks turned on (frappe.boot.beeone_form)
	F.enabled = (doctype) => {
		if (disabled.has(doctype)) return false;
		if (enabled.has(doctype)) return true;
		const boot = (frappe.boot && frappe.boot.beeone_form) || {};
		if ((boot.exclude || []).includes(doctype)) return false;
		if ((boot.doctypes || []).includes(doctype)) return true;
		const meta = frappe.get_meta(doctype);
		const app = meta && meta.module && (frappe.boot.module_app || {})[frappe.scrub(meta.module)];
		return !!app && (boot.apps || []).includes(app);
	};
	const esc = (v) => frappe.utils.escape_html(v == null ? "" : String(v));
	const ui = () => window.beeone && beeone.ui;
	const icon = (n) => (ui() && ui().icon ? ui().icon(n) : "");

	const SKIP = ["Section Break", "Column Break", "Tab Break"];
	const NEVER_GRID = ["amended_from"];

	F.active = (frm) => {
		if (!F.enabled(frm.doctype)) return false;
		const meta = frappe.get_meta(frm.doctype);
		if (!meta || meta.istable || meta.issingle) return false;
		if (!ui() || !ui().icon || !ui().menu) return false;
		return !(frm.page.current_view_name === "print" || frm.hidden);
	};

	F.perm = (frm) => (frm.perm && frm.perm[0]) || {};

	// T-867: a posted document of an opted-in doctype is edited in place and reposted on save (core beeone posted_edit)
	F.posted_edit = (frm) => frm.doc.docstatus === 1 && !!(frappe.model.beeone_posted_editable && frappe.model.beeone_posted_editable(frm.doc));
	F.editable = (frm) => frm.doc.docstatus === 0 || F.posted_edit(frm);

	// ---------------------------------------------------------------- spec

	// A spec of a DocType without a hand-written one: catalogs follow their Section Breaks, documents get the
	// head fields, then the rest up to 9 fields in "Main", everything else in "Additional".
	// A DocType with Tab Breaks: every tab becomes a group of the template (its label; the fields before the first tab
	// go to "Main"), the tables of all tabs go to the table card, so a tabbed form gets the same layout as the others.
	F.tab_groups = function (meta) {
		const groups = [{ key: "main", label: "Main", fields: [] }];
		let cur = groups[0];
		meta.fields.forEach((df) => {
			if (df.fieldtype === "Tab Break") {
				// a tab named «Main» continues the main group
				if (cur.key === "main" && /^(main|основне|головне)$/i.test(String(df.label || "").trim())) return;
				if (cur.fields.length || groups.length > 1 || cur.key !== "main") {
					// a tab named «Additional» is the template's «more» group (unnamed fields join it, no second one)
					const more = !df.label || /^(additional|more|extra|додатков)/i.test(String(df.label).trim());
					cur = { key: more ? "more" : "t" + groups.length, label: df.label || "Additional fields", fields: [] };
					groups.push(cur);
				} else if (df.label) {
					cur.label = df.label;
				}
			} else if (!SKIP.includes(df.fieldtype) && df.fieldtype !== "Table" && df.fieldname !== "comment") {
				cur.fields.push(df.fieldname);
			}
		});
		return groups.filter((g) => g.fields.length);
	};

	F.auto_spec = function (doctype) {
		const meta = frappe.get_meta(doctype);
		const fields = meta.fields.filter((df) => !SKIP.includes(df.fieldtype));
		const tables = fields.filter((df) => df.fieldtype === "Table").map((df) => ({ field: df.fieldname, label: df.label }));
		const plain = fields.filter((df) => df.fieldtype !== "Table");
		const has = (n) => plain.some((df) => df.fieldname === n);
		if (meta.fields.some((df) => df.fieldtype === "Tab Break")) {
			const totals = meta.is_submittable
				? F.AUTO.totals.filter(has).map((n, i) => [n, plain.find((df) => df.fieldname === n).label, i === 0]).filter((t) => t[0] !== "amount")
				: [];
			return {
				kind: meta.is_submittable ? "document" : "catalog",
				head: meta.is_submittable ? F.AUTO.head.filter(has) : plain.slice(0, 2).map((df) => df.fieldname),
				groups: F.tab_groups(meta),
				tables,
				totals,
			};
		}
		if (!meta.is_submittable) {
			const groups = [{ key: "main", label: "Main", fields: [] }];
			let cur = groups[0];
			meta.fields.forEach((df) => {
				if (df.fieldtype === "Section Break" && df.label && cur.fields.length) {
					cur = { key: "s" + groups.length, label: df.label, fields: [] };
					groups.push(cur);
				} else if (!SKIP.includes(df.fieldtype) && df.fieldtype !== "Table") cur.fields.push(df.fieldname);
			});
			return { kind: "catalog", head: plain.slice(0, 2).map((df) => df.fieldname), groups: groups.filter((g) => g.fields.length), tables, totals: [] };
		}
		const head = F.AUTO.head.filter(has);
		const rest = plain.map((df) => df.fieldname).filter((n) => !head.includes(n) && n !== "comment" && !NEVER_GRID.includes(n));
		const totals = F.AUTO.totals.filter(has).map((n, i) => [n, plain.find((df) => df.fieldname === n).label, i === 0]);
		const money = totals.map((t) => t[0]);
		const main = head.concat(rest.filter((n) => !money.includes(n) || n === "amount")).slice(0, 9);
		return {
			kind: "document",
			head,
			groups: [
				{ key: "main", label: "Main", fields: main },
				{ key: "more", label: "Additional fields", fields: [] },
			],
			tables,
			totals: totals.filter((t) => t[0] !== "amount"),
		};
	};

	F.spec = function (frm) {
		if (frm.bf_spec) return frm.bf_spec;
		const meta = frappe.get_meta(frm.doctype);
		const src = F.LAYOUTS[frm.doctype] || F.auto_spec(frm.doctype);
		const known = new Set(meta.fields.filter((df) => !SKIP.includes(df.fieldtype)).map((df) => df.fieldname));
		const used = new Set();
		const header_fields = (src.header_fields || []).filter((n) => known.has(n) && !used.has(n) && used.add(n));
		const cfg = F.details_cfg(frm.doctype);
		const details = cfg ? (cfg.fields || []).filter((n) => known.has(n) && !used.has(n) && used.add(n)) : [];
		const groups = src.groups.map((g) => ({
			key: g.key,
			label: g.label,
			tables: g.tables || [],
			fields: g.fields.filter((n) => known.has(n) && !used.has(n) && used.add(n)),
		}));
		const tables = (src.tables || []).filter((t) => known.has(t.field));
		// tables not named by the spec still show up
		meta.fields.forEach((df) => {
			if (df.fieldtype === "Table" && !tables.some((t) => t.field === df.fieldname)) tables.push({ field: df.fieldname, label: df.label });
		});
		tables.forEach((t) => used.add(t.field));
		const comment = src.kind === "document" && known.has("comment") ? "comment" : null;
		if (comment) used.add(comment);
		// a field the spec does not name is never lost: it goes to the last group "Additional"
		let more = groups.find((g) => g.key === "more");
		if (!more) {
			more = { key: "more", label: "Additional fields", fields: [] };
			groups.push(more);
		}
		meta.fields.forEach((df) => {
			if (!SKIP.includes(df.fieldtype) && !used.has(df.fieldname)) more.fields.push(df.fieldname);
		});
		frm.bf_spec = Object.assign({}, src, {
			header_fields,
			details: details.length ? { label: cfg.label || "Prices and currency", icon: cfg.icon || "sheet", fields: details } : null,
			head: (src.head || []).filter((n) => !details.includes(n)),
			groups: groups.filter((g) => g.fields.length || g.tables.length),
			tables,
			comment,
			totals: (src.totals || []).filter((t) => known.has(t[0])),
		});
		return frm.bf_spec;
	};

	// ---------------------------------------------------------------- layout

	F.setup = function (frm) {
		if (frm.bf_done) return true;
		const $page = $(frm.layout.wrapper).find(".form-page").first();
		if (!$page.length) return false;
		const spec = F.spec(frm);
		const sections = frm.layout.sections || [];
		const $body = $('<div class="bf-body"></div>');
		const $main = $('<section class="bf-card bf-main"></section>');
		const $tabs = $(`<div class="bf-tabs" role="tablist" aria-label="${esc(__("Form sections"))}"></div>`);
		if (spec.header_fields.length) {
			const $header = $('<section class="bf-card bf-header"><div class="bf-grid"></div></section>');
			const merged = new Set();
			spec.header_fields.forEach((n) => {
				const f = frm.fields_dict[n];
				if (!f || !f.$wrapper || merged.has(n)) return;
				const pair = F.PAIRS.find((p) => p[0] === n && spec.header_fields.includes(p[1]) && frm.fields_dict[p[1]]);
				if (pair) {
					merged.add(pair[1]);
					$header.find('.bf-grid').append(F.pair_cell(frm, pair));
				} else $header.find('.bf-grid').append(f.$wrapper);
			});
			$body.append($header);
		}
		$main.append($tabs);
		spec.groups.forEach((g) => {
			$tabs.append(`<button type="button" class="bf-tab" role="tab" data-grp="${esc(g.key)}">${esc(__(g.label))}</button>`);
			const $grp = $(`<div class="bf-grp" role="tabpanel" data-grp="${esc(g.key)}"><div class="bf-grid"></div></div>`);
			const merged = new Set();
			g.fields.forEach((n) => {
				const f = frm.fields_dict[n];
				if (!f || !f.$wrapper || merged.has(n)) return;
				const pair = F.PAIRS.find((p) => p[0] === n && g.fields.includes(p[1]) && frm.fields_dict[p[1]] && frm.fields_dict[p[1]].$wrapper);
				if (pair) {
					merged.add(pair[1]);
					$grp.find(".bf-grid").append(F.pair_cell(frm, pair));
				} else $grp.find(".bf-grid").append(f.$wrapper);
			});
			$main.append($grp);
		});
		$body.append($main);

		if (spec.tables.length) {
			const $tp = $(
				`<section class="bf-card bf-tp" aria-label="${esc(__("Table parts"))}"><div class="bf-tp-head"><div class="bf-tabs bf-tp-tabs" role="tablist"></div>` +
					`<div class="bf-tp-bar" role="toolbar" aria-label="${esc(__("Table commands"))}"></div></div><div class="bf-tp-body"></div></section>`
			);
			spec.tables.forEach((t) => {
				const f = frm.fields_dict[t.field];
				if (!f || !f.$wrapper) return;
				$tp.find(".bf-tp-tabs").append(
					`<button type="button" class="bf-tab" role="tab" data-tab="${esc(t.field)}">${esc(__(t.label || f.df.label))}<span class="bf-count"></span></button>`
				);
				$tp.find(".bf-tp-body").append($('<div class="bf-tp-sec"></div>').attr("data-tab", t.field).append(f.$wrapper));
			});
			$body.append($tp);
			frm.bf_tab = spec.tables[0].field;
			$tp.on("click", ".bf-tab", function () {
				frm.bf_tab = $(this).attr("data-tab");
				F.render_tp(frm);
			});
			$tp.on("click", "[data-bf]", function () {
				F.bf_command(frm, $(this).attr("data-bf"));
			});
			$tp.on("focusin", ".grid-row", function () {
				frm.bf_row = parseInt($(this).attr("data-idx"), 10) || null;
				F.reveal_row(frm, this);
			});
			// an open cell list is positioned from the cell: scrolling the rows moves the cell, so the list closes
			$tp[0].addEventListener(
				"scroll",
				(e) => {
					if (!e.target.classList || !e.target.classList.contains("form-grid-container")) return;
					$tp.find(".awesomplete > ul:not([hidden])").attr("hidden", "");
				},
				true
			);
		}

		if (spec.comment || spec.totals.length) {
			const $foot = $(
				`<div class="bf-foot">` +
					(spec.comment
						? `<input class="bf-comment" data-bf-comment placeholder="${esc(__("Comment"))}" aria-label="${esc(__("Comment"))}">`
						: "") +
					`<div class="bf-totals" aria-live="polite"></div></div>`
			);
			$body.append($foot);
			$foot.on("change", "[data-bf-comment]", function () {
				if (F.editable(frm)) frm.set_value(spec.comment, this.value);
			});
		}

		if (spec.details) {
			// the fields of the details dialog stay in the form (values, events, autofill), only out of sight
			frm.bf_details = $('<div class="bf-details-holder bf-gone" aria-hidden="true"></div>');
			spec.details.fields.forEach((n) => {
				const f = frm.fields_dict[n];
				if (f && f.$wrapper) frm.bf_details.append(f.$wrapper);
			});
			$body.append(frm.bf_details);
		}

		$page.prepend($body);
		// everything the spec places has moved; the Frappe sections are empty shells now
		sections.forEach((s) => s.wrapper && $(s.wrapper).addClass("bf-gone"));
		// the Frappe tab bar of a tabbed DocType: its tabs are the groups of the template now
		$(frm.layout.wrapper).find(".form-tabs-list").addClass("bf-gone");
		if (spec.comment && frm.fields_dict[spec.comment]) $(frm.fields_dict[spec.comment].$wrapper).addClass("bf-gone");

		$main.on("click", ".bf-tab", function () {
			F.show_group(frm, $(this).attr("data-grp"), true);
		});
		$tabs.on("keydown", (e) => {
			if (!["ArrowLeft", "ArrowRight"].includes(e.key)) return;
			const list = $tabs.find(".bf-tab:visible").get();
			const i = list.indexOf(document.activeElement) + (e.key === "ArrowRight" ? 1 : -1);
			if (list[i]) list[i].focus(), $(list[i]).trigger("click");
		});

		$(frm.page.wrapper).addClass("bf-form bf-form--" + spec.kind);
		F.watch_fit(frm);
		F.setup_queries(frm);
		F.wrap_frm(frm);
		frm.bf_done = true;
		return true;
	};

	// T-2309: "Date and time" - one grid cell under one label; since 2026-11-20 one masked input (dt_input.js)
	F.pair_cell = function (frm, pair) {
		const a = frm.fields_dict[pair[0]];
		const b = frm.fields_dict[pair[1]];
		const id = "bf-dt-" + pair[0];
		const reqd = a.df.reqd || b.df.reqd;
		const $cell = $(
			`<div class="frappe-control bf-dt" data-fieldtype="Datetime" data-fieldname="${esc(pair[0])}" role="group" aria-labelledby="${id}">` +
				`<div class="form-group"><label class="control-label${reqd ? " reqd" : ""}" id="${id}">${esc(__(pair[2]))}</label>` +
				`<div class="bf-dt-row"></div></div></div>`
		);
		// one masked input shows and edits both fields (dt_input.js); the two controls stay in the form, hidden
		$cell.find(".bf-dt-row").append(F.dt_input(frm, a, b, $cell));
		$cell.find("label").attr("for", null);
		const $hidden = $('<div class="bf-dt-fields" hidden></div>').appendTo($cell.find(".form-group"));
		[a, b].forEach((f) => {
			$(f.$wrapper).addClass("bf-dt-part");
			$hidden.append(f.$wrapper);
		});
		return $cell;
	};

	// T-2309: the details dialog ("Prices and currency"): the fields move into it while it is open and go back on close
	F.open_details = function (frm) {
		const spec = F.spec(frm);
		if (!spec.details || !frm.bf_details || !ui() || !ui().dialog) return null;
		if (frm.bf_details_dlg) return frm.bf_details_dlg;
		const title = __(spec.details.label);
		const d = ui().dialog({
			title,
			width: 640,
			className: "bf-form bf-details-dlg",
			html:
				`<div class="bo-dialog-head"><div><div class="bo-dialog-title">${esc(title)}</div></div></div>` +
				`<div class="bf-details-body"><div class="bf-grid"></div></div>` +
				`<div class="bo-dialog-foot"><div class="bo-right"><button class="bo-btn bo-btn--primary" data-close autofocus>${esc(__("Close"))}</button></div></div>`,
			on_close: () => {
				spec.details.fields.forEach((n) => {
					const f = frm.fields_dict[n];
					if (f && f.$wrapper) frm.bf_details.append(f.$wrapper);
				});
				frm.bf_details_dlg = null;
				F.refresh_fields(frm);
				F.render_totals(frm);
			},
		});
		const $grid = $(d.box).find(".bf-grid");
		spec.details.fields.forEach((n) => {
			const f = frm.fields_dict[n];
			if (f && f.$wrapper) $grid.append(f.$wrapper);
		});
		frm.bf_details_dlg = d;
		return d;
	};

	F.refresh_fields = (frm) => {
		const spec = F.spec(frm);
		((spec.details && spec.details.fields) || []).forEach((n) => frm.fields_dict[n] && frm.fields_dict[n].refresh && frm.fields_dict[n].refresh());
	};

	// All groups stay in the layout (one grid cell, see bf_form.css .bf-main), so the head keeps the
	// height of the tallest group; the inactive ones are invisible and inert, not [hidden].
	function set_active_group($w, key) {
		$w.find(".bf-main > .bf-grp").each(function () {
			const off = $(this).attr("data-grp") !== key;
			$(this).prop("hidden", false).toggleClass("is-off", off).attr("aria-hidden", off ? "true" : null);
			if (off) this.setAttribute("inert", "");
			else this.removeAttribute("inert");
		});
	}

	F.show_group = function (frm, key, remember) {
		const $w = $(frm.layout.wrapper);
		$w.find(".bf-main > .bf-tabs .bf-tab").each(function () {
			const on = $(this).attr("data-grp") === key;
			$(this).toggleClass("is-on", on).attr("aria-selected", on).attr("tabindex", on ? 0 : -1);
		});
		set_active_group($w, key);
		frm.bf_group = key;
		const spec = F.spec(frm);
		if (spec.groups.some((g) => g.tables.length)) {
			const group = spec.groups.find((g) => g.key === key);
			const tables = group?.tables || [];
			const $tp = $w.find('.bf-tp');
			$tp.appendTo($w.find(`.bf-main > .bf-grp[data-grp="${key}"]`));
			if (!tables.includes(frm.bf_tab)) frm.bf_tab = tables[0];
			F.render_tp(frm);
		}
		if (remember) {
			try {
				localStorage.setItem("bf_form_grp:" + frm.doctype, key);
			} catch (e) {
				// private mode: the choice is only not remembered
			}
		}
	};

	// a group whose fields are all hidden (depends_on) has no tab; the active group follows
	F.render_groups = function (frm) {
		const spec = F.spec(frm);
		const $w = $(frm.layout.wrapper);
		const tried = frm.bf_tried === frm.doc.name;
		const visible = [];
		spec.groups.forEach((g) => {
			const fs = g.fields.map((n) => frm.fields_dict[n]).filter(Boolean);
			const shown = g.tables.length || fs.some((f) => !f.$wrapper.hasClass("hide-control") && f.$wrapper.css("display") !== "none");
			const bad = tried && fs.some((f) => f.df.reqd && !f.$wrapper.hasClass("hide-control") && (frm.doc[f.df.fieldname] == null || frm.doc[f.df.fieldname] === ""));
			const $t = $w.find(`.bf-main > .bf-tabs .bf-tab[data-grp="${g.key}"]`);
			$t.prop("hidden", !shown).toggleClass("has-error", !!bad);
			if (bad) $t.attr("title", __("Mandatory fields are empty"));
			else $t.removeAttr("title");
			$t.find(".bf-sr-only").remove();
			if (bad) $t.append(`<span class="bf-sr-only"> ${esc(__("Mandatory fields are empty"))}</span>`);
			if (shown) visible.push(g.key);
		});
		$w.find(".bf-main > .bf-tabs").prop("hidden", visible.length < 2);
		if (!visible.length) return;
		let cur = frm.bf_group;
		if (!cur) {
			try {
				cur = localStorage.getItem("bf_form_grp:" + frm.doctype);
			} catch (e) {
				cur = null;
			}
		}
		if (!visible.includes(cur)) cur = visible[0];
		if (cur !== frm.bf_group || !$w.find(".bf-main > .bf-tabs .bf-tab.is-on").length) F.show_group(frm, cur, false);
		// with a single visible group the strip is hidden, the group stays visible
		if (visible.length < 2) set_active_group($w, cur);
		// a group without any visible field takes no room
		spec.groups.forEach((g) => {
			if (!visible.includes(g.key)) $w.find(`.bf-main > .bf-grp[data-grp="${g.key}"]`).prop("hidden", true);
		});
	};

	// ---------------------------------------------------------------- link filters (client only)

	F.setup_queries = function (frm) {
		const by_target = F.TARGET_FILTERS || {};
		const by_field = (F.FIELD_FILTERS || {})[frm.doctype] || {};
		const pick = (df, parent_doctype) => {
			if (by_field[df.fieldname] && parent_doctype === frm.doctype) return by_field[df.fieldname];
			if (df.fieldname.startsWith("parent_") && F.GROUP_FILTER && df.options === frm.doctype) return F.GROUP_FILTER;
			// do not filter a catalog's own link to itself in other roles (the head of a group etc.)
			if (df.options === frm.doctype) return null;
			return by_target[df.options] || null;
		};
		frappe.get_meta(frm.doctype).fields.forEach((df) => {
			if (df.fieldtype === "Link") {
				const fn = pick(df, frm.doctype);
				if (fn) frm.set_query(df.fieldname, () => ({ filters: fn(frm) }));
			} else if (df.fieldtype === "Table") {
				const child = frappe.get_meta(df.options);
				((child && child.fields) || []).forEach((cdf) => {
					const fn = cdf.fieldtype === "Link" && by_target[cdf.options];
					// a contract link inside a table follows the document's counterparty too; the rest is "elements only"
					if (fn) frm.set_query(cdf.fieldname, df.fieldname, () => ({ filters: fn(frm) }));
				});
			}
		});
	};

	// ---------------------------------------------------------------- re-homed Frappe buttons

	// the buttons other scripts add with frm.add_custom_button: {group: [{label, el}]}; "" is the ungrouped ones
	F.custom_buttons = function (frm) {
		const out = {};
		const $tb = frm.page.inner_toolbar || $(frm.page.wrapper).find(".inner-toolbar");
		$tb.find(".inner-group-button").each(function () {
			const group = decodeURIComponent($(this).attr("data-label") || "");
			$(this)
				.find(".dropdown-menu a, .dropdown-menu button")
				.each(function () {
					(out[group] = out[group] || []).push({ label: $(this).text().trim(), el: this });
				});
		});
		$tb.children("button").each(function () {
			const label = decodeURIComponent($(this).attr("data-label") || $(this).text().trim());
			if (
				label !== __("Document Movements") &&
				label !== __("Save and close") &&
				label !== __("Save and Close") &&
				label !== "Save and close" &&
				label !== "Save and Close"
			) (out[""] = out[""] || []).push({ label, el: this });
		});
		return out;
	};

	F.wrap_frm = function (frm) {
		const orig = frm.add_custom_button.bind(frm);
		frm.add_custom_button = function () {
			const r = orig.apply(null, arguments);
			F.soon(frm);
			return r;
		};
		const save = frm.save.bind(frm);
		frm.save = function () {
			frm.bf_tried = frm.doc.name;
			return save.apply(null, arguments);
		};
		const scroll = frm.scroll_to_field && frm.scroll_to_field.bind(frm);
		if (scroll) {
			frm.scroll_to_field = function (fieldname) {
				F.spec(frm).groups.forEach((g) => g.fields.includes(fieldname) && F.show_group(frm, g.key, false));
				if (((F.spec(frm).details || {}).fields || []).includes(fieldname)) F.open_details(frm);
				F.spec(frm).tables.forEach((t) => t.field === fieldname && ((frm.bf_tab = fieldname), F.render_tp(frm)));
				return scroll.apply(null, arguments);
			};
		}
	};

	// after all form-refresh handlers (the custom buttons of other scripts) the bar is drawn once
	F.soon = function (frm) {
		clearTimeout(frm.bf_timer);
		frm.bf_timer = setTimeout(() => {
			if (frm.bf_done && frm === window.cur_frm) F.render_bar(frm);
		}, 0);
	};

	// ---------------------------------------------------------------- head and command bar

	F.title = function (frm) {
		const meta = frappe.get_meta(frm.doctype);
		if (frm.is_new()) return __("New record");
		if (meta.is_submittable) {
			const num = F.AUTO.number.map((n) => frm.doc[n]).find(Boolean) || frm.doc.name;
			return frm.doc.posting_date ? __("{0} dated {1}", [num, frappe.datetime.str_to_user(frm.doc.posting_date)]) : num;
		}
		const spec = F.spec(frm);
		const label = spec.head.map((n) => frm.doc[n]).find((v) => typeof v === "string" && v && v !== frm.doc.code) || frm.doc.name;
		return frm.doc.code ? `${label} · ${frm.doc.code}` : label;
	};

	F.status = function (frm) {
		const meta = frappe.get_meta(frm.doctype);
		if (!meta.is_submittable) return frm.doc.deletion_mark ? ["cancelled", __("Marked for deletion")] : null;
		if (frm.is_new()) return ["draft", __("Draft")];
		const ds = Number(frm.doc.docstatus || 0);
		return ds === 1 ? ["posted", __("Document posted")] : ds === 2 ? ["cancelled", __("Cancelled")] : ["draft", __("Draft")];
	};

	F.render_head = function (frm) {
		const $title = $(frm.page.wrapper).find(".page-head .page-title").first();
		let $h = $title.find(".bf-head");
		if (!$h.length) {
			$h = $(
				`<div class="bf-head"><div class="bf-title-row">` +
					`<button type="button" class="bf-btn bf-btn--ghost bf-btn--icon" data-bf-cmd="back" aria-label="${esc(__("To the list"))}" title="${esc(__("To the list"))} · Esc">${icon("chev-l")}</button>` +
					`<h1 class="bf-title"></h1><span class="bf-badge bf-badge--status bf-doc-state" hidden></span><span class="bf-badge bf-badge--main" role="status"></span>` +
					`<span class="bf-dirty">${esc(__("Unsaved changes"))}</span></div>` +
					`<div class="bf-bar" role="toolbar" aria-label="${esc(__("Form commands"))}"></div></div>`
			);
			$title.prepend($h);
			$h.on("click", "[data-bf-cmd]", function (e) {
				F.command(window.cur_frm && cur_frm.doctype === frm.doctype ? cur_frm : frm, $(this).attr("data-bf-cmd"), this, e);
			});
		}
		const type = __(frm.doctype);
		$h.find(".bf-title").html(`<span class="bf-type">${esc(type)}</span> ${esc(F.title(frm))}`);
		const st = F.status(frm);
		$h.find(".bf-badge--main")
			.attr("class", `bf-badge bf-badge--main ${st ? "bf-badge--" + st[0] : ""}`)
			.text(st ? st[1] : "")
			.prop("hidden", !st);
		const doc_state = frm.doc.status && frappe.meta.has_field(frm.doctype, "status") ? frm.doc.status : "";
		$h.find(".bf-doc-state").text(doc_state ? __(doc_state) : "").prop("hidden", !doc_state);
		$(frm.page.wrapper).addClass("bf-bar-on");
		F.render_dirty(frm);
		F.render_bar(frm);
	};

	F.render_dirty = function (frm) {
		const on = frm.is_dirty() && !frm.is_new() && F.editable(frm);
		$(frm.page.wrapper).find(".bf-dirty").toggleClass("is-on", !!on);
	};

	// the command bar shows icons only, the name is in the tooltip; only the main "... and close" command keeps its text (o.label)
	const btn = (cmd, label, ic, o) => {
		o = Object.assign({ icon_only: true }, o);
		if (o.label) o.icon_only = false;
		if (o.icon_only) o.tip = o.tip ? `${label} · ${o.tip}` : label;
		const cls = ["bf-btn"];
		if (o.primary) cls.push("bf-btn--primary");
		if (o.ghost) cls.push("bf-btn--ghost");
		if (o.icon_only) cls.push("bf-btn--icon");
		const menu = o.menu ? ' aria-haspopup="menu" aria-expanded="false"' : "";
		return (
			`<button type="button" class="${cls.join(" ")}" data-bf-cmd="${cmd}"${menu}${o.tip ? ` title="${esc(o.tip)}"` : ""}${o.icon_only ? ` aria-label="${esc(label)}"` : ""}>` +
			(ic ? icon(ic) : "") +
			(o.icon_only ? "" : `<span>${esc(label)}</span>`) +
			(o.menu && !o.icon_only ? icon("chev-d") : "") +
			"</button>"
		);
	};

	// the side panel (assignment, attachments, tags, share) is closed by default and opened on demand
	function panel_btn(frm) {
		const open = !!(frm.sidebar && frm.sidebar.sidebar_visible);
		const label = open ? __("Hide panel") : __("Show panel");
		return btn("panel", label, "panel", { ghost: true }).replace("<button ", `<button aria-pressed="${open}" `);
	}

	function basis_entries(frm) {
		const api = window.beeone && window.beeone.basis;
		return api && typeof api.entries === "function" ? api.entries(frm) || [] : [];
	}

	F.render_bar = function (frm) {
		const $bar = $(frm.page.wrapper).find(".bf-bar");
		if (!$bar.length) return;
		const spec = F.spec(frm);
		const perm = F.perm(frm);
		const meta = frappe.get_meta(frm.doctype);
		const ds = Number(frm.doc.docstatus || 0);
		const left = [];
		const mid = [];
		const can_write = perm.write && !frm.save_disabled;
		if (!meta.is_submittable) {
			if (can_write) {
				left.push(btn("save_close", __("Save and close"), "check", { primary: true, label: true, tip: "Ctrl + Enter" }));
				left.push(btn("save", __("Save"), "save", { tip: "Ctrl + S" }));
			}
			if ((spec.go || []).length && !frm.is_new()) mid.push(btn("go", __("Go to"), "arrow-right", { menu: true }));
		} else if (ds === 0) {
			if (can_write) {
				if (perm.submit) left.push(btn("post_close", __("Post and close"), "checks", { primary: true, label: true, tip: "Ctrl + Enter" }));
				else left.push(btn("save_close", __("Save and close"), "check", { primary: true, label: true, tip: "Ctrl + Enter" }));
				left.push(btn("save", __("Save"), "save", { tip: "Ctrl + S" }));
				if (perm.submit) left.push(btn("post", __("Post"), "check"));
			}
		} else if (ds === 1) {
			if (F.posted_edit(frm)) {
				left.push(btn("repost_close", __("Post and close"), "checks", { primary: true, label: true, tip: "Ctrl + Enter" }));
				left.push(btn("repost", __("Save"), "save", { tip: "Ctrl + S" }));
				left.push(btn("repost_post", __("Post"), "check"));
			}
			if (perm.cancel) left.push(btn("unpost", __("Cancel posting"), "undo"));
		} else if (ds === 2 && perm.amend) {
			left.push(btn("amend", __("Amend"), "pencil", { primary: true }));
		}
		const custom = F.custom_buttons(frm);
		frm.bf_custom = custom;
		if (!meta.is_submittable && basis_entries(frm).length) mid.push(btn("basis", __("Create on the basis"), "file-plus", { menu: true }));
		if (meta.is_submittable) {
			if (F.group_buttons(frm, "fill").length) mid.push(btn("fill", __("Fill"), "list", { menu: true }));
			if (F.group_buttons(frm, "status").length) mid.push(btn("status", __("Document status"), "sliders", { menu: true }));
			if (basis_entries(frm).length) mid.push(btn("basis", __("Create on the basis"), "file-plus", { menu: true }));
			if (ds === 1 && !frm.is_new()) mid.push(btn("movements", __("Document movements"), "dtkt"));
			if (!frm.is_new() && window.beeone?.subordination?.show) mid.push(btn("structure", __("Subordination structure"), "tree"));
			if (!frm.is_new() && frappe.model.can_print_doc(frm)) mid.push(btn("print", __("Print"), "printer", { menu: true }));
		}
		// the commands other scripts add with frm.add_custom_button outside the menus above: single ones are bar buttons,
		// a named group is a menu (the "Create on basis" group is the «Create on the basis» menu)
		F.own_buttons(frm).forEach((b) => mid.push(btn(b.cmd, b.label, "list", { menu: !!b.group, label: true })));
		if (spec.details) mid.push(btn("details", __(spec.details.label), spec.details.icon));
		((F.COMMANDS[frm.doctype] || []).filter((c) => !c.show || c.show(frm))).forEach((c) =>
			mid.push(btn("x:" + c.name, c.label, c.icon || "list", { menu: !!c.menu }))
		);
		const sep = left.length && mid.length ? '<span class="bf-sep"></span>' : "";
		const html =
			left.join("") +
			sep +
			mid.join("") +
			`<div class="bf-right">${frm.is_new() ? "" : panel_btn(frm)}${btn("more", __("More"), "more", { ghost: true, menu: true })}${btn("close_list", __("Close"), "x", { ghost: true })}</div>`;
		// the same bar is not drawn twice: a redraw would drop the hover and the focus of the button
		if ($bar.data("bf-html") !== html) $bar.data("bf-html", html).html(html);
	};

	F.command = function (frm, cmd, el) {
		if (cmd.startsWith("x:")) {
			const c = (F.COMMANDS[frm.doctype] || []).find((x) => "x:" + x.name === cmd);
			return c && c.run(frm, el);
		}
		if (cmd.startsWith("cb:") || cmd.startsWith("cg:")) {
			const own = F.own_buttons(frm).find((x) => x.cmd === cmd);
			if (!own) return;
			if (!own.group) return own.items[0].el.click();
			return ui().menu(
				el,
				own.items.map((b, i) => `<button class="bo-menu-item" data-i="${i}">${esc(b.label)}</button>`).join(""),
				(item) => {
					const b = own.items[+item.getAttribute("data-i")];
					if (b) b.el.click();
				}
			);
		}
		const go_list = () => frappe.set_route("List", frm.doctype);
		switch (cmd) {
			case "back":
			case "close_list":
				return F.leave(frm, go_list);
			case "repost_close":
				return frm.save("Update", () => go_list(), $(el));
			case "repost":
			case "repost_post":
				return frm.save("Update", null, $(el));
			case "post_close":
				return frm.save("Submit", () => go_list(), $(el));
			case "save_close": {
				// a record made from a link field of another form: its window closes, the caller is shown again
				const from_link = !!frappe._from_link?.field_obj?.frm;
				return frm.save("Save", () => (from_link ? F.close_window(frm) || go_list() : go_list()), $(el));
			}
			case "save":
				return frm.save("Save", null, $(el));
			case "post":
				return frm.save("Submit", null, $(el));
			case "unpost":
				return frm.savecancel($(el));
			case "amend":
				return frm.amend_doc();
			case "print":
				return F.print_menu(frm, el);
			case "movements":
				return window.beeone?.registers?.show_movements && beeone.registers.show_movements(frm);
			case "structure":
				return beeone.subordination.show(frm);
			case "details":
				return F.open_details(frm);
			case "fill":
				return F.custom_menu(frm, el, "fill");
			case "status":
				return F.custom_menu(frm, el, "status");
			case "basis":
				return F.basis_menu(frm, el);
			case "go":
				return F.go_menu(frm, el);
			case "more":
				return F.more_menu(frm, el);
			case "panel":
				if (frm.sidebar && frm.sidebar.toggle_visibility) frm.sidebar.toggle_visibility();
				return F.render_bar(frm);
		}
	};

	// Configurations can supply their enabled forms and their own renderer.
	F.print_menu = async function (frm, el) {
		const formats = frm.get_print_menu_formats
			? await frm.get_print_menu_formats()
			: frappe.meta.get_print_formats(frm.doctype);
		if (!formats.length) {
			frappe.msgprint(__("No print formats available"));
			return;
		}
		ui().menu(
			el,
			formats.map((name, i) => `<button class="bo-menu-item" data-i="${i}">${esc(__(name))}</button>`).join(""),
			(item) => {
				const name = formats[Number(item.getAttribute("data-i"))];
				if (frm.open_print_format) return frm.open_print_format(name);
				frm.print_doc(name);
			}
		);
	};

	// the custom buttons of the groups F.GROUPS[kind] (the English names and their translations)
	F.group_buttons = function (frm, kind) {
		const custom = frm.bf_custom || {};
		const names = new Set();
		(F.GROUPS[kind] || []).forEach((g) => (names.add(g), names.add(__(g))));
		return [...names].reduce((acc, g) => acc.concat(custom[g] || []), []);
	};

	// the custom buttons that no fixed menu takes over: [{cmd, label, group, items}]
	F.own_buttons = function (frm) {
		const custom = frm.bf_custom || {};
		const taken = new Set([__("Create on basis"), "Create on basis"]);
		["fill", "status"].forEach((k) => (F.GROUPS[k] || []).forEach((g) => (taken.add(g), taken.add(__(g)))));
		const out = [];
		(custom[""] || []).forEach((b, i) => out.push({ cmd: "cb:" + i, label: b.label, items: [b] }));
		Object.keys(custom)
			.filter((g) => g && !taken.has(g))
			.forEach((g) => out.push({ cmd: "cg:" + g, label: g, group: g, items: custom[g] }));
		return out;
	};

	F.custom_menu = function (frm, el, kind) {
		const list = F.group_buttons(frm, kind);
		ui().menu(
			el,
			list.map((b, i) => `<button class="bo-menu-item" data-i="${i}">${esc(b.label)}</button>`).join(""),
			(item) => {
				const b = list[+item.getAttribute("data-i")];
				if (b) b.el.click();
			}
		);
	};

	F.basis_menu = function (frm, el) {
		const list = basis_entries(frm);
		ui().menu(
			el,
			`<div class="bo-menu-label">${esc(__("Create on the basis"))}</div>` +
				list.map((b, i) => `<button class="bo-menu-item" data-i="${i}">${icon("file-plus")}${esc(__(b.label))}</button>`).join(""),
			(item) => {
				const b = list[+item.getAttribute("data-i")];
				if (!b) return;
				if ((b.submitted || b.submit_first) && frm.doc.docstatus !== 1) {
					ui().toast && ui().toast({ type: "warning", title: __("Post the document first"), text: __("A document on the basis is created from a posted one.") });
					return;
				}
				if (window.beeone?.basis?.create) window.beeone.basis.create(frm, b);
			}
		);
	};

	// "Go to" of a catalog (the navigation panel): links to the lists of the related records, nothing is loaded here
	F.go_menu = function (frm, el) {
		const list = F.spec(frm).go || [];
		ui().menu(
			el,
			list.map((g, i) => `<button class="bo-menu-item" data-i="${i}">${esc(__(g.label))}</button>`).join(""),
			(item) => {
				const g = list[+item.getAttribute("data-i")];
				if (g) frappe.set_route("List", g.doctype, { [g.field]: frm.doc.name });
			}
		);
	};

	F.more_menu = function (frm, el) {
		const perm = F.perm(frm);
		const items = [];
		if (!frm.is_new()) items.push(`<button class="bo-menu-item" data-a="panel">${icon("panel")}${esc(frm.sidebar && frm.sidebar.sidebar_visible ? __("Hide panel") : __("Show panel"))}</button>`);
		if (!frm.is_new() && frappe.model.can_create(frm.doctype)) items.push(`<button class="bo-menu-item" data-a="copy">${icon("copy")}${esc(__("Copy"))}</button>`);
		if (!frm.is_new()) {
			items.push(`<button class="bo-menu-item" data-a="reload">${icon("refresh")}${esc(__("Reload from the database"))}</button>`);
			items.push(`<button class="bo-menu-item" data-a="history">${icon("history")}${esc(__("Change history"))}</button>`);
		}
		if (!frm.is_new() && frm.doc.docstatus !== 1 && perm.delete) {
			items.push('<div class="bo-menu-sep"></div>');
			items.push(`<button class="bo-menu-item is-danger" data-a="delete">${icon("trash")}${esc(__("Delete record"))}</button>`);
		}
		if (!items.length) items.push(`<div class="bo-menu-empty">${esc(__("No other actions"))}</div>`);
		ui().menu(
			el,
			items.join(""),
			(item) => {
				const a = item.getAttribute("data-a");
				if (a === "panel") F.command(frm, "panel", null);
				if (a === "copy") frm.copy_doc();
				if (a === "reload") frm.reload_doc();
				if (a === "history") $(frm.page.wrapper).find(".form-footer").get(0)?.scrollIntoView({ behavior: "smooth", block: "start" });
				if (a === "delete") {
					frappe.confirm(__("Delete {0}?", [frm.doc.name]), () => frappe.model.delete_doc(frm.doctype, frm.doc.name, () => frappe.set_route("List", frm.doctype)));
				}
			},
			{ align: "right" }
		);
	};

	F.close_window = function (frm) {
		const W = beeone.shell.windows;
		for (const [key, win] of W.wins.map) {
			if (win.page && win.page.frm === frm) {
				W.close(key, true);
				return true;
			}
		}
		return false;
	};

	F.leave = function (frm, go) {
		if (!frm.is_dirty() || !F.editable(frm) || !ui().dialog) return go();
		const d = ui().dialog({
			title: __("Save the changes?"),
			width: 460,
			html:
				`<div class="bo-dialog-head"><div><div class="bo-dialog-title">${esc(__("Save the changes?"))}</div>` +
				`<div class="bo-dialog-sub">${esc(frm.is_new() ? __("The new record is not saved yet.") : __("{0} has unsaved changes.", [frm.doc.name]))}</div></div></div>` +
				`<div class="bo-dialog-foot"><button class="bo-btn bo-btn--danger-ghost" data-act="drop">${esc(__("Do not save"))}</button>` +
				`<div class="bo-right"><button class="bo-btn" data-close>${esc(__("Keep editing"))}</button>` +
				`<button class="bo-btn bo-btn--primary" data-act="save" autofocus>${esc(__("Save"))}</button></div></div>`,
		});
		$(d.box).on("click", "[data-act]", function () {
			const act = $(this).attr("data-act");
			d.close();
			if (act === "save") frm.save().then(() => !frm.is_dirty() && go());
			else {
				frappe.model.remove_from_locals(frm.doctype, frm.doc.name);
				go();
			}
		});
	};

	// ---------------------------------------------------------------- table part

	F.grid = (frm) => {
		const f = frm.fields_dict[frm.bf_tab];
		return f && f.grid;
	};

	F.render_tp = function (frm) {
		const $tp = $(frm.layout.wrapper).find(".bf-tp");
		if (!$tp.length) return;
		const spec = F.spec(frm);
		if (spec.groups.some((g) => g.tables.length)) {
			const group = spec.groups.find((g) => g.key === frm.bf_group);
			const available = (group?.tables || []).filter((n) => {
				const f = frm.fields_dict[n];
				return f && !f.df.hidden && !f.$wrapper.hasClass('hide-control');
			});
			$tp.prop('hidden', !available.length);
			$tp.find('.bf-tp-tabs .bf-tab').each(function () {
				$(this).prop('hidden', !available.includes($(this).attr('data-tab')));
			});
			if (!available.includes(frm.bf_tab)) frm.bf_tab = available[0];
		}
		const tab = frm.bf_tab;
		$tp.find(".bf-tp-sec").each(function () {
			$(this).prop("hidden", $(this).attr("data-tab") !== tab);
		});
		$tp.find(".bf-tab").each(function () {
			const key = $(this).attr("data-tab");
			const on = key === tab;
			$(this).toggleClass("is-on", on).attr("aria-selected", on);
			$(this).find(".bf-count").text((frm.doc[key] || []).length || "");
		});
		if (frm.bf_fit) frm.bf_fit();
		const grid = F.grid(frm);
		const editable = !!grid && F.editable(frm) && !grid.df.read_only && !!F.perm(frm).write;
		const rows = (frm.doc[tab] || []).length;
		const sel = grid ? grid.get_selected_children().length : 0;
		const b = (cmd, label, ic, o) =>
			`<button type="button" class="bf-btn bf-btn--sm${o && o.icon_only ? " bf-btn--ghost bf-btn--icon" : ""}" data-bf="${cmd}"` +
			`${o && o.tip ? ` title="${esc(o.tip)}"` : ""}${o && o.icon_only ? ` aria-label="${esc(label)}"` : ""}>${icon(ic)}${o && o.icon_only ? "" : esc(label)}</button>`;
		const dense = !(frappe.ui.grid_density && frappe.ui.grid_density.get() === "comfortable");
		const dens_label = dense ? __("Regular rows") : __("Dense rows");
		const dens_btn =
			`<button type="button" class="bf-btn bf-btn--sm bf-btn--ghost bf-btn--icon bf-density" data-bf="density" aria-pressed="${dense}" ` +
			`title="${esc(dens_label)}" aria-label="${esc(dens_label)}">${icon("menu")}</button>`;
		$tp.find(".bf-tp-bar").html(
			(editable
				? b("add", __("Add"), "plus", { icon_only: true, tip: __("Add · Ins") }) +
				  b("copy", __("Copy"), "copy", { icon_only: true, tip: __("Copy · F9") }) +
				  '<span class="bf-sep"></span>' +
				  b("up", __("Move up"), "arrow-up", { icon_only: true, tip: __("Up · Ctrl + Shift + ↑") }) +
				  b("down", __("Move down"), "arrow-down", { icon_only: true, tip: __("Down · Ctrl + Shift + ↓") }) +
				  b("delete", __("Delete row"), "trash", { icon_only: true, tip: "Del" })
				: "") +
				dens_btn +
				`<span class="bf-tp-meta">${esc(sel ? __("Selected {0} of {1}", [sel, rows]) : rows ? __("Rows: {0}", [rows]) : "")}</span>`
		);
	};

	// the rows to work on: the marked ones, else the row the focus was in, else the last row
	function target_rows(frm, grid) {
		const marked = grid.get_selected_children();
		if (marked.length) return marked;
		const list = frm.doc[grid.df.fieldname] || [];
		const row = list.find((r) => r.idx === frm.bf_row) || list[list.length - 1];
		return row ? [row] : [];
	}

	F.add_row = function (frm, grid) {
		const row = grid.add_new_row(null, null, true);
		// T-869: the new row is entered in the table; the first column (item) takes the focus
		grid.focus_cell(grid.grid_rows.length - 1);
		return row;
	};

	F.copy_rows = function (frm, grid) {
		const field = grid.df.fieldname;
		const list = frm.doc[field];
		const rows = target_rows(frm, grid);
		if (!rows.length) return;
		const skip = ["name", "idx", "owner", "creation", "modified", "modified_by", "parent", "parenttype", "parentfield", "docstatus", "doctype", "__islocal"];
		let at = Math.max(...rows.map((r) => r.idx));
		const first = at;
		rows.forEach((src) => {
			const row = frappe.model.add_child(frm.doc, grid.df.options, field);
			Object.keys(src).forEach((k) => !skip.includes(k) && k[0] !== "_" && (row[k] = src[k]));
			list.splice(list.indexOf(row), 1);
			list.splice(at++, 0, row);
		});
		list.forEach((r, i) => (r.idx = i + 1));
		frm.dirty();
		grid.refresh();
		grid.focus_cell(first);
	};

	F.move_rows = function (frm, grid, dir) {
		const list = frm.doc[grid.df.fieldname];
		const marked = grid.get_selected_children();
		const rows = marked.length ? marked : target_rows(frm, grid);
		if (!rows.length) return;
		const idx = rows.map((r) => list.indexOf(r)).sort((a, b) => a - b);
		if (dir < 0 ? idx[0] === 0 : idx[idx.length - 1] === list.length - 1) return;
		const order = dir < 0 ? idx : idx.slice().reverse();
		order.forEach((i) => {
			const [r] = list.splice(i, 1);
			list.splice(i + dir, 0, r);
		});
		list.forEach((r, i) => (r.idx = i + 1));
		frm.dirty();
		grid.refresh();
	};

	F.bf_command = function (frm, cmd) {
		if (cmd === "density") {
			if (frappe.ui.grid_density) frappe.ui.grid_density.toggle();
			setTimeout(() => F.render_tp(frm), 50);
			return;
		}
		const grid = F.grid(frm);
		if (!grid) return;
		if (cmd === "add") F.add_row(frm, grid);
		else if (cmd === "copy") F.copy_rows(frm, grid);
		else if (cmd === "up" || cmd === "down") F.move_rows(frm, grid, cmd === "up" ? -1 : 1);
		else if (cmd === "delete") {
			if (!grid.get_selected_children().length) {
				ui().toast && ui().toast({ type: "info", title: __("Mark the rows"), text: __("Tick the box to the left of a row.") });
				return;
			}
			grid.delete_rows();
		}
		setTimeout(() => F.render_tp(frm), 50);
		F.render_totals(frm);
	};

	// ---------------------------------------------------------------- fixed height (T-887)

	F.MIN_ROWS = 8;

	// The height of the table part: the visible window body minus what is above the grid and below it (the totals
	// footer, paddings), at least the header and MIN_ROWS rows. One value for all tabs.
	F.fit_tp = function (frm) {
		const wrap = frm.layout && frm.layout.wrapper;
		const $tp = $(wrap).find(".bf-tp");
		if (!$tp.length || !$tp[0].offsetParent) return;
		const $box = $tp.find(".bf-tp-sec:not([hidden]) .form-grid-container").first();
		if (!$box.length) return;
		const scroller = (window.beeone && beeone.shell && beeone.shell.scroll_parent && beeone.shell.scroll_parent($tp[0])) || document.scrollingElement;
		const sr = scroller === document.scrollingElement ? { top: 0, bottom: window.innerHeight } : scroller.getBoundingClientRect();
		const view = sr.bottom - sr.top;
		const st = scroller.scrollTop || 0;
		// top of the grid and bottom of the card at scroll 0, relative to the scroller's top edge
		const top = $box[0].getBoundingClientRect().top - sr.top + st;
		const foot = $(wrap).find(".bf-foot:not([hidden])")[0];
		// the footer is sticky, so its size is used, not its position: card padding + margin + footer + page padding
		const below = (foot ? foot.offsetHeight + 10 : 0) + 30;
		const row = parseFloat(getComputedStyle($tp[0]).getPropertyValue("--grid-row-h")) || parseFloat(getComputedStyle($box[0]).getPropertyValue("--grid-row-h")) || 32;
		const min = (F.MIN_ROWS + 1) * row;
		const h = Math.max(min, Math.floor(view - top - below));
		$tp[0].style.setProperty("--bf-grid-h", h + "px");
	};

	F.watch_fit = function (frm) {
		const run = () => {
			cancelAnimationFrame(frm.bf_fit_raf);
			frm.bf_fit_raf = requestAnimationFrame(() => frm === window.cur_frm && F.fit_tp(frm));
		};
		frm.bf_fit = run;
		if (typeof ResizeObserver === "undefined") return;
		const scroller = window.beeone && beeone.shell && beeone.shell.scroll_parent && beeone.shell.scroll_parent($(frm.layout.wrapper)[0]);
		const ro = new ResizeObserver(run);
		const main = $(frm.layout.wrapper).find(".bf-main")[0];
		if (scroller) ro.observe(scroller);
		if (main) ro.observe(main);
		ro.observe(document.documentElement);
		frm.bf_ro = ro;
	};

	// a cell that takes the focus is scrolled inside the table, never the page
	F.reveal_row = function (frm, row_el) {
		const box = $(row_el).closest(".form-grid-container")[0];
		if (!box) return;
		const head = box.querySelector(".grid-heading-row");
		const hh = head ? head.offsetHeight : 0;
		const rr = row_el.getBoundingClientRect();
		const br = box.getBoundingClientRect();
		if (rr.top < br.top + hh) box.scrollTop -= br.top + hh - rr.top;
		else if (rr.bottom > br.bottom) box.scrollTop += rr.bottom - br.bottom;
	};

	// ---------------------------------------------------------------- totals

	F.render_totals = function (frm) {
		const $foot = $(frm.layout.wrapper).find(".bf-foot");
		if (!$foot.length) return;
		const spec = F.spec(frm);
		const d = frm.doc;
		const cur = d.currency;
		const m = (v) => (cur ? format_currency(v || 0, cur) : format_currency(v || 0));
		const parts = spec.totals.map(
			(t) => `<span class="${t[2] ? "bf-grand" : ""}">${esc(__(t[1]))} <b>${esc(m(d[t[0]]))}</b></span>`
		);
		// the document values come from the server on save; while the form is edited, the sum of the rows is shown next to them
		const grand = spec.totals.find((t) => t[2] && t[3]);
		if (grand && frm.is_dirty() && F.editable(frm)) {
			// "items.amount+services.amount": the sum over several tables
			const sum = grand[3].split("+").reduce((acc, part) => {
				const [tbl, col] = part.split(".");
				return acc + (d[tbl] || []).reduce((a, r) => a + (flt(r[col]) || 0), 0);
			}, 0);
			parts.unshift(`<span>${esc(__("Sum of rows"))} <b>${esc(m(sum))}</b></span>`);
		}
		$foot.find(".bf-totals").html(parts.join(""));
		const $c = $foot.find("[data-bf-comment]");
		if ($c.length && !$c.is(":focus")) $c.val(d[spec.comment] || "");
		$c.prop("readonly", !F.editable(frm));
		$foot.prop("hidden", !spec.totals.length && !spec.comment);
	};

	// ---------------------------------------------------------------- wiring

	F.refresh = function (frm) {
		if (!F.active(frm)) return;
		if (!F.setup(frm)) return;
		F.render_head(frm);
		F.render_groups(frm);
		F.render_tp(frm);
		F.render_totals(frm);
		F.soon(frm);
		F.fit_tp(frm);
		if (frm.bf_fit) frm.bf_fit();
	};

	$(document).on("form-refresh", (e, frm) => {
		try {
			F.refresh(frm);
		} catch (err) {
			console.error("bf_form", err);
		}
	});

	// "dirty" comes with every change of a value
	$(document).on("dirty", ".page-container", function () {
		const frm = window.cur_frm;
		if (!frm || !frm.bf_done || $(frm.page.wrapper)[0] !== this) return;
		F.render_dirty(frm);
		F.render_totals(frm);
		F.render_tp(frm);
		F.render_groups(frm);
	});

	$(document).on("change", ".bf-form .grid-row-check", () => {
		const frm = window.cur_frm;
		if (frm && frm.bf_done) setTimeout(() => F.render_tp(frm), 0);
	});

	function in_bf_form(e) {
		const frm = window.cur_frm;
		const route = frappe.get_route() || [];
		if (!frm || !frm.bf_done || route[0] !== "Form" || route[1] !== frm.doctype) return null;
		if (document.querySelector(".modal.show, .bo-dialog-backdrop")) return null;
		return frm;
	}

	// Ctrl+Enter = "Post and close" / "Save and close"
	$(document).on("keydown.bf_form_enter", (e) => {
		if (e.key !== "Enter" || !(e.ctrlKey || e.metaKey) || e.shiftKey) return;
		const frm = in_bf_form(e);
		if (!frm || !F.editable(frm) || !F.perm(frm).write) return;
		e.preventDefault();
		if (frm.doc.docstatus === 1) return F.command(frm, "repost_close", null);
		const post = frappe.get_meta(frm.doctype).is_submittable && F.perm(frm).submit;
		F.command(frm, post ? "post_close" : "save_close", null);
	});

	// Esc on a form (no field, menu or dialog in focus) goes back to the list
	$(document).on("keydown.bf_form_esc", (e) => {
		if (e.key !== "Escape" || e.defaultPrevented) return;
		const frm = in_bf_form(e);
		if (!frm || $(document.activeElement).is("input, textarea, select, [contenteditable=true], .bf-tp .grid-static-col")) return;
		if (ui().menu_open && ui().menu_open()) return;
		F.leave(frm, () => frappe.set_route("List", frm.doctype));
	});

	// keys of the table part work only while the focus (or the last click, when a click on a row focuses nothing) is inside the grid
	let last_click_in_tp = false;
	$(document).on("mousedown.bf_form_rows", (e) => {
		last_click_in_tp = !!$(e.target).closest(".bf-tp").length;
	});
	// Ctrl+Shift+Up/Down moves rows. Core grid inputs use the same chord to add a row at the start/end,
	// so inside the table part this runs in the capture phase and stops the event before the cell sees it.
	document.addEventListener(
		"keydown",
		(e) => {
			if (!((e.ctrlKey || e.metaKey) && e.shiftKey && (e.key === "ArrowUp" || e.key === "ArrowDown"))) return;
			if (!$(e.target).closest(".bf-tp").length) return;
			const frm = in_bf_form(e);
			if (!frm || !F.editable(frm) || !frm.bf_tab || !F.grid(frm)) return;
			e.preventDefault();
			e.stopPropagation();
			F.bf_command(frm, e.key === "ArrowUp" ? "up" : "down");
		},
		true
	);
	$(document).on("keydown.bf_form_rows", (e) => {
		const frm = in_bf_form(e);
		if (!frm || !F.editable(frm) || !frm.bf_tab) return;
		const active = document.activeElement;
		const focus_in = $(e.target).closest(".bf-tp").length || (last_click_in_tp && (!active || active === document.body));
		if (!focus_in) return;
		const grid = F.grid(frm);
		if (!grid) return;
		const typing = $(e.target).is("input, textarea, select, [contenteditable=true]");
		if (e.key === "Insert") {
			e.preventDefault();
			F.bf_command(frm, "add");
		} else if (e.key === "F9") {
			e.preventDefault();
			F.bf_command(frm, "copy");
		} else if (e.key === "Delete" && !typing && grid.get_selected_children().length) {
			e.preventDefault();
			F.bf_command(frm, "delete");
		} else if ((e.ctrlKey || e.metaKey) && e.shiftKey && ["ArrowUp", "ArrowDown"].includes(e.key)) {
			e.preventDefault();
			F.bf_command(frm, e.key === "ArrowUp" ? "up" : "down");
		}
	});
})();
