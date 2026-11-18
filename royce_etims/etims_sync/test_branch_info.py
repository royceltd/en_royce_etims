# Copyright (c) 2026, Royce Technologies LTD and Contributors
# See license.txt

"""Branch users and insurers, item composition and imported items - the
payload builders for Go-Live cases 7, 8, 11 and 13. No network."""

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from royce_etims.etims_sync import branch_info, composition, imports


class Doc(frappe._dict):
	"""frappe._dict whose `items` is the child table, not dict.items."""

	@property
	def items(self):
		return self["items"]


class IntegrationTestBranchInfo(IntegrationTestCase):
	def test_user_payload(self):
		doc = frappe._dict(
			user="cashier@lick.co.ke",
			full_name="Jane Cashier",
			contact="0700000000",
			address=None,
			active=1,
			owner="Administrator",
		)
		payload = branch_info.build_user_payload(doc)
		self.assertEqual(payload["userId"], "cashier")
		self.assertEqual(payload["userNm"], "Jane Cashier")
		self.assertEqual(payload["useYn"], "Y")
		self.assertGreaterEqual(len(payload["pwd"]), 12)
		# A fresh password every send: it's never stored or typed.
		self.assertNotEqual(payload["pwd"], branch_info.build_user_payload(doc)["pwd"])

	def test_insurance_payload(self):
		doc = frappe._dict(
			insurer_code="BRITAM", insurer_name="Britam", rate=10, active=0, owner="Administrator"
		)
		payload = branch_info.build_insurance_payload(doc)
		self.assertEqual((payload["isrccCd"], payload["isrcRt"], payload["useYn"]), ("BRITAM", 10.0, "N"))


class IntegrationTestComposition(IntegrationTestCase):
	def test_quantities_are_per_finished_unit_and_merged(self):
		bom = Doc(
			quantity=2,
			items=[
				frappe._dict(item_code="SOAP", stock_qty=4, qty=4),
				frappe._dict(item_code="WRAP", stock_qty=1, qty=1),
				frappe._dict(item_code="SOAP", stock_qty=2, qty=2),
			],
		)
		self.assertEqual(dict(composition.component_quantities(bom)), {"SOAP": 3.0, "WRAP": 0.5})

	def test_unregistered_items_are_all_listed(self):
		bom = Doc(item="PACK", quantity=1, items=[frappe._dict(item_code="SOAP", stock_qty=1)])
		with (
			patch("frappe.get_doc", return_value=frappe._dict(name="PACK")),
			patch("frappe.get_cached_doc", return_value=frappe._dict(name="SOAP")),
			patch("royce_etims.etims_sync.composition.get_etims_id", return_value=None),
			self.assertRaises(frappe.ValidationError) as raised,
		):
			composition.build_payloads(bom, "C")
		self.assertIn("PACK", str(raised.exception))
		self.assertIn("SOAP", str(raised.exception))


class IntegrationTestImports(IntegrationTestCase):
	def test_payload_echoes_kra_and_always_has_a_remark(self):
		doc = frappe._dict(
			task_code="20230209030935", declaration_date="01022023", item_seq=1, hs_code="63079000"
		)
		approved = imports.build_payload(doc, imports.APPROVED, "KE2NTKG0000007", "1010151700")
		self.assertEqual(
			(approved["taskCd"], approved["dclDe"], approved["itemSeq"], approved["imptItemSttsCd"]),
			("20230209030935", "01022023", 1, "3"),
		)
		self.assertEqual(approved["itemCd"], "KE2NTKG0000007")
		# A null remark draws KRA's "unknown error" (2026-11-18).
		self.assertTrue(approved["remark"])
		self.assertTrue(imports.build_payload(doc, imports.CANCELLED)["remark"])
