# Copyright (c) 2026, Royce Technologies LTD and contributors
# For license information, please see license.txt

"""KRA's per-device number sequences (invcNo, sarNo) - shared by receipt and
stock movement sync.

KRA accepts exactly last+1 and nothing else - CONFIRMED 2026-10-26: "Invalid
sarNo: Expected: 6 but found: 1", "Invalid invcNo sequence, expected: 1 but
found: 2". So the counter on eTIMS Branch means "last number KRA accepted",
and only moves when KRA accepts. A rejected call never consumes a number;
the old "consumed either way, never reused" rule left a gap after any
failure, and KRA rejects every number after a gap.

The branch row stays locked (SELECT ... FOR UPDATE) for the whole KRA call,
so two jobs can't send the same number. The caller commits or rolls back,
which releases it.

KRA's own rejection names the number it expected. When ours disagrees (e.g.
KRA's certification harness used numbers on the same device), the counter
resyncs to that and the call is resent once.
"""

import re

import frappe

# Only sequence complaints count: KRA uses the same "Expected: N" wording for
# amounts ("Invalid taxblAmt on item: 1. Expected: 8620.69" - which this
# once misread as sarNo 8620), so the message must name invcNo/sarNo and the
# number must be whole.
EXPECTED_NUMBER = re.compile(
	r"(?:sarNo|invcNo|Invc No)\b.*?expected(?: value)?:\s*(\d+)(?![\d.])",
	re.IGNORECASE,
)


def kra_expected_number(message):
	"""The number KRA says it expected, from its rejection text, or None."""
	match = EXPECTED_NUMBER.search(message or "")
	return int(match.group(1)) if match else None


def lock_branch(branch_name):
	"""Take the branch's row lock before deciding whether something still needs
	sending, so two jobs for the same document can't both send it."""
	frappe.db.sql("SELECT name FROM `tabeTIMS Branch` WHERE name=%s FOR UPDATE", branch_name)


def _lock_counter(branch_name, field):
	row = frappe.db.sql(
		f"SELECT `{field}` FROM `tabeTIMS Branch` WHERE name=%s FOR UPDATE",
		branch_name,
	)
	if not row:
		frappe.throw(frappe._("eTIMS Branch {0} not found.").format(branch_name))
	return row[0][0] or 0


def _set_counter(branch_name, field, value):
	frappe.db.set_value("eTIMS Branch", branch_name, field, value, update_modified=False)


def send_in_sequence(branch_name, field, send):
	"""Call `send(number)` with the branch's next number for `field`, resyncing
	once to KRA's expected number if it names one. Returns (number, result);
	raises whatever `send` raises on final failure. A resync is kept even when
	the resent call fails too - it's still KRA's real position."""
	number = _lock_counter(branch_name, field) + 1
	try:
		result = send(number)
	except Exception as e:
		expected = kra_expected_number(str(e))
		if not expected or expected == number:
			raise
		number = expected
		_set_counter(branch_name, field, number - 1)
		result = send(number)

	_set_counter(branch_name, field, number)
	return number, result
