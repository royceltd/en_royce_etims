// Copyright (c) 2026, Royce Technologies LTD and contributors
// For license information, please see license.txt

frappe.query_reports["KRA Lookup"] = {
	filters: [
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			default: frappe.defaults.get_user_default("Company"),
			reqd: 1,
		},
		{
			fieldname: "lookup",
			label: __("Lookup"),
			fieldtype: "Select",
			options: [
				"Branches",
				"Notices",
				"Customers",
				"Items",
				"Imported Items",
				"Stock Received from Others",
				"Sales",
				"Invoice Details",
				"Purchases",
			],
			default: "Items",
			reqd: 1,
		},
		{
			fieldname: "since",
			label: __("Changed Since"),
			fieldtype: "Date",
			depends_on: "eval:doc.lookup != 'Invoice Details'",
			description: __("Leave empty for everything. Notices only go back one hour."),
		},
		{
			fieldname: "invoice_no",
			label: __("KRA Invoice No."),
			fieldtype: "Int",
			depends_on: "eval:doc.lookup == 'Invoice Details'",
		},
	],
};
