// "Select from list" dialog of a Link control to a hierarchical catalog (the "..." button, F4):
// the tree of groups on the left, the content of the chosen group (groups and items) on the right,
// as in 1C. Opened by LinkPicker.open when frappe.views.HierarchyView.is_available(doctype).
//
// The content comes from frappe.desk.treeview.get_picker_contents, which runs the same search as
// the field's dropdown, so get_query, filters and link_filters apply. There is no pager: the whole
// group arrives at once and its rows are drawn in chunks while the user scrolls.
//
// Double click or Enter on an item selects it, on a group opens it. A group can be put into the
// field only with "Select" / Ctrl+Enter, and only when the field's filters let groups through.

frappe.ui.form.HierarchyLinkPicker = class HierarchyLinkPicker extends frappe.ui.form.LinkPicker {
	static chunk = 200;

	make() {
		this.meta = frappe.get_meta(this.doctype);
		this.current_group = "";
		this.group_path = [];
		this.rendered = 0;
		this.dialog = new frappe.ui.Dialog({
			title: __("Select {0}", [__(this.doctype)]),
			size: "extra-large",
			fields: [
				{ fieldtype: "Data", fieldname: "txt", label: __("Search") },
				{ fieldtype: "HTML", fieldname: "filters_info" },
				{ fieldtype: "HTML", fieldname: "results" },
			],
		});
		this.dialog.$wrapper.addClass("link-picker-dialog link-picker-hierarchy");
		this.$results = this.dialog.fields_dict.results.$wrapper;
		this.$info = this.dialog.fields_dict.filters_info.$wrapper;
		this.$search = this.dialog.get_input("txt");

		this.$results.html(
			`<div class="link-picker-layout">
				<aside class="link-picker-groups"></aside>
				<div class="link-picker-content">
					<div class="link-picker-path"></div>
					<div class="link-picker-scroll">
						<table class="table table-sm link-picker-table" role="listbox" id="${this.id}"
							aria-label="${frappe.utils.escape_html(__("Select {0}", [__(this.doctype)]))}">
							<thead></thead><tbody></tbody>
						</table>
						<div class="link-picker-empty text-muted hide" role="status"></div>
						<div class="link-picker-sentinel"></div>
					</div>
				</div>
			</div>
			<div class="link-picker-footer">
				<button type="button" class="btn btn-primary btn-sm link-picker-choose" disabled>
					${__("Select")}
				</button>
				<button type="button" class="btn btn-default btn-sm link-picker-new hide">
					${__("Create a new {0}", [__(this.doctype)])}
				</button>
				<span class="link-picker-status text-muted small" role="status"></span>
			</div>`
		);
		this.$table = this.$results.find("table");
		this.$tbody = this.$table.find("tbody");
		this.$thead = this.$table.find("thead");
		this.$scroll = this.$results.find(".link-picker-scroll");
		this.$empty = this.$results.find(".link-picker-empty");
		this.$path = this.$results.find(".link-picker-path");
		this.$choose = this.$results.find(".link-picker-choose");
		this.$new = this.$results.find(".link-picker-new");
		this.$status = this.$results.find(".link-picker-status");

		this.$search
			.attr({
				role: "combobox",
				"aria-autocomplete": "list",
				"aria-expanded": "true",
				"aria-controls": this.id,
				autocomplete: "off",
			})
			.val(this.txt || "");

		this.group_tree = new frappe.ui.GroupTree({
			parent: this.$results.find(".link-picker-groups"),
			doctype: this.doctype,
			on_select: (value) => this.open_group(value, { from_tree: true }),
		});

		const debounced = frappe.utils.debounce(() => this.load(), 300);
		this.$search.on("input", debounced);
		this.$search.on("keydown", (e) => this.on_search_keydown(e));
		this.$tbody.on("click", "tr", (e) => this.set_active(this.index_of(e.currentTarget)));
		this.$tbody.on("dblclick", "tr", (e) => this.activate(this.index_of(e.currentTarget)));
		this.$path.on("click", "[data-group]", (e) => {
			this.open_group($(e.currentTarget).attr("data-group") || "");
		});
		this.$choose.on("click", () => this.select(this.active));
		this.observe_end();

		const can_create = frappe.model.can_create(this.doctype) && !this.target.df.only_select;
		this.$new.toggleClass("hide", !can_create).on("click", () => {
			this.close_without_cancel();
			this.target.new_doc();
		});

		this.dialog.onhide = () => {
			this.observer?.disconnect();
			this.group_tree?.destroy();
			if (!this.selected_once) this.target.on_link_picker_cancel?.();
		};
		this.dialog.show();
		this.dialog.$wrapper.one("shown.bs.modal", () => this.$search.trigger("focus"));
		this.$search.trigger("focus");
		this.show_filters_info();
		this.load({ current: this.target.value && !this.txt ? this.target.value : "" });
	}

	observe_end() {
		if (!window.IntersectionObserver) return;
		this.observer = new IntersectionObserver(
			(entries) => entries.some((e) => e.isIntersecting) && this.render_chunk(),
			{ root: this.$scroll.get(0) }
		);
		this.observer.observe(this.$results.find(".link-picker-sentinel").get(0));
	}

	get_args(opts = {}) {
		const args = this.target.get_search_args("");
		const picker_args = {
			doctype: this.doctype,
			group: opts.group ?? this.current_group,
			txt: this.$search.val() || "",
			current: opts.current || "",
			query: args.query,
			searchfield: args.searchfield,
			filters: args.filters,
			reference_doctype: args.reference_doctype,
			link_fieldname: args.link_fieldname,
			ignore_user_permissions: args.ignore_user_permissions,
		};
		if (picker_args.filters && typeof picker_args.filters !== "string") {
			picker_args.filters = JSON.stringify(picker_args.filters);
		}
		return picker_args;
	}

	load(opts = {}) {
		const request_id = ++this.request_id;
		return frappe
			.xcall("frappe.desk.treeview.get_picker_contents", this.get_args(opts), "POST")
			.then((data) => {
				if (request_id !== this.request_id) return;
				this.searching = Boolean(this.$search.val());
				if (!this.searching) {
					this.current_group = data.group || "";
					this.group_path = data.path || [];
					this.sync_tree(opts);
				}
				this.render(data, opts);
			});
	}

	sync_tree(opts) {
		if (opts.from_tree) return;
		this.group_tree.select(this.current_group, { silent: true });
	}

	open_group(value, opts = {}) {
		this.$search.val("");
		this.current_group = value || "";
		return this.load({ group: this.current_group, from_tree: opts.from_tree });
	}

	go_up() {
		if (!this.current_group) return;
		const path = this.group_path;
		const parent = path.length > 1 ? path[path.length - 2].value : "";
		this.open_group(parent);
	}

	render_path() {
		if (this.searching) {
			this.$path.text(__("Search in all of {0}", [__(this.doctype)]));
			return;
		}
		const crumb = (value, title) =>
			`<a href="#" data-group="${frappe.utils.escape_html(value)}">${frappe.utils.escape_html(title)}</a>`;
		const parts = [crumb("", __(this.doctype))].concat(
			this.group_path.map((p) => crumb(p.value, p.title))
		);
		this.$path.html(parts.join(" / ")).find("a").on("click", (e) => e.preventDefault());
	}

	render(data, opts = {}) {
		this.cols = data.columns || [];
		this.rows = (data.rows || []).map((r) => ({ ...r, label: r.title }));
		this.rendered = 0;
		this.$tbody.empty();
		const heads = [__("Name"), ...this.cols.map((c) => this.column_label(c))];
		if (this.searching) heads.push(__("Group"));
		this.$thead.html(
			`<tr>${heads.map((h) => `<th scope="col">${frappe.utils.escape_html(h)}</th>`).join("")}</tr>`
		);
		this.render_path();
		this.render_chunk();

		const empty = !this.rows.length;
		this.$empty.toggleClass("hide", !empty).text(__("No results found"));
		this.$table.toggleClass("hide", empty);
		this.$status.text(
			data.truncated
				? __("Showing the first {0}; narrow the search", [this.rows.length])
				: ""
		);
		let start = empty ? -1 : 0;
		if (opts.current) {
			const i = this.rows.findIndex((r) => r.value === opts.current);
			if (i >= 0) start = i;
		}
		this.$scroll.scrollTop(0);
		this.set_active(start);
	}

	render_chunk() {
		const end = Math.min(this.rows.length, this.rendered + HierarchyLinkPicker.chunk);
		const html = [];
		for (let n = this.rendered; n < end; n++) html.push(this.row_html(this.rows[n], n));
		this.rendered = end;
		this.$tbody.append(html.join(""));
	}

	ensure_rendered(i) {
		while (this.rendered <= i && this.rendered < this.rows.length) this.render_chunk();
	}

	row_html(r, n) {
		const translate = this.target.is_translatable();
		const icon = r.is_group ? frappe.utils.icon("folder-normal", "sm") + " " : "";
		const cells = [icon + frappe.utils.escape_html(r.title)];
		this.cols.forEach((c) => cells.push(this.cell_html(r[c], translate && c === "name", c)));
		if (this.searching) cells.push(frappe.utils.escape_html(r.parent_title || ""));
		const hint = r.is_group
			? __("Double click or Enter to open the group")
			: __("Double click or Enter to select");
		return `<tr role="option" id="${this.id}-${n}" aria-selected="false" tabindex="-1"
				${r.is_group && !r.selectable ? 'aria-disabled="true"' : ""}
				class="${r.is_group ? "is-group" : ""}" title="${frappe.utils.escape_html(hint)}">
				${cells.map((c) => `<td>${c}</td>`).join("")}</tr>`;
	}

	set_active(i) {
		if (i >= 0) this.ensure_rendered(i);
		super.set_active(i);
		const row = this.rows[this.active];
		this.$choose.prop("disabled", !row || !row.selectable);
		this.$status.text(
			row && row.is_group && !row.selectable
				? __("A group cannot be selected here; open it")
				: ""
		);
	}

	// double click / Enter: an item is chosen, a group is opened
	activate(i) {
		const row = this.rows[i];
		if (!row) return;
		if (row.is_group) this.open_group(row.value);
		else this.select(i);
	}

	select(i) {
		const row = this.rows[i];
		if (!row || !row.selectable) return;
		super.select(i);
	}

	on_search_keydown(e) {
		const key = e.key;
		if (key === "Enter" && !e.ctrlKey) {
			e.preventDefault();
			e.stopPropagation();
			this.activate(this.active);
		} else if (key === "Enter" && e.ctrlKey) {
			e.preventDefault();
			e.stopPropagation();
			this.select(this.active);
		} else if (
			(key === "ArrowUp" && e.ctrlKey) ||
			(key === "Backspace" && !this.$search.val() && !this.searching)
		) {
			e.preventDefault();
			e.stopPropagation();
			this.go_up();
		} else if (key === "End" && e.ctrlKey) {
			e.preventDefault();
			e.stopPropagation();
			this.set_active(this.rows.length - 1);
		} else {
			super.on_search_keydown(e);
		}
	}
};
