# Copyright (c) 2026, Royce Technologies LTD and contributors
# For license information, please see license.txt

"""Stock in/out -> KRA insert/stockIO + save/stockMaster.

KRA rejects a sale for an item with no stock record ("Item ... does not
exist in your stock master") - CONFIRMED 2026-10-26. So every stock movement
in ERPNext has to reach KRA too, not just sales.

Built from the Stock Ledger, not per doctype: whatever a voucher did to
stock, its SLEs say it, so Purchase Receipt, Delivery Note, Stock Entry,
Stock Reconciliation and Purchase/Sales Invoice with update_stock all go
through the same path. POS sales reach KRA through the consolidated Sales
Invoice created at POS closing, which is what posts their stock.

One `eTIMS Stock Movement` per voucher per direction (a Manufacture both
consumes and produces). Net-zero items - a transfer between two warehouses
of the same company - are skipped; there's one branch per company for now.

Sending is strictly in order per branch and stops at the first failure:
sarNo must be exactly last+1 (utils/sequence.py), and save/stockMaster's
rsdQty must equal what KRA has summed from our stockIO calls ("rsdQty
mismatch. Expected: 0.0 but found: 10" - CONFIRMED 2026-10-26). Sending out
of order would make both drift. rsdQty is therefore computed from the
movements KRA has accepted, not from ERPNext's Bin.
"""

import frappe
from frappe import _
from frappe.utils import flt, getdate

from royce_etims.etims_sync.tax_lines import exact_amount, kra_split, line_amount
from royce_etims.utils.api_client import request as etims_request
from royce_etims.utils.id_mapping import get_etims_id
from royce_etims.utils.sequence import lock_branch, send_in_sequence

MAX_RETRY_COUNT = 5

# KRA code class 12, "Stock I/O Type" (selectCodeList, 2026-10-26).
SAR_IMPORT, SAR_PURCHASE, SAR_RETURN_IN, SAR_MOVE_IN, SAR_PROCESS_IN, SAR_ADJUST_IN = (
	"01",
	"02",
	"03",
	"04",
	"05",
	"06",
)
SAR_SALE, SAR_RETURN_OUT, SAR_MOVE_OUT, SAR_PROCESS_OUT, SAR_DISCARD, SAR_ADJUST_OUT = (
	"11",
	"12",
	"13",
	"14",
	"15",
	"16",
)

STOCK_VOUCHER_TYPES = (
	"Purchase Receipt",
	"Purchase Invoice",
	"Delivery Note",
	"Sales Invoice",
	"Stock Entry",
	"Stock Reconciliation",
)

PROCESSING_PURPOSES = (
	"Manufacture",
	"Repack",
	"Disassemble",
	"Material Consumption for Manufacture",
)
SUBCONTRACTING_PURPOSES = ("Send to Subcontractor", "Subcontracting Delivery", "Subcontracting Return")


def sar_type_for(voucher_type, direction, is_return=False, purpose=None):
	"""KRA Stock I/O Type for one direction of one voucher."""
	incoming = direction == "In"
	if voucher_type in ("Purchase Receipt", "Purchase Invoice"):
		if is_return:
			return SAR_ADJUST_IN if incoming else SAR_RETURN_OUT
		return SAR_PURCHASE if incoming else SAR_ADJUST_OUT
	if voucher_type in ("Delivery Note", "Sales Invoice"):
		if is_return:
			return SAR_RETURN_IN if incoming else SAR_ADJUST_OUT
		return SAR_ADJUST_IN if incoming else SAR_SALE
	if voucher_type == "Stock Entry":
		if purpose in PROCESSING_PURPOSES:
			return SAR_PROCESS_IN if incoming else SAR_PROCESS_OUT
		if purpose in SUBCONTRACTING_PURPOSES or (purpose or "").startswith("Material Transfer"):
			return SAR_MOVE_IN if incoming else SAR_MOVE_OUT
	return SAR_ADJUST_IN if incoming else SAR_ADJUST_OUT


def net_item_movements(sles):
	"""Group SLE rows by item into {item_code: {"qty": signed qty, "value": abs
	value}}, dropping items whose movements cancel out."""
	totals = {}
	for sle in sles:
		row = totals.setdefault(sle.item_code, {"qty": 0.0, "value": 0.0})
		row["qty"] += flt(sle.actual_qty)
		row["value"] += flt(sle.stock_value_difference)
	return {item: row for item, row in totals.items() if abs(row["qty"]) > 1e-9}


def vat_inclusive_amounts(rate, qty, tax_rate):
	"""(total, taxable, tax) for a VAT-inclusive rate, rounded exactly as KRA
	recomputes them (tax_lines.kra_split) - KRA checks stockIO lines the same
	way: 10 x 1000 at 16% -> "Invalid taxblAmt on item: 1. Expected: 8620.69,
	But Found: 10000.00" (2026-10-26)."""
	taxable, tax = kra_split(exact_amount(qty, rate), tax_rate)
	return line_amount(qty, rate), taxable, tax


def _item_row(item_code, qty, value, company):
	"""eTIMS Stock Movement Item for one item, or None if the item isn't
	registered with KRA for this company (nothing KRA could match it to)."""
	item = frappe.get_cached_doc("Item", item_code)
	item_cd = get_etims_id(item, company)
	if not item_cd or item.get("royce_prevent_etims_submission"):
		return None

	qty = abs(qty)
	rate = flt(abs(value) / qty, 2) if qty else 0
	tax_rate = flt(item.get("royce_etims_taxation_type_rate"))
	total, taxable, tax = vat_inclusive_amounts(rate, qty, tax_rate)
	return {
		"item_code": item_code,
		"item_cd": item_cd,
		"item_name": item.item_name,
		"item_cls_cd": item.get("royce_etims_item_classification_code"),
		"pkg_unit_cd": item.get("royce_etims_packaging_unit_code"),
		"qty_unit_cd": item.get("royce_etims_quantity_unit_code"),
		"tax_ty_cd": item.get("royce_etims_taxation_type_code"),
		"tax_rate": tax_rate,
		"qty": qty,
		"rate": rate,
		"taxable_amount": taxable,
		"tax_amount": tax,
		"total_amount": total,
	}


def _active_settings(company):
	if not frappe.db.exists("eTIMS Settings", company):
		return None
	settings = frappe.get_cached_doc("eTIMS Settings", company)
	if settings.status != "Active" or not settings.get("sync_stock_movements") or not settings.default_branch:
		return None
	return settings


def _enqueue_branch(branch):
	frappe.enqueue(
		"royce_etims.etims_sync.stock.process_branch_queue",
		queue="short",
		enqueue_after_commit=True,
		job_id=f"royce_etims_stock::{branch}",
		deduplicate=True,
		branch=branch,
	)


def on_submit(doc, method=None):
	"""doc_events hook for every STOCK_VOUCHER_TYPES doctype. Only records the
	movements and queues them; never calls KRA inline."""
	settings = _active_settings(doc.company)
	if not settings:
		return

	sles = frappe.get_all(
		"Stock Ledger Entry",
		filters={"voucher_type": doc.doctype, "voucher_no": doc.name, "is_cancelled": 0},
		fields=["item_code", "actual_qty", "stock_value_difference"],
	)
	branch = doc.get("royce_etims_branch") or settings.default_branch
	created = False
	for direction in ("In", "Out"):
		rows = []
		for item_code, totals in net_item_movements(sles).items():
			if (totals["qty"] > 0) != (direction == "In"):
				continue
			row = _item_row(item_code, totals["qty"], totals["value"], doc.company)
			if row:
				rows.append(row)
		if not rows:
			continue

		frappe.get_doc(
			{
				"doctype": "eTIMS Stock Movement",
				"company": doc.company,
				"branch": branch,
				"voucher_type": doc.doctype,
				"voucher_no": doc.name,
				"posting_date": doc.posting_date,
				"direction": direction,
				"sar_ty_cd": sar_type_for(doc.doctype, direction, doc.get("is_return"), doc.get("purpose")),
				"items": rows,
			}
		).insert(ignore_permissions=True)
		created = True

	if created:
		_enqueue_branch(branch)


def on_cancel(doc, method=None):
	"""A movement KRA never accepted is just dropped. One it accepted can't be
	withdrawn - KRA has no cancel for stockIO - so it's reversed with an
	adjustment the other way, pointing back at it via orgSarNo."""
	movements = frappe.get_all(
		"eTIMS Stock Movement",
		filters={"voucher_type": doc.doctype, "voucher_no": doc.name, "reverses": ["is", "not set"]},
		fields=["name", "status", "sar_no"],
	)
	branches = set()
	for mv in movements:
		if mv.status == "Cancelled":
			continue
		if not mv.sar_no:
			frappe.db.set_value("eTIMS Stock Movement", mv.name, "status", "Cancelled")
			continue

		original = frappe.get_doc("eTIMS Stock Movement", mv.name)
		direction = "Out" if original.direction == "In" else "In"
		reversal = frappe.copy_doc(original)
		reversal.update(
			{
				"direction": direction,
				"sar_ty_cd": SAR_ADJUST_IN if direction == "In" else SAR_ADJUST_OUT,
				"status": "Pending",
				"sar_no": 0,
				"retry_count": 0,
				"error": "",
				"reverses": original.name,
			}
		)
		reversal.insert(ignore_permissions=True)
		branches.add(original.branch)

	for branch in branches:
		_enqueue_branch(branch)


def build_stock_io_payload(mv, sar_no, org_sar_no=0):
	items = [
		{
			"itemSeq": idx,
			"itemCd": row.item_cd,
			"itemClsCd": row.item_cls_cd,
			"itemNm": row.item_name,
			"bcd": None,
			"pkgUnitCd": row.pkg_unit_cd,
			"pkg": row.qty,
			"qtyUnitCd": row.qty_unit_cd,
			"qty": row.qty,
			"itemExprDt": None,
			"prc": row.rate,
			"splyAmt": row.total_amount,
			"totDcAmt": 0,
			"taxblAmt": row.taxable_amount,
			"taxTyCd": row.tax_ty_cd,
			"taxAmt": row.tax_amount,
			"totAmt": row.total_amount,
		}
		for idx, row in enumerate(mv.get("items"), start=1)
	]
	return {
		"sarNo": sar_no,
		"orgSarNo": org_sar_no,
		# "M" is what the sandbox has accepted (2026-10-26); "A" (automatic)
		# is untested.
		"regTyCd": "M",
		"custTin": None,
		"custNm": None,
		"custBhfId": None,
		"sarTyCd": mv.sar_ty_cd,
		"ocrnDt": getdate(mv.posting_date).strftime("%Y%m%d"),
		"totItemCnt": len(items),
		"totTaxblAmt": flt(sum(i["taxblAmt"] for i in items), 2),
		"totTaxAmt": flt(sum(i["taxAmt"] for i in items), 2),
		"totAmt": flt(sum(i["totAmt"] for i in items), 2),
		"remark": f"{mv.voucher_type} {mv.voucher_no}",
		"regrId": mv.owner,
		"regrNm": mv.owner,
		"modrId": mv.owner,
		"modrNm": mv.owner,
		"itemList": items,
	}


def kra_stock_balance(branch, item_cd):
	"""Stock KRA holds for `item_cd` on `branch`: the signed sum of every
	movement KRA has accepted (sar_no set), which is what save/stockMaster's
	rsdQty is checked against."""
	result = frappe.db.sql(
		"""
		SELECT COALESCE(SUM(CASE WHEN mv.direction = 'In' THEN i.qty ELSE -i.qty END), 0)
		FROM `tabeTIMS Stock Movement Item` i
		JOIN `tabeTIMS Stock Movement` mv ON mv.name = i.parent
		WHERE mv.branch = %s AND i.item_cd = %s AND mv.sar_no > 0
		""",
		(branch, item_cd),
	)
	return flt(result[0][0])


def send_movement(name):
	"""Send one movement. Returns True if KRA accepted the stockIO (even if a
	stockMaster update then failed - the sarNo is spent either way)."""
	mv = frappe.get_doc("eTIMS Stock Movement", name)
	lock_branch(mv.branch)
	# A locking read: a plain one would see this transaction's older snapshot.
	if frappe.db.get_value(mv.doctype, mv.name, "status", for_update=True) not in ("Pending", "Failed"):
		frappe.db.rollback()
		return True  # another job got here first

	org_sar_no = frappe.db.get_value("eTIMS Stock Movement", mv.reverses, "sar_no") if mv.reverses else 0

	def send(sar_no):
		return etims_request(
			mv.company,
			"insert/stockIO",
			payload=build_stock_io_payload(mv, sar_no, org_sar_no or 0),
			branch=mv.branch,
			reference_doctype=mv.doctype,
			reference_name=mv.name,
		)

	try:
		sar_no, _data = send_in_sequence(mv.branch, "last_sar_no", send)
	except Exception as e:
		mv.db_set({"status": "Failed", "error": str(e)[:500], "retry_count": (mv.retry_count or 0) + 1})
		frappe.db.commit()  # nosemgrep
		return False

	mv.db_set({"status": "Sent", "sar_no": sar_no, "error": ""})
	frappe.db.commit()  # nosemgrep - releases the branch lock as soon as the number is spent

	errors = []
	for item_cd in {row.item_cd for row in mv.get("items")}:
		try:
			etims_request(
				mv.company,
				"save/stockMaster",
				payload={
					"itemCd": item_cd,
					"rsdQty": kra_stock_balance(mv.branch, item_cd),
					"regrId": mv.owner,
					"regrNm": mv.owner,
					"modrId": mv.owner,
					"modrNm": mv.owner,
				},
				branch=mv.branch,
				reference_doctype=mv.doctype,
				reference_name=mv.name,
			)
		except Exception as e:
			errors.append(f"{item_cd}: {e}")

	if errors:
		mv.db_set({"status": "Stock Master Failed", "error": "\n".join(errors)[:500]})
	frappe.db.commit()  # nosemgrep
	return True


def process_branch_queue(branch):
	"""Send this branch's unsent movements oldest first, stopping at the first
	one KRA rejects - see the module docstring for why order matters."""
	pending = frappe.get_all(
		"eTIMS Stock Movement",
		filters={"branch": branch, "status": ["in", ("Pending", "Failed")]},
		fields=["name", "status", "retry_count"],
		order_by="creation asc",
	)
	for mv in pending:
		if mv.status == "Failed" and (mv.retry_count or 0) >= MAX_RETRY_COUNT:
			return  # needs a person; later movements would only drift further
		if not send_movement(mv.name):
			return


def retry_pending_movements():
	"""Scheduled safety net (hooks.py cron), alongside receipt retries."""
	for branch in frappe.get_all(
		"eTIMS Stock Movement",
		filters={"status": ["in", ("Pending", "Failed")]},
		pluck="branch",
		distinct=True,
	):
		_enqueue_branch(branch)


@frappe.whitelist()
def retry_movement_queue(branch):
	"""Manual "Retry" from the eTIMS Stock Movement form/list."""
	frappe.only_for(("System Manager", "Stock Manager"))
	frappe.db.set_value(
		"eTIMS Stock Movement",
		{"branch": branch, "status": "Failed"},
		"retry_count",
		0,
		update_modified=False,
	)
	_enqueue_branch(branch)
	return _("Queued eTIMS stock sync for {0}.").format(branch)
