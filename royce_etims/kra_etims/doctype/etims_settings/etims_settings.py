# Copyright (c) 2026, Royce Technologies LTD and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from royce_etims.utils.api_client import request as etims_request
from royce_etims.utils.validation import validate_kra_pin


class eTIMSSettings(Document):
	def validate(self):
		validate_kra_pin(self.tin, label=_("TIN"))

	@frappe.whitelist()
	def test_connection(self):
		"""One authenticated round trip through every layer a real call uses -
		GavaConnect token, apigee_app_id, tin/bhfId/cmcKey - via the read-only
		selectTaxpayerInfo, so it's safe to click any number of times."""
		if not self.default_branch:
			frappe.throw(
				_("Set a Default Branch first - the connection test authenticates as that branch's device.")
			)

		branch = frappe.get_doc("eTIMS Branch", self.default_branch)
		data = etims_request(
			self.company,
			"selectTaxpayerInfo",
			payload={"tin": self.tin, "bhfId": branch.bhf_id, "lastReqDt": "20180101000000"},
			branch=branch,
			reference_doctype=self.doctype,
			reference_name=self.name,
		)
		body = (data or {}).get("responseBody") or data or {}
		info = (body.get("data") or {}).get("info") or {}
		return {
			"taxpayer_name": info.get("taxprNm"),
			"branch": branch.bhf_id,
			"environment": self.environment,
		}
