# Copyright (c) 2026, Royce Technologies LTD and contributors
# For license information, please see license.txt

"""Seeds only the two reference tables we have real evidence for from the
eTIMS-OSCU-Integrator-Automated-Testing-Sandbox collection - Taxation Type
(taxRtA..E appear in the sendPurchaseTransactionInfo sample: 0/16/0/0/0) and
Item Type (itemTyCd values 1/2/3, described in the saveItem sample comments).

Item Classification / Packaging Unit / Quantity Unit / Country of Origin are
deliberately left EMPTY - the collection only shows a handful of ad hoc
example values (e.g. "NT", "BA", "KE") with no authoritative full list.
Seeding guesses there would look like real reference data when it isn't;
better to leave them for selectCodeList/selectItemClass sync (still an open
item in docs/architecture.md) than assert something unverified.
"""

import frappe

# TODO: confirm rates against KRA's selectCodeList before go-live - same
# caveat as the TAX_RATE_BY_CODE dict this replaces in etims_sync/receipt.py.
TAXATION_TYPES = [
	{"code": "A", "description": "Exempt (best-effort, confirm via selectCodeList)", "rate": 0},
	{"code": "B", "description": "Standard Rate (best-effort, confirm via selectCodeList)", "rate": 16},
	{"code": "C", "description": "Zero Rated (best-effort, confirm via selectCodeList)", "rate": 0},
	{"code": "D", "description": "Non-VAT (best-effort, confirm via selectCodeList)", "rate": 0},
	{"code": "E", "description": "(best-effort, confirm via selectCodeList)", "rate": 0},
]

ITEM_TYPES = [
	{"code": "1", "description": "Raw Material"},
	{"code": "2", "description": "Finished Product"},
	{"code": "3", "description": "Service"},
]


def execute():
	for row in TAXATION_TYPES:
		if not frappe.db.exists("eTIMS Taxation Type", row["code"]):
			frappe.get_doc({"doctype": "eTIMS Taxation Type", **row}).insert(ignore_permissions=True)

	for row in ITEM_TYPES:
		if not frappe.db.exists("eTIMS Item Type", row["code"]):
			frappe.get_doc({"doctype": "eTIMS Item Type", **row}).insert(ignore_permissions=True)

	frappe.db.commit()
