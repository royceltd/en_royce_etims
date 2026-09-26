# Copyright (c) 2026, Royce Technologies LTD and contributors
# For license information, please see license.txt

"""Seeds exactly one SAMPLE-ONLY row each for eTIMS Item Classification,
Packaging Unit, and Quantity Unit - the three reference doctypes
seed_etims_reference_data.py deliberately left empty (see that patch's
docstring: no authoritative full list existed at the time it ran).

These three values (itemClsCd 1010151700, pkgUnitCd NT, qtyUnitCd BA) are NOT
a guess invented for this patch - they're literal example values used in
eTIMS-OSCU-Integrator-Automated-Testing-Sandbox.json's own "Send/Save Item
information" (saveItem) sample request body, the same collection
docs/architecture.md's 2026-09-05 correction confirmed is the real,
currently-correct API surface. Decided 2026-09-11 (with the user, not
unilaterally - see docs/architecture.md): use these to unblock building and
testing one real Item/receipt payload today, rather than wait on the
still-not-built selectCodeList/selectItemClass reference-data sync.

**This is explicitly a stopgap, not a real code list** - it covers exactly
enough to construct one test Item. Before any client's real catalogue goes
live, replace/supplement this with a real sync against KRA's selectItemClass
(or selectItemClsList - see docs/architecture.md's endpoint-name ambiguity
note) and whatever endpoint actually returns packaging/quantity unit codes.
Don't let this patch's existence be mistaken for "reference data sync done."
"""

import frappe

ITEM_CLASSIFICATIONS = [
	{
		"code": "1010151700",
		"description": "Sample-only, from saveItem's Postman example - NOT a full list. Replace before go-live.",
	},
]

PACKAGING_UNITS = [
	{
		"code": "NT",
		"description": "Sample-only, from saveItem's Postman example - NOT a full list. Replace before go-live.",
	},
]

QUANTITY_UNITS = [
	{
		"code": "BA",
		"description": "Sample-only, from saveItem's Postman example - NOT a full list. Replace before go-live.",
	},
]


def execute():
	for row in ITEM_CLASSIFICATIONS:
		if not frappe.db.exists("eTIMS Item Classification", row["code"]):
			frappe.get_doc({"doctype": "eTIMS Item Classification", **row}).insert(ignore_permissions=True)

	for row in PACKAGING_UNITS:
		if not frappe.db.exists("eTIMS Packaging Unit", row["code"]):
			frappe.get_doc({"doctype": "eTIMS Packaging Unit", **row}).insert(ignore_permissions=True)

	for row in QUANTITY_UNITS:
		if not frappe.db.exists("eTIMS Quantity Unit", row["code"]):
			frappe.get_doc({"doctype": "eTIMS Quantity Unit", **row}).insert(ignore_permissions=True)

	frappe.db.commit()
