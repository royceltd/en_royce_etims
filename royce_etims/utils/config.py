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

Auth: GavaConnect's own "Common Headers for all Basic Data Management APIs"
table lists only tin/bhfId/cmcKey - no Bearer token mentioned at the business-
payload level. Whether an Apigee/GavaConnect OAuth token (the original
collection's /v1/token/generate flow) is ALSO required as a gateway-level
layer on top of that is not confirmed either way - "App creation" is a
mandatory portal step before testing, which suggests it might be, but the
"Integration Token" the taxpayer received turned out to belong to a
different, unrelated step (the eTIMS Taxpayer Portal's Service Request form,
gating device registration - not a GavaConnect app credential at all). Left
out of api_client.py until an actual call confirms whether it's needed -
see that module's docstring.

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

SANDBOX_QR_VERIFY_BASE_URL = (
	"https://etims-sbx.kra.go.ke/common/link/etims/receipt/indexEtimsReceiptData"
)
# Inferred by pattern (sbx-suffix removed), not independently confirmed.
PRODUCTION_QR_VERIFY_BASE_URL = "https://etims.kra.go.ke/common/link/etims/receipt/indexEtimsReceiptData"
