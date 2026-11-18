// Copyright (c) 2026, Royce Technologies LTD and contributors
// For license information, please see license.txt

frappe.ui.form.on("eTIMS Imported Item", {
	refresh(frm) {
		if (!["New", "Failed"].includes(frm.doc.status)) return;
		const call = (method, args, message) =>
			frappe
				.call({ method, args, freeze: true, freeze_message: message })
				.then((r) => {
					frappe.show_alert({ message: r.message, indicator: "green" });
					frm.reload_doc();
				})
				.catch(() => frm.reload_doc());

		frm.add_custom_button(__("Approve"), () => {
			const go = () =>
				call(
					"royce_etims.etims_sync.imports.approve",
					{ name: frm.doc.name, item: frm.doc.item },
					__("Approving with KRA eTIMS...")
				);
			frm.is_dirty() ? frm.save().then(go) : go();
		}).addClass("btn-primary");
		frm.add_custom_button(__("Reject"), () =>
			frappe.confirm(__("Tell KRA this import line isn't yours to receive?"), () =>
				call("royce_etims.etims_sync.imports.reject", { name: frm.doc.name }, __("Rejecting with KRA eTIMS..."))
			)
		);
	},
});
