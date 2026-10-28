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
			"fieldname": "royce_etims_section",
			"fieldtype": "Section Break",
			"label": "eTIMS",
			"insert_after": insert_after,
			"collapsible": 1,
		},
		{
			"fieldname": "royce_prevent_etims_submission",
			"fieldtype": "Check",
			"label": "Prevent eTIMS Submission",
			"insert_after": "royce_etims_section",
			"description": "Escape hatch to skip fiscalization for this specific document (pattern borrowed from navari_csf_ke).",
		},
		{
			"fieldname": "royce_etims_branch",
			"fieldtype": "Link",
			"options": "eTIMS Branch",
			"label": "eTIMS Branch",
			"insert_after": "royce_prevent_etims_submission",
			"description": "Registered device this document is submitted through. Defaults to the company's Default Branch if left blank.",
		},
		{
			"fieldname": "royce_etims_refund_reason",
			"fieldtype": "Link",
			"options": "eTIMS Refund Reason",
			"label": "eTIMS Refund Reason",
			"insert_after": "royce_etims_branch",
			"depends_on": "eval:doc.is_return",
			"description": "Required by KRA on a credit note (rfdRsnCd). Only enforced when eTIMS signs this document.",
		},
		{
			"fieldname": "royce_etims_status",
			"fieldtype": "Select",
			"label": "eTIMS Status",
			"options": "Not Applicable\nPending\nSent\nFailed",
			"default": "Not Applicable",
			"read_only": 1,
			"in_list_view": 1,
			"insert_after": "royce_etims_refund_reason",
		},
		{
			"fieldname": "royce_etims_column_break",
			"fieldtype": "Column Break",
			"insert_after": "royce_etims_status",
		},
		{
			"fieldname": "royce_etims_invoice_number",
			"fieldtype": "Int",
			"label": "eTIMS Invoice No (invcNo)",
			"read_only": 1,
			"insert_after": "royce_etims_column_break",
		},
		{
			"fieldname": "royce_etims_error",
			"fieldtype": "Small Text",
			"label": "eTIMS Error",
			"read_only": 1,
			"insert_after": "royce_etims_invoice_number",
			"depends_on": "eval:doc.royce_etims_status=='Failed'",
		},
		{
			"fieldname": "royce_etims_retry_count",
			"fieldtype": "Int",
			"label": "eTIMS Retry Count",
			"read_only": 1,
			"hidden": 1,
			"default": "0",
			"insert_after": "royce_etims_error",
		},
		# Fields below hold KRA's sendSalesTransaction response, per its
		# assumed shape: response["data"] = {rcptSign, curRcptNo, totRcptNo,
		# intrlData, sdcDateTime}. Source: navari's kenya-compliance (tested
		# against the KRA sandbox in 2024) - for the *other* endpoint name,
		# not re-confirmed against this one. See docs/architecture.md.
		{
			"fieldname": "royce_etims_receipt_section",
			"fieldtype": "Section Break",
			"label": "eTIMS Receipt",
			"insert_after": "royce_etims_retry_count",
			"collapsible": 1,
			"depends_on": "eval:doc.royce_etims_status=='Sent'",
		},
		{
			"fieldname": "royce_etims_receipt_signature",
			"fieldtype": "Data",
			"label": "Receipt Signature (rcptSign)",
			"read_only": 1,
			"insert_after": "royce_etims_receipt_section",
		},
		{
			"fieldname": "royce_etims_current_receipt_number",
			"fieldtype": "Int",
			"label": "Current Receipt No (curRcptNo)",
			"read_only": 1,
			"insert_after": "royce_etims_receipt_signature",
		},
		{
			"fieldname": "royce_etims_total_receipt_number",
			"fieldtype": "Int",
			"label": "Total Receipt No (totRcptNo)",
			"read_only": 1,
			"insert_after": "royce_etims_current_receipt_number",
		},
		{
			"fieldname": "royce_etims_receipt_column_break",
			"fieldtype": "Column Break",
			"insert_after": "royce_etims_total_receipt_number",
		},
		{
			"fieldname": "royce_etims_internal_data",
			"fieldtype": "Small Text",
			"label": "Internal Data (intrlData)",
			"read_only": 1,
			"insert_after": "royce_etims_receipt_column_break",
		},
		{
			"fieldname": "royce_etims_control_unit_datetime",
			"fieldtype": "Data",
			"label": "Control Unit Date/Time (sdcDateTime)",
			"read_only": 1,
			"insert_after": "royce_etims_internal_data",
		},
		{
			"fieldname": "royce_etims_qr_verification_url",
			"fieldtype": "Small Text",
			"label": "eTIMS QR Verification URL",
			"read_only": 1,
			"insert_after": "royce_etims_control_unit_datetime",
		},
		{
			"fieldname": "royce_etims_qr_code",
			"fieldtype": "Small Text",
			"label": "eTIMS QR Code (data URI)",
			"read_only": 1,
			"hidden": 1,
			"insert_after": "royce_etims_qr_verification_url",
		},
		{
			"fieldname": "royce_etims_qr_image",
			"fieldtype": "Image",
			"label": "eTIMS QR Code",
			"options": "royce_etims_qr_code",
			"read_only": 1,
			"insert_after": "royce_etims_qr_code",
		},
	]


CUSTOM_FIELDS = {
	# Which eTIMS band an Item Tax Template's lines are signed under - the
	# template decides the VAT actually charged, so it decides the band too.
	# The standard KE templates get theirs automatically (tax_lines.py).
	"Item Tax Template": [
		{
			"fieldname": "royce_etims_taxation_type",
			"fieldtype": "Link",
			"options": "eTIMS Taxation Type",
			"label": "eTIMS Taxation Type",
			"insert_after": "company",
			"description": "Band KRA records lines using this template under: A Exempt, B 16%, C Zero-rated, D Non-VAT, E 8%.",
		},
	],
	# A customer with a KRA PIN is registered with KRA (branchSendCustomerInfo)
	# - see etims_sync/customer.py.
	"Customer": [
		{
			"fieldname": "royce_etims_customer_status",
			"fieldtype": "Select",
			"label": "eTIMS Registration",
			"options": "Not Synced\nSynced\nFailed",
			"default": "Not Synced",
			"read_only": 1,
			"no_copy": 1,
			"insert_after": "tax_id",
			"depends_on": "eval:doc.tax_id",
		},
		{
			"fieldname": "royce_etims_customer_no",
			"fieldtype": "Data",
			"label": "eTIMS Customer No (custNo)",
			"read_only": 1,
			"no_copy": 1,
			"insert_after": "royce_etims_customer_status",
			"depends_on": "eval:doc.royce_etims_customer_no",
			"description": "Assigned on first registration - KRA caps custNo at 15 characters, so the Customer ID can't be used.",
		},
		{
			"fieldname": "royce_etims_customer_error",
			"fieldtype": "Small Text",
			"label": "eTIMS Registration Error",
			"read_only": 1,
			"no_copy": 1,
			"insert_after": "royce_etims_customer_no",
			"depends_on": "eval:doc.royce_etims_customer_status=='Failed'",
		},
	],
	# One "KRA eTIMS" tab before Connections. It used to be a section after
	# item_group, which swallowed ERPNext's own fields that follow it (Default
	# Unit of Measure, Maintain Stock...). The *_code fields repeat the code of
	# the choice above them (the reference lists are named by code), so they're
	# hidden but kept: the KRA payloads read them. What makes up the item code
	# locks once KRA has the item - saveItem refuses a registered itemCd.
	"Item": [
		{
			"fieldname": "royce_etims_tab",
			"fieldtype": "Tab Break",
			"label": "KRA eTIMS",
			"insert_after": "prices_html",
		},
		{
			"fieldname": "royce_etims_sync_status",
			"fieldtype": "Select",
			"label": "KRA Registration",
			"options": "Not Synced\nSynced\nFailed",
			"default": "Not Synced",
			"read_only": 1,
			"no_copy": 1,
			"insert_after": "royce_etims_tab",
			"description": "Click Sync to eTIMS (top of the form) to register the item with KRA. An item must be registered before it can be sold on a signed invoice.",
		},
		{
			"fieldname": "royce_etims_sync_error",
			"fieldtype": "Small Text",
			"label": "Why Registration Failed",
			"read_only": 1,
			"no_copy": 1,
			"insert_after": "royce_etims_sync_status",
			"depends_on": "eval:doc.royce_etims_sync_status=='Failed'",
		},
		{
			"fieldname": "royce_etims_last_synced_on",
			"fieldtype": "Datetime",
			"label": "Registered On",
			"read_only": 1,
			"no_copy": 1,
			"insert_after": "royce_etims_sync_error",
			"depends_on": "eval:doc.royce_etims_sync_status=='Synced'",
		},
		{
			"fieldname": "royce_etims_id_mapping",
			"fieldtype": "Table",
			"options": "eTIMS ID Mapping",
			"label": "KRA Item Code",
			"read_only": 1,
			"no_copy": 1,
			"insert_after": "royce_etims_last_synced_on",
			"depends_on": "eval:(doc.royce_etims_id_mapping || []).length",
			"description": "Given by KRA when the item is registered: one row per company. KRA identifies the item by this code on every invoice and stock movement.",
		},
		{
			"fieldname": "royce_prevent_etims_submission",
			"fieldtype": "Check",
			"label": "Don't Send to KRA",
			"insert_after": "royce_etims_id_mapping",
			"description": "For items you never sell, such as office supplies. The item isn't registered or sent with stock, and an invoice containing it can't be signed.",
		},
		{
			"fieldname": "royce_etims_details_section",
			"fieldtype": "Section Break",
			"label": "What KRA Records",
			"insert_after": "royce_prevent_etims_submission",
			"description": "These make up the KRA item code, so they can't be changed once the item is registered.",
		},
		{
			"fieldname": "royce_etims_item_classification",
			"fieldtype": "Link",
			"options": "eTIMS Item Classification",
			"label": "KRA Product Category",
			"insert_after": "royce_etims_details_section",
			"read_only_depends_on": "eval:doc.royce_etims_sync_status=='Synced'",
			"description": "Search by name, e.g. soap, laptop, diesel. Filled from the Item Group when it has one.",
		},
		{
			"fieldname": "royce_etims_item_classification_code",
			"fieldtype": "Data",
			"label": "KRA Product Category Code",
			"read_only": 1,
			"hidden": 1,
			"fetch_from": "royce_etims_item_classification.code",
			"insert_after": "royce_etims_item_classification",
		},
		{
			"fieldname": "royce_etims_item_type",
			"fieldtype": "Link",
			"options": "eTIMS Item Type",
			"label": "Item Type",
			"insert_after": "royce_etims_item_classification_code",
			"read_only_depends_on": "eval:doc.royce_etims_sync_status=='Synced'",
			"description": "Finished Product for goods you sell, Raw Material for inputs you make things from, Service for anything not stocked.",
		},
		{
			"fieldname": "royce_etims_item_type_code",
			"fieldtype": "Data",
			"label": "Item Type Code",
			"read_only": 1,
			"hidden": 1,
			"fetch_from": "royce_etims_item_type.code",
			"insert_after": "royce_etims_item_type",
		},
		{
			"fieldname": "royce_etims_taxation_type",
			"fieldtype": "Link",
			"options": "eTIMS Taxation Type",
			"label": "KRA VAT Band",
			"insert_after": "royce_etims_item_type_code",
			"description": "Taken from the Item Tax Template on the Tax tab when you save. Set it here only for an item without one.",
		},
		{
			"fieldname": "royce_etims_taxation_type_code",
			"fieldtype": "Data",
			"label": "KRA VAT Band Code",
			"read_only": 1,
			"hidden": 1,
			"fetch_from": "royce_etims_taxation_type.code",
			"insert_after": "royce_etims_taxation_type",
		},
		{
			"fieldname": "royce_etims_taxation_type_rate",
			"fieldtype": "Percent",
			"label": "VAT Rate",
			"read_only": 1,
			"fetch_from": "royce_etims_taxation_type.rate",
			"insert_after": "royce_etims_taxation_type_code",
		},
		{
			"fieldname": "royce_etims_column_break",
			"fieldtype": "Column Break",
			"insert_after": "royce_etims_taxation_type_rate",
		},
		{
			"fieldname": "royce_etims_origin_nation",
			"fieldtype": "Link",
			"options": "eTIMS Country of Origin",
			"label": "Country of Origin",
			"insert_after": "royce_etims_column_break",
			"read_only_depends_on": "eval:doc.royce_etims_sync_status=='Synced'",
			"description": "Where the product is made. Kenya unless imported.",
		},
		{
			"fieldname": "royce_etims_origin_nation_code",
			"fieldtype": "Data",
			"label": "Country of Origin Code",
			"read_only": 1,
			"hidden": 1,
			"fetch_from": "royce_etims_origin_nation.code",
			"insert_after": "royce_etims_origin_nation",
		},
		{
			"fieldname": "royce_etims_packaging_unit",
			"fieldtype": "Link",
			"options": "eTIMS Packaging Unit",
			"label": "Packaging",
			"insert_after": "royce_etims_origin_nation_code",
			"read_only_depends_on": "eval:doc.royce_etims_sync_status=='Synced'",
			"description": "How it's packed when sold: Carton, Bottle, Bag... Net for loose goods and services.",
		},
		{
			"fieldname": "royce_etims_packaging_unit_code",
			"fieldtype": "Data",
			"label": "Packaging Code",
			"read_only": 1,
			"hidden": 1,
			"fetch_from": "royce_etims_packaging_unit.code",
			"insert_after": "royce_etims_packaging_unit",
		},
		{
			"fieldname": "royce_etims_quantity_unit",
			"fieldtype": "Link",
			"options": "eTIMS Quantity Unit",
			"label": "KRA Quantity Unit",
			"insert_after": "royce_etims_packaging_unit_code",
			"read_only_depends_on": "eval:doc.royce_etims_sync_status=='Synced'",
			"description": "The unit quantities are counted in. Filled from the Default Unit of Measure, e.g. Nos becomes Number. KRA only accepts 2-letter units here.",
		},
		{
			"fieldname": "royce_etims_quantity_unit_code",
			"fieldtype": "Data",
			"label": "KRA Quantity Unit Code",
			"read_only": 1,
			"hidden": 1,
			"fetch_from": "royce_etims_quantity_unit.code",
			"insert_after": "royce_etims_quantity_unit",
		},
	],
	# Defaults for new items' KRA fields - see etims_sync/item.py fill_defaults.
	"UOM": [
		{
			"fieldname": "royce_etims_quantity_unit",
			"fieldtype": "Link",
			"options": "eTIMS Quantity Unit",
			"label": "KRA Quantity Unit",
			"insert_after": "must_be_whole_number",
			"description": "Used for new items with this unit of measure.",
		},
	],
	"Item Group": [
		{
			"fieldname": "royce_etims_item_classification",
			"fieldtype": "Link",
			"options": "eTIMS Item Classification",
			"label": "KRA Product Category",
			"insert_after": "is_group",
			"description": "Used for new items in this group (or its sub-groups) that have no category yet.",
		},
	],
	"Sales Invoice": _receipt_fields(insert_after="customer_name"),
	"POS Invoice": _receipt_fields(insert_after="customer_name"),
}


def create_etims_custom_fields():
	from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

	create_custom_fields(CUSTOM_FIELDS, update=True)
