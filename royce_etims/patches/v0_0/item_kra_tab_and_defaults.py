# Copyright (c) 2026, Royce Technologies LTD and contributors
# For license information, please see license.txt

import frappe

from royce_etims.custom_fields import create_etims_custom_fields
from royce_etims.etims_sync.item import map_common_uoms


def execute():
	# The Item's KRA fields moved from a section after item_group to their own
	# tab; the old section break would otherwise keep pulling ERPNext's fields in.
	frappe.delete_doc_if_exists("Custom Field", "Item-royce_etims_section")
	create_etims_custom_fields()
	map_common_uoms()
