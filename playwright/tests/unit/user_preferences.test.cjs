// Run with `node --test`; exercise shared UI preferences without a Desk server.
const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

test("shared preferences retain independent values across concurrent UI changes", async () => {
	let user_settings = { BeeOneUI: { grid_density: "compact" } };
	const writes = [];
	globalThis.frappe = {
		model: {
			user_settings: {
				get: async () => user_settings,
				save: async (doctype, key, value) => {
					writes.push({ doctype, key, value: { ...value } });
					user_settings = {
						...user_settings,
						[key]: { ...(user_settings[key] || {}), ...value },
					};
					return user_settings;
				},
			},
		},
	};
	globalThis.document = { body: { dataset: {} } };
	globalThis.__ = (value) => value;
	globalThis.$ = () => ({ each() {} });

	const read_source = (relative_path) =>
		fs.readFileSync(path.join(__dirname, "../../../", relative_path), "utf8");
	const as_data_url = (source) =>
		`data:text/javascript;base64,${Buffer.from(source).toString("base64")}`;
	const grid_keys = await import(
		as_data_url(read_source("frappe/public/js/frappe/form/grid_settings_key.js"))
	);
	assert.notEqual(
		grid_keys.get_grid_settings_key("Sales Invoice Item", "items"),
		grid_keys.get_grid_settings_key("Sales Invoice Item", "taxes")
	);
	const preferences_url = as_data_url(
		read_source("frappe/public/js/frappe/ui/user_preferences.js")
	);
	const preferences = await import(preferences_url);

	assert.equal(await preferences.get_user_preference("grid_density"), "compact");
	assert.equal(await preferences.get_user_preference("form_sidebar_open", true), true);
	await Promise.all([
		preferences.save_user_preference("grid_density", "comfortable"),
		preferences.save_user_preference("form_sidebar_open", false),
		preferences.save_user_preference("desk_sidebar_expanded", false),
	]);
	assert.deepEqual(user_settings.BeeOneUI, {
		grid_density: "comfortable",
		form_sidebar_open: false,
		desk_sidebar_expanded: false,
	});
	assert.ok(writes.every((write) => write.doctype === "User" && write.key === "BeeOneUI"));

	const density_source = read_source("frappe/public/js/frappe/ui/table_density.js").replace(
		'"./user_preferences"',
		JSON.stringify(preferences_url)
	);
	const density = await import(as_data_url(density_source));
	density.load_table_density();
	await new Promise((resolve) => setImmediate(resolve));
	assert.equal(document.body.dataset.gridDensity, "comfortable");
	await density.toggle_table_density();
	assert.equal(document.body.dataset.gridDensity, "compact");
	assert.equal(user_settings.BeeOneUI.grid_density, "compact");

	delete globalThis.frappe;
	delete globalThis.document;
	delete globalThis.__;
	delete globalThis.$;
});
