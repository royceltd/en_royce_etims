# Copyright (c) 2026, Royce Technologies LTD and contributors
# For license information, please see license.txt

"""Async Sales Invoice / POS Invoice -> KRA sendSalesTransaction ("issue a
receipt"), per docs/architecture.md section 4: submission in ERPNext never
blocks on KRA; sync happens as a background job with a visible status and a
scheduled retry sweep for failures.

KRA's OSCU API has one call for this - sendSalesTransaction - there's no
separate "sign invoice" vs "sign receipt" endpoint; the payload itself carries
a nested `receipt` sub-object. What we actually control is which ERPNext event
triggers that one call. Two doctypes can trigger it, gated independently on
eTIMS Settings:

  - POS Invoice: point-of-sale, payment collected immediately - the direct
    match to a fiscal receipt. Signed by default (sign_pos_invoices).
  - Sales Invoice: general/credit invoice, may be issued unpaid. Off by
    default (sign_sales_invoices) - deliberately not signed yet, see
    docs/architecture.md. Turn on only once that's a considered decision,
    not a default.

Field names for everything this module touches (items, tax_id, posting_date,
customer_name, grand_total, ...) are identical between Sales Invoice and POS
Invoice - confirmed against this bench's ERPNext - so one payload builder
covers both.

Tax-rate mapping is intentionally simple for v1: it trusts each Item's own
eTIMS Taxation Type link as the single source of truth and does not try to
reconcile against ERPNext's Sales Taxes and Charges table. Rates come from
the `eTIMS Taxation Type` reference doctype (seeded from the one sample in
the sandbox collection - see patches/v0_0/seed_etims_reference_data.py) so
they're correctable by an admin without a code change, but they're still
unverified against KRA's real selectCodeList response - a wrong rate here is
a compliance bug, not a UI bug, so don't treat the seed as authoritative.
"""

import frappe
from frappe import _
from frappe.utils import flt, getdate, now_datetime

from royce_etims.utils.api_client import request as etims_request
from royce_etims.utils.id_mapping import get_etims_id
from royce_etims.utils.validation import validate_kra_pin

MAX_RETRY_COUNT = 5

# Which eTIMS Settings checkbox gates each doctype.
SIGN_SETTING_FIELD = {
	"POS Invoice": "sign_pos_invoices",
	"Sales Invoice": "sign_sales_invoices",
}

TAX_CODES = ("A", "B", "C", "D", "E")


def _get_tax_rates():
	"""Live lookup against eTIMS Taxation Type, replacing what used to be a
	hardcoded TAX_RATE_BY_CODE dict - same values today (seeded from the same
	one data point), but now correctable via the UI, not a deploy."""
	rates = dict.fromkeys(TAX_CODES, 0)
	for row in frappe.get_all("eTIMS Taxation Type", fields=["code", "rate"]):
		if row.code in rates:
			rates[row.code] = row.rate or 0
	return rates


def on_submit(doc, method=None):
	"""doc_events hook for both Sales Invoice and POS Invoice on_submit.
	Enqueues sync, never calls KRA inline."""
	if doc.get("prevent_etims_submission"):
		return

	if not frappe.db.exists("eTIMS Settings", doc.company):
		return

	settings = frappe.get_cached_doc("eTIMS Settings", doc.company)
	if settings.status != "Active":
		return

	sign_field = SIGN_SETTING_FIELD.get(doc.doctype)
	if not sign_field or not settings.get(sign_field):
		return

	branch_name = doc.etims_branch or settings.default_branch
	if not branch_name:
		frappe.throw(
			_("eTIMS is Active for {0} but no eTIMS Branch is set on this document, and the company has no Default Branch configured.").format(
				doc.company
			)
		)

	doc.db_set("etims_branch", branch_name, notify=False)
	doc.db_set("etims_status", "Pending", notify=False)

	frappe.enqueue(
		"royce_etims.etims_sync.receipt.sync_receipt",
		queue="short",
		enqueue_after_commit=True,
		doctype=doc.doctype,
		name=doc.name,
	)


def sync_receipt(doctype, name):
	doc = frappe.get_doc(doctype, name)
	branch = frappe.get_doc("eTIMS Branch", doc.etims_branch)

	if branch.device_status not in ("Registered", "Active"):
		doc.db_set("etims_status", "Failed", notify=False)
		doc.db_set("etims_error", _("eTIMS Branch {0} has no registered device.").format(branch.name), notify=False)
		return

	invc_no = _next_invoice_number(branch.name)

	try:
		payload = build_receipt_payload(doc, invc_no)
		data = etims_request(
			doc.company,
			"sendSalesTransaction",
			payload=payload,
			method="POST",
			branch=branch,
			reference_doctype=doctype,
			reference_name=doc.name,
		)
	except Exception as e:
		doc.db_set("etims_status", "Failed", notify=False)
		doc.db_set("etims_error", str(e)[:140], notify=False)
		doc.db_set("etims_invoice_number", invc_no, notify=False)  # number is consumed either way - never reused
		doc.db_set("etims_retry_count", (doc.etims_retry_count or 0) + 1, notify=False)
		frappe.db.commit()
		return

	doc.db_set("etims_status", "Sent", notify=False)
	doc.db_set("etims_invoice_number", invc_no, notify=False)
	doc.db_set("etims_raw_response", frappe.as_json(data), notify=False)
	doc.db_set("etims_error", "", notify=False)


def retry_failed_receipts():
	"""Scheduled safety net (see hooks.py cron) - chases Pending/Failed
	Sales/POS Invoices that never got a final Sent status, up to
	MAX_RETRY_COUNT attempts."""
	for doctype in SIGN_SETTING_FIELD:
		names = frappe.get_all(
			doctype,
			filters={
				"etims_status": ["in", ("Pending", "Failed")],
				"etims_retry_count": ["<", MAX_RETRY_COUNT],
				"docstatus": 1,
			},
			pluck="name",
			limit_page_length=50,
		)
		for name in names:
			frappe.enqueue(
				"royce_etims.etims_sync.receipt.sync_receipt",
				queue="short",
				doctype=doctype,
				name=name,
			)


def _next_invoice_number(branch_name):
	"""Atomic per-branch sequence - KRA requires strictly sequential invcNo.
	Shared across Sales Invoice and POS Invoice: KRA's sequence is per device
	(branch), not per ERPNext doctype."""
	row = frappe.db.sql(
		"SELECT last_invoice_no FROM `tabeTIMS Branch` WHERE name=%s FOR UPDATE",
		branch_name,
		as_dict=True,
	)
	if not row:
		frappe.throw(_("eTIMS Branch {0} not found.").format(branch_name))

	next_no = (row[0].last_invoice_no or 0) + 1
	frappe.db.set_value("eTIMS Branch", branch_name, "last_invoice_no", next_no, update_modified=False)
	return next_no


def build_receipt_payload(doc, invc_no):
	validate_kra_pin(doc.tax_id, label=_("Customer TIN"))

	items_payload = []
	taxbl = dict.fromkeys(TAX_CODES, 0.0)
	tax = dict.fromkeys(TAX_CODES, 0.0)
	posting_date = getdate(doc.posting_date)
	rates = _get_tax_rates()

	for idx, d in enumerate(doc.items, start=1):
		item = frappe.get_cached_doc("Item", d.item_code)
		if item.prevent_etims_submission:
			frappe.throw(
				_("Item {0} has 'Prevent eTIMS Submission' checked - remove it from this document.").format(
					d.item_code
				)
			)

		item_cd = get_etims_id(item, doc.company)
		if not item_cd:
			frappe.throw(
				_("Item {0} has no eTIMS Item Code assigned for {1} yet. Sync it before submitting this document.").format(
					d.item_code, doc.company
				)
			)

		code = item.etims_taxation_type_code or "A"
		rate = rates.get(code, 0)
		taxable_amt = flt(d.base_net_amount)
		tax_amt = flt(taxable_amt * rate / 100, 2)
		taxbl[code] += taxable_amt
		tax[code] += tax_amt

		items_payload.append(
			{
				"itemSeq": idx,
				"itemCd": item_cd,
				"itemClsCd": item.etims_item_classification_code,
				"itemNm": item.item_name,
				"bcd": "",
				"pkgUnitCd": item.etims_packaging_unit_code,
				"pkg": 1,
				"qtyUnitCd": item.etims_quantity_unit_code,
				"qty": d.qty,
				"prc": d.base_rate,
				"splyAmt": d.base_amount,
				"dcRt": d.discount_percentage or 0,
				"dcAmt": d.discount_amount or 0,
				"taxblAmt": taxable_amt,
				"taxTyCd": code,
				"taxAmt": tax_amt,
				"totAmt": d.base_amount,
				"itemExprDt": None,
			}
		)

	payload = {
		"invcNo": invc_no,
		"orgInvcNo": 0,  # credit-note/orig-invoice linkage not handled yet - see docs/architecture.md open items
		"custTin": doc.tax_id or None,
		"custNm": doc.customer_name,
		"salesTyCd": "N",
		"rcptTyCd": "S",
		"pmtTyCd": "01",
		"salesSttsCd": "02",
		"cfmDt": posting_date.strftime("%Y%m%d") + "000000",
		"salesDt": posting_date.strftime("%Y%m%d"),
		"stockRlsDt": None,
		"cnclReqDt": None,
		"cnclDt": None,
		"rfdDt": None,
		"rfdRsnCd": None,
		"totItemCnt": len(items_payload),
		**{f"taxblAmt{c}": taxbl[c] for c in TAX_CODES},
		**{f"taxRt{c}": rates[c] for c in TAX_CODES},
		**{f"taxAmt{c}": tax[c] for c in TAX_CODES},
		"totTaxblAmt": sum(taxbl.values()),
		"totTaxAmt": sum(tax.values()),
		"totAmt": doc.grand_total,
		"prchrAcptcYn": "N",
		"remark": None,
		"regrId": doc.owner,
		"regrNm": doc.owner,
		"modrId": doc.modified_by,
		"modrNm": doc.modified_by,
		"itemList": items_payload,
	}
	return payload
