// Copyright (c) 2026, Royce Technologies LTD and contributors
// For license information, please see license.txt

frappe.listview_settings["eTIMS Imported Item"] = {
	get_indicator(doc) {
		const colour = { New: "blue", Approved: "green", Rejected: "gray", Failed: "red" }[doc.status];
		return [__(doc.status), colour, "status,=," + doc.status];
	},
	onload(listview) {
		listview.page.add_inner_button(__("Fetch from KRA"), () => royce_etims_fetch(listview));
	},
};

function royce_etims_fetch(listview) {
	frappe.prompt(
		[{ fieldname: "company", fieldtype: "Link", options: "eTIMS Settings", label: __("Company"), reqd: 1,
		   default: frappe.defaults.get_user_default("Company") }],
		(values) =>
			frappe
				.call({
					method: "royce_etims.etims_sync.imports.fetch_imported_items",
					args: { company: values.company },
					freeze: true,
					freeze_message: __("Fetching imports from KRA eTIMS..."),
				})
				.then((r) => {
					frappe.show_alert({ message: __("{0} new import lines", [r.message]), indicator: "green" });
					listview.refresh();
				}),
		__("Fetch imports from KRA")
	);
}
