// Copyright (c) 2026, Royce Technologies LTD and contributors
// For license information, please see license.txt

frappe.ui.form.on("eTIMS Purchase", {
	refresh(frm) {
		if (frm.is_new()) return;
		const call = (method, message) =>
			frappe
				.call({ method, args: { name: frm.doc.name }, freeze: true, freeze_message: message })
				.then((r) => {
					frm.reload_doc();
					return r.message;
				})
				.catch(() => frm.reload_doc());

		if (["New", "Ready"].includes(frm.doc.status)) {
			frm.add_custom_button(__("Create Purchase Invoice"), () => {
				const go = () =>
					call("royce_etims.etims_sync.purchase.create_purchase_invoice", __("Creating the invoice...")).then(
						(pi) => pi && frappe.set_route("Form", "Purchase Invoice", pi)
					);
				frm.is_dirty() ? frm.save().then(go) : go();
			}).addClass("btn-primary");
			frm.add_custom_button(__("Reject with KRA"), () =>
				frappe.confirm(__("Tell KRA this isn't your purchase? This can't be undone."), () =>
					call("royce_etims.etims_sync.purchase.reject", __("Rejecting with KRA eTIMS...")).then(
						(m) => m && frappe.show_alert({ message: m, indicator: "green" })
					)
				)
			);
		}
		if (frm.doc.status === "Failed" && frm.doc.purchase_invoice) {
			frm.add_custom_button(__("Confirm with KRA"), () =>
				call("royce_etims.etims_sync.purchase.confirm_now", __("Confirming with KRA eTIMS...")).then(
					(m) => m && frappe.show_alert({ message: m, indicator: "green" })
				)
			).addClass("btn-primary");
		}
		if (frm.doc.status === "New") {
			frm.dashboard.set_headline(
				__("Pick your Item on every line. Royce ERP remembers it for this supplier's next invoice.")
			);
		}
	},
});
