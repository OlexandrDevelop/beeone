// "Create on the basis of": one client function for every command of the registry `basis_map`.
// The commands come from the hooks of the apps (frappe.boot.beeone_basis); the server mapper is
// frappe.beeone.basis.make_on_basis. Country neutral: every text goes through __().

frappe.provide("beeone.basis");

const MAPPER = "frappe.beeone.basis.make_on_basis";

// The commands that the form of a saved document offers.
beeone.basis.entries = function (frm) {
	if (!frm || frm.is_new()) return [];
	const list = (frappe.boot.beeone_basis || {})[frm.doctype] || [];
	return list.filter((entry) => {
		if (entry.submitted && frm.doc.docstatus !== 1) return false;
		if (entry.exclude_status && entry.exclude_status.includes(frm.doc.status)) return false;
		if (entry.onload_flag) {
			let value = frm.doc.__onload;
			for (const key of entry.onload_flag) value = value && value[key];
			if (!value) return false;
		}
		return !entry.target || frappe.model.can_create(entry.target);
	});
};

// Opens the new unsaved document that the command returns. Returns the promise of the call.
beeone.basis.create = function (frm, entry) {
	if ((entry.submitted || entry.submit_first) && frm.doc.docstatus !== 1) {
		frappe.msgprint(__("Submit the document first"));
		return Promise.resolve();
	}
	const make = () =>
		frappe.call({
			method: MAPPER,
			args: { source_doctype: frm.doctype, source_name: frm.doc.name, method: entry.method, target: entry.target },
			freeze: true,
		});
	return make().then((r) => beeone.basis.open(r.message));
};

// Syncs a document dict of the server as a new local document and opens its form.
beeone.basis.open = function (data) {
	if (!data) return;
	const doc = Object.assign({ __islocal: 1, docstatus: 0 }, data);
	if (!doc.name) doc.name = frappe.model.make_new_doc_and_get_name(doc.doctype, true);
	const meta = frappe.get_meta(doc.doctype);
	if (meta) {
		meta.fields
			.filter((df) => frappe.model.table_fields.includes(df.fieldtype))
			.forEach((df) =>
				(doc[df.fieldname] || []).forEach((row) =>
					Object.assign(row, { __islocal: 1, parentfield: df.fieldname, parenttype: doc.doctype })
				)
			);
	}
	const local = frappe.model.sync(doc)[0];
	frappe.set_route("Form", local.doctype, local.name);
};

// The standard buttons of a form, in the group "Create on basis". A form that draws its own menu
// sets `frm.beeone_basis_custom = true` and uses `beeone.basis.entries` and `beeone.basis.create`.
beeone.basis.add_buttons = function (frm) {
	if (frm.beeone_basis_custom) return;
	const group = __("Create on basis");
	beeone.basis.entries(frm).forEach((entry) =>
		frm.add_custom_button(__(entry.label), () => beeone.basis.create(frm, entry), group)
	);
};

$(document).on("form-refresh", (e, frm) => beeone.basis.add_buttons(frm));
