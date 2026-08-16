# Copyright (c) 2026, Royce Technologies LTD and contributors
# For license information, please see license.txt

"""Environment endpoints for the KRA eTIMS OSCU API.

CORRECTED: the original eTIMS-OSCU-Integrator-Automated-Testing-Sandbox
Postman collection this app was first built from pointed at
sbx.kra.go.ke/etims-oscu/api/v1 with an Apigee OAuth2 client-credentials
layer in front of it. Cross-checked against two independent sources -
KRA's own official OSCU Specification Document v2.0, and navariltd's
kenya-compliance (an ERPNext OSCU integration actually tested against the
KRA sandbox in 2024, zero OAuth code anywhere in it) - both agree: the real
API lives at etims-api-sbx.kra.go.ke/etims-api, and there is no separate
OAuth/bearer-token step. Every call authenticates with tin/bhfId/cmcKey
headers only (see utils/api_client.py). SANDBOX_BASE_URL and
PRODUCTION_BASE_URL below reflect that correction, not the original
collection.

QR_VERIFY_BASE_URL is the public receipt-verification host a signed
receipt's QR code links to - a third, distinct KRA host (confirmed from
kenya-compliance's actual QR-generation code, not guessed). Only the
sandbox value is confirmed; the production one follows the same
sbx-suffix-removed pattern seen for the API host, but hasn't been directly
confirmed against a source the way the others have, so treat it as a
reasonable inference, not a verified fact, until checked.
"""

SANDBOX_BASE_URL = "https://etims-api-sbx.kra.go.ke/etims-api"
PRODUCTION_BASE_URL = "https://etims-api.kra.go.ke/etims-api"

SANDBOX_QR_VERIFY_BASE_URL = (
	"https://etims-sbx.kra.go.ke/common/link/etims/receipt/indexEtimsReceiptData"
)
# Inferred by pattern (sbx-suffix removed), not independently confirmed.
PRODUCTION_QR_VERIFY_BASE_URL = "https://etims.kra.go.ke/common/link/etims/receipt/indexEtimsReceiptData"
