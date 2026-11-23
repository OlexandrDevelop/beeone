// Report settings, Actions → Settings (T-2533, user 2026-11-23): one dialog with two tabs.
// «Структура», when the report declares its structure (the module function `get_report_structure`, see
// frappe/beeone/report_variants.py): the levels of the rows turned on and off and put in order (a tick, arrows or
// dragging), the resources turned on and off, and their layout: «one under another» (the default: quantity and cost
// of a resource in one column, two lines a cell) or separate columns. The choice is kept in the default variant of
// the user; the report is built with it on the screen, in Excel and in PDF.
// «Колонки»: a field of a document the report links to, as a new column (once the menu item "Add Column").
frappe.provide("frappe.beeone_report_structure");

(function () {
	const S = frappe.beeone_report_structure;
	const API = "frappe.beeone.api.report_variants";
	const esc = (v) => frappe.utils.escape_html(v == null ? "" : String(v));
	const LAYOUTS = [
		{ value: "stacked", label: "One Under Another", hint: "Quantity above cost in one column" },
		{ value: "columns", label: "Separate Columns", hint: "Every part of a resource in its own column" },
	];

	// the levels in the dialog: the chosen ones in their order, then the others
	S.levels = function (structure, chosen) {
		const by_key = Object.fromEntries(structure.dimensions.map((d) => [d.key, d]));
		const on = chosen.filter((k) => by_key[k]).map((k) => ({ ...by_key[k], on: true }));
		const off = structure.dimensions.filter((d) => !chosen.includes(d.key)).map((d) => ({ ...d, on: false }));
		return [...on, ...off];
	};

	// the settings of a report without a structure are the tab «Колонки» only
	const get_structure = (name) =>
		frappe.xcall(`${API}.get_structure`, { report: name }).catch(() => null);

	S.open = function (report) {
		const name = report.report_name;
		if (!name) return;
		const scripted = report.report_doc && report.report_doc.report_type === "Script Report";
		(scripted ? get_structure(name) : Promise.resolve(null)).then((info) => S.dialog(report, name, info));
	};

	S.dialog = function (report, name, info) {
		const structure = info && info.structure;
		const state = structure && {
			levels: S.levels(structure, info.groupings),
			hidden: new Set(info.hidden_resources || []),
			layout: info.resource_layout || "stacked",
		};
		let dialog;
		const fields = [];
		if (structure) {
			fields.push(
				{ fieldtype: "Tab Break", fieldname: "structure_tab", label: __("Structure") },
				{ fieldtype: "HTML", fieldname: "structure" }
			);
		}
		fields.push(
			{ fieldtype: "Tab Break", fieldname: "columns_tab", label: __("Columns") },
			{ fieldtype: "HTML", fieldname: "columns_intro" },
			...report.add_column_fields(() => dialog),
			{ fieldtype: "Button", fieldname: "column_add", label: __("Add Column") }
		);

		const save = (groupings, resource_layout, hidden_resources) =>
			frappe
				.xcall(`${API}.save_structure`, { report: name, groupings, resource_layout, hidden_resources })
				.then(() => {
					dialog.hide();
					report.refresh();
				});

		dialog = new frappe.ui.Dialog({
			title: __("Report Settings"),
			size: "large",
			// a dialog with a Tab Break needs a doctype: the ids of its tabs are made from it
			doctype: "Report Variant",
			fields,
			primary_action_label: structure ? __("Apply") : null,
			primary_action: structure
				? () => {
						const groupings = state.levels.filter((l) => l.on).map((l) => l.key);
						if (structure.dimensions.length && !groupings.length) {
							frappe.msgprint(__("Choose at least one grouping"));
							return;
						}
						save(groupings, state.layout, [...state.hidden]);
				  }
				: null,
			secondary_action_label: structure ? __("Reset") : null,
			secondary_action: structure ? () => save([], "stacked", []) : null,
		});
		dialog.$wrapper.addClass("bo-report-settings");

		if (structure) S.draw_structure(dialog.fields_dict.structure.$wrapper, structure, state);
		S.setup_columns(dialog, report);
		dialog.show();

		// only our tabs (the layout puts an empty default tab first and hides a single tab)
		const ours = ["structure_tab", "columns_tab"];
		(dialog.tabs || []).forEach((tab) => {
			if (!tab.tab_link) return;
			const show = !!(tab.df && ours.includes(tab.df.fieldname));
			tab.tab_link.toggleClass("hide", !show).toggleClass("show", show);
		});
		dialog.select_tab && dialog.select_tab(structure ? "structure_tab" : "columns_tab");
	};

	S.setup_columns = function (dialog, report) {
		const has_links = (report.linked_doctypes || []).length > 0;
		dialog.fields_dict.columns_intro.$wrapper.html(
			`<div class="bo-rs-hint">${esc(
				has_links
					? __("A field of a document the report links to, as a new column of the table")
					: __("The report links to no documents: there are no fields to add")
			)}</div>`
		);
		["column_doctype", "column_field", "column_insert_after", "column_add"].forEach((f) =>
			dialog.set_df_property(f, "hidden", has_links ? 0 : 1)
		);
		dialog.fields_dict.column_add.$input &&
			dialog.fields_dict.column_add.$input.addClass("btn-primary").removeClass("btn-default");
		dialog.fields_dict.column_add.df.click = () =>
			report.add_column(dialog.get_values(true)).then(
				() => {
					frappe.show_alert({ message: __("Column added"), indicator: "green" });
					dialog.hide();
				},
				() => {}
			);
	};

	S.draw_structure = function ($wrap, structure, state) {
		const max = structure.max_levels;
		const levels_card = () =>
			structure.dimensions.length
				? `<section class="bo-rs-card">
					<div class="bo-rs-title">${esc(__("Groupings of the rows"))}</div>
					<div class="bo-rs-hint">${esc(__("The outer level first, at most {0}", [max]))}</div>
					<ul class="bo-rs-list bo-rs-levels">${state.levels
						.map(
							(l, i) => `<li class="bo-rs-item${l.on ? " is-on" : ""}" data-key="${esc(l.key)}">
							<span class="bo-rs-drag" title="${esc(__("Drag"))}">${frappe.utils.icon("grip-vertical", "sm")}</span>
							<label class="bo-rs-check">
								<input type="checkbox" data-level="${i}" ${l.on ? "checked" : ""}>
								<span>${esc(__(l.label))}</span>
							</label>
							<span class="bo-rs-order">${l.on ? state.levels.filter((x, j) => x.on && j <= i).length : ""}</span>
							<button class="bo-rs-move" data-up="${i}" ${i ? "" : "disabled"} title="${esc(
								__("Move Up")
							)}">${frappe.utils.icon("chevron-up", "sm")}</button>
							<button class="bo-rs-move" data-down="${i}" ${
								i < state.levels.length - 1 ? "" : "disabled"
							} title="${esc(__("Move Down"))}">${frappe.utils.icon("chevron-down", "sm")}</button>
						</li>`
						)
						.join("")}</ul>
				</section>`
				: "";
		const resources_card = () =>
			structure.resources.length
				? `<section class="bo-rs-card">
					<div class="bo-rs-title">${esc(__("Resources"))}</div>
					<div class="bo-rs-hint">${esc(__("A resource turned off is not shown in the report"))}</div>
					<ul class="bo-rs-list">${structure.resources
						.map(
							(r) => `<li class="bo-rs-item${state.hidden.has(r.key) ? "" : " is-on"}">
							<label class="bo-rs-check">
								<input type="checkbox" data-resource="${esc(r.key)}" ${
									state.hidden.has(r.key) ? "" : "checked"
								}>
								<span>${esc(__(r.label))}</span>
							</label>
							<span class="bo-rs-parts">${r.parts
								.map((p) => `<span class="bo-rs-part">${esc(__(p.label || p.key))}</span>`)
								.join("")}</span>
						</li>`
						)
						.join("")}</ul>
					<div class="bo-rs-title bo-rs-gap">${esc(__("Resource Layout"))}</div>
					<div class="bo-rs-layouts">${LAYOUTS.map(
						(l) => `<button class="bo-rs-layout${state.layout === l.value ? " is-on" : ""}" data-layout="${
							l.value
						}">
							<span class="bo-rs-pic bo-rs-pic-${l.value}"><i></i><i></i></span>
							<span class="bo-rs-layout-text"><b>${esc(__(l.label))}</b><small>${esc(
								__(l.hint)
							)}</small></span>
						</button>`
					).join("")}</div>
				</section>`
				: "";

		const draw = () => {
			$wrap.html(`<div class="bo-rs">${levels_card()}${resources_card()}</div>`);
			const list = $wrap.find(".bo-rs-levels")[0];
			if (window.Sortable && list) {
				Sortable.create(list, {
					handle: ".bo-rs-drag",
					animation: 150,
					onEnd: () => {
						const by_key = Object.fromEntries(state.levels.map((l) => [l.key, l]));
						state.levels = $(list)
							.children("li")
							.toArray()
							.map((li) => by_key[li.dataset.key]);
						draw();
					},
				});
			}
		};
		const move = (i, j) => {
			if (j < 0 || j >= state.levels.length) return;
			[state.levels[i], state.levels[j]] = [state.levels[j], state.levels[i]];
			draw();
		};
		$wrap.on("change", "input[data-level]", function () {
			state.levels[cint(this.dataset.level)].on = this.checked;
			draw();
		});
		$wrap.on("change", "input[data-resource]", function () {
			const key = this.dataset.resource;
			if (this.checked) state.hidden.delete(key);
			else if (state.hidden.size + 1 >= structure.resources.length) {
				this.checked = true;
				frappe.show_alert({ message: __("Leave at least one resource"), indicator: "orange" });
				return;
			} else state.hidden.add(key);
			draw();
		});
		$wrap.on("click", "[data-layout]", function (e) {
			e.preventDefault();
			state.layout = this.dataset.layout;
			draw();
		});
		$wrap.on("click", "[data-up]", function (e) {
			e.preventDefault();
			move(cint(this.dataset.up), cint(this.dataset.up) - 1);
		});
		$wrap.on("click", "[data-down]", function (e) {
			e.preventDefault();
			move(cint(this.dataset.down), cint(this.dataset.down) + 1);
		});
		draw();
	};
})();
