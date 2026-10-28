// The desktop of the beeone shell is not a page of Frappe: the route only means "no window is active".
// The shell (public/js/beeone/shell) shows the desktop and hides this empty page.
frappe.pages["beeone-desktop"].on_page_load = function () {};
