# Copyright (c) 2026, Royce Technologies LTD and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from royce_etims.utils.api_client import generate_token
from royce_etims.utils.validation import validate_kra_pin


class eTIMSSettings(Document):
	def validate(self):
		validate_kra_pin(self.tin, label=_("TIN"))

	@frappe.whitelist()
	def test_connection(self):
		"""Fetch a fresh token to prove the Apigee credentials are valid.

		Deliberately doesn't touch `status` - going Active is a separate, explicit
		step in the onboarding flow (see docs/architecture.md), not a side effect
		of a successful credentials test.
		"""
		generate_token(self)
		return {"success": True, "message": _("Connected to eTIMS ({0}) successfully.").format(self.environment)}
