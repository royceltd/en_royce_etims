__version__ = "0.0.1"


def check_app_permission():
	"""Who sees the royce_etims tile on the Frappe Apps screen.

	eTIMS configuration is back-office/accounting territory - portal
	(website) users have no business here, everyone else on the desk does.
	"""
	import frappe
	from frappe.utils.user import is_website_user

	if frappe.session.user == "Administrator":
		return True

	return not is_website_user()
