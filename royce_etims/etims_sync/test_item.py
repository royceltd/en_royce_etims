# Copyright (c) 2026, Royce Technologies LTD and Contributors
# See license.txt

"""Pure-logic tests for etims_sync/item.py - specifically the 2026-09-11 fix
confirmed by a real KRA saveItem rejection ("orgnNatCd cannot be null"):
Country of Origin is mandatory, not optional as REQUIRED_ETIMS_ITEM_FIELDS
previously assumed. See docs/architecture.md.

Uses lightweight frappe._dict stand-ins rather than real Item documents -
_validate_ready_to_sync/build_item_payload only ever touch attributes and
.get(), and a real Item needs UOM/Item Group scaffolding that buys nothing
for what these specific checks need covered.
"""

import frappe
from frappe.tests import IntegrationTestCase

from royce_etims.etims_sync.item import (
	REQUIRED_ETIMS_ITEM_FIELDS,
	_validate_ready_to_sync,
	build_item_payload,
	fill_defaults,
	item_code_prefix,
	next_item_code,
)

EXTRA_TEST_RECORD_DEPENDENCIES = []
IGNORE_TEST_RECORD_DEPENDENCIES = []


def _complete_item(**overrides):
	item = frappe._dict(
		name="TEST-ITEM-001",
		item_code="TEST-ITEM-001",
		item_name="Test Item",
		royce_prevent_etims_submission=0,
		royce_etims_item_classification="1010151700",
		royce_etims_item_type="2",
		royce_etims_taxation_type="B",
		royce_etims_origin_nation="KE",
		royce_etims_packaging_unit="NT",
		royce_etims_quantity_unit="BA",
		royce_etims_quantity_unit_code="BA",
		royce_etims_id_mapping=[],
	)
	item.update(overrides)
	return item


class IntegrationTestItemSync(IntegrationTestCase):
	def test_origin_nation_is_required(self):
		"""CONFIRMED 2026-09-11 by a real saveItem rejection - previously
		missing from REQUIRED_ETIMS_ITEM_FIELDS entirely."""
		self.assertIn("royce_etims_origin_nation", REQUIRED_ETIMS_ITEM_FIELDS)

		item = _complete_item(royce_etims_origin_nation=None)
		with self.assertRaises(frappe.ValidationError):
			_validate_ready_to_sync(item, "Royce Technologies LTD")

	def test_complete_item_passes_validation(self):
		item = _complete_item(
			royce_etims_id_mapping=[
				frappe._dict(
					setup_doctype="eTIMS Settings",
					setup_docname="Royce Technologies LTD",
					etims_id="KE2NTBA00090001",
					disabled=0,
				)
			]
		)
		# Should not raise.
		_validate_ready_to_sync(item, "Royce Technologies LTD")

	def test_item_without_code_mapping_is_ready_to_sync(self):
		"""itemCd is generated at sync time now, so a missing mapping is no
		longer a reason to block."""
		_validate_ready_to_sync(_complete_item(royce_etims_id_mapping=[]), "Royce Technologies LTD")

	def test_packaging_and_quantity_unit_are_required(self):
		for field in ("royce_etims_packaging_unit", "royce_etims_quantity_unit"):
			self.assertIn(field, REQUIRED_ETIMS_ITEM_FIELDS)
			with self.assertRaises(frappe.ValidationError):
				_validate_ready_to_sync(_complete_item(**{field: None}), "Royce Technologies LTD")

	def test_item_code_prefix_order(self):
		item = frappe._dict(
			royce_etims_origin_nation_code="KE",
			royce_etims_item_type_code="2",
			royce_etims_packaging_unit_code="NT",
			royce_etims_quantity_unit_code="BA",
		)
		self.assertEqual(item_code_prefix(item), "KE2NTBA")

	def test_next_item_code_continues_the_pins_sequence_across_prefixes(self):
		"""One sequence per PIN (KRA wanted ********7 for a new KE2NTKG prefix
		after KE2NTBA...6), read from either tail width, with a unit ending in
		a digit (M2) not mistaken for part of the sequence."""
		known = ["KE2NTBA00000003", "KE2NTBA0000006", "KE2NTKG0000005", "KE2NTM20000002", None]
		self.assertEqual(next_item_code("KE2NTM2", known), "KE2NTM20000007")

	def test_next_item_code_starts_at_one_for_a_new_pin(self):
		self.assertEqual(next_item_code("KE2NTNO", []), "KE2NTNO0000001")

	def test_quantity_unit_must_be_two_letters(self):
		for unit in ("U", "LTR"):
			with self.assertRaises(frappe.ValidationError):
				_validate_ready_to_sync(
					_complete_item(royce_etims_quantity_unit_code=unit), "Royce Technologies LTD"
				)

	def test_prevent_etims_submission_raises_regardless_of_other_fields(self):
		item = _complete_item(royce_prevent_etims_submission=1)
		with self.assertRaises(frappe.ValidationError):
			_validate_ready_to_sync(item, "Royce Technologies LTD")

	def test_build_item_payload_maps_confirmed_fields(self):
		item = frappe._dict(
			item_name="Test Item",
			royce_etims_item_classification_code="1010151700",
			royce_etims_item_type_code="2",
			royce_etims_origin_nation_code="KE",
			royce_etims_packaging_unit_code="NT",
			royce_etims_quantity_unit_code="BA",
			royce_etims_taxation_type_code="B",
			standard_rate=1000,
			disabled=0,
		)

		payload = build_item_payload(item, "KE2NTBA00090001")

		self.assertEqual(payload["itemCd"], "KE2NTBA00090001")
		self.assertEqual(payload["orgnNatCd"], "KE")
		self.assertEqual(payload["itemClsCd"], "1010151700")
		self.assertEqual(payload["pkgUnitCd"], "NT")
		self.assertEqual(payload["qtyUnitCd"], "BA")
		self.assertEqual(payload["taxTyCd"], "B")
		self.assertEqual(payload["useYn"], "Y")

	def test_build_item_payload_disabled_item_sends_useyn_n(self):
		item = frappe._dict(
			item_name="Test Item",
			royce_etims_item_classification_code="1010151700",
			royce_etims_item_type_code="2",
			royce_etims_origin_nation_code="KE",
			royce_etims_packaging_unit_code="NT",
			royce_etims_quantity_unit_code="BA",
			royce_etims_taxation_type_code="B",
			standard_rate=1000,
			disabled=1,
		)

		payload = build_item_payload(item, "KE2NTBA00090001")

		self.assertEqual(payload["useYn"], "N")

	def test_band_code_follows_template_band(self):
		"""Live 2026-10-27: an item whose band came from its tax template was
		sent with taxTyCd null - the hook set the band after fetch_from ran."""
		from unittest.mock import patch

		from royce_etims.etims_sync.item import fill_taxation_type

		item = frappe._dict(
			royce_etims_taxation_type=None,
			royce_etims_taxation_type_code=None,
			taxes=[frappe._dict(item_tax_template="KE Standard 16% - X")],
		)
		with patch(
			"frappe.db.get_value",
			side_effect=lambda doctype, name, field: "B" if doctype == "Item Tax Template" else 16,
		):
			fill_taxation_type(item)
		self.assertEqual(
			(
				item.royce_etims_taxation_type,
				item.royce_etims_taxation_type_code,
				item.royce_etims_taxation_type_rate,
			),
			("B", "B", 16),
		)


class IntegrationTestItemDefaults(IntegrationTestCase):
	def tearDown(self):
		frappe.db.rollback()

	def setUp(self):
		for doctype, code in (
			("eTIMS Country of Origin", "KE"),
			("eTIMS Item Type", "2"),
			("eTIMS Item Type", "3"),
			("eTIMS Packaging Unit", "NT"),
			("eTIMS Quantity Unit", "NO"),
			("eTIMS Item Classification", "1010151700"),
		):
			if not frappe.db.exists(doctype, code):
				frappe.get_doc({"doctype": doctype, "code": code, "description": code}).insert(
					ignore_permissions=True
				)
		frappe.db.set_value("UOM", "Nos", "royce_etims_quantity_unit", "NO")

	def test_new_stock_item_gets_kra_defaults_and_codes(self):
		doc = frappe._dict(is_stock_item=1, stock_uom="Nos", item_group=None)
		fill_defaults(doc)
		self.assertEqual(
			(
				doc.royce_etims_origin_nation_code,
				doc.royce_etims_item_type_code,
				doc.royce_etims_packaging_unit_code,
				doc.royce_etims_quantity_unit_code,
			),
			("KE", "2", "NT", "NO"),
		)

	def test_non_stock_item_is_a_service(self):
		doc = frappe._dict(is_stock_item=0, stock_uom="Nos", item_group=None)
		fill_defaults(doc)
		self.assertEqual(doc.royce_etims_item_type, "3")

	def test_values_already_set_are_kept(self):
		doc = frappe._dict(
			is_stock_item=1,
			stock_uom="Nos",
			item_group=None,
			royce_etims_quantity_unit="BA",
			royce_etims_origin_nation="UG",
		)
		fill_defaults(doc)
		self.assertEqual((doc.royce_etims_quantity_unit, doc.royce_etims_origin_nation), ("BA", "UG"))

	def test_category_comes_from_the_nearest_group_that_has_one(self):
		parent = frappe.get_doc(
			{
				"doctype": "Item Group",
				"item_group_name": "_Test KRA Parent Group",
				"parent_item_group": "All Item Groups",
				"is_group": 1,
				"royce_etims_item_classification": "1010151700",
			}
		).insert(ignore_permissions=True)
		child = frappe.get_doc(
			{
				"doctype": "Item Group",
				"item_group_name": "_Test KRA Child Group",
				"parent_item_group": parent.name,
			}
		).insert(ignore_permissions=True)
		doc = frappe._dict(is_stock_item=1, stock_uom="Nos", item_group=child.name)
		fill_defaults(doc)
		self.assertEqual(doc.royce_etims_item_classification_code, "1010151700")
