# Copyright (c) 2026, Royce Technologies LTD and contributors
# For license information, please see license.txt

"""Generic authenticated client for the KRA eTIMS OSCU API.

Every business endpoint (saveItem, sendSalesTransaction, initialize, ...)
should go through `request()` here rather than calling `requests` directly, so
that the standard headers and eTIMS Log entries stay in one place.

Two auth layers, confirmed 2026-09-10 by an actual live call (see
docs/architecture.md, and utils/config.py's docstring for the full,
twice-reversed correction history before touching this again):

1. tin/bhfId/cmcKey headers - matches GavaConnect's own documented "Common
   Headers for all Basic Data Management APIs".
2. A GavaConnect/Apigee OAuth Bearer token on top of that - a live call to
   /initialize with correct tin/bhfId/dvcSrlNo and no Authorization header
   got back a clean 401 "Unauthorised-Invalid Access Token" from KRA's real
   sandbox. Not a guess anymore.

The token comes from eTIMS Settings.gavaconnect_consumer_key/_secret (from
an App created on the GavaConnect developer portal, a separate step from
device registration - see docs/architecture.md). If those are blank, request()
still sends the call without an Authorization header rather than blocking -
it'll fail with the same 401 either way, which is more informative than a
local error for a company that hasn't gotten GavaConnect credentials yet.
"""

import json

import frappe
import requests
from frappe import _
from frappe.model.document import Document

from royce_etims.utils.config import (
	PRODUCTION_BASE_URL,
	PRODUCTION_TOKEN_URL,
	SANDBOX_BASE_URL,
	SANDBOX_TOKEN_URL,
)

REQUEST_TIMEOUT_SECONDS = 60
# Conservative default if KRA's token response doesn't include expires_in -
# Apigee's usual default is 3600s; refresh early rather than risk a call
# failing mid-flight on an expired token.
DEFAULT_TOKEN_TTL_SECONDS = 3000
TOKEN_REFRESH_MARGIN_SECONDS = 60


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


def get_token_url(settings):
	if settings.environment == "Sandbox":
		return SANDBOX_TOKEN_URL
	if settings.environment == "Production":
		return PRODUCTION_TOKEN_URL
	return None


def _get_access_token(settings):
	"""Fetch (and cache) a GavaConnect Bearer token via OAuth2 client_credentials.

	Returns None - not an error - if no Consumer Key/Secret is configured yet,
	so a company without GavaConnect credentials still gets KRA's own 401
	rather than a local validation error masking the same underlying problem.
	"""
	consumer_key = settings.gavaconnect_consumer_key
	consumer_secret = settings.get_password("gavaconnect_consumer_secret", raise_exception=False)
	if not consumer_key or not consumer_secret:
		return None

	cache_key = f"royce_etims:gavaconnect_token:{settings.company}"
	try:
		cached = frappe.cache().get_value(cache_key)
		if cached:
			return cached
	except Exception:
		pass  # cache unavailable - fetch a fresh token instead of failing the call over it

	token_url = get_token_url(settings)
	if not token_url:
		frappe.throw(
			_("GavaConnect token URL is not configured for the {0} environment yet.").format(settings.environment)
		)

	response = _do_request(
		"POST",
		token_url,
		params={"grant_type": "client_credentials"},
		auth=(consumer_key, consumer_secret),
	)
	try:
		data = response.json()
	except ValueError:
		data = {}

	if not response.ok:
		frappe.throw(
			_("Could not get a GavaConnect access token for {0} ({1}): {2}").format(
				settings.company, response.status_code, data or response.text
			)
		)

	token = data.get("access_token")
	if not token:
		frappe.throw(_("GavaConnect token response had no access_token: {0}").format(data))

	ttl = int(data.get("expires_in") or DEFAULT_TOKEN_TTL_SECONDS) - TOKEN_REFRESH_MARGIN_SECONDS
	try:
		frappe.cache().set_value(cache_key, token, expires_in_sec=max(ttl, 60))
	except Exception:
		pass  # caching is an optimisation, not a requirement - a cache miss just means fetching again next call

	return token


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

	access_token = _get_access_token(settings)
	if access_token:
		headers["Authorization"] = f"Bearer {access_token}"

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
