// A tree of the groups (is_group = 1) of a hierarchical DocType, loaded lazily one level at a time.
// Follows the WAI-ARIA tree pattern: one row is in the tab order (roving tabindex), arrows move,
// Right/Left expand/collapse, Enter/Space/click select. Selection is explicit, it does not follow focus.
//
//   const tree = new frappe.ui.GroupTree({ parent, doctype, on_select(value, row) {} });
//   await tree.select("Group A", { silent: true }); // expands the path, marks the node
//   tree.reload("Group A");                          // refetch the children of one node
//   tree.get_selected();                             // "" is the top level
//   tree.destroy();
frappe.provide("frappe.ui");

frappe.ui.GroupTree = class GroupTree {
	constructor({ parent, doctype, root_label, on_select, get_label }) {
		this.doctype = doctype;
		this.root_label = root_label || __(doctype);
		this.on_select = on_select;
		this.get_label = get_label;
		this.selected = "";
		this.nodes = {}; // value -> node
		this.id = frappe.utils.get_random(6);
		this.$parent = $(parent);
		this.$tree = $(
			`<ul class="group-tree" role="tree" aria-label="${frappe.utils.escape_html(__("Groups"))}"></ul>`
		).appendTo(this.$parent);
		this.root = this.make_node({ value: "", title: this.root_label, expandable: true }, 1, 1, 1);
		this.root.$li.appendTo(this.$tree);
		this.bind_events();
		this.set_tab_stop(this.root);
		this.expand(this.root);
	}

	destroy() {
		this.$tree.remove();
		this.nodes = {};
	}

	get_selected() {
		return this.selected;
	}

	make_node(row, level, size, pos) {
		const node = {
			row,
			value: row.value,
			level,
			children: null,
			loaded: false,
			expanded: false,
			parent: null,
			children_nodes: [],
		};
		const label = frappe.utils.escape_html((this.get_label ? this.get_label(row) : row.title) || row.value);
		const expandable = !!row.expandable;
		node.$li = $(`<li class="group-tree-item" role="none"></li>`);
		node.$row = $(`
			<div class="group-tree-row ${row.disabled ? "is-disabled" : ""}" role="treeitem" tabindex="-1"
				aria-level="${level}" aria-setsize="${size}" aria-posinset="${pos}"
				aria-selected="false" ${expandable ? 'aria-expanded="false"' : ""}>
				<span class="group-tree-toggle ${expandable ? "" : "invisible"}" aria-hidden="true">
					${frappe.utils.icon("chevron-right", "xs")}
				</span>
				<span class="group-tree-icon" aria-hidden="true">${frappe.utils.icon("folder", "sm")}</span>
				<span class="group-tree-label">${label}</span>
			</div>`).appendTo(node.$li);
		node.$row.css("padding-left", `${(level - 1) * 16 + 4}px`);
		node.$row.data("node", node);
		node.$group = $(`<ul class="group-tree-children" role="group" hidden></ul>`).appendTo(node.$li);
		this.nodes[row.value] = node;
		return node;
	}

	bind_events() {
		this.$tree.on("click", ".group-tree-row", (e) => {
			const node = $(e.currentTarget).data("node");
			if ($(e.target).closest(".group-tree-toggle").length) {
				this.toggle(node);
			} else {
				this.activate(node);
			}
			this.set_tab_stop(node, true);
		});
		this.$tree.on("keydown", ".group-tree-row", (e) => this.on_key(e));
		this.$tree.on("click", ".group-tree-retry", (e) => {
			const node = $(e.currentTarget).closest(".group-tree-item").children(".group-tree-row").data("node");
			node.loaded = false;
			this.expand(node);
		});
	}

	on_key(e) {
		const node = $(e.currentTarget).data("node");
		const visible = this.visible_nodes();
		const idx = visible.indexOf(node);
		let handled = true;
		switch (e.key) {
			case "ArrowDown":
				this.focus(visible[Math.min(idx + 1, visible.length - 1)]);
				break;
			case "ArrowUp":
				this.focus(visible[Math.max(idx - 1, 0)]);
				break;
			case "ArrowRight":
				if (node.row.expandable && !node.expanded) this.expand(node);
				else if (node.expanded && node.children_nodes.length) this.focus(node.children_nodes[0]);
				break;
			case "ArrowLeft":
				if (node.expanded) this.collapse(node);
				else if (node.parent) this.focus(node.parent);
				break;
			case "Home":
				this.focus(visible[0]);
				break;
			case "End":
				this.focus(visible[visible.length - 1]);
				break;
			case "Enter":
			case " ":
				this.activate(node);
				break;
			default:
				handled = false;
		}
		if (handled) {
			e.preventDefault();
			e.stopPropagation();
		}
	}

	visible_nodes() {
		const out = [];
		const walk = (node) => {
			out.push(node);
			if (node.expanded) node.children_nodes.forEach(walk);
		};
		walk(this.root);
		return out;
	}

	set_tab_stop(node, skip_focus) {
		if (this.tab_node && this.tab_node !== node) this.tab_node.$row.attr("tabindex", "-1");
		this.tab_node = node;
		node.$row.attr("tabindex", "0");
	}

	focus(node) {
		if (!node) return;
		this.set_tab_stop(node);
		node.$row[0].focus();
	}

	activate(node) {
		this.mark_selected(node);
		if (this.on_select) this.on_select(node.value, node.row);
	}

	mark_selected(node) {
		this.selected_node?.$row.attr("aria-selected", "false").removeClass("is-selected");
		this.selected_node = node;
		this.selected = node.value;
		node.$row.attr("aria-selected", "true").addClass("is-selected");
	}

	toggle(node) {
		if (node.expanded) this.collapse(node);
		else this.expand(node);
	}

	collapse(node) {
		node.expanded = false;
		node.$group.prop("hidden", true);
		node.$row.attr("aria-expanded", "false").find(".group-tree-icon").html(frappe.utils.icon("folder", "sm"));
		node.$li.removeClass("is-open");
	}

	async expand(node) {
		if (!node.row.expandable) return;
		if (!node.loaded) {
			if (node.loading) return node.loading;
			node.loading = this.load_children(node).finally(() => (node.loading = null));
			await node.loading;
		}
		if (!node.loaded) return;
		node.expanded = true;
		node.$group.prop("hidden", false);
		node.$li.addClass("is-open");
		node.$row.attr("aria-expanded", "true").find(".group-tree-icon").html(frappe.utils.icon("folder-open", "sm"));
	}

	async load_children(node) {
		node.$row.attr("aria-busy", "true");
		node.$group.empty().prop("hidden", false);
		node.$group.append(`<li class="group-tree-loading text-muted" role="none">${__("Loading")}...</li>`);
		try {
			const rows = await frappe.xcall("frappe.desk.treeview.get_group_children", {
				doctype: this.doctype,
				parent: node.value,
			});
			this.set_children(node, rows);
		} catch (e) {
			node.$group.empty().append(
				`<li class="group-tree-error" role="none"><button type="button" class="btn btn-xs btn-default group-tree-retry">${__("Retry")}</button></li>`
			);
			node.$group.prop("hidden", false);
		} finally {
			node.$row.removeAttr("aria-busy");
		}
	}

	set_children(node, rows) {
		node.children_nodes.forEach((c) => this.forget(c));
		node.children_nodes = [];
		node.$group.empty();
		rows.forEach((row, i) => {
			const child = this.make_node(row, node.level + 1, rows.length, i + 1);
			child.parent = node;
			node.children_nodes.push(child);
			node.$group.append(child.$li);
		});
		node.children = rows;
		node.loaded = true;
		if (this.selected_node && this.nodes[this.selected] === undefined) {
			this.selected_node = null;
		} else if (this.nodes[this.selected]) {
			this.mark_selected(this.nodes[this.selected]);
		}
	}

	forget(node) {
		node.children_nodes.forEach((c) => this.forget(c));
		delete this.nodes[node.value];
	}

	// the cached children of one node, as [{value, title, ...}]
	get_children_cache(value = "") {
		const node = this.nodes[value];
		return node && node.loaded ? node.children : null;
	}

	// refetch the children of one node; keeps it expanded when it was
	async reload(value = "") {
		const node = this.nodes[value];
		if (!node || !node.loaded) return;
		const rows = await frappe.xcall("frappe.desk.treeview.get_group_children", {
			doctype: this.doctype,
			parent: value,
		});
		const was_expanded = node.expanded;
		const open = new Set(node.children_nodes.filter((c) => c.expanded).map((c) => c.value));
		this.set_children(node, rows);
		node.row.expandable = rows.length > 0 || node === this.root;
		node.children_nodes.forEach((c) => {
			if (open.has(c.value) && c.row.expandable) this.expand(c);
		});
		if (node !== this.root) {
			node.$row.attr("aria-expanded", rows.length ? String(was_expanded) : null);
			node.$row.find(".group-tree-toggle").toggleClass("invisible", !rows.length);
		}
	}

	// mark `value` as selected, expanding its path; "" selects the top level
	async select(value, { silent = false } = {}) {
		value = value || "";
		if (!value) {
			this.mark_selected(this.root);
			this.set_tab_stop(this.root);
			return true;
		}
		let path;
		try {
			path = await frappe.xcall("frappe.desk.treeview.get_group_path", {
				doctype: this.doctype,
				name: value,
			});
		} catch (e) {
			this.mark_selected(this.root);
			return false;
		}
		await this.expand(this.root);
		let node = this.root;
		for (let i = 0; i < path.length; i++) {
			const next = node.children_nodes.find((c) => c.value === path[i].value);
			if (!next) {
				// stale cache (a group was added since): refetch this level once
				await this.reload(node.value);
				const retry = node.children_nodes.find((c) => c.value === path[i].value);
				if (!retry) break;
				node = retry;
			} else {
				node = next;
			}
			if (i < path.length - 1) await this.expand(node);
		}
		if (node.value !== value) {
			this.mark_selected(this.root);
			return false;
		}
		this.mark_selected(node);
		this.set_tab_stop(node);
		node.$row[0].scrollIntoView?.({ block: "nearest" });
		if (!silent && this.on_select) this.on_select(node.value, node.row);
		return true;
	}
};
