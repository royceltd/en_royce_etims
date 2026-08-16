# Copyright (c) 2026, Royce Technologies LTD and contributors
# For license information, please see license.txt

"""Custom fields this app adds to core ERPNext doctypes (Item, Sales Invoice,
POS Invoice).

These aren't part of `royce_etims`'s own doctypes since Item/Sales Invoice/POS
Invoice belong to erpnext - shipped via frappe's `create_custom_fields`, the
standard way apps extend doctypes they don't own. Applied on install (see
setup.py) and re-applied via a patch for sites where the app was installed
before these fields existed.

Sales Invoice and POS Invoice get an identical field set: both can produce a
KRA-signed "receipt" (per docs/architecture.md's onboarding decisions - POS
Invoice is signed by default, Sales Invoice only if explicitly turned on via
eTIMS Settings.sign_sales_invoices). Field names match 1:1 between the two
doctypes, confirmed against this bench's ERPNext, so one payload builder in
etims_sync/receipt.py works for either.
"""


def _receipt_fields(insert_after):
	"""eTIMS receipt-signing fields, identical for Sales Invoice and POS Invoice."""
	return [
		{
			"fieldname": "etims_section",
			"fieldtype": "Section Break",
			"label": "eTIMS",
			"insert_after": insert_after,
			"collapsible": 1,
		},
		{
			"fieldname": "prevent_etims_submission",
			"fieldtype": "Check",
			"label": "Prevent eTIMS Submission",
			"insert_after": "etims_section",
			"description": "Escape hatch to skip fiscalization for this specific document (pattern borrowed from navari_csf_ke).",
		},
		{
			"fieldname": "etims_branch",
			"fieldtype": "Link",
			"options": "eTIMS Branch",
			"label": "eTIMS Branch",
			"insert_after": "prevent_etims_submission",
			"description": "Registered device this document is submitted through. Defaults to the company's Default Branch if left blank.",
		},
		{
			"fieldname": "etims_status",
			"fieldtype": "Select",
			"label": "eTIMS Status",
			"options": "Not Applicable\nPending\nSent\nFailed",
			"default": "Not Applicable",
			"read_only": 1,
			"in_list_view": 1,
			"insert_after": "etims_branch",
		},
		{
			"fieldname": "etims_column_break",
			"fieldtype": "Column Break",
			"insert_after": "etims_status",
		},
		{
			"fieldname": "etims_invoice_number",
			"fieldtype": "Int",
			"label": "eTIMS Invoice No (invcNo)",
			"read_only": 1,
			"insert_after": "etims_column_break",
		},
		{
			"fieldname": "etims_error",
			"fieldtype": "Small Text",
			"label": "eTIMS Error",
			"read_only": 1,
			"insert_after": "etims_invoice_number",
			"depends_on": "eval:doc.etims_status=='Failed'",
		},
		{
			"fieldname": "etims_retry_count",
			"fieldtype": "Int",
			"label": "eTIMS Retry Count",
			"read_only": 1,
			"hidden": 1,
			"default": "0",
			"insert_after": "etims_error",
		},
		# Fields below hold KRA's actual saveTrnsSalesOsdc response, per its
		# confirmed shape: response["data"] = {rcptSign, curRcptNo, totRcptNo,
		# intrlData, sdcDateTime}. Ground truth: navari's kenya-compliance
		# (tested against the KRA sandbox in 2024), not a guess.
		{
			"fieldname": "etims_receipt_section",
			"fieldtype": "Section Break",
			"label": "eTIMS Receipt",
			"insert_after": "etims_retry_count",
			"collapsible": 1,
			"depends_on": "eval:doc.etims_status=='Sent'",
		},
		{
			"fieldname": "etims_receipt_signature",
			"fieldtype": "Data",
			"label": "Receipt Signature (rcptSign)",
			"read_only": 1,
			"insert_after": "etims_receipt_section",
		},
		{
			"fieldname": "etims_current_receipt_number",
			"fieldtype": "Int",
			"label": "Current Receipt No (curRcptNo)",
			"read_only": 1,
			"insert_after": "etims_receipt_signature",
		},
		{
			"fieldname": "etims_total_receipt_number",
			"fieldtype": "Int",
			"label": "Total Receipt No (totRcptNo)",
			"read_only": 1,
			"insert_after": "etims_current_receipt_number",
		},
		{
			"fieldname": "etims_receipt_column_break",
			"fieldtype": "Column Break",
			"insert_after": "etims_total_receipt_number",
		},
		{
			"fieldname": "etims_internal_data",
			"fieldtype": "Small Text",
			"label": "Internal Data (intrlData)",
			"read_only": 1,
			"insert_after": "etims_receipt_column_break",
		},
		{
			"fieldname": "etims_control_unit_datetime",
			"fieldtype": "Data",
			"label": "Control Unit Date/Time (sdcDateTime)",
			"read_only": 1,
			"insert_after": "etims_internal_data",
		},
		{
			"fieldname": "etims_qr_verification_url",
			"fieldtype": "Small Text",
			"label": "eTIMS QR Verification URL",
			"read_only": 1,
			"insert_after": "etims_control_unit_datetime",
		},
		{
			"fieldname": "etims_qr_code",
			"fieldtype": "Small Text",
			"label": "eTIMS QR Code (data URI)",
			"read_only": 1,
			"hidden": 1,
			"insert_after": "etims_qr_verification_url",
		},
		{
			"fieldname": "etims_qr_image",
			"fieldtype": "Image",
			"label": "eTIMS QR Code",
			"options": "etims_qr_code",
			"read_only": 1,
			"insert_after": "etims_qr_code",
		},
	]


CUSTOM_FIELDS = {
	"Item": [
		{
			"fieldname": "etims_section",
			"fieldtype": "Section Break",
			"label": "eTIMS",
			"insert_after": "item_group",
			"collapsible": 1,
		},
		{
			"fieldname": "prevent_etims_submission",
			"fieldtype": "Check",
			"label": "Prevent eTIMS Submission",
			"insert_after": "etims_section",
			"description": "Escape hatch for items that should never be pushed to eTIMS (pattern borrowed from navari_csf_ke).",
		},
		{
			"fieldname": "etims_id_mapping",
			"fieldtype": "Table",
			"options": "eTIMS ID Mapping",
			"label": "eTIMS Item Code (itemCd) by Registration",
			"insert_after": "prevent_etims_submission",
			"description": "One row per eTIMS Settings (company) this item is registered under - itemCd is assigned per taxpayer, not global to the Item.",
		},
		{
			"fieldname": "etims_item_classification",
			"fieldtype": "Link",
			"options": "eTIMS Item Classification",
			"label": "eTIMS Item Classification",
			"insert_after": "etims_id_mapping",
		},
		{
			"fieldname": "etims_item_classification_code",
			"fieldtype": "Data",
			"label": "eTIMS Item Classification Code (itemClsCd)",
			"read_only": 1,
			"fetch_from": "etims_item_classification.code",
			"insert_after": "etims_item_classification",
		},
		{
			"fieldname": "etims_item_type",
			"fieldtype": "Link",
			"options": "eTIMS Item Type",
			"label": "eTIMS Item Type",
			"insert_after": "etims_item_classification_code",
		},
		{
			"fieldname": "etims_item_type_code",
			"fieldtype": "Data",
			"label": "eTIMS Item Type Code (itemTyCd)",
			"read_only": 1,
			"fetch_from": "etims_item_type.code",
			"insert_after": "etims_item_type",
		},
		{
			"fieldname": "etims_taxation_type",
			"fieldtype": "Link",
			"options": "eTIMS Taxation Type",
			"label": "eTIMS Taxation Type",
			"insert_after": "etims_item_type_code",
		},
		{
			"fieldname": "etims_taxation_type_code",
			"fieldtype": "Data",
			"label": "eTIMS Taxation Type Code (taxTyCd)",
			"read_only": 1,
			"fetch_from": "etims_taxation_type.code",
			"insert_after": "etims_taxation_type",
		},
		{
			"fieldname": "etims_taxation_type_rate",
			"fieldtype": "Percent",
			"label": "eTIMS VAT Rate",
			"read_only": 1,
			"fetch_from": "etims_taxation_type.rate",
			"insert_after": "etims_taxation_type_code",
			"description": "Sourced from eTIMS Taxation Type - replaces the old hardcoded rate table in etims_sync/receipt.py.",
		},
		{
			"fieldname": "etims_column_break",
			"fieldtype": "Column Break",
			"insert_after": "etims_taxation_type_rate",
		},
		{
			"fieldname": "etims_origin_nation",
			"fieldtype": "Link",
			"options": "eTIMS Country of Origin",
			"label": "eTIMS Country of Origin",
			"insert_after": "etims_column_break",
		},
		{
			"fieldname": "etims_origin_nation_code",
			"fieldtype": "Data",
			"label": "eTIMS Origin Nation Code (orgnNatCd)",
			"read_only": 1,
			"fetch_from": "etims_origin_nation.code",
			"insert_after": "etims_origin_nation",
		},
		{
			"fieldname": "etims_packaging_unit",
			"fieldtype": "Link",
			"options": "eTIMS Packaging Unit",
			"label": "eTIMS Packaging Unit",
			"insert_after": "etims_origin_nation_code",
		},
		{
			"fieldname": "etims_packaging_unit_code",
			"fieldtype": "Data",
			"label": "eTIMS Packaging Unit Code (pkgUnitCd)",
			"read_only": 1,
			"fetch_from": "etims_packaging_unit.code",
			"insert_after": "etims_packaging_unit",
		},
		{
			"fieldname": "etims_quantity_unit",
			"fieldtype": "Link",
			"options": "eTIMS Quantity Unit",
			"label": "eTIMS Quantity Unit",
			"insert_after": "etims_packaging_unit_code",
		},
		{
			"fieldname": "etims_quantity_unit_code",
			"fieldtype": "Data",
			"label": "eTIMS Quantity Unit Code (qtyUnitCd)",
			"read_only": 1,
			"fetch_from": "etims_quantity_unit.code",
			"insert_after": "etims_quantity_unit",
		},
		{
			"fieldname": "etims_sync_status",
			"fieldtype": "Select",
			"label": "eTIMS Sync Status",
			"options": "Not Synced\nSynced\nFailed",
			"default": "Not Synced",
			"read_only": 1,
			"insert_after": "etims_quantity_unit_code",
		},
		{
			"fieldname": "etims_last_synced_on",
			"fieldtype": "Datetime",
			"label": "eTIMS Last Synced On",
			"read_only": 1,
			"insert_after": "etims_sync_status",
		},
		{
			"fieldname": "etims_sync_error",
			"fieldtype": "Small Text",
			"label": "eTIMS Sync Error",
			"read_only": 1,
			"insert_after": "etims_last_synced_on",
			"depends_on": "eval:doc.etims_sync_status=='Failed'",
		},
	],
	"Sales Invoice": _receipt_fields(insert_after="customer_name"),
	"POS Invoice": _receipt_fields(insert_after="customer_name"),
}


def create_etims_custom_fields():
	from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

	create_custom_fields(CUSTOM_FIELDS, update=True)
