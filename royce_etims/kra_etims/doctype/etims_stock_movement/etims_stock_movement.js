// Copyright (c) 2026, Royce Technologies LTD and contributors
// For license information, please see license.txt

frappe.ui.form.on("eTIMS Stock Movement", {
	refresh(frm) {
		if (!["Pending", "Failed"].includes(frm.doc.status)) return;

		// Retries the whole branch queue, oldest first - KRA needs sarNo in
		// order, so this one can't jump ahead of an earlier stuck movement.
		frm.add_custom_button(__("Retry Branch Queue"), () => {
			frappe
				.call({
					method: "royce_etims.etims_sync.stock.retry_movement_queue",
					args: { branch: frm.doc.branch },
				})
				.then((r) => {
					frappe.show_alert({ message: r.message, indicator: "blue" });
				});
		});
	},
});
