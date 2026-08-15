# Copyright (c) 2026, Royce Technologies LTD and contributors
# For license information, please see license.txt

"""Push ERPNext Item master data to KRA via saveItem.

Multi-company: itemCd is issued per taxpayer (Company/TIN), not globally to
the Item - handled via the `eTIMS ID Mapping` child table (one row per
company an item is registered under), rather than a single flat field.
Pattern borrowed from navari_csf_ke's eTims ID Mapping. Classification/tax/
unit codes, by contrast, genuinely are properties of the item description
itself (not per-registration), so those stay as Links to the shared
reference doctypes (eTIMS Item Classification, eTIMS Taxation Type, ...).
"""

import frappe
from frappe import _
from frappe.utils import now_datetime

from royce_etims.utils.api_client import get_settings, request as etims_request
from royce_etims.utils.id_mapping import get_etims_id, set_etims_id

REQUIRED_ETIMS_ITEM_FIELDS = (
	"etims_item_classification",
	"etims_item_type",
	"etims_taxation_type",
)


def build_item_payload(item, item_cd):
	return {
		"itemCd": item_cd,
		"itemClsCd": item.etims_item_classification_code,
		"itemTyCd": item.etims_item_type_code,
		"itemNm": item.item_name,
		"itemStdNm": None,
		"orgnNatCd": item.etims_origin_nation_code,
		"pkgUnitCd": item.etims_packaging_unit_code,
		"qtyUnitCd": item.etims_quantity_unit_code,
		"taxTyCd": item.etims_taxation_type_code,
		"btchNo": None,
		"bcd": None,
		"dftPrc": item.standard_rate or 0,
		"grpPrcL1": 0,
		"grpPrcL2": 0,
		"grpPrcL3": 0,
		"grpPrcL4": 0,
		"grpPrcL5": None,
		"addInfo": None,
		"sftyQty": None,
		"isrcAplcbYn": "N",
		"useYn": "N" if item.disabled else "Y",
		"regrNm": frappe.session.user,
		"regrId": frappe.session.user,
		"modrNm": frappe.session.user,
		"modrId": frappe.session.user,
	}


def _validate_ready_to_sync(item, company):
	if item.prevent_etims_submission:
		frappe.throw(_("Item {0} has 'Prevent eTIMS Submission' checked.").format(item.name))

	missing = [f for f in REQUIRED_ETIMS_ITEM_FIELDS if not item.get(f)]
	if missing:
		frappe.throw(
			_("Fill in the eTIMS section on Item {0} before syncing - missing: {1}").format(
				item.name, ", ".join(missing)
			)
		)

	if not get_etims_id(item, company):
		frappe.throw(
			_(
				"Item {0} has no eTIMS Item Code assigned for {1} yet. Add a row to its "
				"eTIMS ID Mapping table with the itemCd you want to register, then sync again."
			).format(item.name, company)
		)


@frappe.whitelist()
def sync_item(item_code, company):
	item = frappe.get_doc("Item", item_code)
	settings = get_settings(company)

	if not settings.default_branch:
		frappe.throw(
			_("Set a Default Branch on eTIMS Settings for {0} before syncing items - item sync still needs a registered device to authenticate as.").format(
				company
			)
		)

	_validate_ready_to_sync(item, company)
	item_cd = get_etims_id(item, company)
	payload = build_item_payload(item, item_cd)

	try:
		etims_request(
			company,
			"saveItem",
			payload=payload,
			method="POST",
			branch=settings.default_branch,
			reference_doctype="Item",
			reference_name=item.name,
		)
	except Exception as e:
		item.db_set("etims_sync_status", "Failed", notify=False)
		item.db_set("etims_sync_error", str(e)[:140], notify=False)
		raise

	item.db_set("etims_sync_status", "Synced", notify=False)
	item.db_set("etims_last_synced_on", now_datetime(), notify=False)
	item.db_set("etims_sync_error", "", notify=False)

	return {"success": True, "message": _("Item {0} synced to eTIMS.").format(item.item_code)}


@frappe.whitelist()
def assign_etims_item_code(item_code, company, etims_id):
	"""Convenience whitelisted method for the Item form - adds/updates an
	eTIMS ID Mapping row without the user hand-editing the grid."""
	item = frappe.get_doc("Item", item_code)
	set_etims_id(item, company, etims_id)
	item.save()
	return {"success": True, "message": _("eTIMS Item Code set for {0}.").format(company)}
