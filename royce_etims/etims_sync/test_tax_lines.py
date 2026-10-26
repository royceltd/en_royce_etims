# Copyright (c) 2026, Royce Technologies LTD and Contributors
# See license.txt

from decimal import Decimal
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from royce_etims.etims_sync.tax_lines import (
	DEFAULT_TEMPLATE_BANDS,
	kra_split,
	price_parts,
	resolve_band,
	set_default_band,
	vat_by_item_row,
)

RATES = {"A": 0, "B": 16, "C": 0, "D": 0, "E": 8}


def _line(**fields):
	return frappe._dict({"idx": 1, "item_code": "ITEM", "item_tax_template": None, **fields})


class IntegrationTestTaxLines(IntegrationTestCase):
	def test_kra_split_matches_kra_figures(self):
		self.assertEqual(kra_split(1000, 16), (862.07, 137.93))  # KRA's own, 2026-09-23
		self.assertEqual(kra_split(1345.6, 16), (1160, 185.6))
		self.assertEqual(kra_split(500, 0), (500, 0))
		# KRA splits the unrounded 25.37 x 182.50 = 4630.025, each part on its own
		# (live 2026-10-26) - the parts sum to 4630.02, a cent under splyAmt.
		self.assertEqual(kra_split(Decimal("4630.025"), 16), (3991.40, 638.62))

	def test_band_from_item_tax_template_first(self):
		with patch("frappe.get_cached_value", return_value="A"):
			band = resolve_band(
				_line(item_tax_template="KE Exempt - X"),
				frappe._dict(royce_etims_taxation_type="B"),
				100,
				0,
				RATES,
			)
		self.assertEqual(band, "A")

	def test_band_from_item_then_rate(self):
		self.assertEqual(
			resolve_band(_line(), frappe._dict(royce_etims_taxation_type="C"), 100, 0, RATES), "C"
		)
		self.assertEqual(resolve_band(_line(), frappe._dict(), 1000, 160, RATES), "B")
		self.assertEqual(resolve_band(_line(), frappe._dict(), 1000, 80, RATES), "E")

	def test_zero_rate_line_needs_an_explicit_band(self):
		with self.assertRaises(frappe.ValidationError):
			resolve_band(_line(), frappe._dict(), 1000, 0, RATES)

	def test_vat_comes_only_from_vat_rows(self):
		doc = frappe._dict(
			taxes=[frappe._dict(name="t1", idx=1, account_head="VAT", base_tax_amount=160)],
			item_wise_tax_details=[
				frappe._dict(item_row="r1", tax_row="t1", amount=100),
				frappe._dict(item_row="r2", tax_row="t1", amount=60),
			],
		)
		with patch("frappe.get_cached_value", return_value="Tax"):
			self.assertEqual(vat_by_item_row(doc), {"r1": 100, "r2": 60})

	def test_non_vat_charge_is_refused(self):
		doc = frappe._dict(
			taxes=[frappe._dict(name="t1", idx=1, account_head="Freight", base_tax_amount=500)],
			item_wise_tax_details=[],
		)
		with patch("frappe.get_cached_value", return_value="Chargeable"):
			with self.assertRaises(frappe.ValidationError):
				vat_by_item_row(doc)

	def test_standard_templates_get_their_band(self):
		for title, band in DEFAULT_TEMPLATE_BANDS.items():
			doc = frappe._dict(title=title, royce_etims_taxation_type=None)
			set_default_band(doc)
			self.assertEqual(doc.royce_etims_taxation_type, band)
		chosen = frappe._dict(title="KE Exempt", royce_etims_taxation_type="D")
		set_default_band(chosen)
		self.assertEqual(chosen.royce_etims_taxation_type, "D")  # the accountant's choice stays

	def test_price_parts_whole_cents(self):
		self.assertEqual(price_parts(1345.6, 1), [(1, 1345.6)])
		self.assertEqual(price_parts(300, 3), [(3, 100)])
		# Live 2026-10-26: 7 x 13.13 + 16% VAT = 106.62 doesn't divide into cents.
		parts = price_parts(106.62, 7)
		self.assertEqual(parts, [(6, 15.23), (1, 15.24)])
		self.assertAlmostEqual(sum(q * p for q, p in parts), 106.62, places=2)

	def test_price_parts_fractional_quantity_that_divides(self):
		# 25.37 L at 182.50 = 4630.025, which KRA rounds half up.
		self.assertEqual(price_parts(4630.03, 25.37), [(25.37, 182.5)])

	def test_price_parts_refuses_fractional_quantity_off_by_a_cent(self):
		with self.assertRaises(frappe.ValidationError):
			price_parts(100.01, 2.5, _line())
