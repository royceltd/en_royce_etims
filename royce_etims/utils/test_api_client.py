# Copyright (c) 2026, Royce Technologies LTD and Contributors
# See license.txt

"""Pure-logic tests for api_client.py's response parsing - specifically the
2026-09-11 fix for a real, confirmed KRA quirk: a well-formed, successfully-
authenticated business response can arrive with a non-2xx HTTP status (seen:
400 for a "no data found" resultCd "001"). The parsed body's own resultCd,
when present, is the real success/failure signal; HTTP status is only the
fallback for a response that isn't a recognizable KRA envelope at all (e.g. a
raw gateway error). See docs/architecture.md.

Uses a lightweight stand-in for `requests.Response` rather than a real HTTP
call - `_parse_response()` only ever touches `response.ok`/`.status_code`/
`.text`, never anything requiring a real network response object.
"""

import frappe
from frappe.tests import IntegrationTestCase

from royce_etims.utils.api_client import _parse_response

EXTRA_TEST_RECORD_DEPENDENCIES = []
IGNORE_TEST_RECORD_DEPENDENCIES = []


class _FakeResponse:
	def __init__(self, ok, status_code, text=""):
		self.ok = ok
		self.status_code = status_code
		self.text = text


class IntegrationTestApiClientResponseParsing(IntegrationTestCase):
	def test_business_result_code_wins_over_non_2xx_http_status(self):
		"""The exact real-world case that motivated this fix: HTTP 400, but a
		well-formed, fully-authenticated body with resultCd "001" ("There is
		no search result") wrapped in responseBody. Still raises - "001" is
		still a non-"000" resultCd, and downgrading specific codes to a soft
		no-op is a per-endpoint business decision this generic transport
		function shouldn't make on its own (see docs/architecture.md's open
		item on this) - but the message must come from the real, readable
		resultMsg, not a raw dump of the HTTP status/body the old blanket
		`not response.ok` check produced."""
		data = {
			"responseHeader": {"responseCode": 200},
			"responseBody": {"resultCd": "001", "resultMsg": "There is no search result"},
		}
		response = _FakeResponse(ok=False, status_code=400, text="")

		with self.assertRaisesRegex(frappe.ValidationError, "There is no search result"):
			_parse_response(data, response, "selectCodeList")

	def test_business_result_code_failure_still_raises(self):
		"""A real business rejection (resultCd != "000"/absent-success) should
		still raise, regardless of HTTP status - resultCd is authoritative,
		not a free pass."""
		data = {"responseBody": {"resultCd": "999", "resultMsg": "Invalid TIN"}}
		response = _FakeResponse(ok=True, status_code=200)

		with self.assertRaises(frappe.ValidationError):
			_parse_response(data, response, "saveItem")

	def test_no_result_code_falls_back_to_http_status(self):
		"""A raw gateway error (e.g. the real 504 Timeout envelope confirmed
		2026-09-23: {"header": {...}, "body": {}}) has no resultCd anywhere -
		should fall back to the HTTP status and raise."""
		data = {"header": {"responseMessage": "Gateway Timeout", "responseCode": 504}, "body": {}}
		response = _FakeResponse(ok=False, status_code=504, text="")

		with self.assertRaises(frappe.ValidationError):
			_parse_response(data, response, "saveItem")

	def test_no_result_code_and_ok_status_passes_through(self):
		"""No resultCd anywhere, but HTTP status was fine - shouldn't raise,
		even if the shape is otherwise unrecognized (defensive, not every
		endpoint's success shape is confirmed yet)."""
		data = {"some": "shape we haven't seen yet"}
		response = _FakeResponse(ok=True, status_code=200)

		result = _parse_response(data, response, "someEndpoint")

		self.assertEqual(result, data)

	def test_flat_result_code_without_responsebody_wrapper(self):
		"""Defensive fallback: an endpoint whose success response doesn't use
		the responseBody wrapper at all should still be read correctly."""
		data = {"resultCd": "000", "data": {"foo": "bar"}}
		response = _FakeResponse(ok=True, status_code=200)

		result = _parse_response(data, response, "someEndpoint")

		self.assertEqual(result, data)
