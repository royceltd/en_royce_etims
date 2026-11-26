# Copyright (c) 2026, Royce Technologies LTD and Contributors
# See license.txt

"""Register All Items with KRA (etims_sync/bulk_items.py) and the opening stock
declared when an item is registered (item.declare_opening_stock). No network."""

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from royce_etims.etims_sync import bulk_items
from royce_etims.etims_sync import item as item_sync


def _item(**values):
	return frappe.get_doc({"doctype": "Item", "item_code": "BULK-T", "item_group": "All Item Groups", **values})


class IntegrationTestBulkItems(IntegrationTestCase):
	def _fill(self, item, settings):
		saved = {}
		with (
			patch("frappe.get_doc", return_value=item),
			patch("frappe.db.set_value", side_effect=lambda dt, n, v, **kw: saved.update(v)),
			patch("frappe.db.exists", return_value=True),
			patch("frappe.db.get_value", return_value=None),
		):
			bulk_items.fill_kra_fields("BULK-T", settings)
		return saved

	def test_empty_fields_take_the_settings_defaults(self):
		item = _item(is_stock_item=1)
		settings = frappe._dict(default_vat_band="B", default_item_classification="1010151700")
		saved = self._fill(item, settings)
		self.assertEqual(saved["royce_etims_taxation_type"], "B")
		self.assertEqual(saved["royce_etims_taxation_type_code"], "B")
		self.assertEqual(saved["royce_etims_item_classification"], "1010151700")
		self.assertEqual(saved["royce_etims_item_type"], "2")
		self.assertEqual(saved["royce_etims_packaging_unit"], "NT")

	def test_values_on_the_item_are_kept(self):
		item = _item(
			royce_etims_taxation_type="C",
			royce_etims_taxation_type_code="C",
			royce_etims_item_classification="9901200000",
		)
		saved = self._fill(item, frappe._dict(default_vat_band="B", default_item_classification="1010151700"))
		self.assertNotIn("royce_etims_taxation_type", saved)
		self.assertNotIn("royce_etims_item_classification", saved)

	def test_piece_maps_to_a_two_letter_unit(self):
		self.assertEqual(item_sync.UOM_QUANTITY_UNITS["Piece"], "NO")
		self.assertTrue(all(len(unit) == 2 for unit in item_sync.UOM_QUANTITY_UNITS.values()))

	def test_no_opening_stock_when_etims_is_off_or_already_sent(self):
		with patch("royce_etims.etims_sync.stock._active_settings", return_value=None):
			self.assertIsNone(item_sync.declare_opening_stock("BULK-T", "C"))
		with (
			patch("royce_etims.etims_sync.stock._active_settings", return_value=frappe._dict(default_branch="B-00")),
			patch("frappe.db.exists", return_value=True),
		):
			self.assertIsNone(item_sync.declare_opening_stock("BULK-T", "C"))

	def test_no_opening_stock_without_stock_on_hand(self):
		with (
			patch("royce_etims.etims_sync.stock._active_settings", return_value=frappe._dict(default_branch="B-00")),
			patch("frappe.db.exists", return_value=False),
			patch("royce_etims.etims_sync.item.opening_stock", return_value=(0, 0)),
		):
			self.assertIsNone(item_sync.declare_opening_stock("BULK-T", "C"))
