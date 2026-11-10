# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

"""Report composition engine: groupings, subtotals, grand total, drill-down."""

import random
from unittest.mock import patch

import frappe
from frappe.beeone import report_engine as engine
from frappe.tests import IntegrationTestCase
from frappe.utils import flt

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


def _old_compose(rows, groupings=(), measures=(), detail=True, drill=None, label_field=None, total_label=""):
	"""Frozen copy of the algorithm before T-892 (flt and rounding at every addition)."""
	groupings = [engine._norm_grouping(g) for g in groupings]
	measures = [engine._norm_measure(m) for m in measures]
	rows = list(rows)

	class Acc:
		def __init__(self):
			self.state = [
				set() if m["agg"] == "count_distinct" else (0 if m["agg"] in ("sum", "count") else None)
				for m in measures
			]

		def add(self, row):
			for i, m in enumerate(measures):
				agg, value = m["agg"], row.get(m["field"])
				if agg == "sum":
					self.state[i] += flt(value)
				elif agg == "count":
					self.state[i] += 1
				elif agg == "count_distinct":
					if value is not None:
						self.state[i].add(value)
				elif value is not None:
					cur = self.state[i]
					if cur is None or (value < cur if agg == "min" else value > cur):
						self.state[i] = value

		def values(self):
			out = {}
			for m, v in zip(measures, self.state):
				if m["agg"] == "count_distinct":
					v = len(v)
				elif m["agg"] == "sum" and m["precision"] is not None:
					v = flt(v, m["precision"])
				out[m["key"]] = v
			return out

	out = []
	grand = Acc()
	for row in rows:
		grand.add(row)

	def emit(rows_, depth, parent, filters):
		if depth == len(groupings):
			if not detail:
				return
			for i, row in enumerate(rows_):
				acc = Acc()
				acc.add(row)
				target = None
				if drill and row.get(drill["name"]):
					target = {"doctype": row.get(drill["doctype"]), "name": row[drill["name"]]}
				row_id = f"{parent}/{i}" if parent else str(i)
				out.append(
					{
						"id": row_id,
						"parent": parent,
						"level": depth,
						"kind": "item",
						"label": row.get(label_field) if label_field else None,
						"values": acc.values(),
						"drill": target,
					}
				)
			return
		g = groupings[depth]
		buckets = {}
		for row in rows_:
			buckets.setdefault(row.get(g["field"]), []).append(row)
		for key in engine._sorted_keys(list(buckets), g):
			part = buckets[key]
			acc = Acc()
			for row in part:
				acc.add(row)
			label = g["label"](key) if g["label"] else ("" if key is None else str(key))
			node_filters = {**filters, g["field"]: key}
			node_id = f"{parent}/{key}" if parent else str(key)
			out.append(
				{
					"id": node_id,
					"parent": parent,
					"level": depth,
					"kind": "group",
					"label": label,
					"values": acc.values(),
					"drill": {"filters": node_filters},
				}
			)
			emit(part, depth + 1, node_id, node_filters)

	emit(rows, 0, None, {})
	out.append(
		{
			"id": "total",
			"parent": None,
			"level": 0,
			"kind": "total",
			"label": total_label,
			"values": grand.values(),
			"drill": None,
		}
	)
	return out


class TestReportEngineEquivalence(IntegrationTestCase):
	def _data(self, n=600):
		rnd = random.Random(892)
		return [
			{
				"a": rnd.choice(["x", "y", "z", None]),
				"b": rnd.choice([1, 2, 3, None]),
				"c": rnd.choice(["p", "q"]),
				"dt": "Doc",
				"doc": f"D-{rnd.randint(1, 40)}",
				# thirds and halves: ties and floating drift matter
				"amount": rnd.choice([None, "", "1,5", rnd.randint(-5000, 5000) / 8, rnd.random() * 100]),
				"qty": rnd.choice([0, 1, 2.5, -1, None]),
				"day": rnd.choice(["2026-11-01", "2026-11-02", None]),
			}
			for _ in range(n)
		]

	def test_same_output_as_before_under_every_rounding_method(self):
		measures = [
			{"field": "qty"},
			{"field": "amount", "precision": 2},
			{"field": "amount", "precision": 0, "key": "amount0"},
			{"field": "amount", "key": "raw"},
			{"field": "doc", "agg": "count_distinct", "key": "docs"},
			{"field": "doc", "agg": "count", "key": "n"},
			{"field": "day", "agg": "min", "key": "first"},
			{"field": "day", "agg": "max", "key": "last"},
		]
		cases = [
			dict(groupings=[], detail=True),
			dict(groupings=["a"], detail=False),
			dict(groupings=["a", {"field": "b", "order": "desc"}, {"field": "c", "order": "none"}], detail=True),
			dict(groupings=[{"field": "a", "label": lambda v: f"<{v}>"}, "b"], detail=True,
				drill={"doctype": "dt", "name": "doc"}, label_field="doc", total_label="All"),
		]
		rows = self._data()
		saved = frappe.db.get_single_value("System Settings", "rounding_method")
		self.addCleanup(frappe.db.set_single_value, "System Settings", "rounding_method", saved)
		self.addCleanup(frappe.clear_cache)
		for method in ("Banker's Rounding (legacy)", "Banker's Rounding", "Commercial Rounding"):
			frappe.db.set_single_value("System Settings", "rounding_method", method)
			frappe.clear_cache()
			for kw in cases:
				self.assertEqual(engine.compose(rows, measures=measures, **kw), _old_compose(rows, measures=measures, **kw), (method, kw))
		self.assertEqual(engine.compose([], ["a"], measures), _old_compose([], ["a"], measures))

	def test_system_settings_read_once_per_compose(self):
		rows = self._data(200)
		measures = [{"field": "amount", "precision": 2}, {"field": "qty", "precision": 2}]
		with patch("frappe.get_system_settings", wraps=frappe.get_system_settings) as spy:
			engine.compose(rows, ["a", "b"], measures)
		self.assertLessEqual(spy.call_count, 1)
