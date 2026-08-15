# Copyright (c) 2026, Royce Technologies LTD and contributors
# For license information, please see license.txt

"""Generic authenticated client for the KRA eTIMS OSCU API.

Every business endpoint (saveItem, sendSalesTransaction, initialize, ...) should go
through `request()` here rather than calling `requests` directly, so that token
caching/refresh, the standard headers, and eTIMS Log entries stay in one place.
"""

import json

import frappe
import requests
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_to_date, get_datetime, now_datetime

from royce_etims.utils.config import (
	PRODUCTION_BASE_URL,
	PRODUCTION_TOKEN_URL,
	SANDBOX_BASE_URL,
	SANDBOX_TOKEN_URL,
)

# Safety margin before a cached token's real expiry at which we treat it as stale
# and refresh anyway, so we don't hand out a token that expires mid-request.
TOKEN_REFRESH_MARGIN_SECONDS = 30

REQUEST_TIMEOUT_SECONDS = 60


def get_settings(company):
	"""eTIMS Settings is named after its Company (autoname field:company)."""
	return frappe.get_doc("eTIMS Settings", company)


def get_branch(branch):
	if isinstance(branch, Document):
		return branch
	return frappe.get_doc("eTIMS Branch", branch)


def get_urls(settings):
	if settings.environment == "Sandbox":
		return SANDBOX_TOKEN_URL, SANDBOX_BASE_URL

	if settings.environment == "Production":
		if not (PRODUCTION_TOKEN_URL and PRODUCTION_BASE_URL):
			frappe.throw(
				_(
					"Production eTIMS endpoints are not configured yet. Confirm the live "
					"URLs with KRA before switching {0} to Production."
				).format(settings.company)
			)
		return PRODUCTION_TOKEN_URL, PRODUCTION_BASE_URL

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


def generate_token(settings):
	"""Fetch a fresh access token from Apigee and cache it on the settings doc."""
	token_url, _base_url = get_urls(settings)
	client_id = settings.apigee_client_id
	client_secret = settings.get_password("apigee_client_secret")

	if not (client_id and client_secret):
		frappe.throw(_("Apigee Client ID/Secret are not set on eTIMS Settings for {0}").format(settings.company))

	response = _do_request(
		"GET",
		token_url,
		params={"grant_type": "client_credentials"},
		auth=(client_id, client_secret),
	)

	_log_call(
		settings,
		endpoint=token_url,
		request_body={"grant_type": "client_credentials"},
		response=response,
	)

	if not response.ok:
		frappe.throw(
			_("Failed to generate eTIMS access token for {0}: {1}").format(settings.company, response.text)
		)

	data = response.json()
	token = data.get("access_token")
	if not token:
		frappe.throw(_("eTIMS token endpoint did not return an access_token: {0}").format(data))

	settings.db_set("access_token", token, notify=False)
	expires_in = data.get("expires_in")
	if expires_in:
		settings.db_set(
			"token_expiry", add_to_date(now_datetime(), seconds=int(expires_in)), notify=False
		)

	return token


def get_valid_token(settings, force_refresh=False):
	if not force_refresh and settings.access_token and settings.token_expiry:
		safe_until = add_to_date(now_datetime(), seconds=TOKEN_REFRESH_MARGIN_SECONDS)
		if get_datetime(settings.token_expiry) > safe_until:
			return settings.get_password("access_token")

	return generate_token(settings)


def request(
	company,
	endpoint,
	payload=None,
	method="POST",
	branch=None,
	reference_doctype=None,
	reference_name=None,
):
	"""Call an eTIMS business endpoint with standard auth/headers, and log it.

	`branch` should be passed (an eTIMS Branch doc or name) for every endpoint that
	needs the tin/bhfId/cmcKey headers - i.e. everything except `initialize` itself,
	where the device isn't registered yet and those values are the request body.
	"""
	settings = get_settings(company)
	_token_url, base_url = get_urls(settings)

	headers = {
		"Content-Type": "application/json",
		"apigee_app_id": settings.apigee_app_id or "",
		"Authorization": f"Bearer {get_valid_token(settings)}",
	}

	branch_doc = None
	if branch:
		branch_doc = get_branch(branch)
		headers.update(
			{
				"tin": settings.tin,
				"bhfId": branch_doc.bhf_id,
				"cmcKey": branch_doc.get_password("cmc_key") or "",
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

	# KRA's eTIMS responses wrap the payload with a resultCd/resultMsg envelope where
	# "000" means success - this is the documented convention for the OSCU spec, but
	# there are no sample responses in the sandbox collection to verify field-for-field
	# against, so treat this check as best-effort until confirmed live.
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
