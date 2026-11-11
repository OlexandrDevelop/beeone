// Grey tones of the hierarchy levels and red negatives of reports.
// Twin of frappe/beeone/report_tones.py and beeone/report/_tones.scss (kept equal by test_beeone_report_tones).
frappe.provide("frappe.beeone_report_tones");

frappe.beeone_report_tones = {
	STEPS: 8,
	NEGATIVE: "#a50e0e",
	NUMERIC: ["Currency", "Float", "Int", "Percent"],

	// 1 + the deepest indent of the report rows; a flat report has 1
	depth(rows) {
		let deepest = 0;
		for (const row of rows || []) {
			if (row && !row.is_total_row) deepest = Math.max(deepest, cint(row.indent));
		}
		return deepest + 1;
	},

	// tone step 0..8 of a level: 8 darkest, 0 no fill
	step(level, depth) {
		if (depth <= 1) return 0;
		level = Math.min(Math.max(cint(level), 0), depth - 1);
		return Math.floor((8 * (depth - 1 - level)) / (depth - 1) + 0.5);
	},

	// light fill (print); null for step 0
	fill(step) {
		if (!step) return null;
		const c = Math.floor(255 - (55 * step) / 8 + 0.5).toString(16);
		return "#" + c + c + c;
	},

	is_negative(value, fieldtype) {
		return this.NUMERIC.includes(fieldtype) && typeof value === "number" && value < 0;
	},

	// html is already escaped by frappe.format
	wrap(html, { step = 0, total = false, negative = false, group = false } = {}) {
		if (!step && !total && !negative && !group) return html;
		const cls = ["bo-rt"];
		if (step) cls.push("bo-rt-" + step);
		if (total) cls.push("bo-rt-total");
		if (negative) cls.push("bo-rt-neg");
		if (group) cls.push("bo-rt-group");
		return `<div class="${cls.join(" ")}">${html}</div>`;
	},
};
