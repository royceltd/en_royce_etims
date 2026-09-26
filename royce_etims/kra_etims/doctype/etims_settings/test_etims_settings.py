# Copyright (c) 2026, Royce Technologies LTD and Contributors
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase

from royce_etims.setup.utils import TEST_COMPANY

EXTRA_TEST_RECORD_DEPENDENCIES = []
IGNORE_TEST_RECORD_DEPENDENCIES = []


class IntegrationTesteTIMSSettings(IntegrationTestCase):
	def tearDown(self):
		frappe.db.rollback()

	def test_autonames_to_company(self):
		doc = frappe.get_doc(
			{
				"doctype": "eTIMS Settings",
				"company": TEST_COMPANY,
				"tin": "P123456789H",
				"environment": "Sandbox",
			}
		).insert()
		self.assertEqual(doc.name, TEST_COMPANY)
		self.assertEqual(doc.status, "Draft")

	def test_rejects_malformed_tin(self):
		doc = frappe.get_doc(
			{
				"doctype": "eTIMS Settings",
				"company": TEST_COMPANY,
				"tin": "not-a-real-tin",
				"environment": "Sandbox",
			}
		)
		self.assertRaises(frappe.ValidationError, doc.insert)
