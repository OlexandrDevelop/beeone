export function get_grid_settings_key(child_doctype, table_fieldname) {
	return `${child_doctype}::${table_fieldname || "table"}`;
}
