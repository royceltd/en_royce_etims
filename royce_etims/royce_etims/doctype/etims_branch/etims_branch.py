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
		"""Call KRA's /selectInitOsdcInfo to register this branch's device and
		obtain a cmcKey + sdcId.

		No `branch` is passed to etims_request() here on purpose: the cmcKey
		doesn't exist yet, so there are no tin/bhfId/cmcKey headers to send -
		tin/bhfId travel in the body instead. Endpoint name and response shape
		(response["data"]["info"] = {cmcKey, sdcId}) confirmed against
		navariltd/kenya-compliance's before_insert handler, which made this
		exact call against the real KRA sandbox - not a guess, unlike the
		earlier version of this method.
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
			"selectInitOsdcInfo",
			payload=payload,
			method="POST",
			reference_doctype=self.doctype,
			reference_name=self.name,
		)

		info = (data or {}).get("data", {}).get("info", {})
		cmc_key = info.get("cmcKey")
		if not cmc_key:
			frappe.throw(
				_("eTIMS did not return a cmcKey for {0}. Raw response: {1}").format(self.name, data)
			)

		self.db_set("cmc_key", cmc_key, notify=False)
		self.db_set("sdc_id", info.get("sdcId"), notify=False)
		self.db_set("device_status", "Registered", notify=False)
		self.db_set("registered_on", now_datetime(), notify=False)

		return {"success": True, "message": _("Device registered for branch {0}.").format(self.branch)}
