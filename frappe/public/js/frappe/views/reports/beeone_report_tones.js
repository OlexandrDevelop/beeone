// Tones of the hierarchy levels ("Indigo Slate": a cool grey tinted with the accent blue) and red negatives of reports.
// Twin of frappe/beeone/report_tones.py and beeone/report/_tones.scss (kept equal by test_beeone_report_tones).
frappe.provide("frappe.beeone_report_tones");

frappe.beeone_report_tones = {
	STEPS: 8,
	NEGATIVE: "#c0262d",
	// light tones of steps 1..8 (print); the screen takes them from beeone/report/_tones.scss
	FILLS: [
		"#f5f7fd",
		"#f2f4fd",
		"#eef2fc",
		"#ebeffc",
		"#e8edfc",
		"#e5eafc",
		"#e2e8fb",
		"#dfe5fb",
	],
	TOTAL_FILL: "#d3dcfa",
	ACCENT: "#2f54eb",
	BAR: "#9fb0f5",
	NUMERIC: ["Currency", "Float", "Int", "Percent"],

	// 1 + the deepest indent of the report rows; a flat report has 1
	depth(rows) {
		let deepest = 0;
		for (const row of rows || []) {
			if (row && !row.is_total_row) deepest = Math.max(deepest, cint(row.indent));
		}
		return deepest + 1;
	},

	// tone step 0..8 of a level: 8 strongest (top level), 0 no fill
	step(level, depth) {
		if (depth <= 1) return 0;
		level = Math.min(Math.max(cint(level), 0), depth - 1);
		return Math.floor((8 * (depth - 1 - level)) / (depth - 1) + 0.5);
	},

	// light fill (print); null for step 0
	fill(step) {
		if (!step) return null;
		return this.FILLS[Math.min(step, this.STEPS) - 1];
	},

	// light colour of the 3 px bar of a group row in its first column (print); null for a detail row
	bar(step) {
		if (!step) return null;
		return step >= this.STEPS ? this.ACCENT : this.BAR;
	},

	is_negative(value, fieldtype) {
		return this.NUMERIC.includes(fieldtype) && typeof value === "number" && value < 0;
	},

	// html is already escaped by frappe.format
	// lead: the first column of the row, it carries the bar of a group row
	wrap(html, { step = 0, total = false, negative = false, group = false, lead = false } = {}) {
		if (!step && !total && !negative && !group) return html;
		const cls = ["bo-rt"];
		if (step) cls.push("bo-rt-" + step);
		if (total) cls.push("bo-rt-total");
		if (negative) cls.push("bo-rt-neg");
		if (group) cls.push("bo-rt-group");
		if (lead && step) cls.push("bo-rt-lead");
		return `<div class="${cls.join(" ")}">${html}</div>`;
	},
};
