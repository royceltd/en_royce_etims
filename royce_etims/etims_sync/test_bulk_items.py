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

	def test_code_kra_lost_is_replaced_by_the_next_one(self):
		item = _item(royce_etims_quantity_unit_code="NO")
		item.append("royce_etims_id_mapping", {"setup_doctype": "eTIMS Settings", "setup_docname": "C", "etims_id": "KE2NTNO0000124"})
		sent = []
		with (
			patch("frappe.get_doc", side_effect=lambda dt, *a, **k: item if dt == "Item" else frappe._dict(bhf_id="00")),
			patch("royce_etims.etims_sync.item.get_settings", return_value=frappe._dict(default_branch="C-00")),
			patch("royce_etims.etims_sync.item._validate_ready_to_sync"),
			patch("royce_etims.etims_sync.bulk_items.fill_kra_fields", return_value={}),
			patch("royce_etims.etims_sync.item._known_item_codes", side_effect=lambda c, codes: codes + ["KE2NTNO0000124"]),
			patch("royce_etims.etims_sync.item.item_code_prefix", return_value="KE2NTNO"),
			patch("royce_etims.etims_sync.item.build_item_payload", side_effect=lambda i, cd: {"itemCd": cd}),
			patch("royce_etims.etims_sync.item.etims_request", side_effect=lambda *a, **k: sent.append(k["payload"]["itemCd"])),
			patch.object(type(item), "save"),
			patch("royce_etims.etims_sync.item._mark_synced"),
			patch("royce_etims.etims_sync.item.declare_opening_stock"),
			patch("royce_etims.etims_sync.item._move_unsent_stock") as moved,
		):
			item_sync.sync_item("BULK-T", "C", kra_codes=["KE2NTNO0000123", "KE2NTNO0000125"])
		self.assertEqual(sent, ["KE2NTNO0000126"])
		moved.assert_called_once_with("KE2NTNO0000124", "KE2NTNO0000126")
