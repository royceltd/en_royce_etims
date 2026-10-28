# Copyright (c) 2026, Royce Technologies LTD and contributors
# For license information, please see license.txt

"""Everything for one company that KRA hasn't accepted yet: invoices and
credit notes not signed, stock movements not sent, items not registered.
An empty report means the company is fully in step with KRA."""

import frappe
from frappe import _
from frappe.utils import date_diff, get_first_day, today

INVOICE_DOCTYPES = ("Sales Invoice", "POS Invoice")


def execute(filters=None):
	filters = frappe._dict(filters or {})
	if not filters.company:
		frappe.throw(_("Company is required"))

	rows = _invoice_rows(filters.company) + _stock_rows(filters.company) + _item_rows(filters.company)
	rows.sort(key=lambda r: r["age_days"], reverse=True)
	return _columns(), rows, None, None, _summary(filters.company, rows)


def _columns():
	return [
		{"fieldname": "category", "label": _("Category"), "fieldtype": "Data", "width": 130},
		{
			"fieldname": "document_type",
			"label": _("Document Type"),
			"fieldtype": "Link",
			"options": "DocType",
			"width": 150,
		},
		{
			"fieldname": "document",
			"label": _("Document"),
			"fieldtype": "Dynamic Link",
			"options": "document_type",
			"width": 180,
		},
		{"fieldname": "date", "label": _("Date"), "fieldtype": "Date", "width": 100},
		{"fieldname": "age_days", "label": _("Age (Days)"), "fieldtype": "Int", "width": 90},
		{"fieldname": "status", "label": _("eTIMS Status"), "fieldtype": "Data", "width": 140},
		{"fieldname": "retries", "label": _("Retries"), "fieldtype": "Int", "width": 70},
		{"fieldname": "error", "label": _("Error"), "fieldtype": "Small Text", "width": 400},
	]


def _row(category, document_type, document, date, status, error=None, retries=0):
	return {
		"category": category,
		"document_type": document_type,
		"document": document,
		"date": date,
		"age_days": date_diff(today(), date) if date else 0,
		"status": status,
		"retries": retries or 0,
		"error": error,
	}


def _invoice_rows(company):
	rows = []
	for doctype in INVOICE_DOCTYPES:
		for inv in frappe.get_all(
			doctype,
			filters={"company": company, "docstatus": 1, "royce_etims_status": ["in", ("Pending", "Failed")]},
			fields=[
				"name",
				"posting_date",
				"is_return",
				"royce_etims_status",
				"royce_etims_error",
				"royce_etims_retry_count",
			],
		):
			rows.append(
				_row(
					_("Credit Note") if inv.is_return else _("Invoice"),
					doctype,
					inv.name,
					inv.posting_date,
					inv.royce_etims_status,
					inv.royce_etims_error,
					inv.royce_etims_retry_count,
				)
			)
	return rows


def _stock_rows(company):
	return [
		_row(
			_("Stock Movement"),
			"eTIMS Stock Movement",
			mv.name,
			mv.posting_date,
			mv.status,
			mv.error,
			mv.retry_count,
		)
		for mv in frappe.get_all(
			"eTIMS Stock Movement",
			filters={"company": company, "status": ["in", ("Pending", "Failed", "Stock Master Failed")]},
			fields=["name", "posting_date", "status", "error", "retry_count"],
		)
	]


def _item_rows(company):
	"""Items that can't be sold on a signed invoice for this company: active
	sales items with no KRA item code under it. Not registered at all, or
	failed - KRA's or our own checks; the reason is on the item."""
	registered = set(
		frappe.get_all(
			"eTIMS ID Mapping",
			filters={
				"parenttype": "Item",
				"setup_doctype": "eTIMS Settings",
				"setup_docname": company,
				"disabled": 0,
			},
			pluck="parent",
		)
	)
	rows = []
	for item in frappe.get_all(
		"Item",
		filters={"disabled": 0, "is_sales_item": 1, "royce_prevent_etims_submission": 0},
		fields=["name", "modified", "royce_etims_sync_status", "royce_etims_sync_error"],
	):
		if item.name in registered:
			continue
		failed = item.royce_etims_sync_status == "Failed"
		rows.append(
			_row(
				_("Item"),
				"Item",
				item.name,
				item.modified.date(),
				_("Failed") if failed else _("Not Registered"),
				item.royce_etims_sync_error if failed else _("Open the item and click Sync to eTIMS."),
			)
		)
	return rows


def _summary(company, rows):
	by_category = {}
	for r in rows:
		by_category[r["category"]] = by_category.get(r["category"], 0) + 1

	signed_this_month = sum(
		frappe.db.count(
			doctype,
			{
				"company": company,
				"royce_etims_status": "Sent",
				"posting_date": [">=", get_first_day(today())],
			},
		)
		for doctype in INVOICE_DOCTYPES
	)
	needs_attention = len(rows)
	return [
		{
			"value": needs_attention,
			"label": _("Needs Attention"),
			"datatype": "Int",
			"indicator": "Green" if not needs_attention else "Red",
		},
		{
			"value": by_category.get(_("Invoice"), 0) + by_category.get(_("Credit Note"), 0),
			"label": _("Unsigned Invoices / Credit Notes"),
			"datatype": "Int",
		},
		{
			"value": by_category.get(_("Stock Movement"), 0),
			"label": _("Stock Movements Not Sent"),
			"datatype": "Int",
		},
		{"value": by_category.get(_("Item"), 0), "label": _("Items Not Registered"), "datatype": "Int"},
		{"value": signed_this_month, "label": _("Signed This Month"), "datatype": "Int", "indicator": "Blue"},
	]
