# Copyright (c) 2026, Royce Technologies LTD and contributors
# For license information, please see license.txt

"""Environment endpoints for the KRA eTIMS OSCU API.

CORRECTED TWICE. First: the original eTIMS-OSCU-Integrator-Automated-Testing-
Sandbox Postman collection this app was first built from pointed at
sbx.kra.go.ke/etims-oscu/api/v1 with an Apigee OAuth2 client-credentials
layer in front - wrong host, wrong auth model. Fixed against KRA's OSCU
Specification Document v2.0 and navariltd/kenya-compliance (tested against
the real KRA sandbox in 2024), landing on etims-api-sbx.kra.go.ke/etims-api.

Second: KRA's own official "eTIMS OSCU AND VSCU Step-by-Step Guide" (v1.1,
read directly, page 8) gives a worked example that settles the path
question definitively - "the url path for OSCU device activation is
indicated as (url: /selectInitOsdcInfo) therefore the full url path is
https://etims-api-sbx.kra.go.ke/selectInitOsdcInfo" - NO /etims-api segment.
That contradicted kenya-compliance's SANDBOX_SERVER_URL constant, which
included it; the primary source wins here; kenya-compliance's hardcoded
constant was likely a stale default real deployments overrode via their own
`server_url` field (a plain editable Data field in their Settings doctype,
not baked into every call the way this constant was).

No separate OAuth/bearer-token step. Every call authenticates with
tin/bhfId/cmcKey headers only (see utils/api_client.py).

QR_VERIFY_BASE_URL is the public receipt-verification host a signed
receipt's QR code links to - a third, distinct KRA host (confirmed from
kenya-compliance's actual QR-generation code, not guessed, and not directly
cross-checked against the step-by-step guide above the way the base URL
was). Only the sandbox value is confirmed; the production one follows the
same sbx-suffix-removed pattern seen for the API host, but hasn't been
directly confirmed, so treat it as a reasonable inference, not a verified
fact, until checked.
"""

SANDBOX_BASE_URL = "https://etims-api-sbx.kra.go.ke"
PRODUCTION_BASE_URL = "https://etims-api.kra.go.ke"

SANDBOX_QR_VERIFY_BASE_URL = (
	"https://etims-sbx.kra.go.ke/common/link/etims/receipt/indexEtimsReceiptData"
)
# Inferred by pattern (sbx-suffix removed), not independently confirmed.
PRODUCTION_QR_VERIFY_BASE_URL = "https://etims.kra.go.ke/common/link/etims/receipt/indexEtimsReceiptData"
