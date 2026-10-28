# Copyright (c) 2026, Royce Technologies LTD and contributors
# For license information, please see license.txt

"""KRA's read-only lookups - the "Look up ..." cases of KRA's Go-Live test.
Each takes the PIN, branch and a "since" date (or an invoice number) and
returns a list; reply shapes confirmed live 2026-10-29 on the Go-Live test
PIN (docs/kra-go-live-test.md). Shown by the KRA Lookup report."""

import frappe
from frappe import _
from frappe.utils import add_to_date, get_datetime, now_datetime

from royce_etims.utils.api_client import get_settings
from royce_etims.utils.api_client import request as etims_request

FULL_HISTORY = "20180101000000"

# Lookup name -> KRA endpoint and the key its list comes back under.
LOOKUPS = {
	"Branches": {"endpoint": "branchList", "list": "bhfList"},
	"Notices": {"endpoint": "selectNoticeList", "list": "noticeList"},
	"Customers": {"endpoint": "customerPinInfo", "list": "custList"},
	"Items": {"endpoint": "itemInfo", "list": "itemList"},
	"Imported Items": {"endpoint": "importedItemInfo", "list": "itemList"},
	"Stock Received from Others": {"endpoint": "selectStockMoveLists", "list": "stockList"},
	"Sales": {"endpoint": "selectSalesTransactions", "list": "salesList"},
	"Invoice Details": {"endpoint": "selectInvoiceDetail", "list": "salesList", "by_invoice": True},
	"Purchases": {"endpoint": "getPurchaseTransactionInfo", "list": "saleList"},
}


def _since(lookup, since):
	if since:
		return get_datetime(since).strftime("%Y%m%d%H%M%S")
	# KRA's collection: lastReqDt for notices "should not be more than 1 hr ago".
	if lookup == "Notices":
		return add_to_date(now_datetime(), minutes=-59).strftime("%Y%m%d%H%M%S")
	return FULL_HISTORY


def kra_lookup(company, lookup, since=None, invoice_no=None):
	"""KRA's list for `lookup` on the company's default branch. "No search
	result" is an empty list."""
	spec = LOOKUPS.get(lookup)
	if not spec:
		frappe.throw(_("Unknown KRA lookup: {0}").format(lookup))

	settings = get_settings(company)
	if not settings.default_branch:
		frappe.throw(_("Set a Default Branch on eTIMS Settings for {0} first.").format(company))
	branch = frappe.get_doc("eTIMS Branch", settings.default_branch)

	payload = {"tin": settings.tin, "bhfId": branch.bhf_id}
	if spec.get("by_invoice"):
		if not invoice_no:
			frappe.throw(_("Enter the KRA invoice number to look up."))
		payload["invcNo"] = str(invoice_no)
	else:
		payload["lastReqDt"] = _since(lookup, since)

	data = etims_request(
		company,
		spec["endpoint"],
		payload=payload,
		branch=branch,
		reference_doctype="eTIMS Settings",
		reference_name=company,
		allow_empty=True,
	)
	body = (data or {}).get("responseBody") or data or {}
	return (body.get("data") or {}).get(spec["list"]) or []
