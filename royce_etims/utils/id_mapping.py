# Copyright (c) 2026, Royce Technologies LTD and contributors
# For license information, please see license.txt

"""Helpers for the `eTIMS ID Mapping` child table (pattern borrowed from
navari_csf_ke's eTims ID Mapping) - lets any doctype (Item today, Customer/
Supplier later) carry a different eTIMS-assigned ID per registration context,
instead of one flat field that breaks the moment a site runs more than one
company. `setup_docname` is the company name (eTIMS Settings is autonamed to
its company), `setup_doctype` is always "eTIMS Settings" for our use - kept as
a field rather than hardcoded so a future context (e.g. per-Branch mapping)
doesn't need a schema change.
"""

SETUP_DOCTYPE = "eTIMS Settings"


def get_etims_id(doc, company):
	"""Return the eTIMS ID for `doc` under `company`'s registration, or None."""
	for row in doc.get("etims_id_mapping") or []:
		if row.setup_doctype == SETUP_DOCTYPE and row.setup_docname == company and not row.disabled:
			return row.etims_id
	return None


def has_etims_id(doc, company):
	return bool(get_etims_id(doc, company))


def set_etims_id(doc, company, etims_id):
	"""Set (or update) the eTIMS ID for `doc` under `company`. Caller is
	responsible for saving `doc` afterwards."""
	for row in doc.get("etims_id_mapping") or []:
		if row.setup_doctype == SETUP_DOCTYPE and row.setup_docname == company:
			row.etims_id = etims_id
			row.disabled = 0
			return
	doc.append(
		"etims_id_mapping",
		{"setup_doctype": SETUP_DOCTYPE, "setup_docname": company, "etims_id": etims_id},
	)
