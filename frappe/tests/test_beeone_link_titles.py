# beeone: T-886 - a Link never shows an opaque record code (hash, autoincrement, UUID).

import json
from unittest.mock import patch

import frappe
from frappe.boot import get_link_title_doctypes
from frappe.core.doctype.doctype.test_doctype import new_doctype
from frappe.desk import link_title
from frappe.desk.form.load import getdoc
from frappe.desk.listview import get_group_by_count
from frappe.desk.search import build_for_autosuggest, search_link, search_widget
from frappe.tests import IntegrationTestCase

PREFIX = "T886 "
CATALOG_A = PREFIX + "Catalog A"
CATALOG_B = PREFIX + "Catalog B"
CATALOG_UUID = PREFIX + "Catalog Uuid"
CATALOG_AUTOINC = PREFIX + "Catalog Autoinc"
CATALOG_CODE = PREFIX + "Catalog Code"
NO_TITLE_FIELD = PREFIX + "No Title Field"
SEARCH_ONLY = PREFIX + "Search Only"
REQD_ONLY = PREFIX + "Reqd Only"
NOTHING = PREFIX + "Nothing"
WITH_LINK = PREFIX + "With Link"
CHILD = PREFIX + "Child"
PARENT = PREFIX + "Parent"
OTHER_USER = "t886-noroles@example.com"


def make(name, fields=None, **kwargs):
	kwargs.setdefault("autoname", "hash")
	doc = new_doctype(name, fields=fields or [], **kwargs)
	doc.insert()
	return doc


def remove_all():
	frappe.set_user("Administrator")
	for dt in frappe.get_all(
		"DocType", filters={"name": ["like", f"{PREFIX}%"]}, order_by="creation desc", pluck="name"
	):
		frappe.delete_doc("DocType", dt, force=1, ignore_missing=True)
	for table in frappe.db.get_tables():
		if table.startswith(f"tab{PREFIX}"):
			frappe.db.sql_ddl(f"drop table if exists `{table}`")
	frappe.db.commit()
	frappe.clear_cache()


def name_field(**extra):
	return {"fieldname": "thing_name", "fieldtype": "Data", "label": "Thing Name", **extra}


class TestBeeoneLinkTitles(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		remove_all()
		make(CATALOG_A, [name_field(reqd=1)], title_field="thing_name")
		make(CATALOG_B, [name_field(reqd=1)], title_field="thing_name", show_title_field_in_link=0)
		make(CATALOG_UUID, [name_field()], autoname="UUID", title_field="thing_name")
		make(CATALOG_AUTOINC, [name_field()], autoname="autoincrement", title_field="thing_name")
		make(CATALOG_CODE, [{"fieldname": "code", "fieldtype": "Data", "unique": 1}], autoname="field:code", title_field="code")
		make(NO_TITLE_FIELD, [name_field()])
		make(
			SEARCH_ONLY,
			[{"fieldname": "alpha", "fieldtype": "Data"}, {"fieldname": "beta", "fieldtype": "Data"}],
			search_fields="beta",
		)
		make(
			REQD_ONLY,
			[{"fieldname": "alpha", "fieldtype": "Data"}, {"fieldname": "label_text", "fieldtype": "Data", "reqd": 1}],
		)
		make(
			NOTHING,
			[{"fieldname": "qty", "fieldtype": "Int"}, {"fieldname": "ref", "fieldtype": "Link", "options": CATALOG_A}],
		)
		make(
			CHILD,
			[
				{"fieldname": "link_a", "fieldtype": "Link", "options": CATALOG_A},
				{"fieldname": "link_b", "fieldtype": "Link", "options": CATALOG_B},
			],
			istable=1,
			autoname=None,
		)
		make(
			PARENT,
			[
				{"fieldname": "code", "fieldtype": "Data", "unique": 1},
				{"fieldname": "link_a", "fieldtype": "Link", "options": CATALOG_A},
				{"fieldname": "dyn_type", "fieldtype": "Link", "options": "DocType"},
				{"fieldname": "dyn", "fieldtype": "Dynamic Link", "options": "dyn_type"},
				{"fieldname": "rows", "fieldtype": "Table", "options": CHILD},
			],
			autoname="field:code",
		)
		make(
			WITH_LINK,
			[
				{"fieldname": "thing_name", "fieldtype": "Data", "reqd": 1},
				{"fieldname": "parent_a", "fieldtype": "Link", "options": CATALOG_A},
			],
			title_field="thing_name",
			search_fields="parent_a",
		)
		if not frappe.db.exists("User", OTHER_USER):
			frappe.get_doc(
				{"doctype": "User", "email": OTHER_USER, "first_name": "T886", "send_welcome_email": 0}
			).insert(ignore_permissions=True)
		frappe.db.commit()
		frappe.clear_cache()

	@classmethod
	def tearDownClass(cls):
		frappe.set_user("Administrator")
		frappe.delete_doc("User", OTHER_USER, force=1, ignore_missing=True)
		remove_all()
		super().tearDownClass()

	def setUp(self):
		frappe.set_user("Administrator")
		frappe.local.response = frappe._dict(docs=[])

	def tearDown(self):
		frappe.set_user("Administrator")

	def add(self, doctype, **values):
		return frappe.get_doc({"doctype": doctype, **values}).insert().name

	# 1. the meta rule

	def test_opaque_names_show_titles_without_the_app_flag(self):
		for dt in (CATALOG_A, CATALOG_B, CATALOG_UUID, CATALOG_AUTOINC):
			meta = frappe.get_meta(dt)
			self.assertEqual(meta.show_title_field_in_link, 1, dt)
			self.assertEqual(meta.opaque_name, 1, dt)
			self.assertEqual(meta.title_field, "thing_name", dt)

	def test_human_names_keep_the_app_setting(self):
		meta = frappe.get_meta(CATALOG_CODE)
		self.assertFalse(meta.opaque_name)
		self.assertFalse(meta.show_title_field_in_link)
		self.assertFalse(frappe.get_meta(CHILD).opaque_name)

	def test_property_setter_cannot_switch_the_rule_off(self):
		from frappe.custom.doctype.property_setter.property_setter import make_property_setter

		make_property_setter(CATALOG_A, None, "show_title_field_in_link", "0", "Check")
		frappe.clear_cache(doctype=CATALOG_A)
		self.assertEqual(frappe.get_meta(CATALOG_A).show_title_field_in_link, 1)
		frappe.db.delete("Property Setter", {"doc_type": CATALOG_A, "property": "show_title_field_in_link"})
		frappe.clear_cache(doctype=CATALOG_A)

	# 2. fallback title

	def test_fallback_title_field(self):
		meta = frappe.get_meta(NO_TITLE_FIELD)
		self.assertEqual(meta.title_field, "thing_name")
		self.assertEqual(meta.implicit_title_field, "thing_name")
		self.assertEqual(meta.show_title_field_in_link, 1)
		self.assertEqual(frappe.get_meta(SEARCH_ONLY).title_field, "beta")
		self.assertEqual(frappe.get_meta(REQD_ONLY).title_field, "label_text")

	def test_bare_name_only_when_nothing_else_exists(self):
		meta = frappe.get_meta(NOTHING)
		self.assertFalse(meta.title_field)
		self.assertFalse(meta.show_title_field_in_link)
		self.assertIsNone(link_title.get_link_title_field(NOTHING))

	def test_fallback_title_is_shown_in_forms(self):
		name = self.add(NO_TITLE_FIELD, thing_name="Fallback one")
		doc = self.add(PARENT, code="P-FB", link_a=self.add(CATALOG_A, thing_name="A fb"))
		getdoc(PARENT, doc)
		self.assertIn(f"{CATALOG_A}::{frappe.db.get_value(PARENT, doc, 'link_a')}", frappe.local.response["_link_titles"])
		self.assertEqual(link_title.get_titles_by_doctype({NO_TITLE_FIELD: {name}}), {f"{NO_TITLE_FIELD}::{name}": "Fallback one"})

	# 3. boot list

	def test_boot_list_has_implicit_doctypes_and_is_rebuilt(self):
		titled = get_link_title_doctypes()
		for dt in (CATALOG_A, CATALOG_B, CATALOG_UUID, CATALOG_AUTOINC, NO_TITLE_FIELD):
			self.assertIn(dt, titled)
		for dt in (CATALOG_CODE, NOTHING, CHILD):
			self.assertNotIn(dt, titled)

		self.assertIn(CATALOG_A, frappe.cache.get_value("link_title_doctypes"))
		frappe.clear_cache(doctype=CATALOG_A)
		self.assertIsNone(frappe.cache.get_value("link_title_doctypes"))
		self.assertIn(CATALOG_A, get_link_title_doctypes())

	# 4. getdoc is batched

	def make_parent(self, code):
		a = [self.add(CATALOG_A, thing_name=f"A {code} {i}") for i in range(3)]
		b = [self.add(CATALOG_B, thing_name=f"B {code} {i}") for i in range(2)]
		rows = [{"link_a": a[i % 3], "link_b": b[i % 2]} for i in range(50)]
		parent = self.add(PARENT, code=code, link_a=a[0], rows=rows)
		return parent, a, b

	def test_getdoc_sends_all_titles_with_one_query_per_doctype(self):
		parent, a, b = self.make_parent("P-BATCH")
		with patch.object(link_title, "get_link_titles", wraps=link_title.get_link_titles) as batch:
			getdoc(PARENT, parent)
		titles = frappe.local.response["_link_titles"]
		for name in a:
			self.assertEqual(titles[f"{CATALOG_A}::{name}"], frappe.db.get_value(CATALOG_A, name, "thing_name"))
		for name in b:
			self.assertEqual(titles[f"{CATALOG_B}::{name}"], frappe.db.get_value(CATALOG_B, name, "thing_name"))
		self.assertEqual(sorted(call.args[0] for call in batch.call_args_list), sorted([CATALOG_A, CATALOG_B]))

	def test_dynamic_link_value_is_titled(self):
		target = self.add(CATALOG_A, thing_name="Dynamic target")
		parent = self.add(PARENT, code="P-DYN", dyn_type=CATALOG_A, dyn=target)
		getdoc(PARENT, parent)
		self.assertEqual(frappe.local.response["_link_titles"][f"{CATALOG_A}::{target}"], "Dynamic target")

	# 5. permissions

	def test_titles_need_read_permission(self):
		name = self.add(CATALOG_A, thing_name="Hidden")
		parent = self.add(PARENT, code="P-PERM", link_a=name)
		self.assertIn(f"{CATALOG_A}::{name}", link_title.get_titles_by_doctype({CATALOG_A: {name}}))

		frappe.set_user(OTHER_USER)
		self.assertIsNone(link_title.get_link_title_field(CATALOG_A))
		self.assertEqual(link_title.get_titles_by_doctype({CATALOG_A: {name}}), {})
		self.assertEqual(link_title.get_titles({CATALOG_A: [name]}), {})
		self.assertTrue(parent)

	# 6. dropdown

	def test_dropdown_does_not_repeat_the_code(self):
		name = self.add(CATALOG_A, thing_name="Dropdown thing")
		rows = search_link(CATALOG_A, "Dropdown")
		row = next(r for r in rows if r["value"] == name)
		self.assertEqual(row["label"], "Dropdown thing")
		self.assertNotIn(name, row["description"])

	def test_dropdown_with_custom_query_still_shows_titles(self):
		name = self.add(CATALOG_A, thing_name="Custom query thing")
		rows = build_for_autosuggest([(name,)], CATALOG_A, custom_query=True)
		self.assertEqual(rows[0]["label"], "Custom query thing")
		self.assertNotIn(name, rows[0]["description"])
		rows = build_for_autosuggest([(name, "extra info")], CATALOG_A, custom_query=True)
		self.assertEqual(rows[0]["label"], "Custom query thing")
		self.assertEqual(rows[0]["description"], "extra info")

	def test_dropdown_shows_titles_of_link_search_fields(self):
		catalog = self.add(CATALOG_A, thing_name="Search field title")
		name = self.add(WITH_LINK, thing_name="With search link", parent_a=catalog)
		row = next(r for r in search_link(WITH_LINK, "With search link") if r["value"] == name)
		self.assertEqual(row["label"], "With search link")
		self.assertIn("Search field title", row["description"])
		self.assertNotIn(catalog, row["description"])
		self.assertNotIn(name, row["description"])

	# 7. picker and get_titles

	def test_picker_rows_send_titles_for_link_columns(self):
		catalog = self.add(CATALOG_A, thing_name="Picker catalog")
		self.add(WITH_LINK, thing_name="Picker row", parent_a=catalog)
		rows = search_widget(WITH_LINK, "Picker row", as_dict=True)
		self.assertEqual(rows[0]["label"], "Picker row")
		self.assertEqual(frappe.local.response["_link_titles"][f"{CATALOG_A}::{catalog}"], "Picker catalog")

	def test_get_titles_is_batched_ignores_unknown_and_is_capped(self):
		a = self.add(CATALOG_A, thing_name="T one")
		b = self.add(CATALOG_B, thing_name="T two")
		with patch.object(frappe, "get_list", wraps=frappe.get_list) as get_list:
			titles = link_title.get_titles(json.dumps({CATALOG_A: [a, a], CATALOG_B: [b], "No Such DocType": ["x"], CATALOG_CODE: [1]}))
		self.assertEqual(titles, {f"{CATALOG_A}::{a}": "T one", f"{CATALOG_B}::{b}": "T two"})
		self.assertEqual(
			[c.args[0] for c in get_list.call_args_list if c.args[0].startswith(PREFIX)],
			[CATALOG_A, CATALOG_B],
		)
		self.assertEqual(frappe.local.response["_link_titles"], titles)

		names = [f"missing-{i}" for i in range(link_title.MAX_TITLE_REQUEST + 10)]
		with patch.object(link_title, "get_titles_by_doctype", return_value={}) as lookup:
			link_title.get_titles({CATALOG_A: names})
		self.assertEqual(len(lookup.call_args.args[0][CATALOG_A]), link_title.MAX_TITLE_REQUEST)

	# 8. other server paths

	def test_report_columns_get_titles_including_dynamic_links(self):
		a = self.add(CATALOG_A, thing_name="Report A")
		columns = [
			{"fieldname": "link_a", "fieldtype": "Link", "options": CATALOG_A},
			{"fieldname": "dyn", "fieldtype": "Dynamic Link", "options": "dyn_type"},
		]
		rows = [{"link_a": a, "dyn": a, "dyn_type": CATALOG_A}]
		self.assertEqual(link_title.get_report_link_titles(columns, rows), {f"{CATALOG_A}::{a}": "Report A"})

	def test_reportview_returns_titles(self):
		a = self.add(CATALOG_A, thing_name="Reportview A")
		self.add(PARENT, code="P-RV", link_a=a)
		frappe.form_dict.update(
			{"doctype": PARENT, "fields": json.dumps(["name", "link_a"]), "with_link_titles": 1}
		)
		try:
			frappe.call("frappe.desk.reportview.get")
		finally:
			for key in ("doctype", "fields", "with_link_titles"):
				frappe.form_dict.pop(key, None)
		self.assertEqual(frappe.local.response["_link_titles"][f"{CATALOG_A}::{a}"], "Reportview A")

	def test_group_by_count_uses_one_title_query(self):
		a = [self.add(CATALOG_A, thing_name=f"Group {i}") for i in range(3)]
		for i, name in enumerate(a):
			self.add(PARENT, code=f"P-GRP{i}", link_a=name)
		with patch.object(link_title, "get_link_titles", wraps=link_title.get_link_titles) as batch:
			data = get_group_by_count(PARENT, "[]", "link_a")
		self.assertEqual(batch.call_count, 1)
		self.assertEqual({d.name: d.title for d in data if d.name in a}, {name: f"Group {i}" for i, name in enumerate(a)})

	# 9. customize form

	def test_customize_form_does_not_store_the_implicit_values(self):
		from frappe.custom.doctype.customize_form.customize_form import CustomizeForm

		form = frappe.get_doc("Customize Form")
		form.doc_type = "ToDo"  # standard, hash name
		self.assertEqual(frappe.get_meta("ToDo").show_title_field_in_link, 1)
		form.fetch_to_customize()
		form.save_customization()
		self.assertFalse(
			frappe.db.exists(
				"Property Setter",
				{"doc_type": "ToDo", "property": ["in", ["title_field", "show_title_field_in_link"]]},
			)
		)
		self.assertIsInstance(form, CustomizeForm)
