const SETTINGS_KEY = "BeeOneUI";
let preferences_request;
let save_queue = Promise.resolve();

function load_preferences() {
	if (!preferences_request) {
		preferences_request = frappe.model.user_settings
			.get("User")
			.then((settings) => {
				frappe.model.user_settings.User = settings;
				return { ...(settings[SETTINGS_KEY] || {}) };
			});
	}
	return preferences_request;
}

export async function get_user_preference(name, fallback) {
	const preferences = await load_preferences();
	return Object.prototype.hasOwnProperty.call(preferences, name)
		? preferences[name]
		: fallback;
}

export async function save_user_preference(name, value) {
	const preferences = await load_preferences();
	preferences[name] = value;
	save_queue = save_queue
		.catch(() => {})
		.then(() => {
			return frappe.model.user_settings.save("User", SETTINGS_KEY, { ...preferences });
		});
	return save_queue;
}
