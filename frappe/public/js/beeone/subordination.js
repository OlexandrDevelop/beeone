/**
 * Subordination tree: displays basis documents and documents made from the current document.
 * Loads on document open and updates on save/refresh.
 */

frappe.ui.form.on("*", {
	onload: function(frm) {
		if (!_is_subordination_supported(frm.doctype)) {
			return;
		}
		_load_subordination_data(frm);
	},
	after_save: function(frm) {
		if (!_is_subordination_supported(frm.doctype)) {
			return;
		}
		_load_subordination_data(frm);
	},
	refresh: function(frm) {
		if (!_is_subordination_supported(frm.doctype)) {
			return;
		}
		_load_subordination_data(frm);
	}
});

function _is_subordination_supported(doctype) {
	// Check if subordination is enabled for this doctype
	// The apps register supported types through beeone_documents hook
	const beeone_docs = frappe.boot.beeone_documents || [];
	if (Array.isArray(beeone_docs)) {
		return beeone_docs.includes(doctype);
	}
	return false;
}

function _load_subordination_data(frm) {
	if (!_is_subordination_supported(frm.doctype) || frm.doc.name === "__new") {
		return;
	}

	frappe.call({
		method: "frappe.beeone.api.subordination.get_related",
		args: {
			doctype: frm.doctype,
			name: frm.doc.name
		},
		callback: function(r) {
			if (r.message) {
				_render_subordination_tree(frm, r.message);
			}
		}
	});
}

function _render_subordination_tree(frm, related) {
	// Find or create dashboard section
	let section = frm.dashboard.find_section("subordination_tree");
	if (!section) {
		section = frm.dashboard.add_section(
			frappe.ui.form.DashboardSection,
			{ title: "Subordination Tree", icon: "icon-sitemap", collapsible: true }
		);
	}

	let content = "";

	if (!related || related.length === 0) {
		content = '<p style="color: var(--text-muted); font-size: 12px; padding: 8px;">No related documents</p>';
	} else {
		// Separate basis and derived documents
		const basis = related.filter(r => r.role === "basis");
		const derived = related.filter(r => r.role === "derived");

		content = '<div style="padding: 8px 0;">';

		if (basis.length > 0) {
			content += '<div style="margin-bottom: 12px;">';
			content += '<div style="font-weight: 500; font-size: 12px; color: var(--text-muted); margin-bottom: 4px;">Basis Documents</div>';
			content += _render_document_list(basis);
			content += '</div>';
		}

		if (derived.length > 0) {
			content += '<div>';
			content += '<div style="font-weight: 500; font-size: 12px; color: var(--text-muted); margin-bottom: 4px;">Derived Documents</div>';
			content += _render_document_list(derived);
			content += '</div>';
		}

		content += '</div>';
	}

	section.body.innerHTML = content;

	// Attach click handlers
	section.body.querySelectorAll("[data-doctype][data-name]").forEach(el => {
		el.style.cursor = "pointer";
		el.addEventListener("click", function() {
			frappe.set_route("Form", this.dataset.doctype, this.dataset.name);
		});
	});
}

function _render_document_list(docs) {
	let html = '<div style="display: flex; flex-direction: column; gap: 4px;">';

	for (const doc of docs) {
		const status_label = _get_status_label(doc.docstatus);
		const date_str = doc.posting_date ? ` • ${frappe.utils.escape_html(doc.posting_date)}` : "";
		const escaped_name = frappe.utils.escape_html(doc.name);
		const escaped_doctype = frappe.utils.escape_html(doc.doctype);

		html += `<div style="display: flex; align-items: center; gap: 8px; padding: 4px; border-radius: 3px; background-color: var(--bg-light);">
			<div data-doctype="${escaped_doctype}" data-name="${escaped_name}" style="flex: 1; color: var(--primary); text-decoration: none; cursor: pointer;">
				<span style="font-weight: 500;">${escaped_name}</span>
				<span style="font-size: 11px; color: var(--text-muted);">(${escaped_doctype})${date_str}</span>
			</div>
			<span style="padding: 2px 6px; border-radius: 2px; font-size: 11px; font-weight: 500; background-color: ${_get_status_color(doc.docstatus)}; color: white;">${status_label}</span>
		</div>`;
	}

	html += '</div>';
	return html;
}

function _get_status_label(docstatus) {
	switch (docstatus) {
		case 0: return "Draft";
		case 1: return "Submitted";
		case 2: return "Cancelled";
		default: return "Unknown";
	}
}

function _get_status_color(docstatus) {
	switch (docstatus) {
		case 0: return "var(--warning)";
		case 1: return "var(--success)";
		case 2: return "var(--danger)";
		default: return "var(--text-muted)";
	}
}
