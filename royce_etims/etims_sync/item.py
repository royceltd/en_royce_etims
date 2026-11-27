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
		# A PIN with no items yet answers "There is no search result" (resultCd 001):
		# an empty list, not a failure - FOUND 2026-11-25 on a fresh Go-Live test PIN.
		allow_empty=True,
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
	"Piece": "NO",  # KRA's Pieces/item is "U", one letter - refused in item codes
	"Packet": "PA",
	"Roll": "RO",
	"Bag": "BG",
	"Dozen": "DZ",
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


# itemCd character 3 is KRA's item type: 1 raw material, 2 finished product, 3 service.
ITEM_TYPE_POSITION = 2
SERVICE_ITEM_TYPE = "3"


def guard_registered_item_type(doc, method=None):
	"""Item validate hook: refuse to make an item a stock item once KRA holds it
	as a service. KRA then rejects every stock movement that includes it ("You
	cannot add stock for a service") and the whole stockIO fails with it, while
	saveItem won't re-register an item already known - FOUND 2026-11-05 on the
	hospital demo (admission kit registered as a service, then stocked).

	An item already in that state is only warned about on later saves, so its
	price, taxes and description can still be maintained."""
	if not doc.get("is_stock_item"):
		return
	for row in doc.get("royce_etims_id_mapping") or []:
		code = row.etims_id or ""
		if row.disabled or code[ITEM_TYPE_POSITION : ITEM_TYPE_POSITION + 1] != SERVICE_ITEM_TYPE:
			continue
		message = _(
			"{0} is registered with KRA eTIMS as a service ({1}) for {2}, so KRA will refuse "
			"stock for it. Create a separate stock item for the product instead."
		).format(doc.name, code, row.setup_docname)
		# frappe._dict answers hasattr() for anything, so check for a real method.
		is_document = callable(getattr(doc, "has_value_changed", None))
		becoming_stock = not is_document or doc.is_new() or doc.has_value_changed("is_stock_item")
		if becoming_stock:
			frappe.throw(message, title=_("Registered with KRA as a service"))
		frappe.msgprint(message, title=_("Registered with KRA as a service"), indicator="orange")
		return


def _mark_failed(item, error):
	item.db_set(
		{"royce_etims_sync_status": "Failed", "royce_etims_sync_error": frappe.utils.strip_html(str(error))},
		notify=False,
	)
	# Keep the Failed status (and any eTIMS Log row) through the rollback the
	# caller's re-raise triggers.
	frappe.db.commit()  # nosemgrep


def _mark_synced(item):
	item.db_set("royce_etims_sync_status", "Synced", notify=False)
	item.db_set("royce_etims_last_synced_on", now_datetime(), notify=False)
	item.db_set("royce_etims_sync_error", "", notify=False)


@frappe.whitelist()
def sync_item(item_code, company, kra_codes=None):
	"""Register the item with KRA and declare the stock it already has (KRA
	won't sign a sale of an item missing from its stock master). `kra_codes`:
	KRA's itemCd list, passed by a bulk run so it isn't fetched per item; a new
	code is appended to it."""
	item = frappe.get_doc("Item", item_code)
	settings = get_settings(company)

	if not settings.default_branch:
		frappe.throw(
			_(
				"Set a Default Branch on eTIMS Settings for {0} before syncing items - item sync still needs a registered device to authenticate as."
			).format(company)
		)

	try:
		_validate_ready_to_sync(item, company)
	except frappe.ValidationError as e:
		# Stopped before reaching KRA - still Failed, so Compliance Status shows it.
		_mark_failed(item, e)
		raise
	branch = frappe.get_doc("eTIMS Branch", settings.default_branch)
	item_cd = get_etims_id(item, company)
	lost_code = None
	if kra_codes is None or isinstance(kra_codes, str):
		kra_codes = _kra_item_codes(company, branch)
	if item_cd and item_cd not in kra_codes:
		# A code we recorded that KRA doesn't hold: KRA answered "Successful" for
		# KE2NTNO0000124 and then didn't have it (FOUND 2026-11-27, sandbox), and
		# it refuses the same code again ("Expected sequence ending with 126").
		# So the item gets the next code, and unsent stock moves to it.
		lost_code, item_cd = item_cd, None
	is_new_code = not item_cd

	if is_new_code:
		prefix = item_code_prefix(item)
		item_cd = next_item_code(prefix, _known_item_codes(company, kra_codes))
	elif item_cd in kra_codes:
		# KRA rejects saveItem for an itemCd it already holds ("The itemCd is
		# either reused or not incremented properly") - CONFIRMED 2026-10-26
		# by re-syncing KE2NTBA0000005 a second after registering it. So a
		# registered item can't be re-sent or updated through saveItem here.
		_mark_synced(item)
		declare_opening_stock(item.name, company)
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
		_mark_failed(item, e)
		raise

	# Recorded only once KRA has accepted it, so a rejected attempt never
	# leaves a code behind that KRA doesn't know about.
	if is_new_code:
		kra_codes.append(item_cd)
		set_etims_id(item, company, item_cd)
		item.save(ignore_permissions=True)
		if lost_code:
			_move_unsent_stock(lost_code, item_cd)

	_mark_synced(item)
	declare_opening_stock(item.name, company)

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


def _move_unsent_stock(old_code, new_code):
	"""Point stock movements KRA hasn't accepted yet at the item's new code, and
	queue them again."""
	from royce_etims.etims_sync.stock import _enqueue_branch

	rows = frappe.db.sql(
		"""
		SELECT DISTINCT m.name, m.branch FROM `tabeTIMS Stock Movement Item` i
		JOIN `tabeTIMS Stock Movement` m ON m.name = i.parent
		WHERE i.item_cd = %s AND m.status IN ('Pending', 'Failed')
		""",
		old_code,
		as_dict=True,
	)
	for row in rows:
		frappe.db.sql(
			"UPDATE `tabeTIMS Stock Movement Item` SET item_cd = %s WHERE parent = %s AND item_cd = %s",
			(new_code, row.name, old_code),
		)
		frappe.db.set_value("eTIMS Stock Movement", row.name, "retry_count", 0, update_modified=False)
	for branch in {row.branch for row in rows}:
		_enqueue_branch(branch)


def declare_opening_stock(item_code, company):
	"""Queue the stock an item holds now as one incoming movement to KRA, once
	per item. Stock received before the item had its KRA code was never sent
	(stock.on_submit skips unregistered items), and KRA refuses a sale of an
	item its stock master doesn't have - FOUND 2026-11-27 on lick.localhost:
	"Item KE2NTNO0000087 does not exist in your stock master". Returns the
	movement's name, or None when there's nothing to send."""
	from royce_etims.etims_sync.stock import SAR_ADJUST_IN, _active_settings, _enqueue_branch, _item_row

	settings = _active_settings(company)
	if not settings:
		return None
	if frappe.db.exists(
		"eTIMS Stock Movement",
		{"company": company, "voucher_type": "Item", "voucher_no": item_code, "status": ["!=", "Cancelled"]},
	):
		return None
	qty, value = opening_stock(item_code, company)
	if qty <= 0:
		return None
	row = _item_row(item_code, qty, value, company)
	if not row:
		return None
	movement = frappe.get_doc(
		{
			"doctype": "eTIMS Stock Movement",
			"company": company,
			"branch": settings.default_branch,
			"voucher_type": "Item",
			"voucher_no": item_code,
			"posting_date": frappe.utils.nowdate(),
			"direction": "In",
			"sar_ty_cd": SAR_ADJUST_IN,
			"items": [row],
		}
	).insert(ignore_permissions=True)
	_enqueue_branch(settings.default_branch)
	return movement.name


def opening_stock(item_code, company):
	"""(qty, value) on hand across the company's warehouses. Value falls back to
	the item's valuation rate when the bins carry none."""
	qty, value = frappe.db.sql(
		"""
		SELECT COALESCE(SUM(b.actual_qty), 0), COALESCE(SUM(b.stock_value), 0)
		FROM `tabBin` b JOIN `tabWarehouse` w ON w.name = b.warehouse
		WHERE b.item_code = %s AND w.company = %s AND b.actual_qty > 0
		""",
		(item_code, company),
	)[0]
	qty, value = float(qty), float(value)
	if qty > 0 and value <= 0:
		rate = frappe.db.get_value("Item", item_code, "valuation_rate") or 0
		value = qty * float(rate)
	return qty, value
