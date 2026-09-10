# Royce eTIMS — OSCU Integration Guide

**What this is:** the settled, current "how to" for getting a company signing real eTIMS receipts —
initializing a device and making authenticated calls. For *why* things are built this way, and the
sometimes-painful history of how each piece got confirmed, see [`architecture.md`](./architecture.md)
— that file is the decision log; this one is the operating manual. Update both when something
changes: architecture.md gets the reasoning, this file gets the current correct steps.

**Status:** confirmed working end-to-end against KRA's real sandbox as of 2026-09-10 — token fetch,
device initialization, and two independent business endpoint calls (`selectCodeList`,
`selectBhfList`) have all returned genuine KRA data through this exact code path.

---

## 1. One-time setup per company

1. **Company** — country must be Kenya (KRA's own tax defaults piggyback on this; see the sibling
   `kenyan_accountant` app for the accounting side).
2. **`eTIMS Settings`** (one per Company, autonamed to the company) — set:
   - `tin` — the company's KRA PIN
   - `environment` — `Sandbox` or `Production`
   - `gavaconnect_consumer_key` / `gavaconnect_consumer_secret` — see step 3
3. **Get GavaConnect App credentials.** Go to `developer.go.ke`, create an App, subscribe it to the
   eTIMS OSCU product. This is a **portal action, not a code step** — there's no API to automate
   it. You get a Consumer Key and Consumer Secret; both go on `eTIMS Settings`. This is a
   *different* thing from the "Integration Token" you get from the eTIMS Taxpayer Portal in step 4
   below — don't confuse the two (see architecture.md's correction history for how that confusion
   cost real debugging time).

## 2. KRA-side onboarding (a human process — not something this app can do for you)

Per KRA's own GavaConnect walkthrough (full detail in architecture.md):

1. Sign up at the eTIMS Taxpayer Sandbox Portal (`etims-sbx.kra.go.ke`) — PIN, OTP, password.
2. Service Request → eTIMS → select **OSCU** as the type. This form has an **"Integration Token"**
   field (issued by KRA support by email, tied to your PIN + system name + version + device
   serial) — enter it and submit.
3. Wait for KRA's approval SMS.
4. **The `bhfId` KRA assigns may not be `"00"`**, even though that's the conventional
   single-branch/head-office default. If the Service Request fails with "Device Serial Number
   already used," the fix that actually worked was a *different* `bhfId` (`02`), not a different
   device serial — the uniqueness constraint is more likely on the `(bhfId, dvcSrlNo)` pair than
   the serial alone. Don't assume `"00"` is safe; be ready to ask KRA support for the one they
   actually issued.

## 3. Registering a device (`eTIMS Branch`)

1. Create an **`eTIMS Branch`** record: `company`, `branch` (an ERPNext Branch), `bhf_id` (from step
   2.4), `dvc_srl_no`.
   - **Leave `dvc_srl_no` blank** and it auto-generates (`ROYCEERP-<tin>-<sequence>`) on save. This
     is deliberate — a device serial is a self-chosen unique string, not a real hardware ID (Odoo's
     own eTIMS integration does the same: vendor prefix + PIN + sequence). Using a real machine
     serial risks exactly the "already used" collision above.
2. Call **`register_device()`** on that document (whitelisted — callable from the Desk UI or the
   API). This does `POST /initialize` with `{tin, bhfId, dvcSrlNo}` and, on success, stores:
   - `cmc_key` — the communication key every subsequent signed call needs
   - `sdc_id`, `dvc_id`, `mrc_no` — KRA's device identifiers
   - `device_status` → `Registered`
3. **Do this once per device.** The code itself refuses to re-run if `device_status` is already
   `Active`, and KRA's own docs warn re-initializing an already-registered device isn't expected to
   behave safely. If registration already happened outside this app (e.g. a standalone debugging
   script — see architecture.md), record the known-good result directly rather than re-triggering
   the live call:
   ```python
   branch = frappe.get_doc("eTIMS Branch", branch_name)
   branch.db_set("cmc_key", cmc_key, notify=False)
   branch.db_set("sdc_id", sdc_id, notify=False)
   branch.db_set("dvc_id", dvc_id, notify=False)
   branch.db_set("mrc_no", mrc_no, notify=False)
   branch.db_set("device_status", "Registered", notify=False)
   branch.db_set("registered_on", now_datetime(), notify=False)
   frappe.db.commit()
   ```

## 4. Making any other authenticated call

**Always go through `royce_etims.utils.api_client.request()`** — never call `requests` directly
from feature code. It's the one place that knows how to authenticate a call correctly.

```python
from royce_etims.utils.api_client import request as etims_request

data = etims_request(
    company,            # e.g. "Royce Technologies LTD"
    "selectCodeList",   # endpoint name, no leading slash, no host/version prefix
    payload={"tin": tin, "bhfId": bhf_id, "lastReqDt": "20200101000000"},
    method="POST",       # most business endpoints are POST even when "Get"-only per KRA's docs
    branch=branch_name,  # an eTIMS Branch name or doc - omit only for /initialize itself
)
```

What `request()` handles for you, so you don't have to think about it per call:

- **Bearer token** — fetched via the GavaConnect `client_credentials` OAuth flow and cached
  (`frappe.cache`, degrades gracefully if the cache is unreachable) until it's close to expiry.
  Added automatically as `Authorization: Bearer ...` whenever `gavaconnect_consumer_key`/`_secret`
  are set on `eTIMS Settings` — silently omitted otherwise (you'll get KRA's own 401 rather than a
  local error, which is more informative for a company that hasn't gotten GavaConnect credentials
  yet).
- **`tin`/`bhfId`/`cmcKey` headers** — added whenever you pass `branch`. Omit `branch` only for
  `/initialize` itself, where the device isn't registered yet and these travel in the body instead.
- **Logging** — every call, success or failure, gets an `eTIMS Log` entry (request/response body,
  status, linked back to whatever document triggered it via `reference_doctype`/`reference_name`).
  Logging failures never break the actual call.
- **Result validation** — `resultCd != "000"` raises a clear `frappe.throw` with KRA's own
  `resultMsg`, rather than a caller having to check it themselves.

### Reading the response

KRA's real response envelope (confirmed for real, not guessed) wraps the business payload:

```json
{
  "responseHeader": {"responseCode": 200, "customerMessage": "Successful", ...},
  "responseBody": {
    "resultCd": "000",
    "resultMsg": "Successful",
    "data": { "...the actual payload you want..." }
  }
}
```

`request()`'s own `resultCd` check already unwraps `responseBody` for you (with a fallback to the
flat shape for safety). But if you're pulling data out of a response yourself, reach into
`data["responseBody"]["data"]`, not `data["data"]` — the earlier (wrong, unverified) assumption
was one level shallower and would silently find nothing on a real response. `register_device()`'s
parsing is the reference example to copy for a new endpoint.

**One open gotcha:** KRA's gateway has returned HTTP 400 for a well-formed, fully-authenticated
response that just legitimately found no data (`resultCd "001"`, "There is no search result") —
not only for real errors. `request()` currently throws on any non-2xx status without distinguishing
these. If you're calling an endpoint that can legitimately return "no results," don't be surprised
by an exception that isn't actually a failure — check `docs/architecture.md`'s open items before
assuming it's a bug in your call.

## 5. Confirmed-working endpoints so far

Only these have actually been called against real KRA infrastructure and returned genuine data —
everything else in the OSCU spec is still unverified against the real API, even if the endpoint
name/path is confirmed from GavaConnect's docs:

| Endpoint | Verified | Notes |
|---|---|---|
| `initialize` | ✅ 2026-09-10 | Device registration; response shape confirmed |
| `selectCodeList` | ✅ 2026-09-10 | Returned real Taxation Type codes (`A`=Exempt, `B`=16%, `C`=Zero Rated, `E`=8%) |
| `selectBhfList` | ✅ 2026-09-10 | Returned real branch data, cross-checked against `initialize`'s result |
| `sendSalesTransaction` | ❌ not yet | The one `receipt.py` actually depends on for signing invoices - build/test this next |

## 6. Quick-reference gotchas

- **New fields on `eTIMS Settings`/`eTIMS Branch` not showing up?** If `bench migrate` fails in
  your dev environment (e.g. `redis_cache is not running`), a plain JSON edit won't reach the
  database — Frappe's `Document` doesn't validate attribute assignment against the meta, so a
  `.save()` can *look* successful while silently not persisting. Run
  `bench --site <site> reload-doctype "<Doctype Name>"` instead — a lighter sync that doesn't need
  the full service stack.
- **Token endpoint is `GET`, not `POST`** — easy to get backwards, and the failure mode (empty body
  or a generic 400) gives almost no hint which is wrong.
- **`bhfId "00"` isn't automatically safe** — see section 2.4 above.
