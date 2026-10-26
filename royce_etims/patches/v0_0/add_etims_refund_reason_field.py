# Copyright (c) 2026, Royce Technologies LTD and contributors
# For license information, please see license.txt

from royce_etims.custom_fields import create_etims_custom_fields


def execute():
	# Idempotent (update=True) - adds royce_etims_refund_reason to Sales/POS
	# Invoice on sites installed before credit notes were supported.
	create_etims_custom_fields()
