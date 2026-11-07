# Copyright (c) 2026, Royce Technologies LTD and contributors
# For license information, please see license.txt

from royce_etims.custom_fields import create_etims_custom_fields


def execute():
	# Idempotent (update=True). KRA's result fields on Sales/POS Invoice become
	# no_copy, so Duplicate, Amend and Return no longer carry another invoice's
	# KRA number, signature and QR code; field help reworded for users.
	create_etims_custom_fields()
