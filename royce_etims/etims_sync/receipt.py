# Copyright (c) 2026, Royce Technologies LTD and contributors
# For license information, please see license.txt

"""Async Sales Invoice / POS Invoice -> KRA sendSalesTransaction ("issue a
receipt"), per docs/architecture.md section 4: submission in ERPNext never
blocks on KRA; sync happens as a background job with a visible status and a
scheduled retry sweep for failures.

KRA's OSCU API has one call for this - sendSalesTransaction. This name was
originally in this codebase (from the Postman collection royce_etims was
first built from), then changed to saveTrnsSalesOsdc during a "correction"
that turned out to be itself wrong - confirmed back to sendSalesTransaction
2026-09-05 against KRA's own official GavaConnect developer portal docs
(https://developer.go.ke/apis/KRA-ETIMS-SBX). See docs/architecture.md for
the full, embarrassing correction history. There's no separate "sign
invoice" vs "sign receipt" endpoint; the payload itself carries a nested
`receipt` sub-object. What we actually control is which
ERPNext event triggers that one call. Two doctypes can trigger it, gated
independently on eTIMS Settings:

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
from frappe.contacts.doctype.address.address import get_address_display
from frappe.utils import flt, getdate, now_datetime

from royce_etims.utils.api_client import request as etims_request
from royce_etims.utils.config import PRODUCTION_QR_VERIFY_BASE_URL, SANDBOX_QR_VERIFY_BASE_URL
from royce_etims.utils.id_mapping import get_etims_id
from royce_etims.utils.qr_code import build_verification_url, generate_qr_data_uri
from royce_etims.utils.sequence import lock_branch, send_in_sequence
from royce_etims.utils.validation import validate_kra_pin

MAX_RETRY_COUNT = 5

# Which eTIMS Settings checkbox gates each doctype.
SIGN_SETTING_FIELD = {
	"POS Invoice": "sign_pos_invoices",
	"Sales Invoice": "sign_sales_invoices",
}

TAX_CODES = ("A", "B", "C", "D", "E")

TRADE_NAME_MAX_LENGTH = 20


def _get_tax_rates():
	"""Live lookup against eTIMS Taxation Type, replacing what used to be a
	hardcoded TAX_RATE_BY_CODE dict - same values today (seeded from the same
	one data point), but now correctable via the UI, not a deploy.

	A band KRA has disabled reports rate 0 - CONFIRMED 2026-10-26 with E
	(VAT 8%, useYn "N"): "Rule taxRtE failed: Tax rate mismatch. Expected:
	0.00, Found: 8.0"."""
	rates = dict.fromkeys(TAX_CODES, 0)
	for row in frappe.get_all("eTIMS Taxation Type", fields=["code", "rate", "disabled"]):
		if row.code in rates and not row.disabled:
			rates[row.code] = row.rate or 0
	return rates


def on_submit(doc, method=None):
	"""doc_events hook for both Sales Invoice and POS Invoice on_submit.
	Enqueues sync, never calls KRA inline."""
	if doc.get("royce_prevent_etims_submission"):
		return

	if not frappe.db.exists("eTIMS Settings", doc.company):
		return

	settings = frappe.get_cached_doc("eTIMS Settings", doc.company)
	if settings.status != "Active":
		return

	sign_field = SIGN_SETTING_FIELD.get(doc.doctype)
	if not sign_field or not settings.get(sign_field):
		return

	branch_name = doc.royce_etims_branch or settings.default_branch
	if not branch_name:
		frappe.throw(
			_(
				"eTIMS is Active for {0} but no eTIMS Branch is set on this document, and the company has no Default Branch configured."
			).format(doc.company)
		)

	if doc.get("is_return") and not doc.get("royce_etims_refund_reason"):
		frappe.throw(_("Select an eTIMS Refund Reason - KRA requires one on every credit note."))

	doc.db_set("royce_etims_branch", branch_name, notify=False)
	doc.db_set("royce_etims_status", "Pending", notify=False)

	frappe.enqueue(
		"royce_etims.etims_sync.receipt.sync_receipt",
		queue="short",
		enqueue_after_commit=True,
		doctype=doc.doctype,
		name=doc.name,
	)


def sync_receipt(doctype, name):
	doc = frappe.get_doc(doctype, name)
	branch = frappe.get_doc("eTIMS Branch", doc.royce_etims_branch)
	settings = frappe.get_cached_doc("eTIMS Settings", doc.company)

	if branch.device_status not in ("Registered", "Active"):
		doc.db_set("royce_etims_status", "Failed", notify=False)
		doc.db_set(
			"royce_etims_error",
			_("eTIMS Branch {0} has no registered device.").format(branch.name),
			notify=False,
		)
		return

	lock_branch(branch.name)
	# A locking read: a plain one would see this transaction's older snapshot.
	if frappe.db.get_value(doctype, name, "royce_etims_status", for_update=True) == "Sent":
		frappe.db.rollback()
		return  # another job (e.g. the retry sweep) already signed it

	def send(invc_no):
		return etims_request(
			doc.company,
			"sendSalesTransaction",
			payload=build_receipt_payload(doc, invc_no, settings),
			method="POST",
			branch=branch,
			reference_doctype=doctype,
			reference_name=doc.name,
		)

	try:
		invc_no, data = send_in_sequence(branch.name, "last_invoice_no", send)
	except Exception as e:
		# No invoice number is recorded: KRA didn't accept one, so the next
		# attempt (this invoice's retry, or another invoice) reuses it.
		doc.db_set("royce_etims_status", "Failed", notify=False)
		doc.db_set("royce_etims_error", str(e)[:140], notify=False)
		doc.db_set("royce_etims_retry_count", (doc.royce_etims_retry_count or 0) + 1, notify=False)
		frappe.db.commit()
		return

	_apply_success(doc, invc_no, data, settings, branch)


def _apply_success(doc, invc_no, data, settings, branch):
	"""Store sendSalesTransaction's response and generate the receipt QR code.

	Envelope: unwraps the same "responseBody" wrapper CONFIRMED for real
	2026-09-10 against /initialize (see eTIMS Branch.register_device()) -
	resultCd/data sit one level inside responseBody, not at the top, for at
	least that endpoint. What's NOT yet confirmed for THIS endpoint
	specifically is whether the business fields (rcptSign, curRcptNo, ...)
	sit directly under responseBody.data (this guess, and what
	navariltd/kenya-compliance's shape - the origin of these field names -
	implies) or nested one level further under an "info" key the way
	/initialize's device fields turned out to be. Verify against the first
	real signed receipt and correct this comment either way - don't let it
	go stale."""
	body = (data or {}).get("responseBody") or data or {}
	info = body.get("data") or {}
	receipt_signature = info.get("rcptSign")

	doc.db_set("royce_etims_status", "Sent", notify=False)
	doc.db_set("royce_etims_invoice_number", invc_no, notify=False)
	doc.db_set("royce_etims_error", "", notify=False)
	doc.db_set("royce_etims_receipt_signature", receipt_signature, notify=False)
	doc.db_set("royce_etims_current_receipt_number", info.get("curRcptNo"), notify=False)
	doc.db_set("royce_etims_total_receipt_number", info.get("totRcptNo"), notify=False)
	doc.db_set("royce_etims_internal_data", info.get("intrlData"), notify=False)
	doc.db_set("royce_etims_control_unit_datetime", info.get("sdcDateTime"), notify=False)

	if not receipt_signature:
		# Success per resultCd, but no signature to build a QR from - log and
		# move on rather than block the whole sync on a QR code specifically.
		frappe.log_error(title=f"eTIMS: no rcptSign in successful response for {doc.name}")
		return

	qr_verify_base_url = (
		SANDBOX_QR_VERIFY_BASE_URL if settings.environment == "Sandbox" else PRODUCTION_QR_VERIFY_BASE_URL
	)
	if not qr_verify_base_url:
		return

	verification_url = build_verification_url(
		qr_verify_base_url, settings.tin, branch.bhf_id, receipt_signature
	)
	doc.db_set("royce_etims_qr_verification_url", verification_url, notify=False)
	doc.db_set("royce_etims_qr_code", generate_qr_data_uri(verification_url), notify=False)


def retry_failed_receipts():
	"""Scheduled safety net (see hooks.py cron) - chases Pending/Failed
	Sales/POS Invoices that never got a final Sent status, up to
	MAX_RETRY_COUNT attempts."""
	for doctype in SIGN_SETTING_FIELD:
		names = frappe.get_all(
			doctype,
			filters={
				"royce_etims_status": ["in", ("Pending", "Failed")],
				"royce_etims_retry_count": ["<", MAX_RETRY_COUNT],
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


def _build_receipt_block(doc, settings):
	"""KRA's nested `receipt` object - drives what actually prints on the
	fiscal receipt (trade name, address, header/footer messages), separate
	from the top-level invoice/tax fields. Confirmed real field names from
	eTIMS-OSCU-Integrator-Automated-Testing-Sandbox.json (the same Postman
	collection docs/architecture.md's 2026-09-05 correction confirmed is the
	real, currently-correct API surface) - this whole object was previously
	missing from the payload entirely, despite this module's own docstring
	claiming it existed.

	trdeNm/adrs prefer real per-document data (Company name, the invoice's
	own Company Address) over the eTIMS Settings fallbacks, so a company with
	multiple addresses/trade names on its invoices isn't flattened to one
	fixed value.
	"""
	trade_name = settings.get("receipt_trade_name") or frappe.db.get_value(
		"Company", doc.company, "company_name"
	)

	address = ""
	if doc.get("company_address"):
		address = get_address_display(doc.company_address) or ""
	elif settings.get("receipt_address"):
		address = settings.receipt_address

	return {
		"custTin": doc.tax_id or None,
		"custMblNo": doc.get("contact_mobile") or None,
		# Reprint sequence, assumed 1 (original print) - unconfirmed against a
		# real response, but there's no reprint flow in this app yet for it
		# to differ. Revisit if/when reprints are ever supported.
		"rptNo": 1,
		"rcptPbctDt": now_datetime().strftime("%Y%m%d%H%M%S"),
		# KRA caps this at 20 characters - CONFIRMED 2026-10-26: "<receipt>
		# <trdeNm> : length must be between 0 and 20" for "Royce Technologies Ltd".
		"trdeNm": (trade_name or "")[:TRADE_NAME_MAX_LENGTH],
		"adrs": address,
		"topMsg": settings.get("receipt_top_message") or "",
		"btmMsg": settings.get("receipt_bottom_message") or "",
		"prchrAcptcYn": "N",
	}


def _original_invoice_number(doc):
	"""KRA invcNo of the invoice a credit note returns against. The original
	must be signed first - until it is, this raises and the credit note stays
	Failed for the retry sweep to pick up once it has a number."""
	if not doc.get("return_against"):
		frappe.throw(_("Credit note {0} has no Return Against invoice to reference.").format(doc.name))

	status, number = frappe.db.get_value(
		doc.doctype, doc.return_against, ["royce_etims_status", "royce_etims_invoice_number"]
	) or (None, None)
	if status != "Sent" or not number:
		frappe.throw(
			_(
				"Original invoice {0} isn't signed by eTIMS yet, so this credit note can't reference it."
			).format(doc.return_against)
		)
	return number


def build_receipt_payload(doc, invc_no, settings):
	validate_kra_pin(doc.tax_id, label=_("Customer TIN"))

	items_payload = []
	taxbl = dict.fromkeys(TAX_CODES, 0.0)
	tax = dict.fromkeys(TAX_CODES, 0.0)
	posting_date = getdate(doc.posting_date)
	rates = _get_tax_rates()

	for idx, d in enumerate(doc.items, start=1):
		item = frappe.get_cached_doc("Item", d.item_code)
		if item.royce_prevent_etims_submission:
			frappe.throw(
				_("Item {0} has 'Prevent eTIMS Submission' checked - remove it from this document.").format(
					d.item_code
				)
			)

		item_cd = get_etims_id(item, doc.company)
		if not item_cd:
			frappe.throw(
				_(
					"Item {0} has no eTIMS Item Code assigned for {1} yet. Sync it before submitting this document."
				).format(d.item_code, doc.company)
			)

		code = item.royce_etims_taxation_type_code or "A"
		rate = rates.get(code, 0)

		# KRA's OSCU expects tax-INCLUSIVE amounts - CONFIRMED 2026-09-23 by a
		# real sendSalesTransaction rejection: a line sent as prc/totAmt 1000,
		# taxblAmt 1000 (tax added on top: taxAmt 160) came back
		# "Invalid taxblAmt on item: 1. Expected: 862.07, But Found: 1000.00"
		# - 862.07 x 1.16 = 1000.00, i.e. the tax portion must be backed OUT
		# of the line total, not added on top. Matches standard Kenyan retail
		# VAT-inclusive pricing. gross_amt (the amount actually charged -
		# same value used for prc/splyAmt/totAmt below) is now the basis;
		# taxblAmt/taxAmt are derived from it, not the other way around.
		#
		# Still open: whether this ERPNext site's own Kenya VAT tax template
		# is itself configured tax-inclusive (in which case d.base_amount
		# already IS this gross, VAT-inclusive figure, and this fix is
		# complete) or tax-exclusive (in which case d.base_amount is a
		# pre-tax subtotal, and reconciling against ERPNext's own Sales Taxes
		# and Charges table - deliberately NOT done here, see this module's
		# top docstring - would be needed before this is correct for a real
		# invoice). Confirm before relying on this for a real client invoice.
		# ERPNext stores a return with negative qty/amounts; KRA wants the
		# same positive figures with rcptTyCd "R" saying it's a credit note.
		gross_amt = abs(flt(d.base_amount))
		taxable_amt = flt(gross_amt / (1 + rate / 100), 2) if rate else gross_amt
		tax_amt = flt(gross_amt - taxable_amt, 2)
		taxbl[code] += taxable_amt
		tax[code] += tax_amt

		items_payload.append(
			{
				"itemSeq": idx,
				"itemCd": item_cd,
				"itemClsCd": item.royce_etims_item_classification_code,
				"itemNm": item.item_name,
				"bcd": "",
				"pkgUnitCd": item.royce_etims_packaging_unit_code,
				"pkg": 1,
				"qtyUnitCd": item.royce_etims_quantity_unit_code,
				"qty": abs(flt(d.qty)),
				"prc": abs(flt(d.base_rate)),
				"splyAmt": gross_amt,
				"dcRt": d.discount_percentage or 0,
				"dcAmt": abs(flt(d.discount_amount)),
				# Compulsory-insurance fields (motor vehicles etc.) - null in
				# the confirmed sample payload too. Item has no insurance data
				# to source these from yet; sent explicitly rather than
				# omitted in case KRA's validator expects the keys present.
				"isrccCd": None,
				"isrccNm": None,
				"isrcRt": None,
				"isrcAmt": None,
				"taxblAmt": taxable_amt,
				"taxTyCd": code,
				"taxAmt": tax_amt,
				"totAmt": gross_amt,
				"itemExprDt": None,
			}
		)

	is_return = bool(doc.get("is_return"))
	payload = {
		"invcNo": invc_no,
		"orgInvcNo": _original_invoice_number(doc) if is_return else 0,
		"custTin": doc.tax_id or None,
		"custNm": doc.customer_name,
		"salesTyCd": "N",
		"rcptTyCd": "R" if is_return else "S",
		"pmtTyCd": "01",
		"salesSttsCd": "02",
		"cfmDt": posting_date.strftime("%Y%m%d") + "000000",
		"salesDt": posting_date.strftime("%Y%m%d"),
		# Required - CONFIRMED 2026-10-26: "StockRlsDt cannot be null or empty".
		"stockRlsDt": posting_date.strftime("%Y%m%d") + "000000",
		"cnclReqDt": None,
		"cnclDt": None,
		"rfdDt": posting_date.strftime("%Y%m%d") + "000000" if is_return else None,
		"rfdRsnCd": doc.get("royce_etims_refund_reason") if is_return else None,
		"totItemCnt": len(items_payload),
		**{f"taxblAmt{c}": taxbl[c] for c in TAX_CODES},
		**{f"taxRt{c}": rates[c] for c in TAX_CODES},
		**{f"taxAmt{c}": tax[c] for c in TAX_CODES},
		"totTaxblAmt": sum(taxbl.values()),
		"totTaxAmt": sum(tax.values()),
		"totAmt": abs(flt(doc.grand_total)),
		"prchrAcptcYn": "N",
		"remark": None,
		"regrId": doc.owner,
		"regrNm": doc.owner,
		"modrId": doc.modified_by,
		"modrNm": doc.modified_by,
		"itemList": items_payload,
		"receipt": _build_receipt_block(doc, settings),
	}
	return payload
