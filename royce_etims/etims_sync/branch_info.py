# Copyright (c) 2026, Royce Technologies LTD and contributors
# For license information, please see license.txt

"""Branch information KRA keeps per device: the people who issue invoices on it
(branchUserAccount, Go-Live case 7) and the insurers it records compulsory
insurance for (branchInsuranceInfo, case 8).

Both are plain "save" calls with no number sequence, so a re-send of the same
record is just KRA's upsert. Saving queues the send; the form's "Send to KRA"
button sends at once and shows KRA's answer.

KRA wants a password with every branch user (`pwd`, required). Royce ERP users
sign in to Royce ERP, never to KRA's device, so no one ever types this
password: a random one is generated per send and not stored anywhere.
"""

import secrets

import frappe
from frappe import _
from frappe.utils import cstr, flt, now_datetime

from royce_etims.utils.api_client import request as etims_request

# KRA's sample values are 9-character IDs; until KRA says otherwise, keep within 20.
MAX_USER_ID_LENGTH = 20

SENDERS = {
	"eTIMS Branch User": ("branchUserAccount", "build_user_payload"),
	"eTIMS Branch Insurance": ("branchInsuranceInfo", "build_insurance_payload"),
}


def validate_branch_user(doc):
	duplicate = frappe.db.exists(
		"eTIMS Branch User", {"branch": doc.branch, "user": doc.user, "name": ["!=", doc.name]}
	)
	if duplicate:
		frappe.throw(
			_("{0} is already a user of eTIMS Branch {1} ({2}).").format(doc.user, doc.branch, duplicate)
		)
	if len(kra_user_id(doc.user)) > MAX_USER_ID_LENGTH:
		frappe.throw(
			_("KRA keeps user IDs to {0} characters; {1} is longer.").format(MAX_USER_ID_LENGTH, doc.user)
		)
	_mark_unsent_if_changed(doc, ("user", "contact", "address", "active"))


def validate_branch_insurance(doc):
	if flt(doc.rate) < 0:
		frappe.throw(_("The insurance rate can't be negative."))
	duplicate = frappe.db.exists(
		"eTIMS Branch Insurance",
		{"branch": doc.branch, "insurer_code": doc.insurer_code, "name": ["!=", doc.name]},
	)
	if duplicate:
		frappe.throw(
			_("Insurer {0} is already set up on eTIMS Branch {1} ({2}).").format(
				doc.insurer_code, doc.branch, duplicate
			)
		)
	_mark_unsent_if_changed(doc, ("insurer_code", "insurer_name", "rate", "active"))


def _mark_unsent_if_changed(doc, fields):
	if doc.is_new() or any(doc.has_value_changed(f) for f in fields):
		doc.status = "Not Sent"


def kra_user_id(user):
	"""The user's login without the mail domain - KRA's IDs are short codes."""
	return cstr(user).split("@", 1)[0]


def build_user_payload(doc):
	return {
		"userId": kra_user_id(doc.user),
		"userNm": (doc.full_name or doc.user)[:60],
		"pwd": secrets.token_urlsafe(12),
		"adrs": doc.address or None,
		"cntc": doc.contact or None,
		"authCd": None,
		"remark": None,
		"useYn": "Y" if doc.active else "N",
		"regrNm": doc.owner,
		"regrId": doc.owner,
		"modrNm": frappe.session.user,
		"modrId": frappe.session.user,
	}


def build_insurance_payload(doc):
	return {
		"isrccCd": doc.insurer_code,
		"isrccNm": doc.insurer_name,
		"isrcRt": flt(doc.rate),
		"useYn": "Y" if doc.active else "N",
		"regrNm": doc.owner,
		"regrId": doc.owner,
		"modrNm": frappe.session.user,
		"modrId": frappe.session.user,
	}


def on_update(doc, method=None):
	"""Queue the send after any save that left the record unsent."""
	if doc.status == "Sent":
		return
	frappe.enqueue(
		"royce_etims.etims_sync.branch_info.send",
		queue="short",
		enqueue_after_commit=True,
		job_id=f"royce_etims_branch_info::{doc.doctype}::{doc.name}",
		deduplicate=True,
		doctype=doc.doctype,
		name=doc.name,
	)


def send(doctype, name, raise_on_error=False):
	endpoint, builder = SENDERS[doctype]
	doc = frappe.get_doc(doctype, name)
	branch = frappe.get_doc("eTIMS Branch", doc.branch)
	try:
		etims_request(
			branch.company,
			endpoint,
			payload=globals()[builder](doc),
			branch=branch,
			reference_doctype=doctype,
			reference_name=name,
		)
	except Exception as e:
		doc.db_set(
			{"status": "Failed", "error": frappe.utils.strip_html(str(e))[:500]}, update_modified=False
		)
		frappe.db.commit()  # nosemgrep - keep the Failed status through the caller's rollback
		if raise_on_error:
			raise
		return False

	doc.db_set({"status": "Sent", "error": "", "sent_on": now_datetime()}, update_modified=False)
	frappe.db.commit()  # nosemgrep
	return True


@frappe.whitelist()
def send_now(doctype, name):
	""" "Send to KRA" button: send at once, show KRA's answer."""
	if doctype not in SENDERS:
		frappe.throw(_("{0} isn't sent to KRA from here.").format(doctype))
	frappe.get_doc(doctype, name).check_permission("write")
	send(doctype, name, raise_on_error=True)
	return _("KRA accepted {0}.").format(name)
