// Copyright (c) 2026, Royce Technologies LTD and contributors
// For license information, please see license.txt

// KRA signing at the till (hooks.py page_js). A sale is signed in the
// background a few seconds after payment, but the receipt handed over must
// carry KRA's signature and QR. So the order summary shows where signing
// stands, and printing waits for it - up to WAIT_SECONDS, then prints with
// "KRA signature pending" so the queue never stops at the till.
frappe.provide("royce_etims.pos");

royce_etims.pos.WAIT_SECONDS = 15;

royce_etims.pos.status = (doc) =>
	frappe
		.call({
			method: "royce_etims.etims_sync.receipt.signing_status",
			args: { doctype: doc.doctype, name: doc.name },
		})
		.then((r) => r.message || {});

royce_etims.pos.render = (summary, state) => {
	let $pill = summary.$summary_container.find(".royce-kra-status");
	if (!$pill.length) {
		$pill = $('<div class="royce-kra-status" style="margin: var(--margin-sm) 0"></div>');
		summary.$summary_btns.before($pill);
	}
	if (!state.applies) {
		$pill.empty();
		return;
	}
	const pills = {
		Sent: ["green", __("Signed by KRA: CU invoice no. {0}", [state.invoice_number])],
		Pending: ["orange", __("Signing with KRA...")],
		Failed: ["red", __("Not signed by KRA")],
	};
	const [color, label] = pills[state.status] || ["gray", __(state.status)];
	$pill.html(
		`<span class="indicator-pill ${color}"><span>${label}</span></span>` +
			(state.error
				? `<div class="text-muted small" style="margin-top: var(--margin-xs)">${frappe.utils.escape_html(
						state.error,
					)}</div>`
				: ""),
	);
};

// Poll until KRA has decided or the wait runs out; resolves the last state.
royce_etims.pos.wait = async (summary, doc) => {
	let state = await royce_etims.pos.status(doc);
	for (
		let s = 0;
		state.applies && state.status === "Pending" && s < royce_etims.pos.WAIT_SECONDS;
		s++
	) {
		royce_etims.pos.render(summary, state);
		await new Promise((resolve) => setTimeout(resolve, 1000));
		state = await royce_etims.pos.status(doc);
	}
	royce_etims.pos.render(summary, state);
	return state;
};

royce_etims.pos.patch = () => {
	const Summary = erpnext.PointOfSale.PastOrderSummary.prototype;
	if (Summary.royce_etims_patched) return;
	Summary.royce_etims_patched = true;

	const load_summary_of = Summary.load_summary_of;
	Summary.load_summary_of = function (doc, after_submission = false) {
		this.royce_etims_state = null;
		this.$summary_container.find(".royce-kra-status").empty();
		load_summary_of.call(this, doc, after_submission);
		if (doc.docstatus !== 1) return;
		royce_etims.pos.wait(this, doc).then((state) => {
			this.royce_etims_state = state;
			if (state.applies && state.status === "Failed") {
				frappe.show_alert(
					{ message: __("KRA did not sign {0}", [doc.name]), indicator: "red" },
					10,
				);
			}
		});
	};

	const print_receipt = Summary.print_receipt;
	Summary.print_receipt = async function () {
		const doc = this.doc;
		if (!doc || doc.docstatus !== 1) return print_receipt.call(this);

		frappe.dom.freeze(__("Signing with KRA..."));
		let state;
		try {
			state = await royce_etims.pos.wait(this, doc);
		} finally {
			frappe.dom.unfreeze();
		}
		if (state.applies && state.status !== "Sent") {
			frappe.show_alert(
				{
					message:
						state.status === "Failed"
							? __("Printed without KRA's signature: KRA did not sign this sale.")
							: __(
									"Printed with 'KRA signature pending'. Print again once it's signed.",
								),
					indicator: "orange",
				},
				10,
			);
		}
		return print_receipt.call(this);
	};
};

frappe.require("point-of-sale.bundle.js", royce_etims.pos.patch);
