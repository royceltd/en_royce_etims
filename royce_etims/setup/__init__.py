# Copyright (c) 2026, Royce Technologies LTD and contributors
# For license information, please see license.txt

from royce_etims.custom_fields import create_etims_custom_fields


def after_install():
	create_etims_custom_fields()
