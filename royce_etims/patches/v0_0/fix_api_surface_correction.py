# Copyright (c) 2026, Royce Technologies LTD and contributors
# For license information, please see license.txt

"""Applies the API-surface correction to already-installed sites - see
docs/architecture.md's correction history. The original Postman collection
this app was first built from targeted the wrong host, wrong endpoint paths
for most calls, and an OAuth/Apigee auth layer the real OSCU API doesn't
have. Corrected against two independent sources: KRA's own OSCU
Specification Document v2.0, and navariltd/kenya-compliance (tested against
the real KRA sandbox in 2024).

eTIMS Settings/eTIMS Branch are this app's own doctypes, so their field
changes (drop Apigee fields, add sdc_id) sync automatically via the normal
DocType migration - nothing to do here. Sales Invoice/POS Invoice's
etims_raw_response was a Custom Field (this app doesn't own those doctypes),
so it needs explicit removal the same way add_etims_reference_fields_to_item
handled Item's etims_item_type - Custom Field sync only adds/updates, it
never removes a field that's no longer in CUSTOM_FIELDS.
"""

import frappe

from royce_etims.custom_fields import create_etims_custom_fields


def execute():
	for doctype in ("Sales Invoice", "POS Invoice"):
		frappe.db.delete("Custom Field", {"dt": doctype, "fieldname": "etims_raw_response"})

	frappe.clear_cache(doctype="Sales Invoice")
	frappe.clear_cache(doctype="POS Invoice")
	create_etims_custom_fields()
	frappe.db.commit()
