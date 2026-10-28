# Copyright (c) 2026, Royce Technologies LTD and Contributors
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase

from royce_etims.kra_etims.report.etims_compliance_status.etims_compliance_status import (
	execute as compliance_execute,
)
from royce_etims.kra_etims.report.etims_vat_summary.etims_vat_summary import summarize_by_band
from royce_etims.setup.utils import TEST_COMPANY


class IntegrationTestVatSummary(IntegrationTestCase):
	def test_credit_notes_are_subtracted_per_band(self):
		payloads = [
			# 1000 at 16%, VAT-inclusive (KRA's own split, 2026-09-23).
			{
				"rcptTyCd": "S",
				"salesDt": "20261026",
				"taxblAmtB": 862.07,
				"taxAmtB": 137.93,
				"taxblAmtA": 500,
			},
			{"rcptTyCd": "S", "salesDt": "20261026", "taxblAmtB": 862.07, "taxAmtB": 137.93},
			{"rcptTyCd": "R", "salesDt": "20261026", "taxblAmtB": 862.07, "taxAmtB": 137.93},
		]
		rows = {r["tax_band"]: r for r in summarize_by_band(payloads)}

		self.assertAlmostEqual(rows["B"]["invoice_taxable"], 1724.14, places=2)
		self.assertAlmostEqual(rows["B"]["credit_vat"], 137.93, places=2)
		self.assertAlmostEqual(rows["B"]["net_taxable"], 862.07, places=2)
		self.assertAlmostEqual(rows["B"]["net_vat"], 137.93, places=2)
		self.assertEqual(rows["A"]["net_taxable"], 500)
		self.assertEqual(rows["E"]["net_vat"], 0)


class IntegrationTestComplianceStatus(IntegrationTestCase):
	def test_runs_and_reports_summary(self):
		columns, data, _message, _chart, summary = compliance_execute({"company": TEST_COMPANY})
		self.assertTrue(columns)
		self.assertIsInstance(data, list)
		self.assertEqual(summary[0]["label"], "Needs Attention")
		self.assertEqual(summary[0]["value"], len(data))

	def test_company_is_required(self):
		with self.assertRaises(frappe.ValidationError):
			compliance_execute({})

	def tearDown(self):
		frappe.db.rollback()

	def _item(self, code, **fields):
		return frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": code,
				"item_group": "All Item Groups",
				"stock_uom": "Nos",
				"is_sales_item": 1,
				**fields,
			}
		).insert(ignore_permissions=True)

	def test_sellable_items_without_a_kra_code_are_listed(self):
		if not frappe.db.exists("eTIMS Settings", TEST_COMPANY):
			frappe.get_doc(
				{
					"doctype": "eTIMS Settings",
					"company": TEST_COMPANY,
					"tin": "A123456789Z",
					"environment": "Sandbox",
				}
			).insert(ignore_permissions=True, ignore_links=True)
		self._item("_Test KRA Unregistered")
		self._item("_Test KRA Not Sent", royce_prevent_etims_submission=1)
		self._item("_Test KRA Not Sold", is_sales_item=0)
		self._item(
			"_Test KRA Registered",
			royce_etims_id_mapping=[
				{
					"setup_doctype": "eTIMS Settings",
					"setup_docname": TEST_COMPANY,
					"etims_id": "KE2NTNO0000099",
				}
			],
		)
		frappe.db.set_value(
			"Item",
			"_Test KRA Unregistered",
			{
				"royce_etims_sync_status": "Failed",
				"royce_etims_sync_error": "KRA only accepts 2-letter units",
			},
		)

		_columns, data, *_rest = compliance_execute({"company": TEST_COMPANY})
		items = {r["document"]: r for r in data if r["document_type"] == "Item"}
		self.assertEqual(items["_Test KRA Unregistered"]["error"], "KRA only accepts 2-letter units")
		for code in ("_Test KRA Not Sent", "_Test KRA Not Sold", "_Test KRA Registered"):
			self.assertNotIn(code, items)
