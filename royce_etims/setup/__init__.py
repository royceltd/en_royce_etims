# Copyright (c) 2026, Royce Technologies LTD and contributors
# For license information, please see license.txt

from royce_etims.custom_fields import create_etims_custom_fields


def after_install():
	create_etims_custom_fields()
	# install-app marks every patch in patches.txt as done without running it, so a new
	# site never got the KRA-confirmed taxation/item types. Seed them here too. The
	# sample-only item reference patch stays out: it is a stopgap, not a real code list.
	from royce_etims.patches.v0_0 import seed_etims_reference_data

	seed_etims_reference_data.execute()
