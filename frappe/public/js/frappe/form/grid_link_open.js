// Open the card of the document a Link / Dynamic Link grid cell points to.
// Goes through the router so the shell gives it its own window; in plain /app it is a normal
// navigation. The parent form stays in locals, so its unsaved state is kept.
export function get_link_target(df, doc) {
	if (!df || !doc) return null;
	let doctype = null;
	if (df.fieldtype === "Link") doctype = df.options;
	else if (df.fieldtype === "Dynamic Link") doctype = doc[df.options];
	const name = doc[df.fieldname];
	if (!doctype || !name) return null;
	return { doctype, name };
}

export function can_open_link(df, doc) {
	const target = get_link_target(df, doc);
	return Boolean(target && frappe.model.can_read(target.doctype));
}

export function open_link_target(df, doc, { notify = false } = {}) {
	const target = get_link_target(df, doc);
	if (!target || !frappe.model.can_read(target.doctype)) {
		if (notify) {
			frappe.show_alert({ message: __("Nothing to open"), indicator: "orange" }, 3);
		}
		return false;
	}
	frappe.set_route("Form", target.doctype, target.name);
	return true;
}

frappe.ui.form.open_link_target = open_link_target;
frappe.ui.form.can_open_link = can_open_link;
