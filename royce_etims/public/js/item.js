// Copyright (c) 2026, Royce Technologies LTD and contributors
// For license information, please see license.txt

frappe.ui.form.on("Item", {
	refresh(frm) {
		if (frm.is_new()) return;

		frm.add_custom_button(__("Sync to eTIMS"), () => {
			frappe.db.get_list("eTIMS Settings", { fields: ["name"], limit_page_length: 0 }).then((rows) => {
				if (!rows.length) {
					frappe.msgprint(__("No eTIMS Settings found. Set up a company for eTIMS first."));
					return;
				}

				const run = (company) => {
					frappe.call({
						method: "royce_etims.etims_sync.item.sync_item",
						args: { item_code: frm.doc.name, company },
						freeze: true,
						freeze_message: __("Syncing item to eTIMS..."),
						callback: (r) => {
							if (r.message?.success) {
								frappe.show_alert({ message: r.message.message, indicator: "green" });
								frm.reload_doc();
							}
						},
					});
				};

				if (rows.length === 1) {
					run(rows[0].name);
				} else {
					frappe.prompt(
						[
							{
								fieldname: "company",
								fieldtype: "Link",
								options: "eTIMS Settings",
								label: __("Company"),
								reqd: 1,
							},
						],
						(values) => run(values.company),
						__("Sync to eTIMS")
					);
				}
			});
		});
	},
});
