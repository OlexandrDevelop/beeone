import { get_user_preference, save_user_preference } from "./user_preferences";

let preference_was_changed = false;
let preference_loaded = false;

export function apply_table_density(density) {
	const normalized = density === "compact" ? "compact" : "comfortable";
	document.body.dataset.gridDensity = normalized;
	$(".grid-density-toggle").each(function () {
		const next = normalized === "compact" ? "comfortable" : "compact";
		$(this)
			.attr("data-density", normalized)
			.attr("aria-pressed", normalized === "compact")
			.attr(
				"aria-label",
				__(next === "compact" ? "Use compact table rows" : "Use comfortable table rows")
			)
			.attr(
				"title",
				__(next === "compact" ? "Use compact table rows" : "Use comfortable table rows")
			)
			.find(".grid-density-label")
			.text(__(normalized === "compact" ? "Compact" : "Comfortable"));
	});
}

export function load_table_density() {
	if (preference_loaded) return;
	preference_loaded = true;
	get_user_preference("grid_density")
		.then((density) => {
			if (!preference_was_changed) apply_table_density(density);
		})
		.catch(() => apply_table_density("comfortable"));
}

export function toggle_table_density() {
	const next = document.body.dataset.gridDensity === "compact" ? "comfortable" : "compact";
	preference_was_changed = true;
	apply_table_density(next);
	return save_user_preference("grid_density", next);
}
