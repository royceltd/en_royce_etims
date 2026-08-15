# Copyright (c) 2026, Royce Technologies LTD and contributors
# For license information, please see license.txt

"""Fixes the Apps-screen tile's broken logo on already-installed sites.

`add_to_apps_screen` in hooks.py originally pointed at a logo.png that was
never actually created - a leftover placeholder path from the app scaffold,
never replaced. Frappe only creates the Desktop Icon record for this once,
at install time (frappe.desk.doctype.desktop_icon.desktop_icon.
create_desktop_icons_from_installed_apps skips if one already exists for
this app) - `bench migrate` never re-syncs it, so fixing hooks.py alone
doesn't fix a site that already installed this app. A fresh install gets
the correct logo automatically; this patch is only needed for sites that
installed before the logo.svg existed.
"""

import frappe


def execute():
	app_details = frappe.get_hooks("add_to_apps_screen", app_name="royce_etims")
	if not app_details:
		return

	name = frappe.db.exists("Desktop Icon", {"icon_type": "App", "app": "royce_etims"})
	if not name:
		return

	frappe.db.set_value(
		"Desktop Icon",
		name,
		{"logo_url": app_details[0]["logo"], "link": app_details[0]["route"]},
	)
	frappe.db.commit()
