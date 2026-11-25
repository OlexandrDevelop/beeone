# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

from frappe.model.document import Document


class BeeOneAccount(Document):
	def validate(self):
		self.server_url = (self.server_url or "").strip().rstrip("/") or None
		# a new key: the rights of the old one no longer apply until the next check
		if not self.flags.get("from_check") and self.has_value_changed("installation_key"):
			self.update({"entitlements": None, "signature": None, "state": "Not Connected", "features": None, "valid_until": None, "instance_id": None})
