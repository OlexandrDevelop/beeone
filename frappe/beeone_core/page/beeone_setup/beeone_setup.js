// Initial setup: demo data and the setup wizard (docs/platform/SETUP.md). The work is in setup/*.js.
frappe.pages["beeone-setup"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Initial setup"), single_column: true });
	wrapper.beeone_setup = new beeone.setup.Page(page);
};

frappe.pages["beeone-setup"].on_page_show = function (wrapper) {
	wrapper.beeone_setup && wrapper.beeone_setup.show(frappe.get_route());
};
