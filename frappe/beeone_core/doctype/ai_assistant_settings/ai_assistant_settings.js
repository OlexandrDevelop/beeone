// Copyright (c) 2026, beeone contributors
// License: MIT. See LICENSE

frappe.ui.form.on("AI Assistant Settings", {
	refresh(frm) {
		frm.add_custom_button(__("Test the connection"), () =>
			frappe.xcall("frappe.beeone.ai.api.test_connection").then((r) =>
				frappe.msgprint({ message: r.message, indicator: r.ok ? "green" : "red", title: __("AI model") })
			)
		);
		frm.add_custom_button(__("Reread the help"), () =>
			frappe.xcall("frappe.beeone.ai.api.rebuild_help").then((r) =>
				frappe.show_alert({ message: __("Help pages: {0}, sections: {1}", [r.pages, r.sections]), indicator: "green" })
			)
		);
		frm.add_custom_button(__("Open the log"), () => frappe.set_route("List", "AI Assistant Log"));
		frm.add_custom_button(__("Open the assistant"), () => beeone.shell && beeone.shell.assistant && beeone.shell.assistant.open());
		const help =
			`<p>${__("Gemini: create a key at aistudio.google.com (API keys). The free tier allows a few requests per minute and a limited number per day per project, and Google may use the requests to improve its models; on the paid tier it does not.")}</p>` +
			`<p>${__("OpenAI compatible: a local server (for example Ollama with a model that supports tools) keeps the data on your servers; or a gateway such as OpenRouter.")}</p>` +
			`<p>${__("Without a model the assistant still finds help pages and runs the checks.")}</p>`;
		frm.get_field("status_html").$wrapper.html(`<div class="text-muted small">${help}</div>`);
	},
});
