# Copyright (c) 2026, Royce Technologies LTD and contributors
# For license information, please see license.txt

"""eTIMS Settings > Register All Items with KRA: every item a company sells,
registered in one background run, each with the stock it has now.

A shop going live has its whole catalogue to register (Lick Agencies: 1,965
items, 444 item groups, no Item Tax Templates). Each item gets the KRA fields
it lacks from what ERPNext already knows (item.fill_defaults), then from the
company's eTIMS Settings defaults: VAT band (B, 16%) for an item with no Item
Tax Template, and a KRA product category for an item group that has none. A
value already on the item is never changed. Items that still can't be
registered (a unit with no 2-letter KRA code, say) are listed in the run's
summary on eTIMS Settings and in Compliance Status."""

import frappe
from frappe import _

from royce_etims.etims_sync import item as item_sync
from royce_etims.utils.api_client import get_settings
from royce_etims.utils.id_mapping import SETUP_DOCTYPE

KRA_FIELDS = (
	"royce_etims_item_classification",
	"royce_etims_item_type",
	"royce_etims_taxation_type",
	"royce_etims_origin_nation",
	"royce_etims_packaging_unit",
	"royce_etims_quantity_unit",
)


@frappe.whitelist()
def register_all_items(company):
	frappe.only_for(("System Manager", "Accounts Manager"))
	settings = get_settings(company)
	if settings.status != "Active":
		frappe.throw(_("Activate eTIMS for {0} first.").format(company))
	count = len(items_to_register(company))
	if not count:
		return _("Every item of {0} is already registered with KRA.").format(company)
	frappe.enqueue(
		"royce_etims.etims_sync.bulk_items.register_items",
		queue="long",
		timeout=6 * 3600,
		job_id=f"royce_etims_register_items::{company}",
		deduplicate=True,
		company=company,
	)
	return _(
		"Registering {0} items with KRA in the background. Compliance Status shows what's left; the summary is added to this page's comments when it finishes."
	).format(count)


def items_to_register(company):
	registered = set(
		frappe.get_all(
			"eTIMS ID Mapping",
			filters={"parenttype": "Item", "setup_doctype": SETUP_DOCTYPE, "setup_docname": company, "disabled": 0},
			pluck="parent",
		)
	)
	items = frappe.get_all(
		"Item",
		filters={"disabled": 0, "is_sales_item": 1, "has_variants": 0, "royce_prevent_etims_submission": 0},
		pluck="name",
		order_by="name",
	)
	return [name for name in items if name not in registered]


def register_items(company, limit=None):
	"""The background run. `limit`: only the first N items - for a trial run
	from the console before registering a whole catalogue."""
	settings = get_settings(company)
	item_sync.map_common_uoms()
	branch = frappe.get_doc("eTIMS Branch", settings.default_branch)
	kra_codes = item_sync._kra_item_codes(company, branch)
	registered, failed = 0, {}
	for name in items_to_register(company)[: limit or None]:
		try:
			fill_kra_fields(name, settings)
			frappe.db.commit()  # nosemgrep - the defaults stay even if KRA refuses the item
			item_sync.sync_item(name, company, kra_codes=kra_codes)
			frappe.db.commit()  # nosemgrep
			registered += 1
		except Exception as e:
			frappe.db.rollback()
			failed[name] = frappe.utils.strip_html(str(e))[:200]
	_record_summary(company, registered, failed)
	return {"registered": registered, "failed": failed}


def fill_kra_fields(item_code, settings):
	"""Fill the empty KRA fields of one item; returns what was set."""
	item = frappe.get_doc("Item", item_code)
	before = {f: item.get(f) for f in KRA_FIELDS}
	item_sync.fill_defaults(item)
	if not item.get("royce_etims_item_classification"):
		item_sync._fill(
			item,
			"royce_etims_item_classification",
			settings.get("default_item_classification"),
			"eTIMS Item Classification",
		)
	item_sync.fill_taxation_type(item)  # from the item's Item Tax Template
	if not item.get("royce_etims_taxation_type"):
		item.royce_etims_taxation_type = settings.get("default_vat_band") or None
		item_sync.fill_taxation_type(item)  # sets the band's code and rate
	changed = {}
	for field in KRA_FIELDS:
		if item.get(field) != before[field]:
			changed[field] = item.get(field)
			changed[f"{field}_code"] = item.get(f"{field}_code")
	if changed.get("royce_etims_taxation_type"):
		changed["royce_etims_taxation_type_rate"] = item.get("royce_etims_taxation_type_rate")
	if changed:
		frappe.db.set_value("Item", item_code, changed, update_modified=False)
	return changed


def _record_summary(company, registered, failed):
	reasons = {}
	for name, error in failed.items():
		reasons.setdefault(error, []).append(name)
	lines = [_("Registered with KRA: {0}. Not registered: {1}.").format(registered, len(failed))]
	for error, names in sorted(reasons.items(), key=lambda r: -len(r[1]))[:10]:
		shown = ", ".join(names[:5]) + (_(" and {0} more").format(len(names) - 5) if len(names) > 5 else "")
		lines.append(f"{len(names)} x {frappe.utils.escape_html(error)} ({shown})")
	frappe.get_doc("eTIMS Settings", company).add_comment("Info", "<br>".join(lines))
	frappe.db.commit()  # nosemgrep
