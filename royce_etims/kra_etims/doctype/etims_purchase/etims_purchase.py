# Copyright (c) 2026, Royce Technologies LTD and contributors
# For license information, please see license.txt

from frappe.model.document import Document

from royce_etims.etims_sync.purchase import refresh_status


class eTIMSPurchase(Document):
	def validate(self):
		refresh_status(self)
