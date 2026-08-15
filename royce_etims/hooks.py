app_name = "royce_etims"
app_title = "Royce Etims"
app_publisher = "Royce Technologies LTD"
app_description = "Generate etims compliant invoices"
app_email = "developer@roycetechnologies.co.ke"
app_license = "mit"

# Apps
# ------------------

# Doctypes here Link to Company/Branch, which belong to erpnext, not core frappe -
# without this, installing on a site without erpnext installed first fails at
# doctype sync ("options is not a valid doctype"). Found by comparing against
# csf_ke, which declares the same for its own erpnext/hrms dependency.
required_apps = ["erpnext"]

# Each item in the list will be shown as an app in the apps page
add_to_apps_screen = [
	{
		"name": "royce_etims",
		"logo": "/assets/royce_etims/logo.png",
		"title": "Royce Etims",
		"route": "/app/etims-settings",
		"has_permission": "royce_etims.check_app_permission",
	}
]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/royce_etims/css/royce_etims.css"
# app_include_js = "/assets/royce_etims/js/royce_etims.js"

# include js, css files in header of web template
# web_include_css = "/assets/royce_etims/css/royce_etims.css"
# web_include_js = "/assets/royce_etims/js/royce_etims.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "royce_etims/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
doctype_js = {"Item": "public/js/item.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "royce_etims/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# automatically load and sync documents of this doctype from downstream apps
# importable_doctypes = [doctype_1]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "royce_etims.utils.jinja_methods",
# 	"filters": "royce_etims.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "royce_etims.install.before_install"
after_install = "royce_etims.setup.after_install"

# Uninstallation
# ------------

# before_uninstall = "royce_etims.uninstall.before_uninstall"
# after_uninstall = "royce_etims.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "royce_etims.utils.before_app_install"
# after_app_install = "royce_etims.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "royce_etims.utils.before_app_uninstall"
# after_app_uninstall = "royce_etims.utils.after_app_uninstall"

# Build
# ------------------
# To hook into the build process

# after_build = "royce_etims.build.after_build"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "royce_etims.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# Document Events
# ---------------
# Hook on document methods and events

# Which doctypes can trigger an eTIMS sign call is gated per-company by
# eTIMS Settings.sign_pos_invoices / sign_sales_invoices - see
# royce_etims.etims_sync.receipt for why both point at the same handler.
doc_events = {
	"POS Invoice": {
		"on_submit": "royce_etims.etims_sync.receipt.on_submit",
	},
	"Sales Invoice": {
		"on_submit": "royce_etims.etims_sync.receipt.on_submit",
	},
}

# Scheduled Tasks
# ---------------

scheduler_events = {
	"cron": {
		"*/15 * * * *": ["royce_etims.etims_sync.receipt.retry_failed_receipts"],
	},
}

# Testing
# -------

before_tests = "royce_etims.setup.utils.before_tests"

# Extend DocType Class
# ------------------------------
#
# Specify custom mixins to extend the standard doctype controller.
# extend_doctype_class = {
# 	"Task": "royce_etims.custom.task.CustomTaskMixin"
# }

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "royce_etims.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "royce_etims.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["royce_etims.utils.before_request"]
# after_request = ["royce_etims.utils.after_request"]

# Job Events
# ----------
# before_job = ["royce_etims.utils.before_job"]
# after_job = ["royce_etims.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"royce_etims.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }

# Translation
# ------------
# List of apps whose translatable strings should be excluded from this app's translations.
# ignore_translatable_strings_from = []

