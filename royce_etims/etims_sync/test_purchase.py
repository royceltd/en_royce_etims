# Copyright (c) 2026, Royce Technologies LTD and Contributors
# See license.txt

"""Purchases (etims_sync/purchase.py). The figures are KRA's own record of
supplier invoice 9 on the Go-Live test PIN, which KRA accepted as confirmed on
2026-11-18 exactly as built here. No network."""

import json
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from royce_etims.etims_sync import purchase


class Doc(frappe._dict):
	"""frappe._dict whose `items` is the child table, not dict.items."""

	@property
	def items(self):
		return self["items"]


KRA_RECORD = {
	"spplrTin": "P051909825V",
	"spplrBhfId": "02",
	"spplrInvcNo": 9,
	"rcptTyCd": "S",
	"pmtTyCd": "01",
	"salesDt": "20260923",
	"taxRtA": 0,
	"taxRtB": 16,
	"taxRtC": 0,
	"taxRtD": 0,
	"taxRtE": 0,
}


def _line(**values):
	row = frappe._dict(
		item=None,
		supplier_item_code="KE1NTXU1000005",
		supplier_item_class="5059690800",
		supplier_item_name="Product-B-5",
		package_unit="NT",
		package=1,
		qty_unit="XU",
		qty=1,
		price=9637.24,
		supply_amount=8308,  # KRA's list really says this for the line; it isn't qty x prc
		discount_rate=0,
		discount_amount=0,
		tax_type="B",
	)
	row.update(values)
	return row


def _purchase(items):
	return Doc(
		company="KRA Go-Live Test",
		supplier_tin="P051909825V",
		supplier_bhf_id="02",
		supplier_name="ROYCE TECHNOLOGIES LIMITED",
		supplier_invoice_no=9,
		payment_type="01",
		sales_date="2026-09-23",
		owner="Administrator",
		raw=json.dumps(KRA_RECORD),
		items=items,
	)


def _item(code, cls="1010151700"):
	return frappe._dict(
		item_name=code,
		royce_etims_item_classification_code=cls,
		royce_etims_packaging_unit_code="NT",
		royce_etims_quantity_unit_code="BA",
		royce_etims_id_mapping=[],
	)


class IntegrationTestPurchase(IntegrationTestCase):
	def _payload(self, doc, status=purchase.APPROVED):
		codes = {"SOAP": "KE2NTBA0000004", "MAIZE": "KE2NTBA0000005"}
		with (
			patch("frappe.get_cached_doc", side_effect=lambda dt, name: _item(name)),
			patch(
				"royce_etims.etims_sync.purchase.get_etims_id",
				side_effect=lambda item, company: codes.get(item.item_name),
			),
		):
			return purchase.build_payload(doc, 4, status)

	def test_confirmation_matches_what_kra_accepted(self):
		doc = _purchase(
			[
				_line(item="SOAP"),
				_line(
					item="MAIZE",
					supplier_item_code="KE1NTXU1000003",
					supplier_item_name="Product-C-3",
					price=9294.95,
					tax_type="C",
				),
			]
		)
		payload = self._payload(doc)
		soap, maize = payload["itemList"]
		self.assertEqual((soap["itemCd"], soap["spplrItemCd"]), ("KE2NTBA0000004", "KE1NTXU1000005"))
		self.assertEqual(soap["splyAmt"], 9637.24)  # qty x prc, not KRA's listed 8308
		self.assertEqual((soap["taxblAmt"], soap["taxAmt"]), (8307.97, 1329.27))
		self.assertEqual((maize["taxblAmt"], maize["taxAmt"]), (9294.95, 0))
		self.assertEqual(payload["totAmt"], 18932.19)
		self.assertEqual(payload["totTaxAmt"], 1329.27)
		self.assertEqual(payload["taxRtB"], 16)
		self.assertEqual(
			(payload["invcNo"], payload["pchsSttsCd"], payload["regTyCd"], payload["rcptTyCd"]),
			(4, "02", "A", "P"),
		)
		self.assertEqual(payload["pchsDt"], "20260923")
		self.assertIsNone(payload["cnclDt"])

	def test_every_line_needs_our_registered_item_even_to_reject(self):
		doc = _purchase([_line(item=None)])
		for status in (purchase.APPROVED, purchase.CANCELED):
			with self.assertRaises(frappe.ValidationError):
				self._payload(doc, status)

	def test_rejection_is_status_04_with_cancel_date(self):
		payload = self._payload(_purchase([_line(item="SOAP")]), purchase.CANCELED)
		self.assertEqual(payload["pchsSttsCd"], "04")
		self.assertTrue(payload["cnclDt"])

	def test_unit_price_ignores_kras_listed_supply_amount(self):
		self.assertEqual(purchase.unit_price(_line()), 9637.24)
		self.assertAlmostEqual(purchase.unit_price(_line(qty=2, price=100, discount_amount=20)), 90)
		self.assertEqual(purchase.unit_price(_line(qty=0)), 0)

	def test_purchase_key_and_dates(self):
		key = purchase.purchase_key("C", KRA_RECORD)
		self.assertEqual(
			key,
			{
				"company": "C",
				"supplier_tin": "P051909825V",
				"supplier_bhf_id": "02",
				"supplier_invoice_no": 9,
				"receipt_type": "S",
			},
		)
		self.assertEqual(str(purchase._kra_date("20260923")), "2026-09-23")
		self.assertEqual(str(purchase._kra_date("20260923135200")), "2026-09-23")
		self.assertIsNone(purchase._kra_date(None))

	def test_status_ready_once_every_line_has_an_item(self):
		doc = Doc(status="New", supplier="S", supplier_tin="P1", items=[_line(item="A"), _line()])
		with patch("royce_etims.etims_sync.purchase.match_item", return_value=None):
			purchase.refresh_status(doc)
			self.assertEqual(doc.status, "New")
			doc.items[1].item = "B"
			purchase.refresh_status(doc)
		self.assertEqual(doc.status, "Ready")

	def test_status_fills_remembered_items(self):
		doc = Doc(status="New", supplier=None, supplier_tin="P1", items=[_line()])
		with (
			patch("royce_etims.etims_sync.purchase.find_supplier", return_value="Supplier A"),
			patch("royce_etims.etims_sync.purchase.match_item", return_value="SOAP"),
		):
			purchase.refresh_status(doc)
		self.assertEqual((doc.supplier, doc.items[0].item, doc.status), ("Supplier A", "SOAP", "Ready"))

	def test_confirmed_purchase_keeps_its_status(self):
		doc = Doc(status="Confirmed", supplier="S", supplier_tin="P1", items=[_line()])
		purchase.refresh_status(doc)
		self.assertEqual(doc.status, "Confirmed")
