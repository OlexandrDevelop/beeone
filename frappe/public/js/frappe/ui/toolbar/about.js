frappe.provide("frappe.ui.misc");
frappe.ui.misc.about = function () {
	if (frappe.ui.misc.about_dialog) {
		frappe.ui.misc.about_dialog.show();
		return;
	}

	const dialog = new frappe.ui.Dialog({ title: __("About") });
	$(dialog.wrapper).addClass("about-dialog");

	$(dialog.body).html(
		`<div class="about-body flex flex-col gap-5 items-start">
			<div class="about-frappe-section flex flex-col items-center gap-3 py-3 w-full">
				<div class="about-frappe-header flex flex-col justify-center items-center gap-1.5">
					<img src="/assets/frappe/images/beeone-logo.svg" alt="beeone" class="about-frappe-wordmark">
					<p class="about-tagline text-p-sm text-ink-gray-5 m-0">${__("Платформа BeeOne")}</p>
				</div>
			</div>

			<div class="about-info-rows flex flex-col gap-3 w-full">
				<div class="about-info-row flex items-center justify-between">
					<div class="about-info-content flex flex-col gap-1">
						<div class="about-info-title inline-flex items-center gap-1 text-base-semibold text-ink-gray-8">${__(
							"Версія платформи BeeOne"
						)}</div>
						<div class="about-info-sub text-p-sm text-ink-gray-5" id="about-framework-version">
							${__("Loading...")}
						</div>
					</div>
				</div>
			</div>

			<div class="about-section-header flex items-center justify-between w-full">
				<div class="about-section-label text-2xs text-ink-gray-6 text-uppercase">${__(
					"Installed Apps"
				)}</div>
				<button class="es-button hidden" data-variant="ghost" data-icon-button="true"
					id="copy-apps-info" title="${__("Copy Apps Version")}" aria-label="${__("Copy Apps Version")}">
					${frappe.utils.icon("clipboard", "sm", "", "", "", true)}
				</button>
			</div>

			<div id="about-app-versions" class="about-app-list flex flex-col gap-3 w-full"></div>
		</div>`
	);

	$(dialog.footer)
		.removeClass("hide")
		.prepend(
			`<div class="about-footer text-p-sm text-ink-gray-4 text-center">
			${__("&copy; BeeOne")}
		</div>`
		);

	frappe.ui.misc.about_dialog = dialog;

	frappe.ui.misc.about_dialog.on_page_show = function () {
		if (!frappe.versions) {
			frappe.call({
				method: "frappe.utils.change_log.get_versions",
				callback: function (r) {
					show_versions(r.message);
				},
			});
		} else {
			show_versions(frappe.versions);
		}
	};

	const get_version_text = function (app) {
		const is_pr_branch = app.branch && /^pr-\d+/i.test(app.branch);
		if (app.branch && !is_pr_branch) {
			return `${app.version} (${app.branch})`;
		}
		return app.version;
	};

	const render_app_icon = function (app_name, app) {
		const first_letter = (app.title || app_name).charAt(0).toUpperCase();
		if (app.logo) {
			return `<img src="${app.logo}" class="about-app-logo size-8 rounded shrink-0" alt="${first_letter}">`;
		}
		if (app.color) {
			return `<div class="about-app-icon text-sm-semibold flex items-center justify-center size-8 rounded shrink-0" style="background-color: ${app.color};">${first_letter}</div>`;
		}
		const palette = frappe.get_palette(app_name);
		return `<div class="about-app-icon text-sm-semibold flex items-center justify-center size-8 rounded shrink-0" style="background-color: var(${palette[0]}); color: var(${palette[1]});">${first_letter}</div>`;
	};

	const show_versions = function (versions) {
		if (versions.frappe) {
			$("#about-framework-version").text(`BeeOne ${get_version_text(versions.frappe)}`);
		}

		const $wrap = $("#about-app-versions").empty();

		for (const app_name in versions) {
			if (app_name === "frappe") continue;
			const app = versions[app_name];
			const version_text = get_version_text(app);
			const title = `${app_name}: ${app.version}`;

			$(`<div class="about-app-row flex items-center gap-3 cursor-pointer" role="button" tabindex="0" title="${title}">
					${render_app_icon(app_name, app)}
					<div class="about-app-info flex-1 min-w-0">
						<div class="about-app-name text-base-semibold text-ink-gray-8">${__(app.title)}</div>
						<div class="about-app-version text-sm text-ink-gray-5">${app_name}: ${version_text}</div>
					</div>
				</div>`).appendTo($wrap);
		}

		frappe.versions = versions;

		if (frappe.versions) {
			$(dialog.body).find("#copy-apps-info").removeClass("hidden");
		}
	};

	const code_block = (snippet, lang = "") => "```" + lang + "\n" + snippet + "\n```";

	// Listener for copying installed apps info
	$(dialog.body).on("click", "#copy-apps-info", function () {
		if (!frappe.versions) return;

		const versions = Object.entries(frappe.versions).reduce((acc, [key, app]) => {
			acc[key] = app.branch_version || app.version;
			return acc;
		}, {});

		frappe.utils.copy_to_clipboard(code_block(JSON.stringify(versions, null, "\t"), "json"));
	});

	// Listener for copy app version
	$(dialog.body).on("click", ".about-app-row", function () {
		const title = $(this).attr("title");
		if (title) {
			frappe.utils.copy_to_clipboard(title);
		}
	});

	// Keyboard support for copy app version (Enter / Space)
	$(dialog.body).on("keydown", ".about-app-row", function (e) {
		if (e.key === "Enter" || e.key === " ") {
			e.preventDefault();
			$(this).trigger("click");
		}
	});

	frappe.ui.misc.about_dialog.show();
};
