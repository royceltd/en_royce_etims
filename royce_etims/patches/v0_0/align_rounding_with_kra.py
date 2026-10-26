# Copyright (c) 2026, Royce Technologies LTD and contributors
# For license information, please see license.txt

import frappe

from royce_etims.kra_etims.doctype.etims_settings.etims_settings import align_rounding_with_kra


def execute():
	"""Sites already signing with eTIMS get KRA's half-up rounding now; new ones
	get it when eTIMS Settings is first set Active."""
	if frappe.db.exists("eTIMS Settings", {"status": "Active"}):
		align_rounding_with_kra()
