// Copyright (c) 2026, Royce Technologies LTD and contributors
// For license information, please see license.txt

frappe.listview_settings["eTIMS Purchase"] = {
	get_indicator(doc) {
		const colour = {
			New: "orange", Ready: "blue", Invoiced: "purple", Confirmed: "green", Rejected: "gray", Failed: "red",
		}[doc.status];
		return [__(doc.status), colour, "status,=," + doc.status];
	},
	onload(listview) {
		listview.page.add_inner_button(__("Fetch from KRA"), () =>
			frappe.prompt(
				[{ fieldname: "company", fieldtype: "Link", options: "eTIMS Settings", label: __("Company"), reqd: 1,
				   default: frappe.defaults.get_user_default("Company") }],
				(values) =>
					frappe
						.call({
							method: "royce_etims.etims_sync.purchase.fetch_purchases",
							args: { company: values.company },
							freeze: true,
							freeze_message: __("Fetching purchases from KRA eTIMS..."),
						})
						.then((r) => {
							frappe.show_alert({ message: __("{0} new purchases", [r.message]), indicator: "green" });
							listview.refresh();
						}),
				__("Fetch purchases from KRA")
			)
		);
	},
};
