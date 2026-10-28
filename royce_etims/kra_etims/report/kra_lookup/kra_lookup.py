# Copyright (c) 2026, Royce Technologies LTD and contributors
# For license information, please see license.txt

"""What KRA holds for a company, read live through KRA's lookups (see
utils/lookups.py), with each row linked to the matching record in Royce ERP
where there is one. Also how the Go-Live test's lookup cases are run."""

import frappe
from frappe import _

from royce_etims.utils.lookups import kra_lookup

INVOICE_HEADER_FIELDS = ("invcNo", "orgInvcNo", "rcptTyCd", "salesDt", "custTin", "custNm")


def execute(filters=None):
	filters = frappe._dict(filters or {})
	if not filters.company or not filters.lookup:
		return [], []

	rows = kra_lookup(filters.company, filters.lookup, filters.since, filters.invoice_no)
	if filters.lookup == "Invoice Details":
		rows = _invoice_lines(rows)
	rows = [_flatten(row) for row in rows]
	_link_to_royce_erp(filters.company, filters.lookup, rows)

	message = _("{0} rows from KRA.").format(len(rows)) if rows else _("KRA has nothing for this lookup.")
	return _columns(rows), rows, message


def _invoice_lines(invoices):
	"""One row per invoice line, carrying the invoice's own fields."""
	lines = []
	for invoice in invoices:
		header = {f: invoice.get(f) for f in INVOICE_HEADER_FIELDS}
		header.update({"rcptSign": (invoice.get("receipt") or {}).get("rcptSign")})
		for item in invoice.get("itemList") or []:
			lines.append({**header, **item})
	return lines


def _flatten(row):
	"""Nested receipt fields become receipt_*; line lists become a count."""
	flat = {}
	for key, value in row.items():
		if isinstance(value, dict):
			flat.update({f"{key}_{k}": v for k, v in value.items()})
		elif isinstance(value, list):
			flat[f"{key}_count"] = len(value)
		else:
			flat[key] = value
	return flat


def _link_to_royce_erp(company, lookup, rows):
	match = {
		"Branches": lambda r: (
			"eTIMS Branch",
			frappe.db.get_value("eTIMS Branch", {"company": company, "bhf_id": r.get("bhfId")}),
		),
		"Customers": lambda r: ("Customer", frappe.db.get_value("Customer", {"tax_id": r.get("custTin")})),
		"Items": lambda r: ("Item", _item_for(company, r.get("itemCd"))),
		"Sales": lambda r: _invoice_for(company, r.get("invcNo")),
		"Invoice Details": lambda r: _invoice_for(company, r.get("invcNo")),
		"Purchases": lambda r: ("Supplier", frappe.db.get_value("Supplier", {"tax_id": r.get("spplrTin")})),
	}.get(lookup)
	if not match:
		return
	for row in rows:
		doctype, name = match(row)
		row.update({"royce_doctype": doctype if name else None, "in_royce_erp": name})


def _item_for(company, item_cd):
	return frappe.db.get_value(
		"eTIMS ID Mapping",
		{
			"parenttype": "Item",
			"setup_doctype": "eTIMS Settings",
			"setup_docname": company,
			"etims_id": item_cd,
		},
		"parent",
	)


def _invoice_for(company, invc_no):
	for doctype in ("Sales Invoice", "POS Invoice"):
		name = frappe.db.get_value(
			doctype, {"company": company, "royce_etims_invoice_number": invc_no, "docstatus": 1}
		)
		if name:
			return doctype, name
	return None, None


def _columns(rows):
	columns, seen = [], set()
	if rows and "in_royce_erp" in rows[0]:
		columns = [
			{"fieldname": "royce_doctype", "label": _("Type"), "fieldtype": "Data", "hidden": 1},
			{
				"fieldname": "in_royce_erp",
				"label": _("In Royce ERP"),
				"fieldtype": "Dynamic Link",
				"options": "royce_doctype",
				"width": 180,
			},
		]
		seen = {"royce_doctype", "in_royce_erp"}
	for row in rows:
		for key, value in row.items():
			if key in seen:
				continue
			seen.add(key)
			numeric = isinstance(value, int | float) and not isinstance(value, bool)
			columns.append(
				{"fieldname": key, "label": key, "fieldtype": "Float" if numeric else "Data", "width": 130}
			)
	return columns
