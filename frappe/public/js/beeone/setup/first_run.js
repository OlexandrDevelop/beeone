// The "demo or setup" screen: shown once, to the first System Manager of a fresh site.
frappe.provide("beeone.setup");

const esc = (v) => frappe.utils.escape_html(v == null ? "" : String(v));

beeone.setup.call = (method, args) => frappe.xcall("frappe.beeone.setup." + method, args || {});

beeone.setup.maybe_first_run = function () {
	const info = frappe.boot.beeone_first_run;
	if (!info || !info.show || beeone.setup.shown || frappe.boot.setup_complete === false) return;
	beeone.setup.shown = true;
	const demo = info.demo || {};
	const card = (act, icon, title, text, disabled) =>
		`<button type="button" class="bo-setup-choice" data-choice="${act}"${disabled ? " disabled" : ""}>` +
		`${beeone.ui.icon(icon)}<span class="bo-setup-choice-title">${esc(title)}</span>` +
		`<span class="bo-setup-choice-text">${esc(text)}</span></button>`;
	beeone.ui.inject_icons();
	const dlg = beeone.ui.dialog({
		title: __("Welcome"),
		locked: true,
		width: 640,
		html:
			`<div class="bo-dialog-head"><h3>${esc(__("Welcome"))}</h3></div>` +
			`<div class="bo-dialog-body"><p class="bo-setup-lead">${esc(__("How do you want to start?"))}</p>` +
			`<div class="bo-setup-choices">` +
			card("demo", "package", __("Fill with demo data"), demo.allowed ? __("Look around with ready sample records") : demo.reason, !demo.allowed) +
			card("wizard", "sliders", __("Enter the organization's initial settings"), __("A short wizard collects what you need to start real work"), false) +
			`</div><div class="bo-field-error bo-setup-error" hidden></div>` +
			`<p class="bo-setup-later"><button type="button" class="bo-btn bo-btn--ghost bo-btn--sm" data-choice="later">${esc(__("Decide later"))}</button></p></div>`,
	});
	dlg.el.addEventListener("click", (e) => {
		const btn = e.target.closest("[data-choice]");
		if (!btn || btn.disabled) return;
		const choice = btn.dataset.choice;
		dlg.el.querySelectorAll("[data-choice]").forEach((b) => (b.disabled = true));
		beeone.setup.call("choose", { choice }).then(
			(r) => {
				if (!r.ok) {
					const err = dlg.el.querySelector(".bo-setup-error");
					err.textContent = r.reason;
					err.hidden = false;
					dlg.el.querySelectorAll("[data-choice]").forEach((b) => (b.disabled = false));
					return;
				}
				info.show = false;
				dlg.close();
				if (r.choice === "demo") beeone.ui.toast({ type: "info", title: __("Demo data is loading"), text: __("This takes a few minutes") });
				if (r.choice === "wizard") frappe.set_route("beeone-setup", "wizard");
			},
			() => dlg.el.querySelectorAll("[data-choice]").forEach((b) => (b.disabled = false))
		);
	});
};

// the demo job reports through a realtime event
beeone.setup.on_demo_event = function (data) {
	if (data.state === "done") {
		beeone.ui.toast({ title: data.action === "delete" ? __("Demo data removed") : __("Demo data is ready") });
	} else {
		beeone.ui.toast({ type: "error", title: __("Demo data failed"), text: data.message });
	}
	if (beeone.setup.page) beeone.setup.page.overview();
};

$(document).on("startup.beeone_setup", () => {
	frappe.realtime && frappe.realtime.on("beeone_demo", beeone.setup.on_demo_event);
	beeone.setup.maybe_first_run();
});

frappe.ui.form.on("User", {
	refresh(frm) {
		// a site fixed to one language has no language choice
		if (frappe.boot.beeone_language) frm.toggle_display("language", false);
	},
});
