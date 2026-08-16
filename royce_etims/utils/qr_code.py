# Copyright (c) 2026, Royce Technologies LTD and contributors
# For license information, please see license.txt

"""Receipt QR code generation.

Verification URL format and the (pin + branch_id + receipt_signature)
concatenation confirmed against navariltd/kenya-compliance's actual,
sandbox-tested QR generation code - not derived from the original Postman
collection, which had no QR/signature handling at all.
"""

from base64 import b64encode
from io import BytesIO
from urllib.parse import quote

import qrcode


def build_verification_url(qr_verify_base_url, tin, bhf_id, receipt_signature):
	data = f"{tin}{bhf_id}{receipt_signature}"
	return f"{qr_verify_base_url}?Data={quote(data, safe='')}"


def generate_qr_data_uri(url):
	"""PNG QR code for `url`, as a data: URI - lets an Image field render it
	directly from a Small Text value, no File document needed per receipt."""
	buffer = BytesIO()
	qrcode.make(url).save(buffer, format="PNG")
	encoded = b64encode(buffer.getvalue()).decode("utf-8")
	return f"data:image/png;base64,{encoded}"
