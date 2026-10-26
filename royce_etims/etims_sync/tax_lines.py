# Copyright (c) 2026, Royce Technologies LTD and contributors
# For license information, please see license.txt

"""Per-line VAT for a signed invoice, taken from what ERPNext actually posted.

KRA must receive exactly the VAT that's in the books. Two live rejections on
2026-10-26 showed how it goes wrong when the payload works VAT out on its own:
an invoice with VAT added on top (1,160 + 16% = 1,345.60) was sent as 1,160
VAT-inclusive ("Invalid totAmt . Expected: 1160.00, But Found: 1345.6"), and
an invoice with no VAT row at all - which posted no VAT - would have been
signed with 160 VAT the ledger didn't have.

So each line's VAT is read from ERPNext's Item Wise Tax Detail (v16), and:

- gross (what KRA calls the VAT-inclusive line total) = net + that VAT, so
  inclusive and VAT-on-top templates both come out right;
- KRA recomputes taxblAmt = gross / (1 + rate) itself (confirmed 2026-09-23),
  so taxblAmt/taxAmt are split that way - and must agree with ERPNext's VAT
  to the cent, or the line's band and the books disagree and signing stops;
- the band comes from the line's Item Tax Template (its eTIMS Taxation Type),
  then the Item's own band, then the rate itself (16 -> B, 8 -> E). A 0% line
  needs an explicit band: exempt (A), zero-rated (C) and non-VAT (D) can't be
  told apart by rate, and the difference decides who can claim input VAT.
"""

from decimal import ROUND_HALF_UP, Decimal

import frappe
from frappe import _
from frappe.utils import flt

# eTIMS band for kenyan_accountant's standard Item Tax Templates, by title.
# Non-Claimable is about the buyer's input VAT; the sale itself is still 16%/8%.
DEFAULT_TEMPLATE_BANDS = {
	"KE Standard 16%": "B",
	"KE Non-Claimable 16%": "B",
	"KE Reduced 8%": "E",
	"KE Non-Claimable 8%": "E",
	"KE Exempt": "A",
	"KE Zero Rated": "C",
}

# Per-line tolerance between ERPNext's VAT and KRA's split of the same gross:
# ERPNext spreads invoice-level rounding across lines a cent at a time.
CENT_TOLERANCE = 0.05


def vat_by_item_row(doc):
	"""{Sales Invoice Item name: VAT posted on that line}, from the invoice's
	VAT rows only. Any other charge row (freight, packaging...) can't be put
	on a KRA invoice, which has items and VAT and nothing else."""
	vat_rows = set()
	for tax in doc.get("taxes") or []:
		if frappe.get_cached_value("Account", tax.account_head, "account_type") == "Tax":
			vat_rows.add(tax.name)
		elif flt(tax.base_tax_amount):
			frappe.throw(
				_(
					"Row {0} in Taxes and Charges ({1}) isn't VAT. A KRA invoice can only carry items and VAT -"
					" add this charge as an item instead."
				).format(tax.idx, tax.account_head)
			)

	vat = {}
	for detail in doc.get("item_wise_tax_details") or []:
		if detail.tax_row in vat_rows:
			vat[detail.item_row] = vat.get(detail.item_row, 0.0) + flt(detail.amount)
	return vat


def money(value):
	"""Round to cents the way KRA does: half up - CONFIRMED 2026-10-26, 25.37 x
	182.50 = 4630.025 is "Expected: 4630.03". Python floats and ERPNext's
	Banker's Rounding both give 4630.02, so KRA amounts never go through flt()."""
	return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def exact_amount(qty, prc):
	return Decimal(str(qty)) * Decimal(str(prc))


def line_amount(qty, prc):
	return money(exact_amount(qty, prc))


def kra_split(amount, rate):
	"""(taxable, tax) for a VAT-inclusive line, as KRA recomputes them: each on
	its own from the *unrounded* qty x prc, rounded half up - CONFIRMED live
	2026-10-26 for 25.37 x 182.50 = 4630.025: taxblAmt "Expected: 3991.40",
	taxAmt "Expected: 638.62". They needn't add up to the rounded splyAmt
	(4630.03); KRA's line totAmt is their sum (4630.02, also confirmed)."""
	exact = Decimal(str(amount))
	if not rate:
		return money(exact), 0.0
	r = Decimal(str(rate))
	return money(exact * 100 / (100 + r)), money(exact * r / (100 + r))


def price_parts(gross, qty, line=None):
	"""[(qty, prc), ...] whose qty x prc add up to `gross` exactly, with prc in
	whole cents. KRA checks splyAmt == prc x qty at 2 decimals - CONFIRMED
	2026-10-26: 7 x 13.13 + VAT = 106.62 sent as prc 15.23 (or 15.231429) came
	back "Invalid splyAmnt on item: 1. Expected: 106.61". A discount can't take
	up the cent either: KRA only honours whole-percent dcRt (0.06% was read as
	0%). So such a line goes as two: some units at the lower cent, the rest one
	cent up - 6 x 15.23 + 1 x 15.24 = 106.62.

	Only whole quantities split; a fractional quantity whose total doesn't
	divide into cents is refused rather than sent off by a cent. In practice
	that's VAT-on-top pricing by litre or kilo - price such items VAT-inclusive
	(fuel already is) and the amount always divides."""
	if not qty:
		return [(qty, gross)]
	prc = money(Decimal(str(gross)) / Decimal(str(qty)))
	if abs(line_amount(qty, prc) - gross) < 0.001:
		return [(qty, prc)]

	if qty != int(qty):
		frappe.throw(
			_(
				"Row {0} ({1}): {2} for a quantity of {3} doesn't come to a whole-cent unit price, which KRA"
				" requires. Price this item VAT-inclusive, or adjust the rate."
			).format(line.idx if line else "", line.item_code if line else "", gross, qty)
		)
	cents, units = round(gross * 100), int(qty)
	low, extra = divmod(cents, units)
	parts = [(units - extra, low / 100), (extra, (low + 1) / 100)]
	return [(q, p) for q, p in parts if q]


def resolve_band(line, item, net, vat, rates):
	"""eTIMS taxation type (A-E) for one invoice line - see module docstring."""
	if line.get("item_tax_template"):
		band = frappe.get_cached_value(
			"Item Tax Template", line.item_tax_template, "royce_etims_taxation_type"
		)
		if band:
			return band
	if item.get("royce_etims_taxation_type"):
		return item.royce_etims_taxation_type

	effective = flt(vat / net * 100, 2) if net else 0
	if effective:
		for code in ("B", "E", *rates):
			if rates.get(code) and abs(rates[code] - effective) < 0.1:
				return code
	frappe.throw(
		_(
			"Row {0} ({1}) is charged {2}% VAT and has no eTIMS band. Set an eTIMS Taxation Type on its"
			" Item Tax Template or Item - exempt (A), zero-rated (C) and non-VAT (D) are all 0% and KRA"
			" needs to know which."
		).format(line.idx, line.item_code, effective)
	)


def check_line(line, band, rate, vat, kra_tax):
	if abs(kra_tax - abs(flt(vat))) > CENT_TOLERANCE:
		frappe.throw(
			_(
				"Row {0} ({1}): its eTIMS band {2} means {3}% VAT ({4}), but the invoice charges {5} VAT on it."
				" Pick the right VAT template on the invoice, or the right tax template on the item, so the"
				" books and KRA agree."
			).format(line.idx, line.item_code, band, flt(rate), kra_tax, abs(flt(vat)))
		)


def check_total(doc, total_gross):
	expected = abs(flt(doc.base_grand_total))
	if abs(total_gross - expected) > CENT_TOLERANCE:
		frappe.throw(
			_(
				"The invoice lines add up to {0} including VAT but the invoice total is {1}. An invoice-level"
				" discount or charge can't be split onto KRA's lines - apply it per item instead."
			).format(total_gross, expected)
		)


def set_default_band(doc, method=None):
	"""Item Tax Template validate hook: give a standard KE template its band if
	none is set. One the accountant has set is left alone."""
	if not doc.get("royce_etims_taxation_type") and doc.title in DEFAULT_TEMPLATE_BANDS:
		band = DEFAULT_TEMPLATE_BANDS[doc.title]
		if frappe.db.exists("eTIMS Taxation Type", band):
			doc.royce_etims_taxation_type = band
