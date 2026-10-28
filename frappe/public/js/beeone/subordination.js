/**
 * Subordination tree: displays basis documents and documents made from the current document.
 * Loaded on document forms and updated when the document is changed.
 */

frappe.ui.form.on("*", {
	onload: function(frm) {
		if (!_is_subordination_supported(frm.doctype)) {
			return;
		}
		_setup_subordination_panel(frm);
		_load_subordination_data(frm);
	},
	after_save: function(frm) {
		if (!_is_subordination_supported(frm.doctype)) {
			return;
		}
		_load_subordination_data(frm);
	}
});

function _is_subordination_supported(doctype) {
	// Check if subordination is enabled for this doctype
	// The apps register supported types through beeone_documents hook
	const beeone_docs = frappe.boot.beeone_documents || {};
	if (Array.isArray(beeone_docs)) {
		return beeone_docs.includes(doctype);
	}
	// If beeone_documents is not available, fall back to checking if there's data
	return false;
}

function _setup_subordination_panel(frm) {
	// Create the subordination panel if it doesn't exist
	if (frm.get_section("subordination_section")) {
		return;
	}

	frm.add_section("Subordination Tree", "subordination_section");
	frm.get_section("subordination_section").collapsible = true;
	frm.get_section("subordination_section").collapsed = false;

	const panel = frm.get_section("subordination_section");
	panel.wrapper.innerHTML = '<div class="subordination-tree-container"></div>';
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
	const container = frm.get_section("subordination_section")
		?.wrapper.querySelector(".subordination-tree-container");
	if (!container) {
		return;
	}

	if (!related || related.length === 0) {
		container.innerHTML = '<p style="color: var(--text-muted); font-size: 12px;">No related documents</p>';
		return;
	}

	// Separate basis and derived documents
	const basis = related.filter(r => r.role === "basis");
	const derived = related.filter(r => r.role === "derived");

	let html = '<div style="padding: 8px 0;">';

	if (basis.length > 0) {
		html += '<div style="margin-bottom: 12px;">';
		html += '<div style="font-weight: 500; font-size: 12px; color: var(--text-muted); margin-bottom: 4px;">Basis Documents</div>';
		html += _render_document_list(basis);
		html += '</div>';
	}

	if (derived.length > 0) {
		html += '<div>';
		html += '<div style="font-weight: 500; font-size: 12px; color: var(--text-muted); margin-bottom: 4px;">Derived Documents</div>';
		html += _render_document_list(derived);
		html += '</div>';
	}

	html += '</div>';
	container.innerHTML = html;

	// Attach click handlers
	container.querySelectorAll("[data-doctype][data-name]").forEach(el => {
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
		const date_str = doc.posting_date ? ` • ${doc.posting_date}` : "";

		html += `<div style="display: flex; align-items: center; gap: 8px; padding: 4px; border-radius: 3px; background-color: var(--bg-light);">
			<div data-doctype="${doc.doctype}" data-name="${doc.name}" style="flex: 1; color: var(--primary); text-decoration: none;">
				<span style="font-weight: 500;">${frappe.utils.get_indicator_color(status_label)[1]}</span>
				<span>${doc.name}</span>
				<span style="font-size: 11px; color: var(--text-muted);">(${doc.doctype})${date_str}</span>
			</div>
			<span class="badge" style="background-color: ${_get_status_color(doc.docstatus)}">${status_label}</span>
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
