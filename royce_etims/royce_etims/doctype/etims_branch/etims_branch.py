# Copyright (c) 2026, Royce Technologies LTD and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime

from royce_etims.utils.api_client import request as etims_request


class eTIMSBranch(Document):
	@frappe.whitelist()
	def register_device(self):
		"""Call KRA's /initialize to register this branch's device and obtain a cmcKey.

		No `branch` is passed to etims_request() here on purpose: the cmcKey doesn't
		exist yet, so there are no tin/bhfId/cmcKey headers to send - tin/bhfId travel
		in the body instead, per the collection's "OSCU initialization" request.
		"""
		if self.device_status == "Active":
			frappe.throw(_("This device is already active. Re-registering isn't expected to be safe - check with KRA before retrying."))

		settings = frappe.get_doc("eTIMS Settings", self.company)
		payload = {
			"tin": settings.tin,
			"bhfId": self.bhf_id,
			"dvcSrlNo": self.dvc_srl_no,
		}

		data = etims_request(
			self.company,
			"initialize",
			payload=payload,
			method="POST",
			reference_doctype=self.doctype,
			reference_name=self.name,
		)

		cmc_key = _extract_cmc_key(data)
		if not cmc_key:
			frappe.throw(
				_(
					"eTIMS did not return a cmcKey in a recognised shape for {0}. "
					"Raw response: {1}. Check the eTIMS Log for this call and update "
					"_extract_cmc_key() once the real response shape is confirmed."
				).format(self.name, data)
			)

		self.db_set("cmc_key", cmc_key, notify=False)
		self.db_set("device_status", "Registered", notify=False)
		self.db_set("registered_on", now_datetime(), notify=False)

		return {"success": True, "message": _("Device registered for branch {0}.").format(self.branch)}


def _extract_cmc_key(data):
	"""Best-effort extraction of cmcKey - the sandbox collection has no sample
	response body to confirm the exact envelope shape against, so try the
	shapes documented elsewhere in KRA's OSCU spec and fall back gracefully.
	"""
	if not isinstance(data, dict):
		return None

	if data.get("cmcKey"):
		return data["cmcKey"]

	for key in ("data", "info", "result"):
		nested = data.get(key)
		if isinstance(nested, dict) and nested.get("cmcKey"):
			return nested["cmcKey"]

	return None
