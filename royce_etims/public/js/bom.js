// Copyright (c) 2026, Royce Technologies LTD and contributors
// For license information, please see license.txt

frappe.ui.form.on("BOM", {
	refresh(frm) {
		if (frm.doc.docstatus !== 1) return;
		frm.add_custom_button(
			__("Send to KRA eTIMS"),
			() =>
				frappe
					.call({
						method: "royce_etims.etims_sync.composition.send_now",
						args: { bom: frm.doc.name },
						freeze: true,
						freeze_message: __("Sending the composition to KRA eTIMS..."),
					})
					.then((r) => {
						frappe.show_alert({ message: r.message, indicator: "green" });
						frm.reload_doc();
					})
					.catch(() => frm.reload_doc()),
			__("Actions")
		);
	},
});
