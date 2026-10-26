# Copyright (c) 2026, Royce Technologies LTD and contributors
# For license information, please see license.txt

"""Pull KRA's own code lists into the eTIMS reference doctypes, replacing the
sample-only seed data (patches/v0_0/seed_sample_item_reference_data.py).

Two endpoints, both CONFIRMED 2026-10-26 against the sandbox for TIN
P051909825V / bhfId 02:

  - selectCodeList  -> responseBody.data.clsList[], one entry per code class
    (cdCls), each with a dtlList[] of {cd, cdNm, useYn, userDfnCd1, ...}.
  - selectItemClass -> responseBody.data.itemClsList[] of {itemClsCd,
    itemClsNm, taxTyCd, useYn, ...}. The sandbox only returns 26 rows;
    production is expected to carry KRA's full UNSPSC-based catalogue.

Taxation Type's rate comes from userDfnCd1 ("Tax Rate" per the class's own
userDfnNm1) rather than our seed. KRA's useYn drives the Disabled flag - at
the time of writing the sandbox marks E (VAT 8%) as useYn "N", which the seed
offered as a normal option.

Rows KRA doesn't return are left alone, not deleted: an Item may still link
to them, and a missing row in one response isn't proof KRA withdrew a code.
"""

import frappe
from frappe import _

from royce_etims.utils.api_client import get_settings
from royce_etims.utils.api_client import request as etims_request

# KRA code class (cdCls) -> reference doctype it fills.
CODE_CLASS_DOCTYPE = {
	"04": "eTIMS Taxation Type",
	"05": "eTIMS Country of Origin",
	"10": "eTIMS Quantity Unit",
	"17": "eTIMS Packaging Unit",
	"24": "eTIMS Item Type",
}

# Full pull every time: these lists are small (a few hundred rows) and an
# incremental lastReqDt sync would miss rows if a run ever failed halfway.
FULL_SYNC_FROM = "20180101000000"


def _response_data(data):
	body = (data or {}).get("responseBody") or data or {}
	return body.get("data") or {}


def _upsert(doctype, code, values):
	"""Insert or update one reference row. Returns "created", "updated" or None."""
	if frappe.db.exists(doctype, code):
		doc = frappe.get_doc(doctype, code)
		if all(doc.get(k) == v for k, v in values.items()):
			return None
		doc.update(values)
		doc.save(ignore_permissions=True)
		return "updated"

	frappe.get_doc({"doctype": doctype, "code": code, **values}).insert(ignore_permissions=True)
	return "created"


def _apply_code_list(cls_list, counts):
	for cls in cls_list:
		doctype = CODE_CLASS_DOCTYPE.get(cls.get("cdCls"))
		if not doctype:
			continue
		for row in cls.get("dtlList") or []:
			values = {
				"description": (row.get("cdNm") or "").strip() or row["cd"],
				"disabled": 0 if row.get("useYn") == "Y" else 1,
			}
			if doctype == "eTIMS Taxation Type":
				values["rate"] = float(row.get("userDfnCd1") or 0)
			result = _upsert(doctype, row["cd"], values)
			if result:
				counts[doctype][result] += 1


def _apply_item_classes(item_cls_list, counts):
	doctype = "eTIMS Item Classification"
	for row in item_cls_list:
		tax_code = row.get("taxTyCd")
		values = {
			"description": (row.get("itemClsNm") or "").strip() or row["itemClsCd"],
			"taxation_type": tax_code
			if tax_code and frappe.db.exists("eTIMS Taxation Type", tax_code)
			else None,
			"disabled": 0 if row.get("useYn") == "Y" else 1,
		}
		result = _upsert(doctype, row["itemClsCd"], values)
		if result:
			counts[doctype][result] += 1


@frappe.whitelist()
def sync_reference_data(company):
	"""Fetch selectCodeList + selectItemClass for this company's default branch
	and upsert them. Code list first: Item Classification links to Taxation Type."""
	frappe.only_for("System Manager")
	settings = get_settings(company)
	if not settings.default_branch:
		frappe.throw(
			_("Set a Default Branch on eTIMS Settings for {0} before syncing reference data.").format(company)
		)

	branch = frappe.get_doc("eTIMS Branch", settings.default_branch)
	payload = {"tin": settings.tin, "bhfId": branch.bhf_id, "lastReqDt": FULL_SYNC_FROM}
	counts = {
		dt: {"created": 0, "updated": 0} for dt in [*CODE_CLASS_DOCTYPE.values(), "eTIMS Item Classification"]
	}

	code_data = etims_request(
		company,
		"selectCodeList",
		payload=payload,
		branch=branch,
		reference_doctype="eTIMS Settings",
		reference_name=company,
	)
	_apply_code_list(_response_data(code_data).get("clsList") or [], counts)

	class_data = etims_request(
		company,
		"selectItemClass",
		payload=payload,
		branch=branch,
		reference_doctype="eTIMS Settings",
		reference_name=company,
	)
	_apply_item_classes(_response_data(class_data).get("itemClsList") or [], counts)

	frappe.db.commit()
	return counts


def sync_all_companies():
	"""Weekly scheduler job (hooks.py) - KRA revises these lists, e.g. after a
	Finance Act. One company failing must not stop the rest."""
	for company in frappe.get_all("eTIMS Settings", filters={"status": "Active"}, pluck="name"):
		try:
			sync_reference_data(company)
		except Exception:
			frappe.db.rollback()
			frappe.log_error(title=f"eTIMS: reference data sync failed for {company}")
