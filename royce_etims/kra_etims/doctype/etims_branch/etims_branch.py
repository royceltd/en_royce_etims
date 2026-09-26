# Copyright (c) 2026, Royce Technologies LTD and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime

from royce_etims.utils.api_client import request as etims_request


class eTIMSBranch(Document):
	def validate(self):
		if not self.dvc_srl_no:
			self.dvc_srl_no = self._generate_dvc_srl_no()

	def _generate_dvc_srl_no(self):
		"""A device serial is a self-chosen unique string, not a real hardware
		ID - confirmed by how Odoo's own eTIMS integration does it (vendor
		prefix + company VAT number + sequence). Generating one avoids the
		'Device Serial Number already used' collision a real machine serial
		risks (someone else's sandbox test, or a re-run, reusing the same
		hardware ID). Format: ROYCEERP-<tin>-<3-digit sequence, per company>.
		"""
		tin = frappe.db.get_value("eTIMS Settings", self.company, "tin") or self.company
		existing = frappe.db.count("eTIMS Branch", {"company": self.company})
		return f"ROYCEERP-{tin}-{existing + 1:03d}"

	@frappe.whitelist()
	def register_device(self):
		"""Call KRA's /initialize to register this branch's device and obtain
		a cmcKey + sdcId.

		Endpoint name confirmed directly against KRA's official GavaConnect
		developer portal documentation (https://developer.go.ke/apis/KRA-ETIMS-SBX,
		read 2026-09-05) - NOT selectInitOsdcInfo, which was this method's
		prior (wrong) value, itself a correction away from the original
		Postman collection that turns out to have been right about this all
		along. Full path per that same doc's own worked example:
		https://sbx.kra.go.ke/etims-oscu/api/v1/initialize - see
		docs/architecture.md for the full correction history.

		Response shape CONFIRMED 2026-09-10 from a real successful sandbox call:
		{"responseHeader": {...}, "responseBody": {"resultCd": "000", "data":
		{"info": {tin, bhfId, dvcId, sdcId, mrcNo, cmcKey, ...}}}} - nested
		one level deeper than the prior guess (which lacked the "responseBody"
		wrapper, carried over from kenya-compliance and never actually
		verified). A gateway-level error (e.g. the 401 "Unauthorised-Invalid
		Access Token" this app hit before getting real credentials) uses a
		different, flatter "header"/"body" shape instead - see
		docs/architecture.md. Handled defensively: falls back to the
		unwrapped shape if "responseBody" isn't present, rather than assuming
		either is universal across every endpoint.

		No `branch` is passed to etims_request() here on purpose: the cmcKey
		doesn't exist yet, so there are no tin/bhfId/cmcKey headers to send -
		tin/bhfId travel in the body instead.
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

		body = (data or {}).get("responseBody") or data or {}
		info = (body.get("data") or {}).get("info", {})
		cmc_key = info.get("cmcKey")
		if not cmc_key:
			frappe.throw(
				_("eTIMS did not return a cmcKey for {0}. Raw response: {1}").format(self.name, data)
			)

		self.db_set("cmc_key", cmc_key, notify=False)
		self.db_set("sdc_id", info.get("sdcId"), notify=False)
		self.db_set("dvc_id", info.get("dvcId"), notify=False)
		self.db_set("mrc_no", info.get("mrcNo"), notify=False)
		self.db_set("device_status", "Registered", notify=False)
		self.db_set("registered_on", now_datetime(), notify=False)

		return {"success": True, "message": _("Device registered for branch {0}.").format(self.branch)}
