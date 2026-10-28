# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

from frappe.model.document import Document
from frappe.beeone.catalog_meta import validate_catalog


class Catalog(Document):
	def before_insert(self):
		validate_catalog(self)

	def before_update(self):
		validate_catalog(self)
