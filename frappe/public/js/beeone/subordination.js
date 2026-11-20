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

function _container_of(frm) {
	// one container per form, inside this form's own layout (several forms can be open in windows)
	const root = frm.layout && frm.layout.wrapper && frm.layout.wrapper[0] ? frm.layout.wrapper[0] : null;
	return root ? root.querySelector(":scope > .bo-subordination") : null;
}

function _ensure_subordination_container(frm) {
	if (_container_of(frm)) {
		return;
	}
	const root = frm.layout && frm.layout.wrapper && frm.layout.wrapper[0];
	if (!root) return;

	const container = document.createElement("div");
	container.className = "bo-subordination";
	container.style.marginTop = "12px";
	container.style.padding = "12px";
	container.style.backgroundColor = "var(--bg-light)";
	container.style.borderRadius = "4px";
	container.style.borderLeft = "3px solid var(--primary)";
	root.appendChild(container);
}

function _load_subordination_data(frm) {
	if (!_is_subordination_supported(frm.doctype) || frm.doc.name === "__new" || frm.is_new()) {
		_ensure_subordination_container(frm);
		const container = _container_of(frm);
		if (container) {
			container.innerHTML = '<p style="color: var(--text-muted); font-size: 12px;">' + __("No related documents") + '</p>';
		}
		return;
	}

	frappe.call({
		// beeone: inaccessible related documents must not interrupt the host form.
		silent: true,
		error_handlers: { PermissionError: () => {} },
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
	_ensure_subordination_container(frm);
	const container = _container_of(frm);
	if (!container) return;

	if (!related || related.length === 0) {
		container.innerHTML = '<p style="color: var(--text-muted); font-size: 12px;">' + __("No related documents") + '</p>';
		return;
	}

	// Separate basis and derived documents
	const basis = related.filter(r => r.role === "basis");
	const derived = related.filter(r => r.role === "derived");

	let html = '<div style="padding: 0;">';
	html += '<div style="font-weight: 600; font-size: 13px; color: var(--text-dark); margin-bottom: 12px;">' + __("Subordination Tree") + '</div>';

	if (basis.length > 0) {
		html += '<div style="margin-bottom: 12px;">';
		html += '<div style="font-weight: 500; font-size: 12px; color: var(--text-muted); margin-bottom: 6px;">📋 ' + __("Basis Documents") + '</div>';
		html += _render_document_list(basis);
		html += '</div>';
	}

	if (derived.length > 0) {
		html += '<div>';
		html += '<div style="font-weight: 500; font-size: 12px; color: var(--text-muted); margin-bottom: 6px;">📄 ' + __("Derived Documents") + '</div>';
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
		case 0: return __("Draft");
		case 1: return __("Submitted");
		case 2: return __("Cancelled");
		default: return __("Unknown");
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

// ---------------------------------------------------------------- the structure window (user 2026-11-20, like 1C)
// «Subordination structure»: the tree from the root basis document down to every document made from it; the current
// document is marked, every node shows its kind, number, date, amount and state; a click opens the document.
frappe.provide("beeone.subordination");

beeone.subordination.show = function (frm) {
	const esc = (v) => frappe.utils.escape_html(v == null ? "" : String(v));
	const dialog = new frappe.ui.Dialog({
		title: __("Subordination structure") + ": " + __(frm.doctype) + " " + frm.doc.name,
		size: "large",
		fields: [{ fieldtype: "HTML", fieldname: "body" }],
	});
	dialog.$wrapper.addClass("bo-sub-dialog");
	const $body = dialog.fields_dict.body.$wrapper;
	$body.html(`<div class="bo-sub"><div class="bo-sub-loading">${esc(__("Loading..."))}</div></div>`);
	dialog.show();

	const state = (n) => {
		if (n.deletion_mark) return { cls: "is-deleted", label: __("Marked for deletion") };
		if (n.docstatus === 1) return { cls: "is-posted", label: __("Posted document") };
		if (n.docstatus === 2) return { cls: "is-cancelled", label: __("Cancelled") };
		return { cls: "is-draft", label: __("Draft") };
	};
	const node_html = (n) => {
		const s = state(n);
		const date = n.posting_date ? frappe.datetime.str_to_user(n.posting_date) + (n.posting_time ? " " + n.posting_time : "") : "";
		const amount =
			n.amount != null && n.amount !== ""
				? frappe.format(n.amount, { fieldtype: "Currency", options: n.currency ? undefined : undefined }, { inline: true })
				: "";
		const kids = (n.children || []).map(node_html).join("");
		return (
			`<li class="bo-sub-node${n.current ? " is-current" : ""}${kids ? " has-kids" : ""}">` +
			`<div class="bo-sub-row" tabindex="0" data-doctype="${esc(n.doctype)}" data-name="${esc(n.name)}">` +
			(kids ? `<button type="button" class="bo-sub-toggle" tabindex="-1" aria-label="${esc(__("Collapse"))}"></button>` : `<span class="bo-sub-toggle is-leaf"></span>`) +
			`<span class="bo-sub-state ${s.cls}" title="${esc(s.label)}"></span>` +
			`<span class="bo-sub-kind">${esc(__(n.doctype))}</span>` +
			`<span class="bo-sub-name">${esc(n.name)}</span>` +
			(date ? `<span class="bo-sub-date">${esc(__("dated"))} ${esc(date)}</span>` : "") +
			(amount ? `<span class="bo-sub-amount">${amount}</span>` : "") +
			`</div>` +
			(kids ? `<ul>${kids}</ul>` : "") +
			`</li>`
		);
	};

	frappe
		.xcall("frappe.beeone.api.subordination.get_structure", { doctype: frm.doctype, name: frm.doc.name })
		.then((r) => {
			if (!r || !r.root) {
				$body.find(".bo-sub").html(`<div class="bo-sub-empty">${esc(__("No related documents"))}</div>`);
				return;
			}
			const count = (n) => 1 + (n.children || []).reduce((s, c) => s + count(c), 0);
			const legend = [
				["is-posted", __("Posted document")],
				["is-draft", __("Draft")],
				["is-deleted", __("Marked for deletion")],
			]
				.map(([cls, label]) => `<span><i class="bo-sub-state ${cls}"></i>${esc(label)}</span>`)
				.join("");
			$body.find(".bo-sub").html(
				`<div class="bo-sub-bar"><span class="bo-sub-total">${esc(__("Documents"))}: <b>${count(r.root)}</b></span>` +
					`<span class="bo-sub-legend">${legend}</span></div>` +
					`<ul class="bo-sub-tree">${node_html(r.root)}</ul>` +
					(r.truncated ? `<div class="bo-sub-note">${esc(__("Only the first documents are shown"))}</div>` : "")
			);
			const $cur = $body.find(".is-current > .bo-sub-row");
			setTimeout(() => $cur.trigger("focus"), 50);
		});

	$body.on("click", ".bo-sub-toggle", function (e) {
		e.stopPropagation();
		$(this).closest(".bo-sub-node").toggleClass("is-collapsed");
	});
	const open = (el) => {
		const { doctype, name } = el.dataset;
		if (doctype === frm.doctype && name === frm.doc.name) return dialog.hide();
		dialog.hide();
		frappe.set_route("Form", doctype, name);
	};
	$body.on("click", ".bo-sub-row", function () {
		open(this);
	});
	$body.on("keydown", ".bo-sub-row", function (e) {
		const rows = $body.find(".bo-sub-row:visible").toArray();
		const i = rows.indexOf(this);
		if (e.key === "Enter") open(this);
		else if (e.key === "ArrowDown" && rows[i + 1]) rows[i + 1].focus(), e.preventDefault();
		else if (e.key === "ArrowUp" && rows[i - 1]) rows[i - 1].focus(), e.preventDefault();
		else if (e.key === "ArrowLeft") $(this).closest(".bo-sub-node").addClass("is-collapsed");
		else if (e.key === "ArrowRight") $(this).closest(".bo-sub-node").removeClass("is-collapsed");
	});
};
