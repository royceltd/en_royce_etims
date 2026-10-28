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

itemCd is generated here, not typed in: origin country + item type +
packaging unit + quantity unit + a 7-digit sequence, e.g. KE2NTBA0000005.
KRA enforces one sequence per PIN, across all prefixes - CONFIRMED
2026-10-26 ("Expected sequence ending with: ********4" after KE2NTBA...1-3)
and 2026-10-29 (a new KE2NTKG prefix had to continue at 7, not restart at 1).
The quantity unit must be 2 characters: KRA refused every form of a code for
U and LTR tried on 2026-10-29 ("The ItemCd isn't made up of correct
QtyUnitCd" - KE2NTU..., KE2NTXU..., KE2NTLTR..., KE2NTLT...) and accepted
KG and NO. 7 digits
matches KRA's own test-harness items (KE1NTXU1000001) and the Odoo/Navari
OSCU integrations; the sandbox also accepted 8 (the Postman sample's
KE2NTBA00000001), so the sequence is read from either width.
"""

import frappe
from frappe import _
from frappe.utils import now_datetime

from royce_etims.utils.api_client import get_settings
from royce_etims.utils.api_client import request as etims_request
from royce_etims.utils.id_mapping import SETUP_DOCTYPE, get_etims_id, set_etims_id

ITEM_CODE_SEQUENCE_DIGITS = 7

# Country (2) + item type (1) + packaging (2) + quantity unit (2).
ITEM_CODE_PREFIX_LENGTH = 7

# The four reference codes an itemCd's prefix is built from, in order.
ITEM_CODE_PREFIX_FIELDS = (
	"royce_etims_origin_nation_code",
	"royce_etims_item_type_code",
	"royce_etims_packaging_unit_code",
	"royce_etims_quantity_unit_code",
)

REQUIRED_ETIMS_ITEM_FIELDS = (
	"royce_etims_item_classification",
	"royce_etims_item_type",
	"royce_etims_taxation_type",
	# CONFIRMED required 2026-09-11 by a real saveItem rejection against KRA's
	# sandbox: {"customerMessage": "orgnNatCd cannot be null"}. Previously
	# left out on the (wrong) assumption it was optional, since the Postman
	# sample's comment on this field had no "REQ" marker the way other
	# required fields did.
	"royce_etims_origin_nation",
	# Part of the generated itemCd's prefix, and required by saveItem itself.
	"royce_etims_packaging_unit",
	"royce_etims_quantity_unit",
)


def item_code_prefix(item):
	return "".join(item.get(f) or "" for f in ITEM_CODE_PREFIX_FIELDS)


def next_item_code(prefix, known_codes):
	"""`prefix` plus one past the highest sequence among all `known_codes` of
	this PIN. KRA counts one sequence per PIN, not per prefix - CONFIRMED
	2026-10-29: with KE2NTBA...0000006 registered, KE2NTKG0000001 was refused
	("Expected sequence ending with ********7") and KE2NTKG0000007 accepted.
	The prefix is always ITEM_CODE_PREFIX_LENGTH characters (2-character units
	only, see _validate_ready_to_sync), so the sequence is everything after it -
	a unit like M2 ends in a digit, so trailing digits alone would misread it."""
	highest = 0
	for code in known_codes:
		tail = (code or "")[ITEM_CODE_PREFIX_LENGTH:]
		if tail.isdigit():
			highest = max(highest, int(tail))
	return f"{prefix}{highest + 1:0{ITEM_CODE_SEQUENCE_DIGITS}d}"


def _kra_item_codes(company, branch):
	"""Every itemCd KRA has registered for this branch (itemInfo)."""
	settings = get_settings(company)
	data = etims_request(
		company,
		"itemInfo",
		payload={"tin": settings.tin, "bhfId": branch.bhf_id, "lastReqDt": "20180101000000"},
		branch=branch,
	)
	body = (data or {}).get("responseBody") or data or {}
	return [row.get("itemCd") for row in (body.get("data") or {}).get("itemList") or []]


def _known_item_codes(company, kra_codes):
	"""KRA's codes plus any we've recorded locally - KRA is the authority on
	the sequence, the local list only covers a registration KRA hasn't
	reflected yet."""
	local_codes = frappe.get_all(
		"eTIMS ID Mapping",
		filters={"setup_doctype": SETUP_DOCTYPE, "setup_docname": company},
		pluck="etims_id",
	)
	return kra_codes + local_codes


def build_item_payload(item, item_cd):
	return {
		"itemCd": item_cd,
		"itemClsCd": item.royce_etims_item_classification_code,
		"itemTyCd": item.royce_etims_item_type_code,
		"itemNm": item.item_name,
		"itemStdNm": None,
		"orgnNatCd": item.royce_etims_origin_nation_code,
		"pkgUnitCd": item.royce_etims_packaging_unit_code,
		"qtyUnitCd": item.royce_etims_quantity_unit_code,
		"taxTyCd": item.royce_etims_taxation_type_code,
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
	if item.royce_prevent_etims_submission:
		frappe.throw(_("Item {0} has 'Prevent eTIMS Submission' checked.").format(item.name))

	meta = frappe.get_meta("Item")
	missing = [meta.get_label(f) for f in REQUIRED_ETIMS_ITEM_FIELDS if not item.get(f)]
	if missing:
		frappe.throw(
			_("Fill in the KRA eTIMS tab on Item {0} before syncing - missing: {1}").format(
				item.name, ", ".join(missing)
			)
		)
	unit = item.get("royce_etims_quantity_unit_code") or ""
	if len(unit) != 2:
		frappe.throw(
			_(
				"KRA only accepts item codes with a 2-letter quantity unit, and {0} isn't one. Pick a 2-letter unit for Item {1}, such as Number (NO), Kilo-Gramme (KG), box (BX) or bag (BG)."
			).format(unit, item.name)
		)


# ERPNext's standard units of measure -> KRA quantity unit (code class 10).
# Only 2-letter units: KRA refuses item codes built from the others (U, L,
# LTR, GRM, TNE...), so litres, grams etc. are left for the accountant until
# KRA says how to code them. Only fills a UOM that has none.
UOM_QUANTITY_UNITS = {
	"Nos": "NO",
	"Unit": "NO",
	"Kg": "KG",
	"Box": "BX",
	"Pair": "PR",
	"Square Meter": "M2",
	"Cubic Meter": "M3",
}


def map_common_uoms():
	"""Give the standard UOMs their KRA quantity unit. Runs after KRA's code
	lists are synced (the units come from there) and from a patch."""
	for uom, unit in UOM_QUANTITY_UNITS.items():
		if (
			frappe.db.exists("UOM", uom)
			and frappe.db.exists("eTIMS Quantity Unit", unit)
			and not frappe.db.get_value("UOM", uom, "royce_etims_quantity_unit")
		):
			frappe.db.set_value("UOM", uom, "royce_etims_quantity_unit", unit, update_modified=False)


def _group_classification(item_group):
	"""The KRA product category of the item's group, or of its nearest parent group that has one."""
	while item_group:
		group = frappe.db.get_value(
			"Item Group", item_group, ["royce_etims_item_classification", "parent_item_group"], as_dict=True
		)
		if not group:
			return None
		if group.royce_etims_item_classification:
			return group.royce_etims_item_classification
		item_group = group.parent_item_group
	return None


def _fill(doc, field, value, reference_doctype):
	"""Set an empty KRA field and its code. The code is set too because this
	runs after fetch_from (see fill_taxation_type); the lists are named by code."""
	if doc.get(field) or not value or not frappe.db.exists(reference_doctype, value):
		return
	doc.update({field: value, f"{field}_code": value})


def fill_defaults(doc, method=None):
	"""Item validate hook: fill the KRA fields a new item can't do without, from
	what ERPNext already knows. Never overwrites a value."""
	_fill(doc, "royce_etims_origin_nation", "KE", "eTIMS Country of Origin")
	_fill(doc, "royce_etims_item_type", "2" if doc.get("is_stock_item") else "3", "eTIMS Item Type")
	_fill(doc, "royce_etims_packaging_unit", "NT", "eTIMS Packaging Unit")
	if doc.get("stock_uom"):
		unit = frappe.db.get_value("UOM", doc.stock_uom, "royce_etims_quantity_unit")
		_fill(doc, "royce_etims_quantity_unit", unit, "eTIMS Quantity Unit")
	_fill(
		doc,
		"royce_etims_item_classification",
		_group_classification(doc.get("item_group")),
		"eTIMS Item Classification",
	)


def fill_taxation_type(doc, method=None):
	"""Item validate hook: an item with no eTIMS band takes the one on its Item
	Tax Template, so the band isn't a second thing to keep in step with VAT.

	Also fills the band's code and rate: this runs after Frappe has copied
	fetch_from values, so a band set here would otherwise leave
	royce_etims_taxation_type_code empty - and saveItem sends that code, which
	KRA rejects as "taxTyCd cannot be null" (found live 2026-10-27)."""
	band = doc.get("royce_etims_taxation_type")
	if not band:
		for row in doc.get("taxes") or []:
			band = frappe.db.get_value(
				"Item Tax Template", row.item_tax_template, "royce_etims_taxation_type"
			)
			if band:
				doc.royce_etims_taxation_type = band
				break
	if band and doc.get("royce_etims_taxation_type_code") != band:
		doc.royce_etims_taxation_type_code = band  # eTIMS Taxation Type is named by its code
		doc.royce_etims_taxation_type_rate = frappe.db.get_value("eTIMS Taxation Type", band, "rate")


def _mark_synced(item):
	item.db_set("royce_etims_sync_status", "Synced", notify=False)
	item.db_set("royce_etims_last_synced_on", now_datetime(), notify=False)
	item.db_set("royce_etims_sync_error", "", notify=False)


@frappe.whitelist()
def sync_item(item_code, company):
	item = frappe.get_doc("Item", item_code)
	settings = get_settings(company)

	if not settings.default_branch:
		frappe.throw(
			_(
				"Set a Default Branch on eTIMS Settings for {0} before syncing items - item sync still needs a registered device to authenticate as."
			).format(company)
		)

	_validate_ready_to_sync(item, company)
	branch = frappe.get_doc("eTIMS Branch", settings.default_branch)
	item_cd = get_etims_id(item, company)
	is_new_code = not item_cd
	kra_codes = _kra_item_codes(company, branch)

	if is_new_code:
		prefix = item_code_prefix(item)
		item_cd = next_item_code(prefix, _known_item_codes(company, kra_codes))
	elif item_cd in kra_codes:
		# KRA rejects saveItem for an itemCd it already holds ("The itemCd is
		# either reused or not incremented properly") - CONFIRMED 2026-10-26
		# by re-syncing KE2NTBA0000005 a second after registering it. So a
		# registered item can't be re-sent or updated through saveItem here.
		_mark_synced(item)
		return {
			"success": True,
			"message": _("Item {0} is already registered with KRA as {1}.").format(item.item_code, item_cd),
		}

	payload = build_item_payload(item, item_cd)

	try:
		etims_request(
			company,
			"saveItem",
			payload=payload,
			method="POST",
			branch=branch,
			reference_doctype="Item",
			reference_name=item.name,
		)
	except Exception as e:
		item.db_set("royce_etims_sync_status", "Failed", notify=False)
		item.db_set("royce_etims_sync_error", str(e)[:140], notify=False)
		# Keep the Failed status (and the eTIMS Log row) through the rollback
		# the re-raise triggers.
		frappe.db.commit()  # nosemgrep
		raise

	# Recorded only once KRA has accepted it, so a rejected attempt never
	# leaves a code behind that KRA doesn't know about.
	if is_new_code:
		set_etims_id(item, company, item_cd)
		item.save()

	_mark_synced(item)

	return {
		"success": True,
		"message": _("Item {0} synced to eTIMS as {1}.").format(item.item_code, item_cd),
	}


@frappe.whitelist()
def assign_etims_item_code(item_code, company, etims_id):
	"""Convenience whitelisted method for the Item form - adds/updates an
	eTIMS ID Mapping row without the user hand-editing the grid."""
	item = frappe.get_doc("Item", item_code)
	set_etims_id(item, company, etims_id)
	item.save()
	return {"success": True, "message": _("eTIMS Item Code set for {0}.").format(company)}
