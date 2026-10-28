# Copyright (c) 2026, Royce Technologies LTD and Contributors
# See license.txt

"""KRA lookups and the KRA Lookup report, against replies shaped like the
real ones from the Go-Live test PIN (2026-10-29). No network."""

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from royce_etims.kra_etims.report.kra_lookup.kra_lookup import execute
from royce_etims.utils.lookups import FULL_HISTORY, kra_lookup

INVOICE = {
	"invcNo": 6,
	"rcptTyCd": "S",
	"salesDt": "20261028",
	"custTin": "P051909825V",
	"custNm": "Royce Technologies Limited",
	"receipt": {"rcptSign": "YAH2B5EFO4FJPU5M", "curRcptNo": "6"},
	"itemList": [
		{"itemSeq": 1, "itemCd": "KE2NTBA0000004", "qty": 4, "taxTyCd": "B"},
		{"itemSeq": 2, "itemCd": "KE2NTBA0000005", "qty": 5, "taxTyCd": "A"},
	],
}


def _reply(list_key, rows):
	return {"responseBody": {"resultCd": "000", "data": {list_key: rows}}}


class IntegrationTestKraLookups(IntegrationTestCase):
	def _run(self, lookup, reply, **kw):
		settings = frappe._dict(tin="P600004665A", default_branch="B-00")
		with (
			patch("royce_etims.utils.lookups.get_settings", return_value=settings),
			patch("frappe.get_doc", return_value=frappe._dict(bhf_id="00")),
			patch("royce_etims.utils.lookups.etims_request", return_value=reply) as request,
		):
			return kra_lookup("KRA Go-Live Test", lookup, **kw), request.call_args.kwargs

	def test_list_comes_from_the_lookups_key_and_empty_is_allowed(self):
		rows, call = self._run("Customers", _reply("custList", [{"custTin": "P051909825V"}]))
		self.assertEqual(rows, [{"custTin": "P051909825V"}])
		self.assertEqual(call["payload"]["lastReqDt"], FULL_HISTORY)
		self.assertTrue(call["allow_empty"])

		rows, _call = self._run("Notices", {"responseBody": {"resultCd": "001", "data": None}})
		self.assertEqual(rows, [])

	def test_invoice_details_asks_by_invoice_number(self):
		_rows, call = self._run("Invoice Details", _reply("salesList", [INVOICE]), invoice_no=6)
		self.assertEqual(call["payload"]["invcNo"], "6")
		self.assertNotIn("lastReqDt", call["payload"])

	def test_report_gives_one_row_per_invoice_line(self):
		with (
			patch("royce_etims.kra_etims.report.kra_lookup.kra_lookup.kra_lookup", return_value=[INVOICE]),
			patch(
				"royce_etims.kra_etims.report.kra_lookup.kra_lookup._invoice_for",
				return_value=("Sales Invoice", "ACC-SINV-TEST"),
			),
		):
			columns, rows, _message = execute(
				{"company": "KRA Go-Live Test", "lookup": "Invoice Details", "invoice_no": 6}
			)
		self.assertEqual([r["itemCd"] for r in rows], ["KE2NTBA0000004", "KE2NTBA0000005"])
		self.assertEqual(rows[0]["rcptSign"], "YAH2B5EFO4FJPU5M")
		self.assertEqual(rows[0]["in_royce_erp"], "ACC-SINV-TEST")
		self.assertEqual(columns[1]["fieldname"], "in_royce_erp")
