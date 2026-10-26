// Copyright (c) 2026, Royce Technologies LTD and contributors
// For license information, please see license.txt

// Shared by Sales Invoice and POS Invoice (hooks.py doctype_js).
const royce_etims_invoice = {
	refresh(frm) {
		if (frm.doc.docstatus !== 1 || !["Pending", "Failed"].includes(frm.doc.royce_etims_status))
			return;

		frm.add_custom_button(__("Retry eTIMS"), () => {
			frappe
				.call({
					method: "royce_etims.etims_sync.receipt.retry_receipt",
					args: { doctype: frm.doctype, name: frm.doc.name },
					freeze: true,
				})
				.then((r) => {
					frappe.show_alert({ message: r.message, indicator: "blue" });
					frm.reload_doc();
				});
		});
	},
};

frappe.ui.form.on("Sales Invoice", royce_etims_invoice);
frappe.ui.form.on("POS Invoice", royce_etims_invoice);
