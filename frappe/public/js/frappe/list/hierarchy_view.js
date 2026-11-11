// Hierarchy view of a hierarchical catalog (a DocType with is_tree and is_group): the groups tree on
// the left, the direct contents of the selected group on the right (subgroups first, then items).
// The right side is the ordinary list view, scoped to one group.
frappe.provide("frappe.views");

frappe.views.HierarchyView = class HierarchyView extends frappe.views.ListView {
	static parent_field(doctype) {
		const meta = frappe.get_meta(doctype);
		return meta.nsm_parent_field || "parent_" + frappe.scrub(doctype);
	}

	static is_available(doctype) {
		const meta = frappe.get_meta(doctype);
		if (!meta || !meta.is_tree || meta.issingle) return false;
		return (
			!!frappe.meta.has_field(doctype, "is_group") &&
			!!frappe.meta.has_field(doctype, HierarchyView.parent_field(doctype)) &&
			frappe.listview_settings[doctype]?.hierarchy_view !== false
		);
	}

	get view_name() {
		return "Hierarchy";
	}

	get show_saved_layout_menu() {
		return false;
	}

	setup_defaults() {
		const result = super.setup_defaults();
		this.parent_field = HierarchyView.parent_field(this.doctype);
		this.current_group = this.view_user_settings.current_group || "";
		this.group_path = [];
		if (!this.view_user_settings.sort_by) {
			this.sort_by = this.meta.title_field || "name";
			this.sort_order = "asc";
		}
		this.base_filter_keys = this.parse_filters_from_settings().map((f) =>
			JSON.stringify(f.slice(0, 4))
		);
		return result;
	}

	// a recency filter would hide the contents of a group
	add_recent_filter_on_large_tables() {}

	async set_fields() {
		await super.set_fields();
		this._add_field("is_group");
		this._add_field(this.parent_field);
	}

	setup_list_wrapper() {
		const $layout = $(`<div class="hierarchy-layout"></div>`).appendTo(this.page.main);
		this.$layout = $layout;
		const collapsed = !!this.view_user_settings.groups_collapsed;
		const pane_id = "hierarchy-groups-" + frappe.utils.get_random(5);
		this.$aside = $(`<aside class="hierarchy-groups" id="${pane_id}" aria-label="${__("Groups")}"></aside>`).appendTo(
			$layout
		);
		this.$toggle = $(`
			<button type="button" class="btn btn-xs btn-default hierarchy-groups-toggle"
				aria-controls="${pane_id}" aria-expanded="${!collapsed}">
				${frappe.utils.icon("folder-tree", "sm")} <span>${__("Groups")}</span>
			</button>`).insertBefore(this.$aside);
		this.$toggle.on("click", () => this.toggle_groups_pane());
		this.$layout.toggleClass("groups-collapsed", collapsed);

		const $content = $(`<div class="hierarchy-content"></div>`).appendTo($layout);
		this.$path = $(`<nav class="hierarchy-path" aria-label="${__("Group path")}"></nav>`).appendTo($content);
		this.$scope = $(`<div class="hierarchy-scope" role="status" hidden></div>`).appendTo($content);
		this.$live = $(`<div class="bo-sr-only" aria-live="polite"></div>`).appendTo($content);
		this.$frappe_list = $('<div class="frappe-list">').appendTo($content);

		this.group_tree = new frappe.ui.GroupTree({
			parent: this.$aside,
			doctype: this.doctype,
			on_select: (value) => {
				if (value !== this.current_group) this.open_group(value, { focus: false, from_tree: true });
			},
		});
		this.group_tree_ready = this.group_tree
			.select(this.current_group, { silent: true })
			.then((ok) => {
				if (!ok && this.current_group) {
					this.current_group = "";
				}
				return this.render_path();
			});
	}

	toggle_groups_pane() {
		const collapsed = !this.$layout.hasClass("groups-collapsed");
		this.$layout.toggleClass("groups-collapsed", collapsed);
		this.$toggle.attr("aria-expanded", String(!collapsed));
		this.save_view_user_settings({ groups_collapsed: collapsed });
		setTimeout(() => this.set_result_height(), 0);
	}

	setup_page_head() {
		super.setup_page_head();
		if (this.can_create && !frappe.boot.read_only) {
			this.page.add_inner_button(__("Add Group"), () => this.make_new_group());
		}
	}

	set_actions_menu_items() {
		super.set_actions_menu_items();
		if (this.can_write) {
			this.page.add_actions_menu_item(__("Move to Group…"), () => this.move_checked(), true);
		}
	}

	async before_refresh() {
		await this.group_tree_ready;
		// a deep link: /desk/<catalog>/view/hierarchy?parent_<catalog>=<group>
		const wanted = frappe.route_options && frappe.route_options[this.parent_field];
		if (wanted) {
			delete frappe.route_options[this.parent_field];
			if (wanted !== this.current_group) {
				this.current_group = wanted;
				await this.group_tree.select(wanted, { silent: true });
				await this.render_path();
			}
		}
		return super.before_refresh();
	}

	is_search_mode() {
		return super
			.get_filters_for_args()
			.some((f) => !this.base_filter_keys.includes(JSON.stringify(f.slice(0, 4))));
	}

	get_current_group_node() {
		return this.group_path[this.group_path.length - 1];
	}

	// The user's filters plus the scope of the table: the direct contents of the current group, or,
	// while the user filters, the whole subtree of it (nested set range, not a list of names).
	// The list count and the sidebar read the filters through this method too, so they agree.
	get_filters_for_args() {
		const filters = super.get_filters_for_args();
		const dt = this.doctype;
		if (!this.is_search_mode()) {
			filters.push(
				this.current_group
					? [dt, this.parent_field, "=", this.current_group]
					: [dt, this.parent_field, "is", "not set"]
			);
		} else {
			const node = this.get_current_group_node();
			if (this.current_group && node && node.lft > 0 && node.rgt > 0) {
				filters.push([dt, "lft", ">", node.lft], [dt, "rgt", "<", node.rgt]);
			}
		}
		return filters;
	}

	get_args() {
		const args = super.get_args();
		const sort = this.sort_selector && this.sort_selector.get_sql_string();
		args.order_by = "`tab" + this.doctype + "`.`is_group` desc" + (sort ? ", " + sort : "");
		return args;
	}

	render_scope() {
		const search = this.is_search_mode();
		this.$scope.prop("hidden", !search);
		if (!search) return;
		const node = this.get_current_group_node();
		const text = this.current_group
			? __("Showing matches in {0} and its subgroups", [
					frappe.utils.escape_html(node?.title || this.current_group),
			  ])
			: __("Showing matches in the whole catalog");
		this.$scope.html(
			`<span>${text}</span> <button type="button" class="btn btn-xs btn-default hierarchy-scope-clear">${__(
				"Clear filters"
			)}</button>`
		);
		this.$scope.find(".hierarchy-scope-clear").on("click", () => this.filter_area.clear());
	}

	async render_path() {
		let path = [];
		if (this.current_group) {
			try {
				path = await frappe.xcall("frappe.desk.treeview.get_group_path", {
					doctype: this.doctype,
					name: this.current_group,
				});
			} catch (e) {
				this.current_group = "";
			}
		}
		this.group_path = path;
		const crumbs = [{ value: "", title: __(this.doctype) }, ...path];
		const $nav = this.$path.empty();
		const $up = $(
			`<button type="button" class="btn btn-xs btn-default hierarchy-up" aria-keyshortcuts="Control+ArrowUp"
				aria-label="${__("Up one level")}" title="${__("Up one level")}">${frappe.utils.icon("corner-left-up", "sm")}</button>`
		)
			.prop("disabled", !this.current_group)
			.on("click", () => this.go_up())
			.appendTo($nav);
		const $list = $(`<ol class="hierarchy-crumbs"></ol>`).appendTo($nav);
		crumbs.forEach((c, i) => {
			const last = i === crumbs.length - 1;
			const $li = $(`<li></li>`).appendTo($list);
			const $b = $(`<button type="button" class="btn btn-link btn-xs hierarchy-crumb"></button>`)
				.text(c.title)
				.appendTo($li);
			if (last) $b.attr("aria-current", "location");
			$b.on("click", () => this.open_group(c.value));
		});
		this.render_scope();
		return $up;
	}

	async open_group(name, { focus = true, from_tree = false } = {}) {
		name = name || "";
		this.current_group = name;
		this.save_view_user_settings({ current_group: name });
		this.start = 0;
		this.checked_docnames.clear();
		if (!from_tree) await this.group_tree.select(name, { silent: true });
		await this.render_path();
		await this.refresh();
		const label = this.get_current_group_node()?.title || __(this.doctype);
		this.$live.text(`${label}: ${this.data.length}`);
		if (focus) this.$result.find(".list-row-container:first").focus();
	}

	go_up() {
		if (!this.current_group) return;
		const parent = this.group_path[this.group_path.length - 2];
		this.open_group(parent ? parent.value : "");
	}

	// the table is rebuilt from the server: the client-side re-sort of the base class would break
	// the groups-first order
	process_document_refreshes() {
		this.pending_document_refreshes = [];
		this.refresh();
	}

	after_render() {
		super.after_render();
		this.render_scope();
		if (!this.is_search_mode()) {
			const cached = this.group_tree?.get_children_cache(this.current_group);
			if (cached) {
				const shown = this.data.filter((d) => d.is_group).map((d) => d.name).sort().join("\n");
				const known = cached.map((c) => c.value).sort().join("\n");
				// a subgroup was added or removed elsewhere: the tree learns about it
				if (this.data.length < this.page_length && shown !== known) {
					this.group_tree.reload(this.current_group);
				}
			}
		}
	}

	show() {
		const r = super.show();
		this.group_tree?.reload(this.current_group);
		return r;
	}

	get_list_row_attrs(doc) {
		return `data-name="${frappe.utils.escape_html(doc.name)}" data-is-group="${doc.is_group ? 1 : 0}"`;
	}

	get_subject_element(doc, title) {
		const div = super.get_subject_element(doc, title);
		if (!doc.is_group) return div;
		const link = div.querySelector("a");
		if (link) {
			link.classList.add("is-group");
			const icon = document.createElement("span");
			icon.className = "hierarchy-group-icon";
			icon.setAttribute("aria-hidden", "true");
			icon.innerHTML = frappe.utils.icon("folder", "sm");
			link.parentNode.insertBefore(icon, link);
			const sr = document.createElement("span");
			sr.className = "bo-sr-only";
			sr.textContent = __("Group") + ": ";
			link.insertBefore(sr, link.firstChild);
			if (this.can_write || frappe.model.can_read(this.doctype)) {
				const edit = document.createElement("button");
				edit.type = "button";
				edit.className = "btn btn-link btn-xs hierarchy-edit-group";
				edit.setAttribute("aria-label", __("Edit group"));
				edit.setAttribute("data-edit-group", doc.name);
				edit.innerHTML = frappe.utils.icon("pencil", "xs");
				link.parentNode.appendChild(edit);
			}
		}
		return div;
	}

	row_doc($row) {
		const name = $row.attr("data-name");
		return this.data.find((d) => d.name === name);
	}

	open_form(doc) {
		if (this.bo_pick_doc(doc)) return;
		frappe.set_route(this.get_form_link(doc));
	}

	// beeone: the hierarchy is the selection form of a Link field: an element (not a group) is chosen
	bo_pick_doc(doc) {
		const pick = frappe.ui.form.link_pick;
		if (!doc || doc.is_group || !pick || !pick.active(this.doctype)) return false;
		const title = this.meta?.title_field ? doc[this.meta.title_field] : null;
		return pick.choose(doc.name, title || null);
	}

	open_list_row($row) {
		const doc = this.row_doc($row);
		if (!doc) return;
		if (doc.is_group) this.open_group(doc.name);
		else this.open_form(doc);
	}

	setup_list_click() {
		this.$result.on("click", ".list-row", (e) => {
			const $target = $(e.target);
			const $row = $(e.currentTarget);
			if ((e.ctrlKey || e.metaKey) && !$target.is("a")) {
				const $check = $row.find(".list-row-checkbox");
				$check.prop("checked", !$check.prop("checked"));
				this.sync_checked_docname($check);
				e.preventDefault();
				this.on_row_checked();
				return;
			}
			if ($target.is("[data-toggle='dropdown']")) return true;
			if (
				$target.hasClass("filterable") ||
				$target.hasClass("select-like") ||
				$target.hasClass("list-row-like") ||
				$target.is(":checkbox")
			) {
				e.stopPropagation();
				return;
			}
			const $edit = $target.closest("[data-edit-group]");
			if ($edit.length) {
				e.preventDefault();
				e.stopPropagation();
				frappe.set_route("Form", this.doctype, $edit.attr("data-edit-group"));
				return;
			}
			const $container = $row.closest(".list-row-container");
			if ($container.attr("data-is-group") !== "1" && this.bo_pick_doc(this.row_doc($container))) {
				e.preventDefault();
				e.stopPropagation();
				return;
			}
			// the name of a group drills in; the name of an element is a normal link to its form
			if ($target.closest("a").length) {
				if ($container.attr("data-is-group") === "1") {
					e.preventDefault();
					e.stopPropagation();
					this.open_group($container.attr("data-name"));
				}
				return;
			}
			// a click on the row only focuses it
			$container.trigger("focus");
		});

		this.$result.on("dblclick", ".list-row-container", (e) => {
			if ($(e.target).is(":checkbox, button, .list-row-like")) return;
			e.preventDefault();
			this.open_list_row($(e.currentTarget));
		});
	}

	setup_keyboard_navigation() {
		super.setup_keyboard_navigation();
		const focused_row = () => {
			const $row = $(document.activeElement).closest(".list-row-container");
			return $row.length && this.$result.has($row).length ? $row : null;
		};
		frappe.ui.keys.add_shortcut({
			shortcut: "f2",
			action: () => {
				const $row = focused_row();
				const doc = $row && this.row_doc($row);
				if (!doc) return false;
				this.open_form(doc);
				return true;
			},
			description: __("Open the form of a group or item", null, "Description of a list view shortcut"),
			page: this.page,
		});
		frappe.ui.keys.add_shortcut({
			shortcut: "ctrl+up",
			action: () => {
				if (!this.current_group) return false;
				this.go_up();
				return true;
			},
			description: __("Up one level", null, "Description of a list view shortcut"),
			page: this.page,
		});
	}

	make_new_doc() {
		this.new_in_current_group(0);
	}

	make_new_group() {
		this.new_in_current_group(1);
	}

	new_in_current_group(is_group) {
		const values = { is_group };
		if (this.current_group) values[this.parent_field] = this.current_group;
		frappe.new_doc(this.doctype, values);
	}

	move_checked() {
		const names = this.get_checked_items(true);
		if (!names.length) {
			frappe.show_alert({ message: __("Select items to move first"), indicator: "orange" });
			return;
		}
		const d = new frappe.ui.Dialog({
			title: __("Move to Group"),
			fields: [
				{
					fieldname: "top_level",
					fieldtype: "Check",
					label: __("Top level"),
					onchange: () => {
						const top = d.get_value("top_level");
						d.set_df_property("group", "reqd", top ? 0 : 1);
						d.set_df_property("group", "hidden", top ? 1 : 0);
					},
				},
				{
					fieldname: "group",
					fieldtype: "Link",
					options: this.doctype,
					label: __("Group"),
					reqd: 1,
					get_query: () => ({ filters: { is_group: 1, name: ["not in", names] } }),
				},
			],
			primary_action_label: __("Move"),
			primary_action: async (values) => {
				const group = values.top_level ? "" : values.group;
				d.hide();
				const r = await frappe.xcall(
					"frappe.desk.treeview.move_to_group",
					{ doctype: this.doctype, names: JSON.stringify(names), group },
					"POST"
				);
				frappe.show_alert({ message: __("Moved {0}", [r.moved]), indicator: "green" });
				this.clear_checked_items();
				await this.refresh();
				this.group_tree.reload(this.current_group);
				if (group) this.group_tree.reload(group);
			},
		});
		d.show();
	}
};
