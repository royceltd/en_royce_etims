# Copyright (c) 2026, Royce Technologies LTD and contributors
# For license information, please see license.txt

"""Test-site bootstrap. Pattern borrowed from csf_ke's before_tests (which itself
runs a full ERPNext setup_wizard for exactly this reason) - eTIMS Settings/Branch
both Link to Company, so tests need a real Company to exist, not a mocked one.
"""

import frappe
from erpnext.setup.utils import enable_all_roles_and_domains
from frappe.utils import now_datetime

TEST_COMPANY = "eTIMS Test Co"


def before_tests():
	frappe.clear_cache()

	if not frappe.get_list("Company"):
		from frappe.desk.page.setup_wizard.setup_wizard import setup_complete

		year = now_datetime().year
		setup_complete(
			{
				"currency": "KES",
				"full_name": "Test User",
				"company_name": TEST_COMPANY,
				"timezone": "Africa/Nairobi",
				"company_abbr": "ETC",
				"industry": "Software",
				"country": "Kenya",
				"fy_start_date": f"{year}-01-01",
				"fy_end_date": f"{year}-12-31",
				"language": "english",
				"company_tagline": "Testing",
				"email": "test@roycetechnologies.co.ke",
				"password": "test",
				"chart_of_accounts": "Standard",
			}
		)

	enable_all_roles_and_domains()
	frappe.db.commit()  # nosemgrep
