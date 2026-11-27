// Copyright (c) 2026, Royce Technologies LTD and contributors
// For license information, please see license.txt

// The eTIMS User Guide: app-owned HTML and screenshots (public/guide/), shipped
// and versioned with royce_etims, so every eTIMS site gets the same guide.
frappe.pages["etims-user-guide"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("eTIMS User Guide"),
		single_column: true,
	});
	page.set_secondary_action(__("Open eTIMS Settings"), () => frappe.set_route("List", "eTIMS Settings"));
	const $body = $('<div class="etims-user-guide">').appendTo(page.main);
	$body.html(`<p class="text-muted">${__("Loading...")}</p>`);

	fetch(`/assets/royce_etims/guide/etims_user_guide.html?v=${frappe.boot.versions?.royce_etims || ""}`)
		.then((r) => {
			if (!r.ok) throw new Error(r.status);
			return r.text();
		})
		.then((html) => {
			$body.html(html);
			// In-page links scroll; the desk router would treat "#..." as a route.
			$body.on("click", 'a[href^="#"]', (e) => {
				e.preventDefault();
				const target = $body.find(e.currentTarget.getAttribute("href"))[0];
				target && target.scrollIntoView({ behavior: "smooth", block: "start" });
			});
		})
		.catch(() => $body.html(`<p>${__("The guide couldn't be loaded. Refresh the page or contact support.")}</p>`));
};
