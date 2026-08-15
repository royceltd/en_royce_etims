# Copyright (c) 2026, Royce Technologies LTD and contributors
# For license information, please see license.txt

from royce_etims.custom_fields import create_etims_custom_fields


def execute():
	# create_etims_custom_fields() is idempotent (update=True) - safe to call
	# again even though add_etims_custom_fields already ran; this picks up the
	# newly added POS Invoice fields without re-touching what's already there.
	create_etims_custom_fields()
