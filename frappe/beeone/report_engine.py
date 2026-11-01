# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

"""Report composition engine: groupings, totals and drill-down over plain rows.

The engine does not read the database. A report reads its rows (through the query API, e.g.
`frappe.beeone.accounting_query`, or any other reader) and gives them here with a description:

	groupings  fields to group by, outermost first. A grouping is a field name or a dict
	           {"field", "label": callable(value) -> str, "order": "asc" | "desc" | "none"}.
	measures   numbers to total. A measure is {"field", "agg", "precision", "key"}; `agg` is one of
	           sum, count, count_distinct, min, max (default sum); `key` is the name in the result (default `field`).
	drill      optional {"doctype": field, "name": field}: a detail row opens that document.

compose() returns a flat list of rows in display order:

	{"id", "parent", "level", "kind": group | item | total, "label", "values": {key: number},
	 "drill": {"filters": {field: value, ...}} for groups, {"doctype", "name"} for details, or None}

Group rows carry the totals of their rows, the last row is the grand total (`kind` total). With no
groupings only detail rows (when `detail`) and the grand total are given. Totals are computed from the
rows and rounded once at the end, so a total never differs from the sum of the unrounded rows.
"""

from frappe.utils import flt

AGGREGATES = ("sum", "count", "count_distinct", "min", "max")


def _norm_grouping(grouping):
	if isinstance(grouping, str):
		grouping = {"field": grouping}
	g = {"label": None, "order": "asc", **grouping}
	if g["order"] not in ("asc", "desc", "none"):
		raise ValueError(f"Unknown order {g['order']}")
	return g


def _norm_measure(measure):
	if isinstance(measure, str):
		measure = {"field": measure}
	m = {"agg": "sum", "precision": None, "key": measure["field"], **measure}
	if m["agg"] not in AGGREGATES:
		raise ValueError(f"Unknown aggregate {m['agg']}")
	return m


class _Acc:
	"""Running totals of one node."""

	def __init__(self, measures):
		self.measures = measures
		self.state = [self._start(m) for m in measures]

	@staticmethod
	def _start(m):
		return set() if m["agg"] == "count_distinct" else (0 if m["agg"] in ("sum", "count") else None)

	def add(self, row):
		for i, m in enumerate(self.measures):
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
		for m, v in zip(self.measures, self.state):
			if m["agg"] == "count_distinct":
				v = len(v)
			elif m["agg"] == "sum" and m["precision"] is not None:
				v = flt(v, m["precision"])
			out[m["key"]] = v
		return out


def _sorted_keys(keys, g):
	if g["order"] == "none":
		return keys
	# the empty group stays last in both directions
	present = sorted((k for k in keys if k is not None), reverse=g["order"] == "desc")
	return present + [k for k in keys if k is None]


def compose(rows, groupings=(), measures=(), detail=True, drill=None, label_field=None, total_label=""):
	"""Build the grouped rows with subtotals and the grand total. See the module docstring."""
	groupings = [_norm_grouping(g) for g in groupings]
	measures = [_norm_measure(m) for m in measures]
	rows = list(rows)
	out = []
	grand = _Acc(measures)
	for row in rows:
		grand.add(row)

	def emit(rows_, depth, parent, filters):
		if depth == len(groupings):
			if not detail:
				return
			for i, row in enumerate(rows_):
				acc = _Acc(measures)
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
		for key in _sorted_keys(list(buckets), g):
			part = buckets[key]
			acc = _Acc(measures)
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


def drill_rows(rows, filters):
	"""The rows a group row opens: those whose fields equal every value of `filters` (the `drill` of a group)."""
	return [r for r in rows if all(r.get(k) == v for k, v in (filters or {}).items())]
