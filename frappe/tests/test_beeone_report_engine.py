# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

"""Report composition engine: groupings, subtotals, grand total, drill-down."""

from frappe.beeone import report_engine as engine
from frappe.tests import IntegrationTestCase

ROWS = [
	{"region": "N", "item": "A", "dt": "Invoice", "doc": "INV-1", "qty": 2, "amount": 10.5},
	{"region": "N", "item": "B", "dt": "Invoice", "doc": "INV-2", "qty": 1, "amount": 5.0},
	{"region": "S", "item": "A", "dt": "Invoice", "doc": "INV-3", "qty": 4, "amount": 20.0},
	{"region": "S", "item": "A", "dt": "Invoice", "doc": "INV-3", "qty": 1, "amount": 2.5},
	{"region": None, "item": "C", "dt": "Return", "doc": "RET-1", "qty": -1, "amount": -3.0},
]
MEASURES = [
	{"field": "qty"},
	{"field": "amount", "precision": 2},
	{"field": "doc", "agg": "count_distinct", "key": "docs"},
]


class TestReportEngine(IntegrationTestCase):
	def test_no_groupings_gives_details_and_total(self):
		out = engine.compose(ROWS, measures=MEASURES)
		self.assertEqual([r["kind"] for r in out], ["item"] * 5 + ["total"])
		total = out[-1]["values"]
		self.assertEqual(total["qty"], 7)
		self.assertEqual(total["amount"], 35.0)
		self.assertEqual(total["docs"], 4)

	def test_one_level_group_order_and_totals(self):
		out = engine.compose(ROWS, ["region"], MEASURES, detail=False)
		self.assertEqual([r["id"] for r in out], ["N", "S", "None", "total"])
		self.assertEqual(out[0]["values"], {"qty": 3, "amount": 15.5, "docs": 2})
		self.assertEqual(out[1]["values"]["docs"], 1)  # INV-3 counted once
		# the empty group is last and has an empty label
		self.assertEqual(out[2]["label"], "")

	def test_descending_and_label(self):
		g = {"field": "region", "order": "desc", "label": lambda v: f"R:{v}"}
		out = engine.compose(ROWS, [g], MEASURES, detail=False)
		self.assertEqual([r["label"] for r in out[:2]], ["R:S", "R:N"])

	def test_nested_groups_subtotals_equal_total(self):
		out = engine.compose(ROWS, ["region", "item"], ["qty"], detail=False)
		level0 = [r for r in out if r["kind"] == "group" and r["level"] == 0]
		level1 = [r for r in out if r["kind"] == "group" and r["level"] == 1]
		total = out[-1]["values"]["qty"]
		self.assertEqual(sum(r["values"]["qty"] for r in level0), total)
		self.assertEqual(sum(r["values"]["qty"] for r in level1), total)
		child = [r for r in level1 if r["parent"] == "S"][0]
		self.assertEqual(child["drill"]["filters"], {"region": "S", "item": "A"})
		self.assertEqual(child["values"]["qty"], 5)

	def test_detail_rows_drill_to_document(self):
		out = engine.compose(
			ROWS, ["region"], ["qty"], drill={"doctype": "dt", "name": "doc"}, label_field="doc"
		)
		items = [r for r in out if r["kind"] == "item" and r["parent"] == "N"]
		self.assertEqual([r["drill"] for r in items], [{"doctype": "Invoice", "name": "INV-1"}, {"doctype": "Invoice", "name": "INV-2"}])
		self.assertEqual(items[0]["label"], "INV-1")

	def test_group_drill_filters_select_its_rows(self):
		out = engine.compose(ROWS, ["region", "item"], ["qty"], detail=False)
		node = [r for r in out if r["id"] == "S/A"][0]
		rows = engine.drill_rows(ROWS, node["drill"]["filters"])
		self.assertEqual(sum(r["qty"] for r in rows), node["values"]["qty"])

	def test_min_max_and_empty(self):
		out = engine.compose(
			ROWS, measures=[{"field": "amount", "agg": "min", "key": "lo"}, {"field": "amount", "agg": "max", "key": "hi"}], detail=False
		)
		self.assertEqual((out[-1]["values"]["lo"], out[-1]["values"]["hi"]), (-3.0, 20.0))
		empty = engine.compose([], ["region"], ["qty"])
		self.assertEqual([r["kind"] for r in empty], ["total"])
		self.assertEqual(empty[0]["values"]["qty"], 0)

	def test_unknown_aggregate_is_rejected(self):
		with self.assertRaises(ValueError):
			engine.compose(ROWS, measures=[{"field": "qty", "agg": "median"}])
