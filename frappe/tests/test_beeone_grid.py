# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

"""Table-part grids never page their rows (T-890): static rules of the core files and the inert grid_page_length."""

import re
from pathlib import Path

import frappe
from frappe.custom.doctype.property_setter.property_setter import make_property_setter
from frappe.tests import IntegrationTestCase

PAGER_NAMES = ("grid_pagination", "change_page_if_reqd", "go_to_last_page_to_add_row", "grid-pagination")


class TestBeeoneGrid(IntegrationTestCase):
	def setUp(self):
		self.public = Path(frappe.get_app_path("frappe")) / "public"

	def test_pager_file_is_gone_and_no_script_names_it(self):
		self.assertFalse((self.public / "js" / "frappe" / "form" / "grid_pagination.js").exists())
		roots = [self.public / "js", Path(frappe.get_app_path("frappe")) / "core", Path(frappe.get_app_path("frappe")) / "custom"]
		for root in roots:
			for path in list(root.rglob("*.js")) + list(root.rglob("*.html")):
				text = path.read_text(encoding="utf-8")
				for name in PAGER_NAMES:
					self.assertNotIn(name, text, f"{name} in {path}")

	def test_grid_has_no_pager_markup_or_style(self):
		js = (self.public / "js" / "frappe" / "form" / "grid.js").read_text()
		self.assertNotIn("grid-pagination", js)
		self.assertNotIn("page_index", js)
		self.assertNotIn("page_length", js)
		scss = (self.public / "scss" / "common" / "grid.scss").read_text()
		for name in (".grid-pagination", ".current-page-number", ".page-text"):
			self.assertNotIn(name, scss)

	def test_render_walks_every_row(self):
		js = (self.public / "js" / "frappe" / "form" / "grid.js").read_text()
		body = js[js.index("render_result_rows($rows) {") :][:3600]
		self.assertIn("for (let ri = 0; ri < result_length; ri++)", body)
		self.assertNotRegex(body, r"delete this\._?grid_rows\[")

	def test_a_big_table_is_built_in_chunks_but_every_reader_gets_all_rows(self):
		js = (self.public / "js" / "frappe" / "form" / "grid.js").read_text()
		# grid_rows is a getter that first builds the pending tail; only the renderer reads the raw array
		self.assertIn("get grid_rows() {\n\t\tthis.render_pending_rows();", js)
		self.assertIn("get grid_rows_by_docname() {\n\t\tthis.render_pending_rows();", js)
		self.assertIn("render_pending_rows(PENDING_CHUNK)", js)
		layout = (self.public / "js" / "frappe" / "form" / "layout.js").read_text()
		self.assertIn("f.grid?.built_rows", layout)

	def test_rows_off_screen_are_not_laid_out(self):
		scss = (self.public / "scss" / "common" / "grid.scss").read_text()
		block = scss[scss.index(".grid-body .rows > .grid-row:not(.grid-row-open)") :][:200]
		self.assertIn("content-visibility: auto", block)
		# an edited row keeps its popups (link suggestions)
		self.assertIn(":not(:has(.editable-row))", block)

	def test_add_row_has_no_page_arguments(self):
		js = (self.public / "js" / "frappe" / "form" / "grid.js").read_text()
		self.assertIn("add_new_row(idx, callback, show, copy_doc) {", js)
		self.assertIsNone(re.search(r"go_to_(first|last)_page", js))

	def test_grid_page_length_is_hidden_and_inert(self):
		for doctype in ("DocType", "Customize Form"):
			df = frappe.get_meta(doctype).get_field("grid_page_length")
			self.assertEqual(df.hidden, 1, doctype)

	def test_property_setter_for_grid_page_length_still_saves(self):
		make_property_setter("Contact Phone", None, "grid_page_length", "20", "Int", for_doctype=True)
		self.assertEqual(frappe.get_meta("Contact Phone", cached=False).grid_page_length, 20)
		frappe.db.rollback()
		frappe.clear_cache(doctype="Contact Phone")
