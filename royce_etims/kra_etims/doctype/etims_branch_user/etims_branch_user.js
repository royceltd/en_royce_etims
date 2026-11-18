// Copyright (c) 2026, Royce Technologies LTD and contributors
// For license information, please see license.txt

frappe.ui.form.on("eTIMS Branch User", {
	refresh(frm) {
		if (frm.is_new()) return;
		frm.add_custom_button(__("Send to KRA"), () =>
			frappe
				.call({
					method: "royce_etims.etims_sync.branch_info.send_now",
					args: { doctype: frm.doctype, name: frm.doc.name },
					freeze: true,
					freeze_message: __("Sending to KRA eTIMS..."),
				})
				.then((r) => {
					frappe.show_alert({ message: r.message, indicator: "green" });
					frm.reload_doc();
				})
				.catch(() => frm.reload_doc())
		);
	},
});
