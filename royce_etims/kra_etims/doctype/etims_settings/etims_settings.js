// Copyright (c) 2026, Royce Technologies LTD and contributors
// For license information, please see license.txt

frappe.ui.form.on("eTIMS Settings", {
	refresh(frm) {
		if (frm.is_new() || !frm.doc.default_branch) return;

		if (frm.doc.status !== "Active") {
			frm.add_custom_button(__("Activate eTIMS"), () => {
				frappe.confirm(
					__(
						"From now on every sale of {0} is signed with KRA eTIMS ({1}), and the site's rounding is set to Commercial Rounding to match KRA. Activate?",
						[frm.doc.company, frm.doc.environment]
					),
					() =>
						frm
							.call({ doc: frm.doc, method: "activate", freeze: true })
							.then(() => frm.reload_doc())
				);
			});
		} else {
			frm.add_custom_button(__("Register All Items with KRA"), () => {
				frappe.confirm(
					__(
						"Registers every item {0} sells that KRA doesn't have yet, with the stock it holds now, in the background. Empty KRA fields are filled from the Item Defaults below. Continue?",
						[frm.doc.company]
					),
					() =>
						frappe
							.call({
								method: "royce_etims.etims_sync.bulk_items.register_all_items",
								args: { company: frm.doc.company },
								freeze: true,
							})
							.then((r) => frappe.msgprint(r.message))
				);
			});
			frm.add_custom_button(__("Disable eTIMS"), () => {
				frappe.confirm(
					__("Sales of {0} will no longer be sent to KRA eTIMS. Disable?", [frm.doc.company]),
					() =>
						frm
							.call({ doc: frm.doc, method: "disable", freeze: true })
							.then(() => frm.reload_doc())
				);
			});
		}

		frm.add_custom_button(__("Test Connection"), () => {
			frm.call({
				doc: frm.doc,
				method: "test_connection",
				freeze: true,
				freeze_message: __("Contacting KRA eTIMS..."),
			}).then((r) => {
				const info = r.message || {};
				frappe.msgprint({
					title: __("Connected"),
					indicator: "green",
					message: __("KRA eTIMS ({0}) recognises branch {1} as {2}.", [
						info.environment,
						info.branch,
						frappe.utils.escape_html(info.taxpayer_name || __("an unnamed taxpayer")),
					]),
				});
			});
		});

		frm.add_custom_button(__("Sync KRA Reference Data"), () => {
			frappe
				.call({
					method: "royce_etims.etims_sync.reference_data.sync_reference_data",
					args: { company: frm.doc.company },
					freeze: true,
					freeze_message: __("Fetching code lists and item classifications from KRA..."),
				})
				.then((r) => {
					const rows = Object.entries(r.message || {}).map(
						([doctype, c]) =>
							`<tr><td>${__(doctype)}</td><td>${c.created}</td><td>${
								c.updated
							}</td></tr>`
					);
					frappe.msgprint({
						title: __("KRA Reference Data Synced"),
						indicator: "green",
						message: `<table class="table table-bordered"><thead><tr><th>${__(
							"List"
						)}</th><th>${__("New")}</th><th>${__(
							"Updated"
						)}</th></tr></thead><tbody>${rows.join("")}</tbody></table>`,
					});
				});
		});
	},
});
