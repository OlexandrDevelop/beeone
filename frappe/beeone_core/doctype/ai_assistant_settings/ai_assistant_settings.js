// Copyright (c) 2026, beeone contributors
// License: MIT. See LICENSE

frappe.ui.form.on("AI Assistant Settings", {
	refresh(frm) {
		frm.add_custom_button(__("Test the connection"), () =>
			frappe.xcall("frappe.beeone.ai.api.test_connection").then((r) =>
				frappe.msgprint({ message: r.message, indicator: r.ok ? "green" : "red", title: __("AI assistant") })
			)
		);
		frm.add_custom_button(__("Reread the help"), () =>
			frappe.xcall("frappe.beeone.ai.api.rebuild_help").then((r) =>
				frappe.show_alert({ message: __("Help pages: {0}, sections: {1}", [r.pages, r.sections]), indicator: "green" })
			)
		);
		frm.add_custom_button(__("Open the log"), () => frappe.set_route("List", "AI Assistant Log"));
		frm.add_custom_button(__("Open the assistant"), () => beeone.shell && beeone.shell.assistant && beeone.shell.assistant.open());
		const sub = frappe.boot.beeone_subscription || {};
		const on = (sub.features || []).includes("ai");
		const esc = frappe.utils.escape_html;
		frm.get_field("status_html").$wrapper.html(
			`<div class="small"><p>${esc(on ? __("The AI of BeeOne is available by the subscription until {0}.", [frappe.datetime.str_to_user(sub.until)]) : __("The AI of BeeOne is available with a subscription."))}</p>` +
				`<p><a href="#" data-sub>${esc(__("Open «Підписка BeeOne»"))}</a></p>` +
				`<p class="text-muted">${esc(__("Without a subscription the assistant still finds help pages and runs the checks."))}</p></div>`
		);
		frm.get_field("status_html").$wrapper.find("[data-sub]").on("click", (e) => {
			e.preventDefault();
			frappe.set_route("Form", "BeeOne Account");
		});
	},
});
