# Copyright (c) 2026, Royce Technologies LTD and Contributors
# See license.txt

"""Tests for etims_sync/reference_data.py's mapping of KRA's selectCodeList /
selectItemClass responses onto the reference doctypes. No network - the
fixtures below are trimmed copies of real sandbox responses (2026-10-26)."""

import frappe
from frappe.tests import IntegrationTestCase

from royce_etims.etims_sync.reference_data import CODE_CLASS_DOCTYPE, _apply_code_list, _apply_item_classes

CODE_LIST = [
	{
		"cdCls": "04",
		"cdClsNm": "Taxation Type",
		"dtlList": [
			{"cd": "B", "cdNm": "B-VAT 16% ", "useYn": "Y", "userDfnCd1": "16"},
			{"cd": "E", "cdNm": "E-VAT 8%", "useYn": "N", "userDfnCd1": "8"},
		],
	},
	{"cdCls": "05", "cdClsNm": "Country", "dtlList": [{"cd": "ZZ", "cdNm": "TEST COUNTRY ", "useYn": "Y"}]},
	{"cdCls": "07", "cdClsNm": "Payment Type", "dtlList": [{"cd": "01", "cdNm": "CASH", "useYn": "Y"}]},
]

ITEM_CLASSES = [
	{"itemClsCd": "9999999901", "itemClsNm": "Test Goats", "taxTyCd": "B", "useYn": "Y"},
	{"itemClsCd": "9999999902", "itemClsNm": "Test Unknown Band", "taxTyCd": "Q", "useYn": "Y"},
]


def _counts():
	return {
		dt: {"created": 0, "updated": 0} for dt in [*CODE_CLASS_DOCTYPE.values(), "eTIMS Item Classification"]
	}


class IntegrationTestReferenceData(IntegrationTestCase):
	def test_code_list_sets_rate_and_disabled_from_kra(self):
		_apply_code_list(CODE_LIST, _counts())

		b = frappe.get_doc("eTIMS Taxation Type", "B")
		self.assertEqual(b.rate, 16)
		self.assertEqual(b.description, "B-VAT 16%")
		self.assertFalse(b.disabled)
		# KRA marks E (VAT 8%) useYn "N" - must not stay selectable.
		self.assertTrue(frappe.db.get_value("eTIMS Taxation Type", "E", "disabled"))
		self.assertEqual(frappe.db.get_value("eTIMS Country of Origin", "ZZ", "description"), "TEST COUNTRY")

	def test_unmapped_code_classes_are_ignored(self):
		counts = _counts()
		_apply_code_list(CODE_LIST, counts)
		self.assertNotIn("Payment Type", str(counts))

	def test_resync_is_idempotent(self):
		_apply_code_list(CODE_LIST, _counts())
		counts = _counts()
		_apply_code_list(CODE_LIST, counts)
		self.assertEqual(counts["eTIMS Country of Origin"], {"created": 0, "updated": 0})

	def test_item_class_links_known_tax_band_only(self):
		_apply_code_list(CODE_LIST, _counts())
		_apply_item_classes(ITEM_CLASSES, _counts())

		self.assertEqual(frappe.db.get_value("eTIMS Item Classification", "9999999901", "taxation_type"), "B")
		# An unrecognised taxTyCd shouldn't fail the whole sync on a broken Link.
		self.assertIsNone(frappe.db.get_value("eTIMS Item Classification", "9999999902", "taxation_type"))
