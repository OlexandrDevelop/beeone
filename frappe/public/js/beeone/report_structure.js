// Report settings, the tab «Структура» (T-2533): a report that declares its structure (the module function
// `get_report_structure`, see frappe/beeone/report_variants.py) gets Actions → Settings. The user turns the levels of
// the rows on and off and changes their order (a tick, arrows or dragging), and chooses the layout of the resources:
// separate columns or «one under another» (quantity and cost of a resource in one column, two lines a cell). The choice
// is kept in the default variant of the user; the report is built with it on the screen, in Excel and in PDF.
frappe.provide("frappe.beeone_report_structure");

(function () {
	const S = frappe.beeone_report_structure;
	const API = "frappe.beeone.api.report_variants";
	const esc = (v) => frappe.utils.escape_html(v == null ? "" : String(v));

	// the levels in the dialog: the chosen ones in their order, then the others
	S.levels = function (structure, chosen) {
		const by_key = Object.fromEntries(structure.dimensions.map((d) => [d.key, d]));
		const on = chosen.filter((k) => by_key[k]).map((k) => ({ ...by_key[k], on: true }));
		const off = structure.dimensions.filter((d) => !chosen.includes(d.key)).map((d) => ({ ...d, on: false }));
		return [...on, ...off];
	};

	S.setup = function (report) {
		const name = report.report_name;
		if (report.bo_structure_button) report.bo_structure_button.remove();
		report.bo_structure_button = null;
		if (!name || !report.report_doc || report.report_doc.report_type !== "Script Report") return;
		return frappe
			.xcall(`${API}.get_structure`, { report: name })
			.then((info) => {
				if (!info || report.report_name !== name) return;
				report.bo_structure_button = report.page.add_inner_button(
					__("Settings..."),
					() => S.open(report, name),
					__("Actions")
				);
			})
			.catch(() => {});
	};

	S.open = function (report, name) {
		frappe.xcall(`${API}.get_structure`, { report: name }).then((info) => {
			if (!info) return;
			const structure = info.structure;
			let levels = S.levels(structure, info.groupings);
			const fields = [
				{ fieldtype: "Tab Break", fieldname: "structure_tab", label: __("Structure") },
				{ fieldtype: "HTML", fieldname: "levels" },
			];
			if (structure.resources.length) {
				fields.push({
					fieldtype: "Select",
					fieldname: "resource_layout",
					label: __("Resource Layout"),
					options: [
						{ value: "columns", label: __("Separate Columns") },
						{ value: "stacked", label: __("One Under Another") },
					],
					default: info.resource_layout || "columns",
				});
			}
			const dialog = new frappe.ui.Dialog({
				title: __("Report Settings"),
				// a dialog with a Tab Break needs a doctype: the ids of its tabs are made from it
				doctype: "Report Variant",
				fields,
				primary_action_label: __("Apply"),
				primary_action(values) {
					const groupings = levels.filter((l) => l.on).map((l) => l.key);
					if (!groupings.length) {
						frappe.msgprint(__("Choose at least one grouping"));
						return;
					}
					save(groupings, values.resource_layout || "columns");
				},
				secondary_action_label: __("Reset"),
				secondary_action() {
					save([], "columns");
				},
			});
			const save = (groupings, resource_layout) =>
				frappe
					.xcall(`${API}.save_structure`, { report: name, groupings, resource_layout })
					.then(() => {
						dialog.hide();
						report.refresh();
					});

			const $wrap = dialog.fields_dict.levels.$wrapper;
			const draw = () => {
				const max = structure.max_levels;
				$wrap.html(
					`<div class="bo-structure">
						<div class="text-muted small mb-2">${esc(
							__("Groupings of the rows, the outer level first (at most {0})", [max])
						)}</div>
						<ul class="list-group bo-structure-levels">${levels
							.map(
								(l, i) => `<li class="list-group-item d-flex align-items-center py-1" data-key="${esc(l.key)}">
								<span class="bo-structure-drag text-muted mr-2" style="cursor: grab">⠿</span>
								<label class="mb-0 flex-grow-1 d-flex align-items-center">
									<input type="checkbox" class="mr-2" data-i="${i}" ${l.on ? "checked" : ""}>${esc(
									__(l.label)
								)}
								</label>
								<button class="btn btn-xs btn-default mr-1" data-up="${i}" ${i ? "" : "disabled"}
									title="${esc(__("Move Up"))}">↑</button>
								<button class="btn btn-xs btn-default" data-down="${i}" ${
									i < levels.length - 1 ? "" : "disabled"
								} title="${esc(__("Move Down"))}">↓</button>
							</li>`
							)
							.join("")}</ul>
					</div>`
				);
				const list = $wrap.find(".bo-structure-levels")[0];
				if (window.Sortable && list) {
					Sortable.create(list, {
						handle: ".bo-structure-drag",
						onEnd: () => {
							const by_key = Object.fromEntries(levels.map((l) => [l.key, l]));
							levels = $(list)
								.children("li")
								.toArray()
								.map((li) => by_key[li.dataset.key]);
							draw();
						},
					});
				}
			};
			const move = (i, j) => {
				if (j < 0 || j >= levels.length) return;
				[levels[i], levels[j]] = [levels[j], levels[i]];
				draw();
			};
			$wrap.on("change", "input[type=checkbox]", function () {
				levels[cint(this.dataset.i)].on = this.checked;
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
			dialog.show();
			// the tab «Структура» is shown even while it is the only one (the layout hides a single tab)
			(dialog.tabs || []).forEach((tab) => tab.tab_link && tab.tab_link.removeClass("hide").addClass("show"));
		});
	};
})();
