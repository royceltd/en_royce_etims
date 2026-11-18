# Copyright (c) 2026, Royce Technologies LTD and contributors
# For license information, please see license.txt

from frappe.model.document import Document

from royce_etims.etims_sync.branch_info import validate_branch_user


class eTIMSBranchUser(Document):
	def validate(self):
		validate_branch_user(self)
