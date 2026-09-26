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

from royce_etims.etims_sync.item import REQUIRED_ETIMS_ITEM_FIELDS, _validate_ready_to_sync, build_item_payload

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

	def test_missing_item_code_mapping_raises(self):
		"""A complete eTIMS profile still isn't enough without an assigned
		itemCd for this company - a separate, deliberate manual step."""
		item = _complete_item(royce_etims_id_mapping=[])
		with self.assertRaises(frappe.ValidationError):
			_validate_ready_to_sync(item, "Royce Technologies LTD")

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
