// Copyright (c) 2026, Royce Technologies LTD and contributors
// For license information, please see license.txt

frappe.ui.form.on("eTIMS Settings", {
	refresh(frm) {
		if (frm.is_new() || !frm.doc.default_branch) return;

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
