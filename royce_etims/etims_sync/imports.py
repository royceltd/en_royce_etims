# Copyright (c) 2026, Royce Technologies LTD and contributors
# For license information, please see license.txt

"""Imported items KRA receives from customs (importedItemInfo, Go-Live case 12)
and our answer on each (importedItemConvertedInfo, case 13).

Customs declarations reach KRA under the importer's PIN. Each declared line is
fetched into an eTIMS Imported Item. Someone picks which of our Items it is,
then Approves (KRA import status 3) or Rejects (4) it. Approving tells KRA the
line was received as that item; the stock itself is still received in ERPNext
the normal way (Purchase Receipt / Invoice, landed costs).

KRA's code class 26: 1 Unsent, 2 Waiting, 3 Approved, 4 Cancelled.
"""

import json

import frappe
from frappe import _
from frappe.utils import cint, flt, now_datetime

from royce_etims.utils.api_client import get_settings
from royce_etims.utils.api_client import request as etims_request
from royce_etims.utils.id_mapping import get_etims_id
from royce_etims.utils.lookups import FULL_HISTORY

APPROVED = "3"
CANCELLED = "4"


def _branch(company):
	settings = get_settings(company)
	if not settings.default_branch:
		frappe.throw(_("Set a Default Branch on eTIMS Settings for {0} first.").format(company))
	return settings, frappe.get_doc("eTIMS Branch", settings.default_branch)


@frappe.whitelist()
def fetch_imported_items(company):
	"""Pull new import lines from KRA. Returns how many were new."""
	frappe.has_permission("eTIMS Imported Item", "create", throw=True)
	settings, branch = _branch(company)
	started = now_datetime()
	since = (
		branch.imports_fetched_until.strftime("%Y%m%d%H%M%S")
		if branch.imports_fetched_until
		else FULL_HISTORY
	)

	data = etims_request(
		company,
		"importedItemInfo",
		payload={"tin": settings.tin, "bhfId": branch.bhf_id, "lastReqDt": since},
		branch=branch,
		reference_doctype="eTIMS Settings",
		reference_name=company,
		allow_empty=True,
	)
	body = (data or {}).get("responseBody") or data or {}
	rows = (body.get("data") or {}).get("itemList") or []

	new = sum(1 for row in rows if upsert_imported_item(company, branch.name, row))
	branch.db_set("imports_fetched_until", started, update_modified=False)
	frappe.db.commit()  # nosemgrep
	return new


def upsert_imported_item(company, branch, row):
	"""Insert one KRA import line, or refresh KRA's status on a known one.
	Returns True for a new line."""
	key = {"company": company, "task_code": row.get("taskCd"), "item_seq": cint(row.get("itemSeq"))}
	values = {
		"branch": branch,
		"item_name": row.get("itemNm"),
		"hs_code": row.get("hsCd"),
		"declaration_no": row.get("dclNo"),
		"declaration_date": row.get("dclDe"),
		"origin_country": row.get("orgnNatCd"),
		"export_country": row.get("exptNatCd"),
		"supplier_name": row.get("spplrNm"),
		"agent_name": row.get("agntNm"),
		"qty": flt(row.get("qty")),
		"qty_unit": row.get("qtyUnitCd"),
		"package": flt(row.get("pkg")),
		"package_unit": row.get("pkgUnitCd"),
		"invoice_amount": flt(row.get("invcFcurAmt")),
		"invoice_currency": row.get("invcFcurCd"),
		"exchange_rate": flt(row.get("invcFcurExcrt")),
		"gross_weight": flt(row.get("totWt")),
		"net_weight": flt(row.get("netWt")),
		"kra_status": row.get("imptItemSttsCd") or row.get("imptItemsttsCd"),
		"raw": json.dumps(row, indent=1),
	}
	existing = frappe.db.exists("eTIMS Imported Item", key)
	if existing:
		frappe.db.set_value("eTIMS Imported Item", existing, values, update_modified=False)
		return False
	frappe.get_doc({"doctype": "eTIMS Imported Item", **key, **values}).insert(ignore_permissions=True)
	return True


def build_payload(doc, status, item_cd=None, item_cls_cd=None):
	return {
		"taskCd": doc.task_code,
		"dclDe": doc.declaration_date,
		"itemSeq": cint(doc.item_seq),
		"hsCd": doc.hs_code,
		"itemClsCd": item_cls_cd,
		"itemCd": item_cd,
		"imptItemSttsCd": status,
		# Required in practice: a null remark draws KRA's "There is an unknown
		# error. Please ask administrator" - CONFIRMED 2026-11-18 on the Go-Live
		# test PIN (the same payload with a remark was accepted).
		"remark": "Approved" if status == APPROVED else "Rejected",
		"modrNm": frappe.session.user,
		"modrId": frappe.session.user,
	}


def _send(doc, status):
	item_cd = item_cls_cd = None
	if doc.item:
		item = frappe.get_doc("Item", doc.item)
		item_cd = get_etims_id(item, doc.company)
		item_cls_cd = item.get("royce_etims_item_classification_code")
	if status == APPROVED and not item_cd:
		frappe.throw(
			_(
				"Pick the Item this import is, and register it with KRA (Item > Sync to eTIMS), before approving."
			)
		)

	try:
		etims_request(
			doc.company,
			"importedItemConvertedInfo",
			payload=build_payload(doc, status, item_cd, item_cls_cd),
			branch=doc.branch,
			reference_doctype=doc.doctype,
			reference_name=doc.name,
		)
	except Exception as e:
		doc.db_set(
			{"status": "Failed", "error": frappe.utils.strip_html(str(e))[:500]}, update_modified=False
		)
		frappe.db.commit()  # nosemgrep - keep the Failed status through the rollback
		raise

	doc.db_set(
		{
			"status": "Approved" if status == APPROVED else "Rejected",
			"kra_status": status,
			"error": "",
			"sent_on": now_datetime(),
		},
		update_modified=False,
	)
	frappe.db.commit()  # nosemgrep


@frappe.whitelist()
def approve(name, item=None):
	doc = frappe.get_doc("eTIMS Imported Item", name)
	doc.check_permission("write")
	if item and item != doc.item:
		doc.db_set("item", item, update_modified=False)
		doc.item = item
	_send(doc, APPROVED)
	return _("KRA has the import approved as {0}.").format(doc.item)


@frappe.whitelist()
def reject(name):
	doc = frappe.get_doc("eTIMS Imported Item", name)
	doc.check_permission("write")
	_send(doc, CANCELLED)
	return _("KRA has the import rejected.")


def fetch_all_companies():
	"""Daily: fetch new import lines for every active company."""
	for company in frappe.get_all(
		"eTIMS Settings", filters={"status": "Active", "default_branch": ["is", "set"]}, pluck="name"
	):
		try:
			fetch_imported_items(company)
		except Exception:
			frappe.db.rollback()
			frappe.log_error(title=f"eTIMS: fetching imported items for {company} failed")
