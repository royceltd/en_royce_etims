# Copyright (c) 2026, Royce Technologies LTD and Contributors
# See license.txt

"""Tests for stock movement mapping (etims_sync/stock.py) and the shared
KRA number sequence (utils/sequence.py). No network."""

import frappe
from frappe.tests import IntegrationTestCase

from royce_etims.etims_sync.stock import (
	build_stock_io_payload,
	net_item_movements,
	sar_type_for,
	vat_inclusive_amounts,
)
from royce_etims.setup.utils import TEST_COMPANY
from royce_etims.utils.sequence import kra_expected_number, send_in_sequence

TEST_BRANCH = f"{TEST_COMPANY}-T9"


class IntegrationTestStockMapping(IntegrationTestCase):
	def test_sar_types(self):
		self.assertEqual(sar_type_for("Purchase Receipt", "In"), "02")
		self.assertEqual(sar_type_for("Purchase Receipt", "Out", is_return=True), "12")
		self.assertEqual(sar_type_for("Delivery Note", "Out"), "11")
		self.assertEqual(sar_type_for("Sales Invoice", "In", is_return=True), "03")
		self.assertEqual(sar_type_for("Stock Entry", "In", purpose="Manufacture"), "05")
		self.assertEqual(sar_type_for("Stock Entry", "Out", purpose="Manufacture"), "14")
		self.assertEqual(sar_type_for("Stock Entry", "In", purpose="Material Receipt"), "06")
		self.assertEqual(sar_type_for("Stock Entry", "Out", purpose="Material Issue"), "16")
		self.assertEqual(sar_type_for("Stock Reconciliation", "Out"), "16")

	def test_net_movements_drop_internal_transfers(self):
		sles = [
			frappe._dict(item_code="A", actual_qty=-5, stock_value_difference=-500),
			frappe._dict(item_code="A", actual_qty=5, stock_value_difference=500),
			frappe._dict(item_code="B", actual_qty=3, stock_value_difference=300),
			frappe._dict(item_code="B", actual_qty=2, stock_value_difference=200),
		]
		self.assertEqual(net_item_movements(sles), {"B": {"qty": 5.0, "value": 500.0}})

	def test_vat_inclusive_amounts_match_kra(self):
		# KRA's own expected figure for 10 x 1000 at 16% (sandbox, 2026-10-26).
		self.assertEqual(vat_inclusive_amounts(1000, 10, 16), (10000, 8620.69, 1379.31))
		self.assertEqual(vat_inclusive_amounts(500, 2, 0), (1000, 1000, 0))

	def test_payload_totals_and_dates(self):
		mv = frappe._dict(
			sar_ty_cd="06",
			posting_date="2026-10-26",
			voucher_type="Stock Entry",
			voucher_no="MAT-STE-0001",
			owner="Administrator",
			items=[
				frappe._dict(
					item_cd="KE2NTBA0000005",
					item_cls_cd="1010151700",
					item_name="Widget",
					pkg_unit_cd="NT",
					qty_unit_cd="BA",
					qty=10,
					rate=1000,
					taxable_amount=10000,
					tax_ty_cd="B",
					tax_amount=1600,
					total_amount=11600,
				)
			],
		)
		payload = build_stock_io_payload(mv, 7)
		self.assertEqual(payload["sarNo"], 7)
		self.assertEqual(payload["orgSarNo"], 0)
		self.assertEqual(payload["ocrnDt"], "20261026")
		self.assertEqual(payload["totItemCnt"], 1)
		self.assertEqual(payload["totAmt"], 11600)
		self.assertEqual(payload["itemList"][0]["splyAmt"], 11600)
		self.assertEqual(payload["itemList"][0]["itemSeq"], 1)


class IntegrationTestSequence(IntegrationTestCase):
	def setUp(self):
		if not frappe.db.exists("eTIMS Branch", TEST_BRANCH):
			frappe.get_doc(
				{
					"doctype": "eTIMS Branch",
					"company": TEST_COMPANY,
					"branch": "Test",
					"bhf_id": "T9",
					"last_sar_no": 5,
				}
			).insert(ignore_permissions=True, ignore_links=True)
		frappe.db.set_value("eTIMS Branch", TEST_BRANCH, "last_sar_no", 5)

	def test_expected_number_from_real_kra_messages(self):
		self.assertEqual(kra_expected_number("Invalid sarNo: Expected: 6 but found: 1"), 6)
		self.assertEqual(kra_expected_number("Invalid invcNo sequence, expected: 1 but found: 2"), 1)
		self.assertEqual(kra_expected_number("Invc No: 2 is invalid, use the expected value: 1"), 1)
		# Amount errors use the same wording - must not be read as a sequence.
		self.assertIsNone(
			kra_expected_number("Invalid taxblAmt on item: 1. Expected: 8620.69, But Found: 10000.00")
		)
		self.assertIsNone(kra_expected_number("rsdQty mismatch. Expected: 0.0 but found: 10"))
		# itemCd's message names only the last digit - not a usable number.
		self.assertIsNone(kra_expected_number("Expected sequence ending with: ********6"))

	def test_success_advances_counter(self):
		number, result = send_in_sequence(TEST_BRANCH, "last_sar_no", lambda n: f"ok {n}")
		self.assertEqual((number, result), (6, "ok 6"))
		self.assertEqual(frappe.db.get_value("eTIMS Branch", TEST_BRANCH, "last_sar_no"), 6)

	def test_failure_does_not_consume_a_number(self):
		def send(n):
			raise frappe.ValidationError("eTIMS rejected: Validation failed")

		with self.assertRaises(frappe.ValidationError):
			send_in_sequence(TEST_BRANCH, "last_sar_no", send)
		self.assertEqual(frappe.db.get_value("eTIMS Branch", TEST_BRANCH, "last_sar_no"), 5)

	def test_resyncs_to_kra_expected_number_and_resends_once(self):
		sent = []

		def send(n):
			sent.append(n)
			if n != 9:
				raise frappe.ValidationError("Invalid sarNo: Expected: 9 but found: 6")
			return "ok"

		number, _result = send_in_sequence(TEST_BRANCH, "last_sar_no", send)
		self.assertEqual((number, sent), (9, [6, 9]))
		self.assertEqual(frappe.db.get_value("eTIMS Branch", TEST_BRANCH, "last_sar_no"), 9)
