# Copyright (c) 2026, Royce Technologies LTD and contributors
# For license information, please see license.txt

"""Environment endpoints for the KRA eTIMS OSCU API.

CORRECTED THREE TIMES - the full history matters here because the pendulum
swung back to where it started. See docs/architecture.md for the complete
account; summary:

1. First (this app's original build): the eTIMS-OSCU-Integrator-Automated-
   Testing-Sandbox Postman collection - sbx.kra.go.ke/etims-oscu/api/v1,
   with an Apigee OAuth2 client-credentials layer in front.
2. "Corrected" away from that to etims-api-sbx.kra.go.ke/selectInitOsdcInfo
   (no /etims-api segment), cross-checked against KRA's OSCU Specification
   Document v2.0 and navariltd/kenya-compliance (tested against the real
   sandbox in 2024) - both of which describe a *different*, no-OAuth,
   tin/bhfId/cmcKey-only API surface.
3. Corrected BACK, 2026-09-05, on discovering that the taxpayer's actual
   KRA integration-support contact directed them to GavaConnect
   (developer.go.ke) - KRA's own official Enterprise API platform - and
   reading developer.go.ke/apis/KRA-ETIMS-SBX directly confirms sbx.kra.go.ke
   with the /etims-oscu/api/v1 prefix and the *original* Postman collection's
   endpoint names (initialize, sendSalesTransaction, getPurchaseTransactionInfo,
   ...), not kenya-compliance's. Step 1's "wrong host" was never actually
   wrong - it's KRA's currently-documented, GavaConnect-fronted route. What
   kenya-compliance and the Spec Document v2.0 describe may be a genuinely
   different, older, or parallel API generation - not established which,
   and not this taxpayer's documented path either way.

Base URL is one thing GavaConnect's docs state outright ("Sandbox environment
use: https://sbx.kra.go.ke"); PRODUCTION_BASE_URL below is deliberately left
unset - nothing in what's been read so far confirms the production host, and
guessing wrong here is worse than throwing loudly (see api_client.py's
get_base_url, which already throws if this is empty).

Auth: CONFIRMED 2026-09-10 - a live call to /initialize with correct tin/
bhfId/dvcSrlNo and no Authorization header got back a clean, real KRA
response: HTTP 401, {"responseMessage": "Unauthorised-Invalid Access
Token", "responseCode": 401, ...}. So the Apigee/GavaConnect OAuth layer
(the original collection's /v1/token/generate client-credentials flow) IS
required on top of tin/bhfId/cmcKey, not just a theoretical possibility.
TOKEN_URL below is that endpoint. Getting an actual token needs a Consumer
Key/Secret from an App created on the GavaConnect developer portal
(developer.go.ke) subscribed to the eTIMS OSCU product - a separate step
from the eTIMS Taxpayer Portal's Service Request/Integration Token, and not
yet done as of this correction. See docs/architecture.md.

QR_VERIFY_BASE_URL is the public receipt-verification host a signed
receipt's QR code links to - a third, distinct KRA host (confirmed from
kenya-compliance's actual QR-generation code, not GavaConnect's docs, and
not re-checked during the 2026-09-05 correction). Only the sandbox value is
confirmed; the production one follows the same sbx-suffix-removed pattern
seen for the API host, but hasn't been directly confirmed, so treat it as a
reasonable inference, not a verified fact, until checked.
"""

SANDBOX_BASE_URL = "https://sbx.kra.go.ke/etims-oscu/api/v1"
PRODUCTION_BASE_URL = ""  # Not yet confirmed - see module docstring. get_base_url() throws rather than guess.

# Same host as SANDBOX_BASE_URL, different path - confirmed by the original
# Postman collection's "Access Token" request, not yet independently
# re-confirmed against GavaConnect's own docs the way the base URL was.
SANDBOX_TOKEN_URL = "https://sbx.kra.go.ke/v1/token/generate"
PRODUCTION_TOKEN_URL = ""  # Not yet confirmed - same reasoning as PRODUCTION_BASE_URL.

SANDBOX_QR_VERIFY_BASE_URL = (
	"https://etims-sbx.kra.go.ke/common/link/etims/receipt/indexEtimsReceiptData"
)
# Inferred by pattern (sbx-suffix removed), not independently confirmed.
PRODUCTION_QR_VERIFY_BASE_URL = "https://etims.kra.go.ke/common/link/etims/receipt/indexEtimsReceiptData"
