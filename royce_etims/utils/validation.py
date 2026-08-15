# Copyright (c) 2026, Royce Technologies LTD and contributors
# For license information, please see license.txt

"""KRA PIN/TIN format check, shared by eTIMS Settings and the Sales Invoice
payload builder. Regex borrowed from csf_ke's Customer PIN validation
(csf_ke/overrides/validate_pin.py) - one letter, nine digits, one letter,
e.g. P123456789H or A123456789Z.
"""

import re

import frappe
from frappe import _

KRA_PIN_PATTERN = re.compile(r"^[A-Z]\d{9}[A-Z]$")


def validate_kra_pin(pin, label=None):
	"""Raise a clear, local error for a malformed PIN/TIN rather than letting
	it reach KRA and come back as an opaque rejection."""
	if not pin:
		return
	if not KRA_PIN_PATTERN.match(pin):
		frappe.throw(
			_("{0} {1} is not a valid KRA PIN/TIN format. Expected e.g. P123456789H.").format(
				label or _("Value"), pin
			)
		)
