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

import frappe
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


def _start(m):
	return set() if m["agg"] == "count_distinct" else (0 if m["agg"] in ("sum", "count") else None)


def _prepare(row, measures):
	"""The values a row adds to every node it belongs to, converted once per row."""
	return [flt(row.get(m["field"])) if m["agg"] == "sum" else row.get(m["field"]) for m in measures]


def _add(state, measures, vals):
	for i, m in enumerate(measures):
		agg, value = m["agg"], vals[i]
		if agg == "sum":
			state[i] += value
		elif agg == "count":
			state[i] += 1
		elif agg == "count_distinct":
			if value is not None:
				state[i].add(value)
		elif value is not None:
			cur = state[i]
			if cur is None or (value < cur if agg == "min" else value > cur):
				state[i] = value


class _Rounding:
	"""The rounding method, read from the system settings once and only when a total is rounded."""

	method = None

	def get(self):
		if self.method is None:
			self.method = frappe.get_system_settings("rounding_method") or "Banker's Rounding (legacy)"
		return self.method


def _values(measures, state, rounding):
	out = {}
	for m, v in zip(measures, state):
		if m["agg"] == "count_distinct":
			v = len(v)
		elif m["agg"] == "sum" and m["precision"] is not None:
			v = flt(v, m["precision"], rounding.get())
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
	rounding = _Rounding()
	depth_max = len(groupings)
	new_state = lambda: [_start(m) for m in measures]  # noqa: E731

	# one pass: a row is converted once and added to the grand total and to every ancestor group;
	# a node is [state, children by key (insertion order), rows of the deepest level]
	grand = new_state()
	root = [None, {}, []]
	for row in rows:
		vals = _prepare(row, measures)
		_add(grand, measures, vals)
		node = root
		for g in groupings:
			key = row.get(g["field"])
			child = node[1].get(key)
			if child is None:
				child = node[1][key] = [new_state(), {}, []]
			_add(child[0], measures, vals)
			node = child
		if detail:
			node[2].append((row, vals))

	out = []

	def emit(node, depth, parent, filters):
		if depth == depth_max:
			for i, (row, vals) in enumerate(node[2]):
				state = new_state()
				_add(state, measures, vals)
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
						"values": _values(measures, state, rounding),
						"drill": target,
					}
				)
			return
		g = groupings[depth]
		for key in _sorted_keys(list(node[1]), g):
			child = node[1][key]
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
					"values": _values(measures, child[0], rounding),
					"drill": {"filters": node_filters},
				}
			)
			emit(child, depth + 1, node_id, node_filters)

	emit(root, 0, None, {})
	out.append(
		{
			"id": "total",
			"parent": None,
			"level": 0,
			"kind": "total",
			"label": total_label,
			"values": _values(measures, grand, rounding),
			"drill": None,
		}
	)
	return out


def drill_rows(rows, filters):
	"""The rows a group row opens: those whose fields equal every value of `filters` (the `drill` of a group)."""
	return [r for r in rows if all(r.get(k) == v for k, v in (filters or {}).items())]
