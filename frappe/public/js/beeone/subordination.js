/**
 * Subordination tree: displays basis documents and documents made from the current document.
 * Loads on document open and updates on save/refresh.
 */

frappe.ui.form.on("*", {
	onload: function(frm) {
		if (!_is_subordination_supported(frm.doctype)) {
			return;
		}
		_ensure_subordination_container(frm);
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
	const beeone_docs = frappe.boot.beeone_documents || [];
	if (Array.isArray(beeone_docs)) {
		return beeone_docs.includes(doctype);
	}
	return false;
}

function _ensure_subordination_container(frm) {
	// Create container if it doesn't exist
	if (document.getElementById("subordination_tree_container")) {
		return;
	}

	// Find the form layout and add our container
	const form_layout = document.querySelector(".form-layout");
	if (!form_layout) return;

	const container = document.createElement("div");
	container.id = "subordination_tree_container";
	container.style.marginTop = "20px";
	container.style.padding = "12px";
	container.style.backgroundColor = "var(--bg-light)";
	container.style.borderRadius = "4px";
	container.style.borderLeft = "3px solid var(--primary)";
	form_layout.appendChild(container);
}

function _load_subordination_data(frm) {
	if (!_is_subordination_supported(frm.doctype) || frm.doc.name === "__new") {
		const container = document.getElementById("subordination_tree_container");
		if (container) {
			container.innerHTML = '<p style="color: var(--text-muted); font-size: 12px;">No related documents</p>';
		}
		return;
	}

	frappe.call({
		// beeone: inaccessible related documents must not interrupt the host form.
		silent: true,
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
	const container = document.getElementById("subordination_tree_container");
	if (!container) return;

	if (!related || related.length === 0) {
		container.innerHTML = '<p style="color: var(--text-muted); font-size: 12px;">No related documents</p>';
		return;
	}

	// Separate basis and derived documents
	const basis = related.filter(r => r.role === "basis");
	const derived = related.filter(r => r.role === "derived");

	let html = '<div style="padding: 0;">';
	html += '<div style="font-weight: 600; font-size: 13px; color: var(--text-dark); margin-bottom: 12px;">Subordination Tree</div>';

	if (basis.length > 0) {
		html += '<div style="margin-bottom: 12px;">';
		html += '<div style="font-weight: 500; font-size: 12px; color: var(--text-muted); margin-bottom: 6px;">📋 Basis Documents</div>';
		html += _render_document_list(basis);
		html += '</div>';
	}

	if (derived.length > 0) {
		html += '<div>';
		html += '<div style="font-weight: 500; font-size: 12px; color: var(--text-muted); margin-bottom: 6px;">📄 Derived Documents</div>';
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
	let html = '<div style="display: flex; flex-direction: column; gap: 6px;">';

	for (const doc of docs) {
		const status_label = _get_status_label(doc.docstatus);
		const date_str = doc.posting_date ? ` • ${frappe.utils.escape_html(doc.posting_date)}` : "";
		const escaped_name = frappe.utils.escape_html(doc.name);
		const escaped_doctype = frappe.utils.escape_html(doc.doctype);
		const status_color = _get_status_color(doc.docstatus);

		html += `<div style="display: flex; align-items: center; gap: 8px; padding: 6px 8px; border-radius: 3px; background-color: var(--bg-white); border: 1px solid var(--border-color);">
			<div data-doctype="${escaped_doctype}" data-name="${escaped_name}" style="flex: 1; color: var(--primary); text-decoration: none; cursor: pointer;">
				<span style="font-weight: 500; font-size: 13px;">${escaped_name}</span>
				<span style="font-size: 11px; color: var(--text-muted); margin-left: 4px;">(${escaped_doctype})${date_str}</span>
			</div>
			<span style="padding: 2px 8px; border-radius: 2px; font-size: 11px; font-weight: 600; background-color: ${status_color}; color: white; white-space: nowrap;">${status_label}</span>
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
