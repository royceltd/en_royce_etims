# Copyright (c) 2026, Royce Technologies LTD and contributors
# For license information, please see license.txt

from frappe import _
from frappe.model.document import Document

from royce_etims.utils.validation import validate_kra_pin


class eTIMSSettings(Document):
	def validate(self):
		validate_kra_pin(self.tin, label=_("TIN"))
