# Copyright (c) 2026, Royce Technologies LTD and contributors
# For license information, please see license.txt

"""Rehearsal for KRA's Go-Live test (Automated App Testing): all 23 cases in
the order a client goes through them, with pass/fail and timing per case.

Each case calls exactly what the desk does: the method behind the button
(Register Device, Sync KRA Reference Data, Sync to eTIMS, Send to KRA, Send to
KRA eTIMS on a BOM, Approve, Create Purchase Invoice, the KRA Lookup report),
or, where the desk just saves or submits, the save/submit itself - signing,
stock movements and purchase confirmation then run in the background worker
exactly as for a user, and the rehearsal waits for them. So a worker must be
running (bench worker).

KRA's clock can't be paused (23 cases inside one hour), so run this on the
test PIN first; then start KRA's session and run it again.

    bench --site <site> execute royce_etims.kra_etims.go_live.rehearse \
        --kwargs "{'company': 'KRA Go-Live Test'}"

It creates real records on the site and at KRA: one new item, a material
receipt, a sales invoice and a credit note, a BOM, and (if KRA lists one) a
confirmed purchase. Use a test site, never a client's.

See docs/kra-go-live-test.md for the case list and what each one taught us.
"""

import time
from datetime import datetime

import frappe
from frappe.utils import add_days, cint, now_datetime, nowdate

from royce_etims.etims_sync import branch_info, composition, imports, purchase
from royce_etims.etims_sync.item import sync_item
from royce_etims.etims_sync.reference_data import sync_reference_data
from royce_etims.utils.api_client import get_settings
from royce_etims.utils.api_client import request as etims_request
from royce_etims.utils.id_mapping import get_etims_id
from royce_etims.utils.lookups import kra_lookup

SALES_TEMPLATE = "KE - Standard VAT 16% Inclusive - Sales"
STANDARD_ITEM_TAX = "KE Standard 16%"


class Rehearsal:
	def __init__(self, company, customer_name=None):
		self.company = company
		self.settings = get_settings(company)
		self.branch = frappe.get_doc("eTIMS Branch", self.settings.default_branch)
		# Named, never guessed: KRA (Seth, 22 Nov 2026) allows only the session's
		# test PINs at the sandbox, never a real taxpayer's PIN.
		self.customer = customer_name
		self.stamp = now_datetime().strftime("%m%d%H%M%S")
		self.results = []
		self.item = None
		self.part = None
		self.invoice = None

	# --- running ---------------------------------------------------------

	def case(self, number, title, fn):
		started = time.monotonic()
		since = datetime.now()
		try:
			detail = fn() or ""
			outcome = "PASS"
		except Exception as e:
			_rollback_keeping_logs(since)
			detail = frappe.utils.strip_html(str(e))[:300]
			outcome = "FAIL"
		self.results.append((number, title, outcome, str(detail), time.monotonic() - started))
		print(f"{number:>2}  {outcome}  {title:<34} {time.monotonic() - started:5.1f}s  {detail}", flush=True)

	def run(self):
		print(f"KRA Go-Live rehearsal - {self.company}, PIN {self.settings.tin}, branch {self.branch.bhf_id}")
		started = time.monotonic()
		self.case(1, "OSCU initialization", self.initialize)
		self.case(23, "Look up tax payer info", self.taxpayer)
		self.case(2, "Look up code list / 3 item classes", self.reference_data)
		self.case(4, "Look up branch list", lambda: self.lookup("Branches"))
		self.case(5, "Look up notices", lambda: self.lookup("Notices"))
		self.case(6, "Save customer branch", self.save_customer)
		self.case(22, "Look up customer list", lambda: self.lookup("Customers"))
		self.case(7, "Save branch user account", lambda: self.branch_record("eTIMS Branch User"))
		self.case(8, "Save branch insurances", lambda: self.branch_record("eTIMS Branch Insurance"))
		self.case(9, "Look up product list", lambda: self.lookup("Items"))
		self.case(10, "Save item", self.save_item)
		self.case(17, "Save stock in/out + stock master (19)", self.receive_stock)
		self.case(11, "Save item composition", self.save_composition)
		self.case(12, "Look up imported items", self.fetch_imports)
		self.case(13, "Update imported items", self.approve_import)
		self.case(18, "Look up stock movement", lambda: self.lookup("Stock Received from Others"))
		self.case(14, "Save sales transaction", self.sell)
		self.case(14, "Save sales transaction (credit note)", self.credit_note)
		self.case(20, "Look up invoice details", self.invoice_details)
		self.case(21, "Look up transaction sales list", lambda: self.lookup("Sales"))
		self.case(15, "Look up purchases-sales list", self.fetch_purchases)
		self.case(16, "Save purchases information", self.confirm_purchase)
		total = time.monotonic() - started
		failed = [r for r in self.results if r[2] == "FAIL"]
		print(f"\n{len(self.results) - len(failed)}/{len(self.results)} passed in {total / 60:.1f} min")
		frappe.db.commit()  # nosemgrep
		return {
			"passed": len(self.results) - len(failed),
			"failed": [r[:2] for r in failed],
			"minutes": total / 60,
		}

	# --- cases -----------------------------------------------------------

	def initialize(self):
		"""eTIMS Branch > Register Device for a device not yet registered. An
		active device has no button (KRA's initialize is sent as the button
		would): KRA answers "This device is installed" or re-issues its keys."""
		if self.branch.device_status not in ("Registered", "Active"):
			result = self.branch.register_device()
			self.branch.reload()
			frappe.db.commit()  # nosemgrep
			return result["message"]
		try:
			data = etims_request(
				self.company,
				"initialize",
				payload={
					"tin": self.settings.tin,
					"bhfId": self.branch.bhf_id,
					"dvcSrlNo": self.branch.dvc_srl_no,
				},
			)
		except Exception as e:
			# KRA's answer for an active device: "This device is installed".
			if "installed" in str(e).lower() or "already" in str(e).lower():
				return f"device already active - KRA: {str(e).split(':')[-1].strip()[:60]}"
			raise
		info = (((data or {}).get("responseBody") or data or {}).get("data") or {}).get("info") or {}
		if info.get("cmcKey"):
			self.branch.db_set("cmc_key", info["cmcKey"], update_modified=False)
			frappe.db.commit()  # nosemgrep
			return "new cmcKey stored"
		return "initialized"

	def taxpayer(self):
		return frappe.get_doc("eTIMS Settings", self.company).test_connection().get("taxpayer_name")

	def reference_data(self):
		counts = sync_reference_data(self.company)
		return ", ".join(
			f"{dt.replace('eTIMS ', '')} {c['created'] + c['updated']}" for dt, c in counts.items()
		)

	def lookup(self, name):
		return f"{len(kra_lookup(self.company, name))} rows"

	def save_customer(self):
		if not self.customer:
			raise frappe.ValidationError(
				"Name the customer: a Customer whose Tax ID is a KRA test PIN (not a real taxpayer's)."
			)
		if frappe.db.get_value("Customer", self.customer, "tax_id") == self.settings.tin:
			raise frappe.ValidationError("The customer's PIN is the seller's own PIN - use the other test PIN.")
		# Saving a Customer queues its registration (Customer on_update); the
		# rehearsal queues the same job directly, since nothing about it changed.
		frappe.db.set_value("Customer", self.customer, "royce_etims_customer_status", "Not Synced")
		frappe.enqueue(
			"royce_etims.etims_sync.customer.sync_customer",
			queue="short",
			name=self.customer,
			job_id=f"royce_etims_customer::{self.customer}",
			deduplicate=True,
			enqueue_after_commit=True,
		)
		frappe.db.commit()  # nosemgrep
		_wait(
			lambda: frappe.db.get_value("Customer", self.customer, "royce_etims_customer_status")
			!= "Not Synced"
		)
		status, error = frappe.db.get_value(
			"Customer", self.customer, ["royce_etims_customer_status", "royce_etims_customer_error"]
		)
		if status != "Synced":
			raise frappe.ValidationError(error)
		return self.customer

	def branch_record(self, doctype):
		name = frappe.db.get_value(doctype, {"branch": self.branch.name})
		if not name:
			values = (
				{"user": frappe.session.user}
				if doctype == "eTIMS Branch User"
				else {"insurer_code": "BRITAM", "insurer_name": "Britam Insurance", "rate": 10}
			)
			name = frappe.get_doc({"doctype": doctype, "branch": self.branch.name, **values}).insert().name
			frappe.db.commit()  # nosemgrep
		branch_info.send_now(doctype, name)  # the "Send to KRA" button
		return name

	def save_item(self):
		template = frappe.db.get_value(
			"Item Tax Template", {"title": STANDARD_ITEM_TAX, "company": self.company}, "name"
		)
		item = frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": f"KRA-TEST-{self.stamp}",
				"item_name": f"KRA Test Item {self.stamp}",
				"item_group": frappe.db.get_value("Item Group", {"is_group": 0}, "name"),
				"stock_uom": "Nos",
				"is_stock_item": 1,
				"standard_rate": 116,
				# A category KRA already accepted on this site; the item's group may have none.
				"royce_etims_item_classification": frappe.db.get_value(
					"Item",
					{"royce_etims_item_classification": ["is", "set"]},
					"royce_etims_item_classification",
				),
				"taxes": [{"item_tax_template": template}] if template else [],
			}
		).insert()
		frappe.db.commit()  # nosemgrep
		result = sync_item(item.name, self.company)  # the "Sync to eTIMS" button
		self.item = item.name
		# A second item to be the composition's component (case 11): KRA wants a
		# component it holds stock of, and a new test PIN holds none yet.
		part = frappe.copy_doc(item)
		part.item_code = part.item_name = f"KRA-PART-{self.stamp}"
		part.set("royce_etims_id_mapping", [])
		part.insert()
		frappe.db.commit()  # nosemgrep
		sync_item(part.name, self.company)
		self.part = part.name
		return result["message"]

	def _warehouse(self):
		return frappe.db.get_value(
			"Warehouse", {"company": self.company, "is_group": 0, "warehouse_name": "Stores"}, "name"
		) or frappe.db.get_value("Warehouse", {"company": self.company, "is_group": 0}, "name")

	def receive_stock(self):
		self._need_item()
		entry = frappe.get_doc(
			{
				"doctype": "Stock Entry",
				"stock_entry_type": "Material Receipt",
				"company": self.company,
				"items": [
					{"item_code": code, "qty": 20, "basic_rate": 80, "t_warehouse": self._warehouse()}
					for code in (self.item, self.part)
					if code
				],
			}
		)
		entry.insert()
		entry.submit()
		frappe.db.commit()  # nosemgrep
		return self._send_stock(entry.doctype, entry.name)

	def _send_stock(self, voucher_type, voucher_no):
		"""Submitting queued the movements (stock on_submit); wait for the worker."""

		def rows():
			return frappe.get_all(
				"eTIMS Stock Movement",
				filters={"voucher_type": voucher_type, "voucher_no": voucher_no},
				fields=["status", "sar_no", "error"],
			)

		_wait(lambda: rows() and all(r.status not in ("Pending",) for r in rows()))
		rows = rows()
		if not rows or any(r.status != "Sent" for r in rows):
			raise frappe.ValidationError(str(rows))
		return "sarNo " + ", ".join(str(r.sar_no) for r in rows)

	def save_composition(self):
		self._need_item()
		components = [self.part] if self.part else self._components_with_kra_stock()
		bom = frappe.get_doc(
			{
				"doctype": "BOM",
				"item": self.item,
				"company": self.company,
				"quantity": 1,
				"is_default": 1,
				"items": [{"item_code": code, "qty": 1, "rate": 10} for code in components],
			}
		)
		bom.insert()
		bom.submit()
		frappe.db.commit()  # nosemgrep
		# Submitting a default BOM queues the send; the button sends at once.
		composition.send_now(bom.name)  # the "Send to KRA eTIMS" button
		return f"{bom.name}: {', '.join(components)}"

	def _components_with_kra_stock(self):
		"""Two registered items KRA holds stock of - KRA refuses a component
		that isn't in its stock master."""
		codes = frappe.db.sql(
			"""
			SELECT DISTINCT i.item_code FROM `tabeTIMS Stock Movement Item` i
			JOIN `tabeTIMS Stock Movement` mv ON mv.name = i.parent
			WHERE mv.company = %s AND mv.status = 'Sent' AND mv.direction = 'In' AND i.item_code != %s
			ORDER BY mv.creation DESC LIMIT 2
			""",
			(self.company, self.item),
			pluck=True,
		)
		if not codes:
			raise frappe.ValidationError("No item with stock at KRA to use as a component.")
		return codes

	def fetch_imports(self):
		imports.fetch_imported_items(self.company)
		return f"{frappe.db.count('eTIMS Imported Item', {'company': self.company})} lines on file"

	def approve_import(self):
		self._need_item()
		name = frappe.db.get_value(
			"eTIMS Imported Item", {"company": self.company, "status": ["in", ("New", "Failed")]}
		) or frappe.db.get_value("eTIMS Imported Item", {"company": self.company})
		if not name:
			raise frappe.ValidationError("KRA lists no imported items for this PIN.")
		doc = frappe.get_doc("eTIMS Imported Item", name)
		doc.db_set("item", doc.item or self.item, update_modified=False)
		imports.approve(name, doc.item or self.item)
		return f"{name} ({doc.task_code})"

	def _invoice(self, **extra):
		template = frappe.db.get_value(
			"Sales Taxes and Charges Template", {"title": SALES_TEMPLATE, "company": self.company}, "name"
		)
		si = frappe.get_doc(
			{
				"doctype": "Sales Invoice",
				"company": self.company,
				"customer": self.customer,
				"posting_date": nowdate(),
				"due_date": add_days(nowdate(), 30),
				"update_stock": 1,
				"set_warehouse": self._warehouse(),
				"taxes_and_charges": template,
				"items": [{"item_code": self.item, "qty": 2, "rate": 116}],
				**extra,
			}
		)
		si.set_missing_values()
		si.set_taxes()
		return si

	def _sign(self, si):
		si.insert()
		si.submit()
		frappe.db.commit()  # nosemgrep
		# Submitting queued the signing (receipt on_submit); wait for the worker.
		_wait(lambda: frappe.db.get_value(si.doctype, si.name, "royce_etims_status") in ("Sent", "Failed"))
		status, number, error = frappe.db.get_value(
			si.doctype, si.name, ["royce_etims_status", "royce_etims_invoice_number", "royce_etims_error"]
		)
		if status != "Sent":
			raise frappe.ValidationError(error)
		stock_detail = self._send_stock(si.doctype, si.name)
		return number, stock_detail

	def sell(self):
		self._need_item()
		si = self._invoice()
		number, stock_detail = self._sign(si)
		self.invoice = (si.name, number)
		return f"{si.name} = KRA invoice {number}; {stock_detail}"

	def credit_note(self):
		if not self.invoice:
			raise frappe.ValidationError("No signed invoice to credit.")
		from erpnext.accounts.doctype.sales_invoice.sales_invoice import make_sales_return

		note = make_sales_return(self.invoice[0])
		note.items[0].qty = -1
		note.royce_etims_refund_reason = "03"
		note.calculate_taxes_and_totals()
		number, stock_detail = self._sign(note)
		return f"{note.name} = KRA invoice {number} against {self.invoice[1]}; {stock_detail}"

	def invoice_details(self):
		if not self.invoice:
			raise frappe.ValidationError("No signed invoice to look up.")
		rows = kra_lookup(self.company, "Invoice Details", invoice_no=self.invoice[1])
		return f"KRA invoice {self.invoice[1]}: {len(rows)} lines"

	def fetch_purchases(self):
		new = purchase.fetch_purchases(self.company)
		waiting = frappe.db.count(
			"eTIMS Purchase", {"company": self.company, "status": ["in", ("New", "Ready")]}
		)
		return f"{new} new, {waiting} waiting"

	def confirm_purchase(self):
		name = frappe.db.get_value(
			"eTIMS Purchase",
			{"company": self.company, "status": ["in", ("New", "Ready")], "receipt_type": "S"},
			order_by="creation asc",
		)
		if not name:
			raise frappe.ValidationError("No supplier invoice waiting at KRA for this PIN.")
		doc = frappe.get_doc("eTIMS Purchase", name)
		for row in doc.items:
			row.item = self.item  # registered on this PIN; older mappings may belong to another PIN
		doc.save()
		pi = frappe.get_doc("Purchase Invoice", purchase.create_purchase_invoice(name))
		pi.submit()
		frappe.db.commit()  # nosemgrep
		# Submitting queued the confirmation (purchase on_submit); wait for the worker.
		_wait(lambda: frappe.db.get_value("eTIMS Purchase", name, "status") in ("Confirmed", "Failed"))
		doc.reload()
		if doc.status != "Confirmed":
			raise frappe.ValidationError(doc.error)
		return f"supplier invoice {doc.supplier_invoice_no} -> {pi.name}, KRA purchase {cint(doc.kra_purchase_no)}"

	def _need_item(self):
		if not self.item:
			raise frappe.ValidationError("Case 10 (save item) didn't pass.")


WAIT_SECONDS = 60


def _wait(done, timeout=WAIT_SECONDS):
	"""Poll until `done()` is true, reading fresh data each time. Raises if the
	background worker hasn't got there in `timeout` seconds."""
	deadline = time.monotonic() + timeout
	while time.monotonic() < deadline:
		frappe.db.commit()  # nosemgrep - end the snapshot so the worker's writes are visible
		if done():
			return
		time.sleep(1)
	raise frappe.ValidationError(
		f"Nothing from the background worker after {timeout}s - is `bench worker` running?"
	)


def _rollback_keeping_logs(since):
	"""Undo a failed case, but keep the eTIMS Log rows its KRA calls wrote: they
	are the evidence (KRA's responseRefID) for support. Found 2026-11-22, when a
	plain rollback lost the log of every failed call in the Go-Live session."""
	logs = frappe.get_all("eTIMS Log", filters={"creation": [">=", since]}, fields=["*"])
	frappe.db.rollback()
	for row in logs:
		row = {k: v for k, v in row.items() if k not in ("name", "idx", "docstatus")}
		frappe.get_doc({**row, "doctype": "eTIMS Log"}).insert(ignore_permissions=True)
	frappe.db.commit()  # nosemgrep


def rehearse(company, customer=None):
	frappe.only_for("System Manager")
	if get_settings(company).environment != "Sandbox":
		frappe.throw("The rehearsal creates test records at KRA - run it on a Sandbox company only.")
	return Rehearsal(company, customer).run()
