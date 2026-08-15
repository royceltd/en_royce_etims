# Copyright (c) 2026, Royce Technologies LTD and contributors
# For license information, please see license.txt

"""Applies the reworked Item eTIMS fields (Link-to-reference-doctype instead of
free text, plus the eTIMS ID Mapping child table replacing the flat
etims_item_code field - see docs/architecture.md). Migrates existing data
before removing/retyping the old fields, so re-running this on an
already-used site doesn't lose data:

  - etims_item_code (Data) -> one eTIMS ID Mapping row per known company.
  - etims_item_type (Select "1"/"2"/"3") -> becomes a Link to eTIMS Item Type.
    Same fieldname, incompatible fieldtype change - Custom Field blocks that
    in place ("Fieldtype cannot be changed from Select to Link"), so the old
    field is dropped and the raw values preserved (the seeded eTIMS Item Type
    records use "1"/"2"/"3" as their code/name, so the old string values are
    already valid Link targets - restored after the field is redefined).
"""

import frappe

from royce_etims.custom_fields import create_etims_custom_fields


def execute():
	_migrate_flat_item_codes()
	old_item_types = _drop_incompatible_item_type_field()
	create_etims_custom_fields()
	_restore_item_types(old_item_types)


def _migrate_flat_item_codes():
	if not frappe.db.has_column("Item", "etims_item_code"):
		return

	companies = frappe.get_all("eTIMS Settings", pluck="company")
	items = frappe.get_all(
		"Item", filters={"etims_item_code": ["is", "set"]}, fields=["name", "etims_item_code"]
	)

	for item in items:
		if not item.etims_item_code:
			continue
		# The old field was global (no per-company concept) - propagate to every
		# known eTIMS Settings company rather than guess which one it meant.
		for company in companies:
			frappe.get_doc(
				{
					"doctype": "eTIMS ID Mapping",
					"parent": item.name,
					"parenttype": "Item",
					"parentfield": "etims_id_mapping",
					"setup_doctype": "eTIMS Settings",
					"setup_docname": company,
					"etims_id": item.etims_item_code,
				}
			).insert(ignore_permissions=True)

	frappe.db.delete("Custom Field", {"dt": "Item", "fieldname": "etims_item_code"})


def _drop_incompatible_item_type_field():
	field = frappe.db.get_value("Custom Field", {"dt": "Item", "fieldname": "etims_item_type"}, "fieldtype")
	if not field or field == "Link":
		return {}

	values = dict(
		frappe.get_all(
			"Item",
			filters={"etims_item_type": ["is", "set"]},
			fields=["name", "etims_item_type"],
			as_list=True,
		)
	)
	frappe.db.delete("Custom Field", {"dt": "Item", "fieldname": "etims_item_type"})
	frappe.clear_cache(doctype="Item")
	return values


def _restore_item_types(old_values):
	for item_name, old_value in (old_values or {}).items():
		if old_value and frappe.db.exists("eTIMS Item Type", old_value):
			frappe.db.set_value("Item", item_name, "etims_item_type", old_value, update_modified=False)
	frappe.clear_cache(doctype="Item")
	frappe.db.commit()
