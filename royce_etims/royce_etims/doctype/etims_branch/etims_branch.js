// Copyright (c) 2026, Royce Technologies LTD and contributors
// For license information, please see license.txt

frappe.ui.form.on("eTIMS Branch", {
	refresh(frm) {
		if (frm.is_new() || frm.doc.device_status === "Active") return;

		frm.add_custom_button(__("Register Device"), () => {
			frappe.db.get_value("eTIMS Settings", frm.doc.company, "environment").then((r) => {
				const environment = r.message?.environment || __("Unknown");
				frappe.confirm(
					__(
						"This registers a device with KRA eTIMS in the <b>{0}</b> environment, for branch {1} (bhfId {2}). This cannot be safely undone from here - continue?",
						[environment, frm.doc.branch, frm.doc.bhf_id]
					),
					() => {
						frappe.call({
							doc: frm.doc,
							method: "register_device",
							freeze: true,
							freeze_message: __("Registering device with eTIMS..."),
							callback: (res) => {
								if (res.message?.success) {
									frappe.show_alert({ message: res.message.message, indicator: "green" });
									frm.reload_doc();
								}
							},
						});
					}
				);
			});
		});
	},
});
