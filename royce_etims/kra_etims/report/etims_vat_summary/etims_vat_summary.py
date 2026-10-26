# Copyright (c) 2026, Royce Technologies LTD and contributors
# For license information, please see license.txt

"""VAT by KRA tax band for a period, from exactly what KRA accepted: the
request body of every successful sendSalesTransaction in eTIMS Log. Using
the accepted payloads (not recomputing from invoices) means this matches
what KRA holds - and so what it pre-fills on the VAT return - even where
our own tax setup and KRA's VAT-inclusive split would round differently.

Credit notes (rcptTyCd "R") are subtracted. Dated by the payload's salesDt.
Relies on eTIMS Log being kept: don't add it to Log Settings' auto-clear.
"""

import json

import frappe
from frappe import _
from frappe.utils import flt, getdate

TAX_CODES = ("A", "B", "C", "D", "E")
SIGN_ENDPOINT = "%sendSalesTransaction"


def execute(filters=None):
	filters = frappe._dict(filters or {})
	if not (filters.company and filters.from_date and filters.to_date):
		frappe.throw(_("Company, From Date and To Date are required"))

	payloads = accepted_payloads(filters.company)
	from_date, to_date = getdate(filters.from_date), getdate(filters.to_date)
	in_period = [p for p in payloads if from_date <= _sales_date(p) <= to_date]

	rows = summarize_by_band(in_period)
	return _columns(), rows, None, _chart(rows), _summary(rows, in_period)


def accepted_payloads(company):
	"""Latest accepted request body per signed document - a document is only
	signed once, but deduplicating keeps a stray double log from counting twice."""
	by_document = {}
	for log in frappe.get_all(
		"eTIMS Log",
		filters={"company": company, "status": "Success", "endpoint": ["like", SIGN_ENDPOINT]},
		fields=["reference_doctype", "reference_name", "request_body", "creation"],
		order_by="creation asc",
	):
		try:
			by_document[(log.reference_doctype, log.reference_name)] = json.loads(log.request_body or "{}")
		except ValueError:
			continue
	return list(by_document.values())


def _sales_date(payload):
	return getdate(str(payload.get("salesDt") or "19700101"))


def summarize_by_band(payloads):
	rates = dict(frappe.get_all("eTIMS Taxation Type", fields=["code", "rate"], as_list=True))
	descriptions = dict(frappe.get_all("eTIMS Taxation Type", fields=["code", "description"], as_list=True))
	rows = []
	for code in TAX_CODES:
		row = {
			"tax_band": code,
			"description": descriptions.get(code, code),
			"rate": flt(rates.get(code)),
			"invoice_taxable": 0.0,
			"invoice_vat": 0.0,
			"credit_taxable": 0.0,
			"credit_vat": 0.0,
		}
		for p in payloads:
			kind = "credit" if p.get("rcptTyCd") == "R" else "invoice"
			row[f"{kind}_taxable"] += flt(p.get(f"taxblAmt{code}"))
			row[f"{kind}_vat"] += flt(p.get(f"taxAmt{code}"))
		row["net_taxable"] = flt(row["invoice_taxable"] - row["credit_taxable"], 2)
		row["net_vat"] = flt(row["invoice_vat"] - row["credit_vat"], 2)
		rows.append(row)
	return rows


def _columns():
	currency = {"fieldtype": "Currency", "width": 140}
	return [
		{"fieldname": "tax_band", "label": _("Band"), "fieldtype": "Data", "width": 60},
		{"fieldname": "description", "label": _("Taxation Type"), "fieldtype": "Data", "width": 150},
		{"fieldname": "rate", "label": _("Rate"), "fieldtype": "Percent", "width": 70},
		{"fieldname": "invoice_taxable", "label": _("Invoices: Taxable"), **currency},
		{"fieldname": "invoice_vat", "label": _("Invoices: VAT"), **currency},
		{"fieldname": "credit_taxable", "label": _("Credit Notes: Taxable"), **currency},
		{"fieldname": "credit_vat", "label": _("Credit Notes: VAT"), **currency},
		{"fieldname": "net_taxable", "label": _("Net Taxable"), **currency},
		{"fieldname": "net_vat", "label": _("Net VAT"), **currency},
	]


def _chart(rows):
	return {
		"data": {
			"labels": [r["description"] for r in rows],
			"datasets": [{"name": _("Net Taxable"), "values": [r["net_taxable"] for r in rows]}],
		},
		"type": "bar",
		"fieldtype": "Currency",
	}


def _summary(rows, payloads):
	credit_notes = sum(1 for p in payloads if p.get("rcptTyCd") == "R")
	return [
		{"value": len(payloads) - credit_notes, "label": _("Signed Invoices"), "datatype": "Int"},
		{"value": credit_notes, "label": _("Signed Credit Notes"), "datatype": "Int"},
		{"value": sum(r["net_taxable"] for r in rows), "label": _("Net Taxable"), "datatype": "Currency"},
		{
			"value": sum(r["net_vat"] for r in rows),
			"label": _("Net VAT"),
			"datatype": "Currency",
			"indicator": "Blue",
		},
	]
