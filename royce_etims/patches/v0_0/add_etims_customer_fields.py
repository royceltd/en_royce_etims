# Copyright (c) 2026, Royce Technologies LTD and contributors
# For license information, please see license.txt

from royce_etims.custom_fields import create_etims_custom_fields


def execute():
	# Idempotent (update=True) - adds the Customer eTIMS registration fields
	# on sites installed before customer registration existed.
	create_etims_custom_fields()
