# Copyright (c) 2026, Royce Technologies LTD and contributors
# For license information, please see license.txt

"""Register customers that have a KRA PIN with KRA (branchSendCustomerInfo).

CONFIRMED 2026-10-26 against the sandbox: customerPinInfo is NOT a PIN
checker - it lists the customers this branch has registered through
branchSendCustomerInfo, and ignores any PIN passed to it. OSCU has no way to
check a PIN against KRA's register (that's GavaConnect's separate PIN
Checker API), so the only PIN check here is the local format one.

Customers are shared across companies, so a customer is registered with
every Active company's default branch.

custNo can't be the Customer's ID: KRA caps it at 15 characters - CONFIRMED
2026-10-26 ("<custNo> : length must be between 0 and 15") with a customer
named after an 82-character business name. Each customer gets its own
RC-######## number on first registration instead, kept for life.
"""

import frappe
from frappe import _
from frappe.model.naming import make_autoname
from frappe.utils import cstr

from royce_etims.utils.api_client import request as etims_request
from royce_etims.utils.validation import KRA_PIN_PATTERN

CUSTOMER_NO_SERIES = "RC-.########"

# Changes to anything else on a Customer don't need re-sending.
SYNCED_FIELDS = ("tax_id", "customer_name", "disabled", "mobile_no", "email_id")


def _active_companies():
	return frappe.get_all(
		"eTIMS Settings",
		filters={"status": "Active", "default_branch": ["is", "set"]},
		pluck="name",
	)


def on_update(doc, method=None):
	"""doc_events hook. Queues registration; never calls KRA inline."""
	if not KRA_PIN_PATTERN.match(cstr(doc.tax_id)) or not _active_companies():
		return
	unchanged = not any(doc.has_value_changed(f) for f in SYNCED_FIELDS)
	if unchanged and doc.get("royce_etims_customer_status") == "Synced":
		return

	frappe.enqueue(
		"royce_etims.etims_sync.customer.sync_customer",
		queue="short",
		enqueue_after_commit=True,
		job_id=f"royce_etims_customer::{doc.name}",
		deduplicate=True,
		name=doc.name,
	)


def build_customer_payload(customer):
	return {
		"custNo": customer.royce_etims_customer_no,
		"custTin": customer.tax_id,
		"custNm": customer.customer_name,
		"adrs": None,
		"telNo": customer.get("mobile_no") or None,
		"email": customer.get("email_id") or None,
		"faxNo": None,
		"useYn": "N" if customer.disabled else "Y",
		"remark": None,
		"regrNm": customer.owner,
		"regrId": customer.owner,
		"modrNm": customer.modified_by,
		"modrId": customer.modified_by,
	}


def sync_customer(name):
	customer = frappe.get_doc("Customer", name)
	if not customer.get("royce_etims_customer_no"):
		customer.db_set("royce_etims_customer_no", make_autoname(CUSTOMER_NO_SERIES), update_modified=False)
	errors = []
	for company in _active_companies():
		try:
			etims_request(
				company,
				"branchSendCustomerInfo",
				payload=build_customer_payload(customer),
				branch=frappe.db.get_value("eTIMS Settings", company, "default_branch"),
				reference_doctype="Customer",
				reference_name=name,
			)
		except Exception as e:
			errors.append(_("{0}: {1}").format(company, e))

	customer.db_set(
		{
			"royce_etims_customer_status": "Failed" if errors else "Synced",
			"royce_etims_customer_error": "\n".join(errors)[:500],
		},
		update_modified=False,
	)
	frappe.db.commit()  # nosemgrep - background job; keep the status with its eTIMS Log rows
