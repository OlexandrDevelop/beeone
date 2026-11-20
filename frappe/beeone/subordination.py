# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

"""Subordination tree: documents that are bases and documents made from them.

get_related(doc) finds:
- Basis documents: linked through Link fields of the document's DocType
- Derived documents: documents of other types that link to this one
Every document is checked for read permission.
"""

import frappe


def get_related(doc):
	"""Find documents this one is based on and documents made from it.

	Args:
		doc: a Frappe document instance

	Returns:
		list of dicts: {doctype, name, role, posting_date, docstatus}
		role is "basis" for documents this one is based on, "derived" for documents made from this one
	"""
	found = []
	meta = frappe.get_meta(doc.doctype)

	# Get the list of supported document types from apps
	supported_types = _get_supported_doctypes()

	# Find basis documents: Link and Dynamic Link fields pointing to other documents
	for df in meta.fields:
		linked_doctype = None
		linked_name = None

		# Handle Link fields
		if df.fieldtype == "Link" and df.options in supported_types and doc.get(df.fieldname):
			linked_doctype = df.options
			linked_name = doc.get(df.fieldname)

		# Handle Dynamic Link fields (fieldname: basis_type, options_field: basis)
		elif df.fieldtype == "Dynamic Link" and doc.get(df.fieldname):
			linked_doctype = doc.get(df.options)
			linked_name = doc.get(df.fieldname)
			if linked_doctype not in supported_types:
				linked_doctype = None

		if linked_doctype and linked_name and frappe.has_permission(linked_doctype, "read", linked_name):
			# Exclude amended_from relationship
			if df.fieldname == "amended_from":
				continue
			found.append({
				"doctype": linked_doctype,
				"name": linked_name,
				"role": "basis"
			})

	# Find derived documents: other document types with Link fields pointing to this doc
	for other_doctype in supported_types:
		if other_doctype == doc.doctype:
			continue
		# beeone: stale app hook entries must not break the host form; skip DocTypes that do not exist.
		if not frappe.db.exists("DocType", other_doctype):
			continue
		if not frappe.has_permission(other_doctype, "read"):
			continue

		other_meta = frappe.get_meta(other_doctype)
		for df in other_meta.fields:
			# Handle regular Link fields
			if df.fieldtype == "Link" and df.options == doc.doctype and df.fieldname != "amended_from":
				# Find all documents of this type that link to the current document
				for row in frappe.get_list(
					other_doctype,
					filters={df.fieldname: doc.name, "docstatus": ("<", 2)},
					fields=["name"],
					limit=5
				):
					found.append({
						"doctype": other_doctype,
						"name": row.name,
						"role": "derived"
					})

			# Handle Dynamic Link fields (check if options field contains our doctype)
			elif df.fieldtype == "Dynamic Link":
				# For Dynamic Link, we need to find docs where:
				# df.fieldname = current doc.name AND df.options = current doc.doctype
				for row in frappe.get_list(
					other_doctype,
					filters={df.fieldname: doc.name, df.options: doc.doctype, "docstatus": ("<", 2)},
					fields=["name"],
					limit=5
				):
					found.append({
						"doctype": other_doctype,
						"name": row.name,
						"role": "derived"
					})

	# Get posting_date and docstatus for each document (batch by doctype)
	if found:
		by_doctype = {}
		for r in found:
			if r["doctype"] not in by_doctype:
				by_doctype[r["doctype"]] = []
			by_doctype[r["doctype"]].append(r["name"])

		for doctype, names in by_doctype.items():
			rows = frappe.db.get_list(
				doctype,
				filters={"name": ["in", names]},
				fields=["name", "posting_date", "docstatus"]
			)
			rows_by_name = {row["name"]: row for row in rows}
			for r in found:
				if r["doctype"] == doctype:
					row = rows_by_name.get(r["name"], {})
					r["posting_date"] = str(row.get("posting_date") or "")
					r["docstatus"] = row.get("docstatus")

	return found


def _get_supported_doctypes():
	"""Get the list of document types that support subordination from app hooks."""
	doctypes = set()
	for doctypes_list in frappe.get_hooks("beeone_documents") or []:
		if isinstance(doctypes_list, list):
			doctypes.update(doctypes_list)
		else:
			doctypes.add(doctypes_list)
	return doctypes


# ---------------------------------------------------------------- the structure (user 2026-11-20: like 1C)

STRUCTURE_LIMIT = 300
DEPTH_LIMIT = 12
AMOUNT_FIELDS = ("document_amount", "grand_total", "total_amount", "amount", "total")


def structure_doctypes() -> set[str]:
	"""The documents of the structure: the `beeone_documents` hook or, without it, the submittable DocTypes of the
	apps that use the platform form template (`beeone_form_apps`)."""
	doctypes = _get_supported_doctypes()
	if doctypes:
		return {dt for dt in doctypes if frappe.db.exists("DocType", dt)}
	apps = set(frappe.get_hooks("beeone_form_apps") or [])
	if not apps:
		return set()
	modules = {
		m.name for m in frappe.get_all("Module Def", fields=["name", "app_name"]) if m.app_name in apps
	}
	return set(
		frappe.get_all(
			"DocType",
			filters={"is_submittable": 1, "istable": 0, "module": ["in", list(modules) or [""]]},
			pluck="name",
		)
	)


def _link_index(doctypes: set[str]) -> dict:
	"""For every document DocType: the fields (of the header or of a table part) that point to other documents.

	{source: [(target or None for Dynamic Link, child DocType or None, fieldname, options field)]}"""
	cache_key = "beeone:subordination_index"
	cached = frappe.cache.get_value(cache_key)
	if cached and cached.get("doctypes") == sorted(doctypes) and not frappe.conf.developer_mode:
		return cached["index"]
	index = {}
	for source in doctypes:
		meta = frappe.get_meta(source)
		entries = []
		tables = [(None, meta)] + [
			(df.options, frappe.get_meta(df.options)) for df in meta.get_table_fields() if df.options
		]
		for child, m in tables:
			for df in m.fields:
				if df.fieldname == "amended_from":
					continue
				if df.fieldtype == "Link" and df.options in doctypes:
					entries.append((df.options, child, df.fieldname, None))
				elif df.fieldtype == "Dynamic Link" and df.options:
					entries.append((None, child, df.fieldname, df.options))
		index[source] = entries
	frappe.cache.set_value(cache_key, {"doctypes": sorted(doctypes), "index": index}, expires_in_sec=3600)
	return index


def _bases(doctype, name, index, doctypes) -> list[tuple[str, str]]:
	"""Documents the document was made from (its header and table part links)."""
	out = []
	entries = index.get(doctype) or []
	if not entries:
		return out
	doc = frappe.get_doc(doctype, name)
	for target, child, fieldname, options in entries:
		rows = [doc] if not child else [r for df in doc.meta.get_table_fields() if df.options == child for r in doc.get(df.fieldname) or []]
		for row in rows:
			value = row.get(fieldname)
			dt = target or (row.get(options) if options else None)
			if value and dt in doctypes and (dt, value) != (doctype, name):
				out.append((dt, value))
	return list(dict.fromkeys(out))


def _derived(doctype, name, index) -> list[tuple[str, str]]:
	"""Documents made from the document: documents whose header or table part points to it."""
	out = []
	for source, entries in index.items():
		if not frappe.has_permission(source, "read"):
			continue
		for target, child, fieldname, options in entries:
			if target not in (doctype, None):
				continue
			filters = {fieldname: name}
			if options:
				filters[options] = doctype
			if child:
				parents = frappe.get_all(child, filters={**filters, "parenttype": source}, pluck="parent", limit=100)
				names = frappe.get_all(source, filters={"name": ["in", list(set(parents))]}, pluck="name") if parents else []
			else:
				names = frappe.get_list(source, filters=filters, pluck="name", limit=100)
			out.extend((source, n) for n in names if (source, n) != (doctype, name))
	return list(dict.fromkeys(out))


def get_structure(doc) -> dict:
	"""The subordination structure of a document like in 1C: from the root basis document down to every document
	made from it, the current one marked. Nodes the user cannot read are left out."""
	doctypes = structure_doctypes() | {doc.doctype}
	index = _link_index(doctypes)

	# up: the chain of bases to the root (the first basis at each level)
	root = (doc.doctype, doc.name)
	seen_up = {root}
	for _ in range(DEPTH_LIMIT):
		bases = [b for b in _bases(*root, index, doctypes) if frappe.has_permission(b[0], "read", b[1])]
		bases = [b for b in bases if b not in seen_up]
		if not bases:
			break
		root = bases[0]
		seen_up.add(root)

	# down: every document made from the root, breadth first
	nodes, children, seen = {}, {}, {root}
	queue = [(root, 0)]
	while queue and len(seen) < STRUCTURE_LIMIT:
		key, depth = queue.pop(0)
		children[key] = []
		if depth >= DEPTH_LIMIT:
			continue
		for child in _derived(*key, index):
			if child in seen or not frappe.has_permission(child[0], "read", child[1]):
				continue
			seen.add(child)
			children[key].append(child)
			queue.append((child, depth + 1))
	current = (doc.doctype, doc.name)
	if current not in seen:
		# the current document hangs under one of its bases that the walk down did not reach (a cycle, a limit)
		seen.add(current)
		children.setdefault(root, []).append(current)
		children.setdefault(current, [])

	# the data of the nodes, one query per DocType
	by_doctype = {}
	for dt, name in seen:
		by_doctype.setdefault(dt, []).append(name)
	for dt, names in by_doctype.items():
		meta = frappe.get_meta(dt)
		fields = ["name", "docstatus"]
		for f in ("posting_date", "posting_time", "deletion_mark", "currency"):
			if meta.has_field(f):
				fields.append(f)
		amount = next((f for f in AMOUNT_FIELDS if meta.has_field(f)), None)
		if amount:
			fields.append(amount)
		if meta.title_field and meta.title_field not in fields and meta.has_field(meta.title_field):
			fields.append(meta.title_field)
		for row in frappe.get_all(dt, filters={"name": ["in", names]}, fields=fields):
			nodes[(dt, row.name)] = {
				"doctype": dt,
				"name": row.name,
				"docstatus": row.docstatus,
				"posting_date": str(row.get("posting_date") or ""),
				"posting_time": str(row.get("posting_time") or "").split(".")[0],
				"deletion_mark": row.get("deletion_mark") or 0,
				"amount": row.get(amount) if amount else None,
				"currency": row.get("currency") or "",
				"current": (dt, row.name) == current,
			}

	def build(key):
		node = nodes.get(key)
		if not node:
			return None
		items = [build(c) for c in sorted(children.get(key, []), key=lambda c: (nodes.get(c, {}).get("posting_date", ""), c))]
		node = dict(node)
		node["children"] = [i for i in items if i]
		return node

	return {"root": build(root), "truncated": len(seen) >= STRUCTURE_LIMIT}
