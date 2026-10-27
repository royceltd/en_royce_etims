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

	def test_next_item_code_follows_kra_sequence_per_prefix(self):
		"""Real sandbox itemInfo for TIN P051909825V, 2026-10-26: mixed 7- and
		8-digit tails under KE2NTBA, plus other prefixes that must not count."""
		known = [
			"KE1NTXU1000005",
			"KE2NTBA00000001",
			"KE2NTBA00000002",
			"KE2NTBA00000003",
			"KE2NTBA0000004",
			"KE3BAXBAX00002",
		]
		self.assertEqual(next_item_code("KE2NTBA", known), "KE2NTBA0000005")

	def test_next_item_code_starts_at_one_for_a_new_prefix(self):
		self.assertEqual(next_item_code("KE3NTU", ["KE2NTBA0000004", None]), "KE3NTU0000001")

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
