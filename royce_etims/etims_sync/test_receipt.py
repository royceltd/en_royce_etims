# Copyright (c) 2026, Royce Technologies LTD and Contributors
# See license.txt

"""Pure-logic tests for etims_sync/receipt.py's payload building and response
parsing - the two things fixed 2026-09-10 after cross-checking
eTIMS-OSCU-Integrator-Automated-Testing-Sandbox.json (see docs/architecture.md):
the nested `receipt` object was entirely missing from the payload, and
`_apply_success` was unwrapping the wrong envelope level.

Uses lightweight stand-ins (frappe._dict / plain objects) rather than real
Sales Invoice submissions - build_receipt_payload/_build_receipt_block/
_apply_success only ever touch attributes and .get(), and a full submitted
Sales Invoice (customer, stock, tax templates, ...) is expensive scaffolding
that buys nothing for what these specific fixes need covered.
"""

import frappe
from frappe.tests import IntegrationTestCase

from royce_etims.etims_sync.receipt import _apply_success, _build_receipt_block, build_receipt_payload
from royce_etims.setup.utils import TEST_COMPANY

EXTRA_TEST_RECORD_DEPENDENCIES = []
IGNORE_TEST_RECORD_DEPENDENCIES = []


class _FakeDoc(frappe._dict):
	"""frappe._dict already gives attribute + .get() access like a real
	Document; db_set just records what was written instead of hitting the DB."""

	def db_set(self, field, value, notify=False):
		self[field] = value


class _FakeInvoiceDoc:
	"""Plain object, NOT a frappe._dict - build_receipt_payload() needs
	doc.items (the line-items child table), and frappe._dict is a dict
	subclass where `.items` resolves to the built-in dict.items() bound
	method instead of our own attribute (confirmed live 2026-09-23: this
	exact collision silently broke a hand-rolled test call with
	"'builtin_function_or_method' object is not iterable" until switched to
	a plain object). _FakeDoc above is fine for _apply_success/
	_build_receipt_block, which never touch .items - only use this stand-in
	for anything going through build_receipt_payload."""

	def __init__(self, **kw):
		self.__dict__.update(kw)

	def get(self, key, default=None):
		return getattr(self, key, default)


class IntegrationTestReceiptSync(IntegrationTestCase):
	def tearDown(self):
		frappe.db.rollback()

	def test_receipt_block_falls_back_to_company_name_and_settings_messages(self):
		"""No receipt_trade_name/receipt_address configured - should fall back
		to the Company's own name, and send an empty (not guessed) address.

		Uses ERPNext's "_Test Company" fixture rather than TEST_COMPANY here
		on purpose: TEST_COMPANY is only created by setup/utils.before_tests'
		`if not frappe.get_list("Company")` guard, which no-ops on any bench
		that already has *a* company (e.g. this shared dev site, which has
		"Royce Technologies LTD") - so TEST_COMPANY isn't reliably present.
		The DB-fallback being tested here just needs *some* real Company row.
		"""
		settings = frappe.get_doc(
			{
				"doctype": "eTIMS Settings",
				"receipt_top_message": "Welcome",
				"receipt_bottom_message": "Thank you, shop with us again",
			}
		)
		company = "_Test Company"
		expected_trade_name = frappe.db.get_value("Company", company, "company_name")
		doc = frappe._dict(
			company=company,
			tax_id="A123456789Z",
			contact_mobile="0712345678",
			company_address=None,
		)

		block = _build_receipt_block(doc, settings)

		self.assertEqual(block["trdeNm"], expected_trade_name)
		self.assertEqual(block["adrs"], "")
		self.assertEqual(block["custTin"], "A123456789Z")
		self.assertEqual(block["custMblNo"], "0712345678")
		self.assertEqual(block["topMsg"], "Welcome")
		self.assertEqual(block["btmMsg"], "Thank you, shop with us again")
		self.assertEqual(block["rptNo"], 1)
		self.assertEqual(block["prchrAcptcYn"], "N")
		# rcptPbctDt: KRA-format timestamp (YYYYMMDDHHMMSS), 14 digits.
		self.assertEqual(len(block["rcptPbctDt"]), 14)
		self.assertTrue(block["rcptPbctDt"].isdigit())

	def test_receipt_block_prefers_explicit_settings_over_fallbacks(self):
		"""An admin-configured Trade Name/Fallback Address on eTIMS Settings
		wins over the Company-name fallback (trdeNm) - address fallback only
		applies when the document itself has no Company Address set."""
		settings = frappe.get_doc(
			{
				"doctype": "eTIMS Settings",
				"receipt_trade_name": "Royce Shop",
				"receipt_address": "P.O. Box 123, Nairobi",
			}
		)
		doc = frappe._dict(company=TEST_COMPANY, tax_id=None, contact_mobile=None, company_address=None)

		block = _build_receipt_block(doc, settings)

		self.assertEqual(block["trdeNm"], "Royce Shop")
		self.assertEqual(block["adrs"], "P.O. Box 123, Nairobi")
		self.assertIsNone(block["custTin"])
		self.assertIsNone(block["custMblNo"])

	def test_apply_success_unwraps_responsebody_envelope(self):
		"""The real, confirmed shape (matching /initialize) wraps the business
		payload in responseBody.data - not a flat top-level "data" key, which
		is what this used to (wrongly) assume."""
		data = {
			"responseHeader": {"resultCd": "000"},
			"responseBody": {
				"resultCd": "000",
				"data": {
					"rcptSign": "SIGN123",
					"curRcptNo": 1,
					"totRcptNo": 1,
					"intrlData": "INTERNAL",
					"sdcDateTime": "20260910120000",
				},
			},
		}
		doc = _FakeDoc(name="SINV-0001")
		settings = frappe._dict(environment="Sandbox", tin="A123456789Z")
		branch = frappe._dict(bhf_id="02")

		_apply_success(doc, 1, data, settings, branch)

		self.assertEqual(doc.royce_etims_status, "Sent")
		self.assertEqual(doc.royce_etims_receipt_signature, "SIGN123")
		self.assertEqual(doc.royce_etims_current_receipt_number, 1)
		self.assertEqual(doc.royce_etims_total_receipt_number, 1)
		self.assertEqual(doc.royce_etims_internal_data, "INTERNAL")
		self.assertEqual(doc.royce_etims_control_unit_datetime, "20260910120000")
		self.assertIn("SIGN123", doc.royce_etims_qr_verification_url)

	def test_build_receipt_payload_uses_tax_inclusive_amounts(self):
		"""CONFIRMED 2026-09-23 by a real sendSalesTransaction rejection against
		KRA's sandbox: a line sent with prc/totAmt 1000, taxblAmt 1000 (tax
		added on top, taxAmt 160) was rejected - "Invalid taxblAmt on item: 1.
		Expected: 862.07, But Found: 1000.00". 862.07 x 1.16 = 1000.00: KRA
		expects tax-INCLUSIVE amounts, with taxblAmt/taxAmt backed OUT of the
		total - the opposite of what this used to (wrongly) compute."""
		# The eTIMS ID Mapping row below Link-validates against a real eTIMS
		# Settings doc (TEST_COMPANY has none by default - see the
		# before_tests note above). Create one directly rather than
		# ignore_links=True on the Item insert - that would also suppress
		# royce_etims_taxation_type's fetch_from resolution, silently defaulting
		# the tax code to "A" and defeating the point of this test (caught
		# live while writing it: taxTyCd came back "A", not "B").
		if not frappe.db.exists("eTIMS Settings", TEST_COMPANY):
			frappe.get_doc(
				{"doctype": "eTIMS Settings", "company": TEST_COMPANY, "tin": "A123456789Z", "environment": "Sandbox"}
			).insert(ignore_permissions=True, ignore_links=True)

		item = frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": "_Test eTIMS Receipt Payload Item",
				"item_name": "_Test eTIMS Receipt Payload Item",
				"item_group": "All Item Groups",
				"stock_uom": "Nos",
				"is_stock_item": 0,
				"royce_etims_taxation_type": "B",  # 16% - seeded rate, confirmed real
				"royce_etims_id_mapping": [
					{"setup_doctype": "eTIMS Settings", "setup_docname": TEST_COMPANY, "etims_id": "TESTCD00000001"}
				],
			}
		)
		item.insert(ignore_permissions=True)

		item_row = frappe._dict(
			item_code=item.item_code,
			qty=1,
			base_rate=1000,
			base_amount=1000,
			base_net_amount=1000,
			discount_percentage=0,
			discount_amount=0,
		)
		doc = _FakeInvoiceDoc(
			name="SINV-TAX-TEST",
			company=TEST_COMPANY,
			tax_id="A123456789Z",
			customer_name="Test Customer",
			posting_date="2026-09-23",
			owner="Administrator",
			modified_by="Administrator",
			grand_total=1000,
			contact_mobile=None,
			company_address=None,
			items=[item_row],
		)
		settings = frappe.get_doc({"doctype": "eTIMS Settings"})

		payload = build_receipt_payload(doc, 1, settings)

		line = payload["itemList"][0]
		self.assertAlmostEqual(line["taxblAmt"], 862.07, places=2)
		self.assertAlmostEqual(line["taxAmt"], 137.93, places=2)
		self.assertEqual(line["totAmt"], 1000)  # the charged amount itself is unchanged
		self.assertAlmostEqual(payload["taxblAmtB"], 862.07, places=2)
		self.assertAlmostEqual(payload["taxAmtB"], 137.93, places=2)

	def test_apply_success_falls_back_to_flat_envelope(self):
		"""Defensive fallback for an endpoint/response that doesn't use the
		responseBody wrapper at all - shouldn't crash, and should still
		extract data if it's sitting at the top level."""
		data = {"data": {"rcptSign": "SIGN456"}}
		doc = _FakeDoc(name="SINV-0002")
		settings = frappe._dict(environment="Sandbox", tin="A123456789Z")
		branch = frappe._dict(bhf_id="02")

		_apply_success(doc, 2, data, settings, branch)

		self.assertEqual(doc.royce_etims_receipt_signature, "SIGN456")
