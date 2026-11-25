# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

from frappe.model.document import Document


class AIAssistantSettings(Document):
	def validate(self):
		self.model = (self.model or "").strip()
		self.base_url = (self.base_url or "").strip().rstrip("/")
		if self.max_steps is not None and self.max_steps < 1:
			self.max_steps = 1
