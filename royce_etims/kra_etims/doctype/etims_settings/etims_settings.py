# Copyright (c) 2026, Royce Technologies LTD and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from royce_etims.utils.api_client import request as etims_request
from royce_etims.utils.validation import validate_kra_pin

# KRA rounds half-cents up; ERPNext's default is Banker's. Signed invoices
# must match KRA to the cent - see etims_sync/tax_lines.money().
KRA_ROUNDING_METHOD = "Commercial Rounding"


class eTIMSSettings(Document):
	def validate(self):
		validate_kra_pin(self.tin, label=_("TIN"))
		if self.status == "Active":
			align_rounding_with_kra()

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


def align_rounding_with_kra():
	"""Make ERPNext round half-cents up like KRA, so the invoice ERPNext prints
	is the one KRA accepts. With Banker's Rounding, 25.37 L x 182.50 is 4630.02
	in ERPNext and 4630.03 at KRA - CONFIRMED 2026-10-26 - and KRA rejects it.
	Site-wide on purpose: one tenant per site, and every signed document has to
	agree with KRA."""
	if frappe.db.get_single_value("System Settings", "rounding_method") == KRA_ROUNDING_METHOD:
		return
	frappe.db.set_single_value("System Settings", "rounding_method", KRA_ROUNDING_METHOD)
	frappe.clear_cache()
	frappe.msgprint(
		_("Rounding set to {0} for the whole site, to match KRA eTIMS to the cent.").format(
			KRA_ROUNDING_METHOD
		),
		alert=True,
	)
