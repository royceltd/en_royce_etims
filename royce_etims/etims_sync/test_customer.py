# Copyright (c) 2026, Royce Technologies LTD and Contributors
# See license.txt

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from royce_etims.etims_sync.customer import build_customer_payload, on_update


def _customer(**overrides):
	doc = frappe._dict(
		name="Automated Test Customer Kenya Wholesale Distributors",
		royce_etims_customer_no="RC-00000001",
		tax_id="P600004473A",
		customer_name="Test Customer",
		disabled=0,
		mobile_no=None,
		email_id=None,
		owner="Administrator",
		modified_by="Administrator",
		royce_etims_customer_status="Not Synced",
	)
	doc.update(overrides)
	doc.has_value_changed = lambda field: True
	return doc


class IntegrationTestCustomerSync(IntegrationTestCase):
	def test_payload(self):
		payload = build_customer_payload(_customer(disabled=1))
		self.assertEqual(payload["custNo"], "RC-00000001")
		self.assertLessEqual(len(payload["custNo"]), 15)
		self.assertEqual(payload["custTin"], "P600004473A")
		self.assertEqual(payload["useYn"], "N")

	def _queued(self, doc, companies=("Royce Technologies Ltd",)):
		with (
			patch("royce_etims.etims_sync.customer._active_companies", return_value=list(companies)),
			patch("frappe.enqueue") as enqueue,
		):
			on_update(doc)
		return enqueue.called

	def test_queues_customer_with_valid_pin(self):
		self.assertTrue(self._queued(_customer()))

	def test_skips_without_valid_pin_or_active_company(self):
		self.assertFalse(self._queued(_customer(tax_id=None)))
		self.assertFalse(self._queued(_customer(tax_id="12345")))
		self.assertFalse(self._queued(_customer(), companies=()))

	def test_skips_unchanged_synced_customer(self):
		doc = _customer(royce_etims_customer_status="Synced")
		doc.has_value_changed = lambda field: False
		self.assertFalse(self._queued(doc))
