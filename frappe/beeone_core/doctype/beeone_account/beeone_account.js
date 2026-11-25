// Copyright (c) 2026, beeone contributors
// License: MIT. See LICENSE

frappe.ui.form.on("BeeOne Account", {
	refresh(frm) {
		frm.add_custom_button(__("Connect"), () => {
			const go = () =>
				frappe.xcall("frappe.beeone.subscription.connect").then((r) => {
					frappe.show_alert({ message: __("Subscription: {0}", [r.label]), indicator: r.state === "Active" ? "green" : "orange" });
					frm.reload_doc();
				});
			if (frm.is_dirty()) frm.save().then(go);
			else go();
		});
		frappe.xcall("frappe.beeone.subscription.sent_data").then((r) => {
			const esc = frappe.utils.escape_html;
			frm.get_field("sent_html").$wrapper.html(
				`<p class="text-muted small">${esc(__("Once a day, and only while the key is filled, the site sends this to {0}. Nothing else is sent.", [r.url]))}</p>` +
					`<pre class="small">${esc(JSON.stringify(r.body, null, 2))}</pre>`
			);
		});
	},
});
