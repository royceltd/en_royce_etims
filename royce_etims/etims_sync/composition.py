# Copyright (c) 2026, Royce Technologies LTD and contributors
# For license information, please see license.txt

"""Tell KRA what a manufactured item is made of (saveItemComposition, Go-Live
case 11), from the item's default Bill of Materials.

KRA takes one component per call: the finished item's code, the component's
code and how much of the component goes into ONE unit of the finished item.
A BOM is written for `quantity` units, so each component's stock quantity is
divided by that. Both items must already be registered with KRA (Item ->
Sync to eTIMS); KRA requires the component to exist.

KRA also requires every component to have stock at KRA (in its stock master):
CONFIRMED 2026-11-18, a component never stocked was refused with "Insufficient
stock: Item KE2NTKG0000007 does not exist in stock master". Receive some of
each component first (any stock entry eTIMS sends), then send the composition.

Sent when a default BOM is submitted, or by the BOM's "Send to KRA eTIMS"
button. A BOM that stops being the default isn't withdrawn - KRA has no call
for that; the next default BOM's components are simply sent too.
"""

from collections import OrderedDict

import frappe
from frappe import _
from frappe.utils import flt

from royce_etims.utils.api_client import get_settings
from royce_etims.utils.api_client import request as etims_request
from royce_etims.utils.id_mapping import get_etims_id

# KRA's sample sends cpstQty as a plain number; keep it to KRA's usual precision.
QTY_PRECISION = 4


def _active_settings(company):
	if not frappe.db.exists("eTIMS Settings", company):
		return None
	settings = get_settings(company)
	if settings.status != "Active" or not settings.default_branch:
		return None
	return settings


def on_submit(doc, method=None):
	"""BOM on_submit hook: queue the send for a default BOM of an eTIMS company."""
	if not doc.get("is_default") or not _active_settings(doc.company):
		return
	frappe.enqueue(
		"royce_etims.etims_sync.composition.send_bom",
		queue="short",
		enqueue_after_commit=True,
		job_id=f"royce_etims_composition::{doc.name}",
		deduplicate=True,
		bom=doc.name,
	)


def component_quantities(bom):
	"""{component item_code: quantity per ONE finished unit}, components merged."""
	per_unit = OrderedDict()
	batch = flt(bom.quantity) or 1
	for row in bom.items:
		qty = flt(row.stock_qty or row.qty) / batch
		per_unit[row.item_code] = per_unit.get(row.item_code, 0) + qty
	return OrderedDict((code, flt(qty, QTY_PRECISION)) for code, qty in per_unit.items())


def build_payloads(bom, company):
	"""One saveItemComposition payload per component. Raises listing every
	item that isn't registered with KRA yet, so they can all be fixed at once."""
	finished = frappe.get_doc("Item", bom.item)
	item_cd = get_etims_id(finished, company)
	missing = [] if item_cd else [bom.item]

	payloads = []
	for code, qty in component_quantities(bom).items():
		component_cd = get_etims_id(frappe.get_cached_doc("Item", code), company)
		if not component_cd:
			missing.append(code)
			continue
		payloads.append(
			{
				"itemCd": item_cd,
				"cpstItemCd": component_cd,
				"cpstQty": qty,
				"regrId": frappe.session.user,
				"regrNm": frappe.session.user,
			}
		)

	if missing:
		frappe.throw(
			_("Register these items with KRA first (Item > Sync to eTIMS): {0}").format(", ".join(missing)),
			title=_("Not registered with KRA"),
		)
	return payloads


def send_bom(bom, raise_on_error=False):
	doc = frappe.get_doc("BOM", bom)
	settings = _active_settings(doc.company)
	if not settings:
		frappe.throw(_("eTIMS isn't active for {0}.").format(doc.company))

	try:
		for payload in build_payloads(doc, doc.company):
			etims_request(
				doc.company,
				"saveItemComposition",
				payload=payload,
				branch=settings.default_branch,
				reference_doctype="BOM",
				reference_name=doc.name,
			)
	except Exception as e:
		if "does not exist in stock master" in str(e):
			e = frappe.ValidationError(
				_(
					"KRA has no stock of a component yet, so it refused the composition. Receive the components into stock first. KRA said: {0}"
				).format(e)
			)
		doc.db_set(
			{
				"royce_etims_composition_status": "Failed",
				"royce_etims_composition_error": frappe.utils.strip_html(str(e))[:500],
			},
			update_modified=False,
		)
		frappe.db.commit()  # nosemgrep - keep the Failed status through the caller's rollback
		if raise_on_error:
			raise
		return False

	doc.db_set(
		{"royce_etims_composition_status": "Sent", "royce_etims_composition_error": ""},
		update_modified=False,
	)
	frappe.db.commit()  # nosemgrep
	return True


@frappe.whitelist()
def send_now(bom):
	doc = frappe.get_doc("BOM", bom)
	doc.check_permission("write")
	if doc.docstatus != 1:
		frappe.throw(_("Submit the BOM before sending its composition to KRA."))
	send_bom(bom, raise_on_error=True)
	return _("KRA has the composition of {0}.").format(doc.item)
