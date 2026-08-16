# Copyright (c) 2026, Royce Technologies LTD and contributors
# For license information, please see license.txt

"""Generic authenticated client for the KRA eTIMS OSCU API.

Every business endpoint (saveItem, saveTrnsSalesOsdc, selectInitOsdcInfo, ...)
should go through `request()` here rather than calling `requests` directly, so
that the standard headers and eTIMS Log entries stay in one place.

No OAuth/bearer-token layer: confirmed against two independent sources (KRA's
own OSCU Specification Document v2.0, and navariltd/kenya-compliance - tested
against the real KRA sandbox in 2024) that the actual API authenticates with
tin/bhfId/cmcKey headers only. See docs/architecture.md for the full
correction history - this replaced an earlier Apigee-OAuth design modeled on
a Postman collection that turned out to target a different host entirely.
"""

import json

import frappe
import requests
from frappe import _
from frappe.model.document import Document

from royce_etims.utils.config import PRODUCTION_BASE_URL, SANDBOX_BASE_URL

REQUEST_TIMEOUT_SECONDS = 60


def get_settings(company):
	"""eTIMS Settings is named after its Company (autoname field:company)."""
	return frappe.get_doc("eTIMS Settings", company)


def get_branch(branch):
	if isinstance(branch, Document):
		return branch
	return frappe.get_doc("eTIMS Branch", branch)


def get_base_url(settings):
	if settings.environment == "Sandbox":
		return SANDBOX_BASE_URL

	if settings.environment == "Production":
		if not PRODUCTION_BASE_URL:
			frappe.throw(
				_("Production eTIMS endpoint is not configured yet. Confirm the live URL with KRA before switching {0} to Production.").format(
					settings.company
				)
			)
		return PRODUCTION_BASE_URL

	frappe.throw(_("Unknown eTIMS environment: {0}").format(settings.environment))


def _do_request(method, url, **kwargs):
	"""requests.request(), with network-level failures turned into a clean
	frappe.throw instead of a raw traceback surfaced to the desk UI."""
	try:
		return requests.request(method, url, timeout=REQUEST_TIMEOUT_SECONDS, **kwargs)
	except requests.exceptions.Timeout:
		frappe.throw(_("eTIMS request to {0} timed out.").format(url))
	except requests.exceptions.RequestException as e:
		frappe.throw(_("Could not reach eTIMS at {0}: {1}").format(url, str(e)))


def request(
	company,
	endpoint,
	payload=None,
	method="POST",
	branch=None,
	reference_doctype=None,
	reference_name=None,
):
	"""Call an eTIMS business endpoint with standard headers, and log it.

	`branch` should be passed (an eTIMS Branch doc or name) for every endpoint
	that needs the tin/bhfId/cmcKey headers - i.e. everything except
	`selectInitOsdcInfo` itself, where the device isn't registered yet and
	tin/bhfId travel in the body instead, with no cmcKey to send.
	"""
	settings = get_settings(company)
	base_url = get_base_url(settings)

	headers = {"Content-Type": "application/json"}

	branch_doc = None
	if branch:
		branch_doc = get_branch(branch)
		headers.update(
			{
				"tin": settings.tin,
				"bhfId": branch_doc.bhf_id,
				# raise_exception=False: a branch with no cmcKey yet (never
				# registered) has nothing in the password vault at all, and
				# get_password() raises by default in that case rather than
				# just returning empty - found via testing, not assumed.
				"cmcKey": branch_doc.get_password("cmc_key", raise_exception=False) or "",
			}
		)

	url = f"{base_url.rstrip('/')}/{endpoint.lstrip('/')}"
	response = _do_request(method, url, json=payload, headers=headers)

	_log_call(
		settings,
		endpoint=url,
		request_body=payload,
		response=response,
		branch=branch_doc,
		reference_doctype=reference_doctype,
		reference_name=reference_name,
	)

	try:
		data = response.json()
	except ValueError:
		data = {}

	if not response.ok:
		frappe.throw(_("eTIMS call to {0} failed ({1}): {2}").format(endpoint, response.status_code, data or response.text))

	# resultCd "000" = success - confirmed against kenya-compliance's actual
	# response handling (not a guess, unlike the earlier version of this check).
	result_cd = data.get("resultCd") if isinstance(data, dict) else None
	if result_cd is not None and result_cd != "000":
		frappe.throw(
			_("eTIMS rejected the request to {0}: {1}").format(
				endpoint, data.get("resultMsg") or data
			)
		)

	return data


def _log_call(settings, endpoint, request_body, response, branch=None, reference_doctype=None, reference_name=None):
	try:
		frappe.get_doc(
			{
				"doctype": "eTIMS Log",
				"company": settings.company,
				"branch": branch.name if branch else None,
				"endpoint": endpoint,
				"status": "Success" if response.ok else "Failed",
				"status_code": response.status_code,
				"request_body": _safe_json(request_body),
				"response_body": _safe_json(_response_json(response)),
				"error": None if response.ok else response.text[:140],
				"reference_doctype": reference_doctype,
				"reference_name": reference_name,
			}
		).insert(ignore_permissions=True)
	except Exception:
		# Logging must never be the reason an eTIMS call fails.
		frappe.log_error(title="eTIMS Log write failed")


def _response_json(response):
	try:
		return response.json()
	except ValueError:
		return response.text


def _safe_json(value):
	if value is None:
		return None
	try:
		return json.dumps(value, indent=2, default=str)
	except TypeError:
		return str(value)
