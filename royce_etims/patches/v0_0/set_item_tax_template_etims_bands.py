# Copyright (c) 2026, Royce Technologies LTD and contributors
# For license information, please see license.txt

import frappe

from royce_etims.custom_fields import create_etims_custom_fields
from royce_etims.etims_sync.tax_lines import DEFAULT_TEMPLATE_BANDS


def execute():
	"""Adds the eTIMS Taxation Type field to Item Tax Template and fills it on
	existing standard KE templates (new ones get it from the validate hook)."""
	create_etims_custom_fields()
	for template in frappe.get_all(
		"Item Tax Template",
		filters={
			"title": ["in", list(DEFAULT_TEMPLATE_BANDS)],
			"royce_etims_taxation_type": ["is", "not set"],
		},
		fields=["name", "title"],
	):
		band = DEFAULT_TEMPLATE_BANDS[template.title]
		if frappe.db.exists("eTIMS Taxation Type", band):
			frappe.db.set_value("Item Tax Template", template.name, "royce_etims_taxation_type", band)
