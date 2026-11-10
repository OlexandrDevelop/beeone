import frappe


def execute():
	"""Add the indexes PostgreSQL tables lacked compared to MariaDB.

	- `parent` of every table with such a column (child table rows are always read by parent)
	- `creation` (and `modified` for doctypes sorted by it) of document tables
	- `search_index` of fields (index names collided between tables, the later tables got nothing)

	Existing indexes are recognised by their column and not by their name (so manual `*_parent_idx`
	indexes are kept), a second run changes nothing. Unique indexes are not added here, as existing
	data may violate them.
	"""
	if frappe.db.db_type != "postgres":
		return

	db = frappe.db
	created = 0

	def add(table, column, suffix, exists):
		nonlocal created
		if exists:
			return
		db.create_index_concurrently(table, [column], db.make_index_name(table, suffix))
		created += 1

	tables = db.sql(
		"""
		SELECT c.table_name
		FROM information_schema.columns c
		JOIN information_schema.tables t
			ON t.table_schema = c.table_schema AND t.table_name = c.table_name
		WHERE c.table_schema = %s AND c.column_name = 'parent' AND t.table_type = 'BASE TABLE'
		ORDER BY c.table_name
		""",
		db.db_schema,
		pluck=True,
	)
	for table in tables:
		add(table, "parent", "parent_idx", db.has_leading_index(table, "parent"))

	for doctype in frappe.get_all("DocType", filters={"issingle": 0, "is_virtual": 0}, pluck="name"):
		table = f"tab{doctype}"
		if not db.table_exists(doctype):
			continue

		meta = frappe.get_meta(doctype)
		if not meta.istable:
			add(table, "creation", "creation_idx", db.get_column_index(table, "creation"))
			if meta.sort_field == "modified":
				add(table, "modified", "modified_idx", db.get_column_index(table, "modified"))

		columns = set(db.get_db_table_columns(table))
		for field in meta.fields:
			if (
				field.search_index
				and field.fieldname in columns
				and field.fieldtype in db.type_map
				and db.type_map[field.fieldtype][0] not in ("text", "longtext")
			):
				add(
					table,
					field.fieldname,
					f"{field.fieldname}_index",
					db.get_column_index(table, field.fieldname) or db.get_column_index(table, field.fieldname, True),
				)

	if created:
		print(f"Added {created} missing indexes")
