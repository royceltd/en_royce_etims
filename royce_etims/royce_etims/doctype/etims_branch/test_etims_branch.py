# Copyright (c) 2026, Royce Technologies LTD and Contributors
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase

from royce_etims.setup.utils import TEST_COMPANY

EXTRA_TEST_RECORD_DEPENDENCIES = []
IGNORE_TEST_RECORD_DEPENDENCIES = []


class IntegrationTesteTIMSBranch(IntegrationTestCase):
	def tearDown(self):
		frappe.db.rollback()

	def test_autonames_company_dash_bhf_id(self):
		branch = frappe.get_doc({"doctype": "Branch", "branch": "Test Branch HQ"}).insert()

		etims_branch = frappe.get_doc(
			{
				"doctype": "eTIMS Branch",
				"company": TEST_COMPANY,
				"branch": branch.name,
				"bhf_id": "00",
				"dvc_srl_no": "TEST-DEVICE-001",
			}
		).insert()

		self.assertEqual(etims_branch.name, f"{TEST_COMPANY}-00")
		self.assertEqual(etims_branch.device_status, "Not Registered")
		self.assertEqual(etims_branch.last_invoice_no, 0)
