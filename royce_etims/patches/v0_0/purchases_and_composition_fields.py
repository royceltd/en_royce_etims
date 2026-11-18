# Copyright (c) 2026, Royce Technologies LTD and contributors
# For license information, please see license.txt

from royce_etims.custom_fields import create_etims_custom_fields


def execute():
	# Idempotent (update=True) - adds Purchase Invoice.royce_etims_purchase and
	# the BOM composition status fields on sites installed before they existed.
	create_etims_custom_fields()
