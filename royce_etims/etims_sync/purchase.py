# Copyright (c) 2026, Royce Technologies LTD and contributors
# For license information, please see license.txt

"""Purchases from eTIMS suppliers (Go-Live cases 15 and 16).

Every sale another taxpayer signs with our PIN as the customer reaches KRA as
our purchase. We fetch them (getPurchaseTransactionInfo) into an eTIMS
Purchase inbox, turn one into a Purchase Invoice, and when that invoice is
submitted confirm the purchase with KRA (sendPurchaseTransactionInfo, status
02 Approved). Confirming matters for stock: KRA's sellable balance only grows
by confirmed purchases - a Purchase Receipt's stock-in (type 02) doesn't add
to it - FOUND 2026-10-29 (docs/kra-go-live-test.md). Without this, an eTIMS
client's sales of bought-in stock are refused once KRA thinks it's sold out.

What was confirmed live on 2026-10-29 and is followed here:
- the confirmation carries OUR itemCd/itemClsCd/itemNm per line, plus the
  supplier's as spplrItemCd/spplrItemClsCd/spplrItemNm. Mapping supplier item
  -> our item is ours: it's remembered in ERPNext's own Item > Supplier Items
  table (supplier + supplier part no = the supplier's KRA item code), so the
  next invoice from the same supplier matches itself;
- KRA recomputes amounts from qty x prc the way it does for sales (it refused
  its own list's rounded 8308 for a 9637.24 line), so the tax split uses the
  same kra_split as receipts;
- purchases have their own number sequence (KRA's lastPchsInvcNo), kept on
  eTIMS Branch.last_purchase_no and moved only when KRA accepts.

Rejecting (status 04 Canceled, code class 34) is for a purchase that isn't
ours. Not yet tried live - see docs/kra-go-live-test.md.
"""

import json
from decimal import Decimal

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, now_datetime, nowdate

from royce_etims.etims_sync.tax_lines import exact_amount, kra_split, line_amount, money
from royce_etims.utils.api_client import get_settings
from royce_etims.utils.api_client import request as etims_request
from royce_etims.utils.id_mapping import get_etims_id
from royce_etims.utils.lookups import FULL_HISTORY
from royce_etims.utils.sequence import lock_branch, send_in_sequence

APPROVED = "02"
CANCELED = "04"
TAX_CODES = ("A", "B", "C", "D", "E")
MAX_RETRY_COUNT = 5

# Grand total difference allowed between the Purchase Invoice and KRA's record:
# ERPNext and KRA each round VAT on their own.
TOTAL_TOLERANCE = 1.0

# kenyan_accountant's purchase template with VAT inside the price - KRA's prc is VAT-inclusive.
INCLUSIVE_PURCHASE_TEMPLATE = "KE - Standard VAT 16% Inclusive - Purchase"
# Claimable Item Tax Template per band, by kenyan_accountant's titles.
BAND_ITEM_TAX_TEMPLATE = {
	"A": "KE Exempt",
	"B": "KE Standard 16%",
	"C": "KE Zero Rated",
	"D": "KE Exempt",
	"E": "KE Reduced 8%",
}


def _active_companies():
	return frappe.get_all(
		"eTIMS Settings", filters={"status": "Active", "default_branch": ["is", "set"]}, pluck="name"
	)


def _kra_date(value):
	"""KRA's yyyyMMdd (or yyyyMMddHHmmss) -> date."""
	value = str(value or "")
	return getdate(f"{value[:4]}-{value[4:6]}-{value[6:8]}") if len(value) >= 8 else None


# --- Fetch -------------------------------------------------------------------


@frappe.whitelist()
def fetch_purchases(company):
	"""Pull new purchases from KRA into the inbox. Returns how many were new."""
	frappe.has_permission("eTIMS Purchase", "create", throw=True)
	settings = get_settings(company)
	if not settings.default_branch:
		frappe.throw(_("Set a Default Branch on eTIMS Settings for {0} first.").format(company))
	branch = frappe.get_doc("eTIMS Branch", settings.default_branch)
	started = now_datetime()
	since = (
		branch.purchases_fetched_until.strftime("%Y%m%d%H%M%S")
		if branch.purchases_fetched_until
		else FULL_HISTORY
	)

	data = etims_request(
		company,
		"getPurchaseTransactionInfo",
		payload={"tin": settings.tin, "bhfId": branch.bhf_id, "lastReqDt": since},
		branch=branch,
		reference_doctype="eTIMS Settings",
		reference_name=company,
		allow_empty=True,
	)
	body = (data or {}).get("responseBody") or data or {}
	rows = (body.get("data") or {}).get("saleList") or []

	new = sum(1 for row in rows if upsert_purchase(company, branch.name, row))
	branch.db_set("purchases_fetched_until", started, update_modified=False)
	frappe.db.commit()  # nosemgrep
	return new


def fetch_all_companies():
	"""Hourly: fetch new purchases for every active company."""
	for company in _active_companies():
		try:
			fetch_purchases(company)
		except Exception:
			frappe.db.rollback()
			frappe.log_error(title=f"eTIMS: fetching purchases for {company} failed")


def purchase_key(company, row):
	return {
		"company": company,
		"supplier_tin": row.get("spplrTin"),
		"supplier_bhf_id": row.get("spplrBhfId"),
		"supplier_invoice_no": cint(row.get("spplrInvcNo")),
		"receipt_type": row.get("rcptTyCd") or "S",
	}


def upsert_purchase(company, branch, row):
	"""Insert a purchase KRA lists, once. Returns True when it was new."""
	key = purchase_key(company, row)
	if frappe.db.exists("eTIMS Purchase", key):
		return False

	supplier = find_supplier(row.get("spplrTin"))
	doc = frappe.get_doc(
		{
			"doctype": "eTIMS Purchase",
			**key,
			"branch": branch,
			"supplier_name": row.get("spplrNm"),
			"supplier": supplier,
			"supplier_sdc_id": row.get("spplrSdcId"),
			"supplier_mrc_no": row.get("spplrMrcNo"),
			"sales_date": _kra_date(row.get("salesDt")),
			"payment_type": row.get("pmtTyCd"),
			"total_taxable": flt(row.get("totTaxblAmt")),
			"total_tax": flt(row.get("totTaxAmt")),
			"total_amount": flt(row.get("totAmt")),
			"raw": json.dumps(row, indent=1),
			"items": [
				{
					"item": match_item(supplier, line.get("itemCd")),
					"item_seq": cint(line.get("itemSeq")),
					"supplier_item_code": line.get("itemCd"),
					"supplier_item_class": line.get("itemClsCd"),
					"supplier_item_name": line.get("itemNm"),
					"package_unit": line.get("pkgUnitCd"),
					"package": flt(line.get("pkg")),
					"qty_unit": line.get("qtyUnitCd"),
					"qty": flt(line.get("qty")),
					"price": flt(line.get("prc")),
					"supply_amount": flt(line.get("splyAmt")),
					"discount_rate": flt(line.get("dcRt")),
					"discount_amount": flt(line.get("dcAmt")),
					"tax_type": line.get("taxTyCd"),
					"taxable_amount": flt(line.get("taxblAmt")),
					"tax_amount": flt(line.get("taxAmt")),
					"total_amount": flt(line.get("totAmt")),
				}
				for line in row.get("itemList") or []
			],
		}
	)
	doc.insert(ignore_permissions=True)
	return True


def find_supplier(tin):
	if not tin:
		return None
	return frappe.db.get_value("Supplier", {"tax_id": tin, "disabled": 0}, "name")


def match_item(supplier, supplier_item_code):
	"""Our Item for a supplier's KRA item code, from Item > Supplier Items."""
	if not supplier or not supplier_item_code:
		return None
	return frappe.db.get_value(
		"Item Supplier",
		{"supplier": supplier, "supplier_part_no": supplier_item_code, "parenttype": "Item"},
		"parent",
	)


def refresh_status(doc):
	"""eTIMS Purchase validate: fill what can be matched now (a supplier or an
	item mapping added since the purchase was fetched), then New until every
	line has an Item, Ready after."""
	if doc.status not in ("New", "Ready", "Failed"):
		return
	doc.supplier = doc.supplier or find_supplier(doc.supplier_tin)
	for row in doc.items:
		row.item = row.item or match_item(doc.supplier, row.supplier_item_code)
	if doc.status in ("New", "Ready"):
		doc.status = "Ready" if doc.items and all(row.item for row in doc.items) else "New"


# --- Purchase Invoice --------------------------------------------------------


@frappe.whitelist()
def create_purchase_invoice(name):
	"""Draft Purchase Invoice for an inbox purchase, with KRA's quantities and
	VAT-inclusive prices. Remembers each line's item for this supplier."""
	doc = frappe.get_doc("eTIMS Purchase", name)
	doc.check_permission("write")
	frappe.has_permission("Purchase Invoice", "create", throw=True)

	if (
		doc.purchase_invoice
		and frappe.db.get_value("Purchase Invoice", doc.purchase_invoice, "docstatus") != 2
	):
		return doc.purchase_invoice
	if doc.status in ("Confirmed", "Rejected"):
		frappe.throw(_("This purchase is already {0} with KRA.").format(doc.status))
	if doc.receipt_type != "S":
		frappe.throw(_("Only supplier invoices can be turned into a Purchase Invoice yet, not credit notes."))

	unmatched = [row.supplier_item_name for row in doc.items if not row.item]
	if unmatched:
		frappe.throw(_("Pick your Item for: {0}").format(", ".join(unmatched)), title=_("Items not matched"))

	supplier = doc.supplier or find_supplier(doc.supplier_tin) or _create_supplier(doc)
	doc.supplier = supplier
	for row in doc.items:
		remember_item(row.item, supplier, row.supplier_item_code)

	pi = frappe.new_doc("Purchase Invoice")
	pi.update(
		{
			"company": doc.company,
			"supplier": supplier,
			"posting_date": nowdate(),
			"bill_no": str(doc.supplier_invoice_no),
			"bill_date": doc.sales_date,
			"royce_etims_purchase": doc.name,
		}
	)
	template = frappe.db.get_value(
		"Purchase Taxes and Charges Template",
		{"title": INCLUSIVE_PURCHASE_TEMPLATE, "company": doc.company, "disabled": 0},
		"name",
	)
	for row in doc.items:
		pi.append("items", {"item_code": row.item, "qty": flt(row.qty), "rate": unit_price(row)})
	if template:
		from erpnext.controllers.accounts_controller import get_taxes_and_charges

		pi.taxes_and_charges = template
		pi.set("taxes", get_taxes_and_charges("Purchase Taxes and Charges Template", template))
	pi.set_missing_values()
	# After set_missing_values, which fills each line's tax template from the
	# Item: on a purchase the VAT is what the supplier charged, so the
	# supplier's band decides it, not our item's own band.
	for line, row in zip(pi.items, doc.items, strict=True):
		line.item_tax_template = _item_tax_template(doc.company, row.tax_type) or line.item_tax_template
		line.item_tax_rate = _item_tax_rate_json(line.item_tax_template)
	pi.insert()

	doc.purchase_invoice = pi.name
	doc.status = "Invoiced"
	doc.error = ""
	doc.save(ignore_permissions=True)
	return pi.name


def unit_price(row):
	"""VAT-inclusive price per unit after discount, from qty x prc. KRA's list
	carries a splyAmt that isn't qty x prc (8308 for a 9637.24 line, seen
	2026-10-29 and again 2026-11-18), so it's never used."""
	qty = flt(row.qty)
	if not qty:
		return 0
	return flt(row.price) - flt(row.discount_amount) / qty


def _item_tax_rate_json(template):
	if not template:
		return None
	rates = {
		d.tax_type: flt(d.tax_rate)
		for d in frappe.get_all(
			"Item Tax Template Detail", filters={"parent": template}, fields=["tax_type", "tax_rate"]
		)
	}
	return json.dumps(rates)


def _item_tax_template(company, band):
	title = BAND_ITEM_TAX_TEMPLATE.get(band)
	if not title:
		return None
	return frappe.db.get_value(
		"Item Tax Template", {"title": title, "company": company, "disabled": 0}, "name"
	)


def _create_supplier(doc):
	group = frappe.db.get_single_value("Buying Settings", "supplier_group") or frappe.db.get_value(
		"Supplier Group", {"is_group": 0}, "name"
	)
	supplier = frappe.get_doc(
		{
			"doctype": "Supplier",
			"supplier_name": doc.supplier_name or doc.supplier_tin,
			"tax_id": doc.supplier_tin,
			"supplier_group": group,
			"supplier_type": "Company",
			"country": "Kenya",
		}
	)
	supplier.insert()
	return supplier.name


def remember_item(item_code, supplier, supplier_item_code):
	"""Add (supplier, supplier's KRA code) to the Item's Supplier Items once."""
	if not supplier_item_code or match_item(supplier, supplier_item_code) == item_code:
		return
	item = frappe.get_doc("Item", item_code)
	item.append("supplier_items", {"supplier": supplier, "supplier_part_no": supplier_item_code})
	item.save(ignore_permissions=True)


def _purchase_for(pi):
	name = pi.get("royce_etims_purchase")
	return frappe.get_doc("eTIMS Purchase", name) if name else None


def before_submit(pi, method=None):
	"""Purchase Invoice before_submit: the books must say what KRA says."""
	purchase = _purchase_for(pi)
	if not purchase:
		return
	if purchase.status in ("Confirmed", "Rejected"):
		frappe.throw(_("eTIMS Purchase {0} is already {1}.").format(purchase.name, purchase.status))

	kra_qty, our_qty = {}, {}
	for row in purchase.items:
		kra_qty[row.item] = kra_qty.get(row.item, 0) + flt(row.qty)
	for row in pi.items:
		our_qty[row.item_code] = our_qty.get(row.item_code, 0) + flt(row.qty)
	differ = [
		f"{code}: KRA {flt(kra_qty.get(code))}, invoice {flt(our_qty.get(code))}"
		for code in sorted(set(kra_qty) | set(our_qty), key=str)
		if abs(flt(kra_qty.get(code)) - flt(our_qty.get(code))) > 0.0001
	]
	if differ:
		frappe.throw(
			_(
				"The quantities differ from the supplier's KRA invoice, which KRA will confirm as it is: {0}"
			).format("; ".join(differ)),
			title=_("Doesn't match KRA"),
		)
	if abs(flt(pi.grand_total) - flt(purchase.total_amount)) > TOTAL_TOLERANCE:
		frappe.throw(
			_("This invoice totals {0} but the supplier's KRA invoice is {1}. Check prices and VAT.").format(
				flt(pi.grand_total, 2), flt(purchase.total_amount, 2)
			),
			title=_("Doesn't match KRA"),
		)


def on_submit(pi, method=None):
	purchase = _purchase_for(pi)
	if not purchase:
		return
	purchase.db_set({"purchase_invoice": pi.name, "status": "Invoiced"}, update_modified=False)
	_enqueue_confirm(purchase.name)


def before_cancel(pi, method=None):
	purchase = _purchase_for(pi)
	if purchase and purchase.status == "Confirmed":
		frappe.throw(
			_("KRA has this purchase confirmed (no. {0}), so the invoice can't be cancelled.").format(
				purchase.kra_purchase_no
			),
			title=_("Confirmed with KRA eTIMS"),
		)


def on_cancel(pi, method=None):
	_release(pi)


def on_trash(pi, method=None):
	_release(pi)


def _release(pi):
	"""A draft deleted or an unconfirmed invoice cancelled: the inbox purchase
	can be invoiced again."""
	purchase = _purchase_for(pi)
	if purchase and purchase.status in ("Invoiced", "Failed") and purchase.purchase_invoice == pi.name:
		purchase.db_set({"purchase_invoice": None, "status": "New", "retry_count": 0}, update_modified=False)
		purchase.reload()
		purchase.save(ignore_permissions=True)  # back to Ready if every line is matched


# --- Confirm / reject with KRA ------------------------------------------------


def _enqueue_confirm(name):
	frappe.enqueue(
		"royce_etims.etims_sync.purchase.confirm",
		queue="short",
		enqueue_after_commit=True,
		job_id=f"royce_etims_purchase::{name}",
		deduplicate=True,
		name=name,
	)


def _rates(purchase):
	"""Band rates as the supplier's signed invoice reported them."""
	raw = json.loads(purchase.raw or "{}")
	rates = {}
	for code in TAX_CODES:
		value = raw.get(f"taxRt{code}")
		if value is None:
			value = frappe.db.get_value("eTIMS Taxation Type", code, "rate") or 0
		rates[code] = flt(value)
	return rates


def build_payload(purchase, invc_no, status=APPROVED):
	rates = _rates(purchase)
	taxbl = dict.fromkeys(TAX_CODES, 0.0)
	tax = dict.fromkeys(TAX_CODES, 0.0)
	items, total = [], 0.0

	for row in purchase.items:
		item = frappe.get_cached_doc("Item", row.item) if row.item else None
		item_cd = get_etims_id(item, purchase.company) if item else None
		if not item_cd:
			# Rejecting too: KRA refuses a line whose itemCd isn't ours - CONFIRMED
			# 2026-11-18, "Item KE1NTXU1000003 ... does not exist in your inventory".
			frappe.throw(
				_("Item {0} isn't registered with KRA for {1}. Sync it to eTIMS, then retry.").format(
					row.item or row.supplier_item_name, purchase.company
				)
			)
		band = row.tax_type or "B"
		qty, prc = flt(row.qty), flt(row.price)
		base = exact_amount(qty, prc) - Decimal(str(flt(row.discount_amount)))
		taxable_amt, tax_amt = kra_split(base, rates.get(band, 0))
		line_total = money(Decimal(str(taxable_amt)) + Decimal(str(tax_amt)))
		taxbl[band] += taxable_amt
		tax[band] += tax_amt
		total += line_total
		items.append(
			{
				"itemSeq": len(items) + 1,
				"itemCd": item_cd or row.supplier_item_code,
				"itemClsCd": (item.get("royce_etims_item_classification_code") if item else None)
				or row.supplier_item_class,
				"itemNm": item.item_name if item else row.supplier_item_name,
				"bcd": "",
				"spplrItemClsCd": row.supplier_item_class,
				"spplrItemCd": row.supplier_item_code,
				"spplrItemNm": row.supplier_item_name,
				"pkgUnitCd": (item.get("royce_etims_packaging_unit_code") if item else None)
				or row.package_unit,
				"pkg": flt(row.package) or 1,
				"qtyUnitCd": (item.get("royce_etims_quantity_unit_code") if item else None) or row.qty_unit,
				"qty": qty,
				"prc": prc,
				"splyAmt": line_amount(qty, prc),
				"dcRt": flt(row.discount_rate),
				"dcAmt": flt(row.discount_amount),
				"taxblAmt": taxable_amt,
				"taxTyCd": band,
				"taxAmt": tax_amt,
				"totAmt": line_total,
				"itemExprDt": None,
			}
		)

	now = now_datetime().strftime("%Y%m%d%H%M%S")
	sales_date = getdate(purchase.sales_date).strftime("%Y%m%d") if purchase.sales_date else now[:8]
	return {
		"invcNo": invc_no,
		"orgInvcNo": 0,
		"spplrTin": purchase.supplier_tin,
		"spplrBhfId": purchase.supplier_bhf_id,
		"spplrNm": purchase.supplier_name,
		"spplrInvcNo": cint(purchase.supplier_invoice_no),
		"regTyCd": "A",
		"pchsTyCd": "N",
		"rcptTyCd": "P",
		"pmtTyCd": purchase.payment_type or "01",
		"pchsSttsCd": status,
		"cfmDt": now,
		"pchsDt": sales_date,
		"wrhsDt": None,
		"cnclReqDt": None,
		"cnclDt": now if status == CANCELED else None,
		"rfdDt": None,
		"totItemCnt": len(items),
		**{f"taxblAmt{c}": money(taxbl[c]) for c in TAX_CODES},
		**{f"taxRt{c}": rates[c] for c in TAX_CODES},
		**{f"taxAmt{c}": money(tax[c]) for c in TAX_CODES},
		"totTaxblAmt": money(sum(taxbl.values())),
		"totTaxAmt": money(sum(tax.values())),
		"totAmt": flt(total, 2),
		"remark": None,
		"regrNm": purchase.owner,
		"regrId": purchase.owner,
		"modrNm": frappe.session.user,
		"modrId": frappe.session.user,
		"itemList": items,
	}


def _send(name, status):
	"""Send the purchase to KRA with `status` under the branch's next purchase
	number. Returns True on success; records the failure and returns False."""
	purchase = frappe.get_doc("eTIMS Purchase", name)
	lock_branch(purchase.branch)
	current = frappe.db.get_value("eTIMS Purchase", name, "status", for_update=True)
	if current in ("Confirmed", "Rejected"):
		frappe.db.rollback()
		return True

	def send(invc_no):
		return etims_request(
			purchase.company,
			"sendPurchaseTransactionInfo",
			payload=build_payload(purchase, invc_no, status),
			branch=purchase.branch,
			reference_doctype="eTIMS Purchase",
			reference_name=name,
		)

	try:
		number, _data = send_in_sequence(purchase.branch, "last_purchase_no", send)
	except Exception as e:
		error = frappe.utils.strip_html(str(e))[:500]
		if status == APPROVED:
			purchase.db_set(
				{"status": "Failed", "error": error, "retry_count": cint(purchase.retry_count) + 1},
				update_modified=False,
			)
		else:
			# A refused rejection leaves the purchase as it was, with the reason.
			purchase.db_set("error", error, update_modified=False)
		frappe.db.commit()  # nosemgrep
		return False

	purchase.db_set(
		{
			"status": "Confirmed" if status == APPROVED else "Rejected",
			"kra_purchase_no": number,
			"confirmed_on": now_datetime(),
			"error": "",
		},
		update_modified=False,
	)
	frappe.db.commit()  # nosemgrep
	return True


def confirm(name):
	"""Background job after the Purchase Invoice is submitted."""
	purchase = frappe.get_doc("eTIMS Purchase", name)
	if (
		not purchase.purchase_invoice
		or frappe.db.get_value("Purchase Invoice", purchase.purchase_invoice, "docstatus") != 1
	):
		return
	_send(name, APPROVED)


@frappe.whitelist()
def confirm_now(name):
	""" "Confirm with KRA" button on a Failed purchase: retry at once."""
	purchase = frappe.get_doc("eTIMS Purchase", name)
	purchase.check_permission("write")
	if (
		not purchase.purchase_invoice
		or frappe.db.get_value("Purchase Invoice", purchase.purchase_invoice, "docstatus") != 1
	):
		frappe.throw(_("Submit the Purchase Invoice first; it confirms the purchase with KRA."))
	if not _send(name, APPROVED):
		frappe.throw(frappe.db.get_value("eTIMS Purchase", name, "error"), title=_("KRA refused"))
	return _("KRA has the purchase confirmed.")


@frappe.whitelist()
def reject(name):
	"""Tell KRA a listed purchase isn't ours (status 04 Canceled)."""
	purchase = frappe.get_doc("eTIMS Purchase", name)
	purchase.check_permission("write")
	if purchase.status in ("Invoiced", "Confirmed") or (
		purchase.purchase_invoice
		and frappe.db.get_value("Purchase Invoice", purchase.purchase_invoice, "docstatus") == 1
	):
		frappe.throw(_("This purchase is already in the books; it can't be rejected."))
	unmatched = [row.supplier_item_name for row in purchase.items if not row.item]
	if unmatched:
		frappe.throw(
			_("KRA needs your own item on every line, even to reject. Pick your Item for: {0}").format(
				", ".join(unmatched)
			)
		)
	if not _send(name, CANCELED):
		frappe.throw(frappe.db.get_value("eTIMS Purchase", name, "error"), title=_("KRA refused"))
	return _("KRA has the purchase rejected.")


def retry_failed_confirmations():
	"""15-minute safety net for confirmations KRA didn't accept."""
	for name in frappe.get_all(
		"eTIMS Purchase",
		filters={
			"status": "Failed",
			"purchase_invoice": ["is", "set"],
			"retry_count": ["<", MAX_RETRY_COUNT],
		},
		pluck="name",
		limit_page_length=50,
	):
		_enqueue_confirm(name)
