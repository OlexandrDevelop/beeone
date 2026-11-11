// "Select from list" dialog of a Link / Dynamic Link control (the "..." button, F4).
// It reads the same search as the field's dropdown (frappe.desk.search.search_widget with
// the arguments of target.get_search_args), so get_query, filters and link_filters apply.
// Double click or Enter on a row selects it, Esc closes without a change.

frappe.ui.form.LinkPicker = class LinkPicker {
	static page_length = 20;
	static uid = 0;

	// A hierarchical catalog gets the picker with the tree of groups, any other the flat one.
	static open(opts) {
		// beeone: the list form of the catalog is the selection form, as in 1C
		if (frappe.ui.form.link_pick.start(opts.target, opts.doctype)) return;
		frappe.model.with_doctype(opts.doctype, () => {
			const Hierarchical = frappe.ui.form.HierarchyLinkPicker;
			const picker =
				Hierarchical && frappe.views.HierarchyView?.is_available(opts.doctype)
					? Hierarchical
					: frappe.ui.form.LinkPicker;
			new picker(opts);
		});
	}

	/**
	 * @param {object} opts
	 * @param {frappe.ui.form.ControlLink} opts.target  the Link / Dynamic Link control
	 * @param {string} opts.doctype  the linked doctype
	 * @param {string} [opts.txt]  initial search text
	 */
	constructor(opts) {
		Object.assign(this, opts);
		this.id = `link-picker-${++frappe.ui.form.LinkPicker.uid}`;
		this.start = 0;
		this.rows = [];
		this.active = -1;
		this.request_id = 0;
		frappe.model.with_doctype(this.doctype, () => this.make());
	}

	make() {
		this.meta = frappe.get_meta(this.doctype);
		this.dialog = new frappe.ui.Dialog({
			title: __("Select {0}", [__(this.doctype)]),
			size: "large",
			fields: [
				{ fieldtype: "Data", fieldname: "txt", label: __("Search") },
				{ fieldtype: "HTML", fieldname: "filters_info" },
				{ fieldtype: "HTML", fieldname: "results" },
			],
		});
		this.dialog.$wrapper.addClass("link-picker-dialog");
		this.$results = this.dialog.fields_dict.results.$wrapper;
		this.$info = this.dialog.fields_dict.filters_info.$wrapper;
		this.$search = this.dialog.get_input("txt");

		this.$results.html(
			`<div class="link-picker-scroll">
				<table class="table table-sm link-picker-table" role="listbox" id="${this.id}"
					aria-label="${frappe.utils.escape_html(__("Select {0}", [__(this.doctype)]))}">
					<thead></thead><tbody></tbody>
				</table>
				<div class="link-picker-empty text-muted hide" role="status"></div>
			</div>
			<div class="link-picker-footer">
				<button type="button" class="btn btn-default btn-sm link-picker-more hide">
					${__("Show more")}
				</button>
				<button type="button" class="btn btn-default btn-sm link-picker-new hide">
					${__("Create a new {0}", [__(this.doctype)])}
				</button>
			</div>`
		);
		this.$table = this.$results.find("table");
		this.$tbody = this.$table.find("tbody");
		this.$thead = this.$table.find("thead");
		this.$scroll = this.$results.find(".link-picker-scroll");
		this.$empty = this.$results.find(".link-picker-empty");
		this.$more = this.$results.find(".link-picker-more");
		this.$new = this.$results.find(".link-picker-new");

		this.$search
			.attr({
				role: "combobox",
				"aria-autocomplete": "list",
				"aria-expanded": "true",
				"aria-controls": this.id,
				autocomplete: "off",
			})
			.val(this.txt || "");

		const debounced = frappe.utils.debounce(() => {
			this.start = 0;
			this.load();
		}, 300);
		this.$search.on("input", debounced);
		this.$search.on("keydown", (e) => this.on_search_keydown(e));
		this.$tbody.on("click", "tr", (e) => this.set_active(this.index_of(e.currentTarget)));
		this.$tbody.on("dblclick", "tr", (e) => this.select(this.index_of(e.currentTarget)));
		this.$more.on("click", () => {
			this.start += LinkPicker.page_length;
			this.load(true);
		});

		const can_create = frappe.model.can_create(this.doctype) && !this.target.df.only_select;
		this.$new.toggleClass("hide", !can_create).on("click", () => {
			this.close_without_cancel();
			this.target.new_doc();
		});

		this.dialog.onhide = () => {
			if (!this.selected_once) this.target.on_link_picker_cancel?.();
		};
		this.dialog.show();
		this.dialog.$wrapper.one("shown.bs.modal", () => this.$search.trigger("focus"));
		this.$search.trigger("focus");
		this.show_filters_info();
		this.load();
	}

	close_without_cancel() {
		this.selected_once = true;
		this.dialog.hide();
	}

	async show_filters_info() {
		const target = this.target;
		const args = target.get_search_args("");
		let text = target.df.filter_description;
		if (!text && args?.filters && Object.keys(args.filters).length) {
			try {
				text = await target.get_filter_description(args.filters);
			} catch (e) {
				text = null;
			}
		}
		this.$info.html(text ? `<p class="text-muted small link-picker-filters">${text}</p>` : "");
	}

	get_args() {
		const args = this.target.get_search_args(this.$search.val() || "");
		args.start = this.start;
		args.page_length = LinkPicker.page_length;
		args.as_dict = 1;
		if (this.meta.is_tree) {
			args.filter_fields = JSON.stringify([
				this.meta.nsm_parent_field || "parent_" + frappe.scrub(this.doctype),
				"is_group",
			]);
		}
		return args;
	}

	load(append) {
		const args = this.get_args();
		const request_id = ++this.request_id;
		return frappe
			.xcall("frappe.desk.search.search_widget", args, "POST")
			.then((results) => {
				if (request_id !== this.request_id) return;
				results = results || [];
				this.has_more = results.length === LinkPicker.page_length;
				this.render(results, append);
			});
	}

	columns_of(results) {
		const first = results.find((r) => r && !Array.isArray(r));
		if (!first) return [];
		const hidden = ["_relevance", "is_group", "label", "description"];
		const cols = Object.keys(first).filter((k) => !hidden.includes(k));
		if (!cols.includes("name") && "value" in first) cols.unshift("value");
		// beeone: records with opaque names (hash) have no ID column, the title is the first one
		const title_field = this.meta.title_field;
		if (this.meta.opaque_name && title_field && title_field in first) {
			return [title_field, ...cols.filter((c) => !["name", "value", title_field].includes(c))];
		}
		return cols;
	}

	column_label(key) {
		if (key === "name" || key === "value") return __("ID");
		return __(frappe.meta.get_label(this.doctype, key));
	}

	render(results, append) {
		const translate = this.target.is_translatable();
		if (!append) {
			this.rows = [];
			this.$tbody.empty();
			this.cols = this.columns_of(results);
			this.$thead.html(
				this.cols.length
					? `<tr>${this.cols
							.map(
								(c) =>
									`<th scope="col">${frappe.utils.escape_html(this.column_label(c))}</th>`
							)
							.join("")}</tr>`
					: ""
			);
		}
		const title_field = this.meta.title_field;
		results.forEach((r) => {
			const is_array = Array.isArray(r);
			const value = is_array ? r[0] : r.name ?? r.value;
			const label = is_array ? r[1] || value : r.label || (title_field && r[title_field]) || value;
			const n = this.rows.length;
			this.rows.push({ value, label });
			const cells = is_array
				? r.map((c) => this.cell_html(c, translate))
				: this.cols.map((c) => this.cell_html(r[c], translate && c === "name", c));
			const group = r.is_group ? frappe.utils.icon("folder-normal", "sm") + " " : "";
			if (cells.length) cells[0] = group + cells[0];
			$(`<tr role="option" id="${this.id}-${n}" aria-selected="false" tabindex="-1"
					class="${r.is_group ? "is-group" : ""}"
					title="${frappe.utils.escape_html(__("Double click or Enter to select"))}">
					${cells.map((c) => `<td>${c}</td>`).join("")}</tr>`)
				.appendTo(this.$tbody);
		});

		this.$more.toggleClass("hide", !this.has_more);
		const empty = !this.rows.length;
		this.$empty.toggleClass("hide", !empty).text(__("No results found"));
		this.$table.toggleClass("hide", empty);
		if (!append) this.set_active(empty ? -1 : 0);
	}

	cell_html(value, translate, fieldname) {
		if (value == null) return "";
		value = cstr(value);
		const df = fieldname && frappe.meta.get_field(this.doctype, fieldname);
		if (df && df.fieldtype === "Link" && df.options) {
			// beeone: a Link column shows the title of the record when it is known
			value = frappe.utils.get_link_title(df.options, value) || value;
		}
		return frappe.utils.escape_html(translate ? __(value) : value);
	}

	index_of(tr) {
		return this.$tbody.children().index(tr);
	}

	set_active(i) {
		if (i < 0 || i >= this.rows.length) {
			this.active = -1;
			this.$search.removeAttr("aria-activedescendant");
			return;
		}
		this.active = i;
		const $rows = this.$tbody.children();
		$rows.removeClass("is-active").attr("aria-selected", "false");
		const $row = $rows.eq(i).addClass("is-active").attr("aria-selected", "true");
		this.$search.attr("aria-activedescendant", $row.attr("id"));
		const row = $row.get(0);
		row && row.scrollIntoView && row.scrollIntoView({ block: "nearest" });
	}

	on_search_keydown(e) {
		const last = this.rows.length - 1;
		const step = 10;
		const key = e.key;
		let handled = true;
		if (key === "ArrowDown") this.set_active(Math.min(last, this.active + 1));
		else if (key === "ArrowUp") this.set_active(Math.max(0, this.active - 1));
		else if (key === "PageDown") this.set_active(Math.min(last, this.active + step));
		else if (key === "PageUp") this.set_active(Math.max(0, this.active - step));
		else if (key === "Home" && e.ctrlKey) this.set_active(0);
		else if (key === "End" && e.ctrlKey) this.set_active(last);
		else if (key === "Enter") this.select(this.active);
		else handled = false;
		if (handled) {
			e.preventDefault();
			e.stopPropagation();
		}
	}

	select(i) {
		const row = this.rows[i];
		if (!row) return;
		this.close_without_cancel();
		this.target.select_from_picker(row.value, row.label);
	}
};

// beeone: "Select from list" (the button of a Link field, F4) opens the list form of the catalog in its window,
// with the filters of the field, as the selection form of 1C. A click on an element (Enter; a double click in a
// hierarchy) puts it into the field, closes the list window it opened and returns to the document; Esc or
// "Cancel" returns without a change. A field with a custom server query keeps the dialog above (a list cannot
// repeat that query).
frappe.ui.form.link_pick = {
	session: null,

	start(target, doctype) {
		if (!target || !doctype || !frappe.model.can_read(doctype) && !(frappe.boot.user.all_read || []).includes(doctype))
			return false;
		const args = target.get_search_args("") || {};
		if (args.query) return false;
		const options = {};
		let filters = args.filters;
		if (typeof filters === "string") {
			try {
				filters = JSON.parse(filters);
			} catch (e) {
				filters = null;
			}
		}
		if (Array.isArray(filters)) {
			for (const f of filters) {
				const [field, op, value] = f.length >= 4 ? [f[1], f[2], f[3]] : f;
				if (field) options[field] = op === "=" ? value : [op, value];
			}
		} else if (filters && typeof filters === "object") {
			Object.assign(options, filters);
		}
		const windows = beeone?.shell?.windows;
		this.cancel(false);
		this.session = {
			doctype,
			target,
			back: frappe.get_route(),
			label: __(target.df.label, null, target.df.parent),
			before: new Set(windows ? windows.list().map((w) => w.key) : []),
			shown: false,
		};
		frappe.route_options = options;
		frappe.set_route("List", doctype);
		setTimeout(() => this.mark(), 400);
		return true;
	},

	active(doctype) {
		return this.session && this.session.doctype === doctype ? this.session : null;
	},

	// the banner over the list of the session
	mark() {
		const s = this.session;
		if (!s) return;
		const list = window.cur_list;
		if (!list || list.doctype !== s.doctype || !list.page) {
			if (!s.tries || s.tries < 10) {
				s.tries = (s.tries || 0) + 1;
				setTimeout(() => this.mark(), 300);
			}
			return;
		}
		s.shown = true;
		s.list = list;
		$(list.page.main).find(".bo-pick-banner").remove();
		const $b = $(`<div class="bo-pick-banner">
			<span>${frappe.utils.escape_html(
				__("Selection for the field «{0}»: click an element or press Enter", [s.label])
			)}</span>
			<button type="button" class="btn btn-xs btn-default bo-pick-cancel">${__("Cancel")}</button>
		</div>`);
		$b.find(".bo-pick-cancel").on("click", () => this.cancel(true));
		$(list.page.main).prepend($b);
	},

	choose(name, label) {
		const s = this.session;
		if (!s) return false;
		this.session = null;
		this.unmark(s);
		this.leave(s).then(() => s.target.select_from_picker(name, label));
		return true;
	},

	cancel(go_back) {
		const s = this.session;
		if (!s) return;
		this.session = null;
		this.unmark(s);
		if (go_back) this.leave(s).then(() => s.target.on_link_picker_cancel?.());
	},

	unmark(s) {
		s.list && $(s.list.page.main).find(".bo-pick-banner").remove();
	},

	// back to the document; the list window opened for the selection is closed
	leave(s) {
		const windows = beeone?.shell?.windows;
		const opened = windows
			? windows
					.list()
					.map((w) => w.key)
					.filter((k) => !s.before.has(k) && k.split("/")[1] === s.doctype)
			: [];
		return Promise.resolve(frappe.set_route(s.back)).then(() => {
			for (const key of opened) windows.close(key, true);
			return new Promise((r) => setTimeout(r, 50));
		});
	},
};

$(document).on("keydown", (e) => {
	const pick = frappe.ui.form.link_pick;
	if (e.key !== "Escape" || !pick.session || !pick.session.shown) return;
	if ($(".modal.show").length) return;
	const list = window.cur_list;
	if (!list || list.doctype !== pick.session.doctype) return;
	e.preventDefault();
	pick.cancel(true);
});

frappe.router?.on?.("change", () => {
	const pick = frappe.ui.form.link_pick;
	const s = pick.session;
	if (!s || !s.shown) return;
	const route = frappe.get_route();
	if (route[0] === "List" && route[1] === s.doctype) return;
	pick.cancel(false);
});
