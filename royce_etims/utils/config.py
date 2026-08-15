# Copyright (c) 2026, Royce Technologies LTD and contributors
# For license information, please see license.txt

"""Environment endpoints for the KRA eTIMS OSCU API.

Sandbox values are taken directly from the eTIMS-OSCU-Integrator-Automated-Testing-Sandbox
Postman collection. Production values are intentionally left unset: KRA's live OSCU host
has not been confirmed against official documentation yet, and guessing a hostname here
is worse than failing loudly - a wrong production URL would look like it "worked" (a
network/DNS error) rather than surfacing as the compliance problem it actually is.

Fill these in once confirmed for a live client, ideally from the KRA-issued go-live
documentation for that taxpayer rather than assumed to be the same for everyone.
"""

SANDBOX_TOKEN_URL = "https://sbx.kra.go.ke/v1/token/generate"
SANDBOX_BASE_URL = "https://sbx.kra.go.ke/etims-oscu/api/v1"

PRODUCTION_TOKEN_URL = None
PRODUCTION_BASE_URL = None
