// Report settings, Actions → Settings (T-2533, user 2026-11-23): one dialog with two tabs.
// «Структура», when the report declares its structure (the module function `get_report_structure`, see
// frappe/beeone/report_variants.py): the levels of the rows turned on and off and put in order (a tick, arrows or
// dragging), the resources turned on and off, and their layout: «one under another» (the default: quantity and cost
// of a resource in one column, two lines a cell) or separate columns. The choice is kept in the default variant of
// the user; the report is built with it on the screen, in Excel and in PDF.
// «Колонки»: any field of a grouping dimension that is turned on (Item → SKU, Counterparty → tax id ...), as a column:
// kept in the variant like the structure, filled on the server (frappe.desk.query_report, report_variants
// .apply_dimension_fields) on the screen, in Excel and PDF. A report without a structure: a field of a document a
// column links to, until the next run (once the menu item "Add Column").
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
			// the fields of the dimensions as columns: [{dimension, doctype, field}]
			fields: (info.dimension_fields || []).slice(),
		};
		let dialog;
		const fields = [];
		if (structure) {
			fields.push(
				{ fieldtype: "Tab Break", fieldname: "structure_tab", label: __("Structure") },
				{ fieldtype: "HTML", fieldname: "structure" },
				{ fieldtype: "Tab Break", fieldname: "columns_tab", label: __("Columns") },
				{ fieldtype: "HTML", fieldname: "dimension_fields" }
			);
		} else {
			// a report without a structure: a field of a document a column links to (until the next run)
			fields.push(
				{ fieldtype: "Tab Break", fieldname: "columns_tab", label: __("Columns") },
				{ fieldtype: "HTML", fieldname: "columns_intro" },
				...report.add_column_fields(() => dialog),
				{ fieldtype: "Button", fieldname: "column_add", label: __("Add Column") }
			);
		}

		const save = (groupings, resource_layout, hidden_resources, dimension_fields) =>
			frappe
				.xcall(`${API}.save_structure`, {
					report: name,
					groupings,
					resource_layout,
					hidden_resources,
					dimension_fields,
				})
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
						save(groupings, state.layout, [...state.hidden], state.fields);
				  }
				: null,
			secondary_action_label: structure ? __("Reset") : null,
			secondary_action: structure ? () => save([], "stacked", [], []) : null,
		});
		dialog.$wrapper.addClass("bo-report-settings");

		if (structure) {
			const $cols = dialog.fields_dict.dimension_fields.$wrapper;
			const redraw_columns = () => S.draw_dimension_fields($cols, report, structure, state);
			S.draw_structure(dialog.fields_dict.structure.$wrapper, structure, state, redraw_columns);
			redraw_columns();
		} else {
			S.setup_columns(dialog, report);
		}
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

	// the DocType of a dimension: declared by the report, else the filter of the report with the same fieldname
	// (warehouse → Business Unit), else the DocType the key names (item → Item); null for a period, a kind ...
	S.dimension_doctype = function (report, dimension) {
		if (dimension.doctype) return dimension.doctype;
		const filter = (report.filters || []).find((f) => f.df && f.df.fieldname === dimension.key);
		const df = filter && filter.df;
		if (df && ["Link", "MultiSelectList", "Table MultiSelect"].includes(df.fieldtype) && df.options)
			return df.options;
		const doctype = frappe.unscrub(dimension.key);
		return (frappe.boot.user.can_read || []).includes(doctype) ? doctype : null;
	};

	const SKIP_TYPES = [
		"Password", "Attach", "Attach Image", "Signature", "Geolocation", "JSON", "Code", "HTML Editor",
		"Text Editor", "Markdown Editor", "Button", "Image", "Barcode",
	];

	S.doctype_fields = function (doctype) {
		return frappe.meta
			.get_docfields(doctype)
			.filter((df) => frappe.model.is_value_type(df) && !SKIP_TYPES.includes(df.fieldtype) && !df.hidden)
			.map((df) => ({ field: df.fieldname, label: __(df.label || df.fieldname, null, doctype) }))
			.sort((a, b) => a.label.localeCompare(b.label));
	};

	// the tab «Колонки»: the fields of every dimension that is a level now, ticks; the chosen ones on top as chips
	S.draw_dimension_fields = function ($wrap, report, structure, state) {
		const on = state.levels.filter((l) => l.on);
		const dims = on
			.map((l) => ({ ...l, doctype: S.dimension_doctype(report, l) }))
			.filter((d) => d.doctype);
		const off = state.levels.filter((l) => !l.on && S.dimension_doctype(report, l));
		$wrap.data("bo-search", $wrap.data("bo-search") || {});
		Promise.all(dims.map((d) => new Promise((ok) => frappe.model.with_doctype(d.doctype, ok)))).then(() => {
			const search = $wrap.data("bo-search");
			const chosen = (d, f) => state.fields.some((x) => x.dimension === d.key && x.field === f);
			const label_of = (x) => {
				const d = dims.find((d) => d.key === x.dimension);
				const f = d && S.doctype_fields(d.doctype).find((f) => f.field === x.field);
				return `${__(d ? d.label : x.dimension)}.${f ? f.label : x.field}`;
			};
			const visible = state.fields.filter((x) => dims.some((d) => d.key === x.dimension));
			const chips = visible.length
				? `<div class="bo-rs-chips">${visible
						.map(
							(x) => `<span class="bo-rs-chip">${esc(label_of(x))}<button data-drop="${esc(
								x.dimension
							)}" data-field="${esc(x.field)}" title="${esc(__("Remove"))}">×</button></span>`
						)
						.join("")}</div>`
				: `<div class="bo-rs-hint">${esc(__("No columns chosen yet"))}</div>`;
			const cards = dims
				.map((d) => {
					const q = (search[d.key] || "").toLowerCase();
					const items = S.doctype_fields(d.doctype).filter((f) => !q || f.label.toLowerCase().includes(q));
					return `<section class="bo-rs-card bo-rs-dim">
						<div class="bo-rs-title">${esc(__(d.label))}</div>
						<input type="search" class="form-control bo-rs-search" data-search="${esc(d.key)}"
							placeholder="${esc(__("Find a field"))}" value="${esc(search[d.key] || "")}">
						<div class="bo-rs-fields">${items
							.map(
								(f) => `<label class="bo-rs-check bo-rs-field">
									<input type="checkbox" data-dim="${esc(d.key)}" data-doctype="${esc(
									d.doctype
								)}" data-field="${esc(f.field)}" ${chosen(d, f.field) ? "checked" : ""}>
									<span>${esc(f.label)}</span>
								</label>`
							)
							.join("") || `<div class="bo-rs-hint">${esc(__("Nothing found"))}</div>`}</div>
					</section>`;
				})
				.join("");
			$wrap.html(`<div class="bo-rs-columns">
				<div class="bo-rs-hint">${esc(
					__(
						"Any field of a grouping turned on, as a column: it is filled on the rows of that level and below"
					)
				)}</div>
				${chips}
				<div class="bo-rs">${
					cards || `<div class="bo-rs-hint">${esc(__("No grouping turned on has fields to add"))}</div>`
				}</div>
				${
					off.length
						? `<div class="bo-rs-hint">${esc(
								__("The fields of {0} appear when the grouping is turned on in «Structure»", [
									off.map((l) => __(l.label)).join(", "),
								])
						  )}</div>`
						: ""
				}
			</div>`);
		});
		$wrap.off(".bo-cols");
		$wrap.on("change.bo-cols", "input[data-field][data-dim]", function () {
			const x = { dimension: this.dataset.dim, doctype: this.dataset.doctype, field: this.dataset.field };
			state.fields = state.fields.filter((f) => !(f.dimension === x.dimension && f.field === x.field));
			if (this.checked) state.fields.push(x);
			S.draw_dimension_fields($wrap, report, structure, state);
		});
		$wrap.on("click.bo-cols", "[data-drop]", function (e) {
			e.preventDefault();
			const dim = this.dataset.drop;
			const field = this.dataset.field;
			state.fields = state.fields.filter((f) => !(f.dimension === dim && f.field === field));
			S.draw_dimension_fields($wrap, report, structure, state);
		});
		$wrap.on("input.bo-cols", "input[data-search]", function () {
			const key = this.dataset.search;
			$wrap.data("bo-search")[key] = this.value;
			const q = this.value.toLowerCase();
			$(this)
				.closest(".bo-rs-dim")
				.find(".bo-rs-field")
				.each(function () {
					$(this).toggle(!q || $(this).text().toLowerCase().includes(q));
				});
		});
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

	S.draw_structure = function ($wrap, structure, state, on_change) {
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
			on_change && on_change();
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
