# Copyright (c) 2026, Royce Technologies LTD and contributors
# For license information, please see license.txt

"""Rehearsal for KRA's Go-Live test (Automated App Testing): all 23 cases in
the order a client goes through them, through the same code the desk buttons
and hooks use, with pass/fail and timing per case.

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

import frappe
from frappe.utils import add_days, cint, now_datetime, nowdate

from royce_etims.etims_sync import branch_info, composition, customer, imports, purchase, receipt, stock
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
		self.customer = customer_name or frappe.db.get_value(
			"Customer", {"tax_id": ["like", "P%"], "disabled": 0}, "name"
		)
		self.stamp = now_datetime().strftime("%m%d%H%M%S")
		self.results = []
		self.item = None
		self.invoice = None

	# --- running ---------------------------------------------------------

	def case(self, number, title, fn):
		started = time.monotonic()
		try:
			detail = fn() or ""
			outcome = "PASS"
		except Exception as e:
			frappe.db.rollback()
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
		"""An active device: KRA answers "already installed" or re-issues its
		keys. Either counts as KRA having answered; a new cmcKey is stored."""
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
			raise frappe.ValidationError("No customer with a KRA PIN - add one first.")
		customer.sync_customer(self.customer)
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
		branch_info.send(doctype, name, raise_on_error=True)
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
		result = sync_item(item.name, self.company)
		self.item = item.name
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
					{"item_code": self.item, "qty": 20, "basic_rate": 80, "t_warehouse": self._warehouse()}
				],
			}
		)
		entry.insert()
		entry.submit()
		frappe.db.commit()  # nosemgrep
		return self._send_stock(entry.doctype, entry.name)

	def _send_stock(self, voucher_type, voucher_no):
		stock.process_branch_queue(self.branch.name)
		rows = frappe.get_all(
			"eTIMS Stock Movement",
			filters={"voucher_type": voucher_type, "voucher_no": voucher_no},
			fields=["status", "sar_no", "error"],
		)
		if not rows or any(r.status != "Sent" for r in rows):
			raise frappe.ValidationError(str(rows))
		return "sarNo " + ", ".join(str(r.sar_no) for r in rows)

	def save_composition(self):
		self._need_item()
		components = self._components_with_kra_stock()
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
		composition.send_bom(bom.name, raise_on_error=True)
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
		receipt.sync_receipt(si.doctype, si.name)
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
			row.item = row.item or self.item
		doc.save()
		pi = frappe.get_doc("Purchase Invoice", purchase.create_purchase_invoice(name))
		pi.submit()
		frappe.db.commit()  # nosemgrep
		purchase.confirm(name)
		doc.reload()
		if doc.status != "Confirmed":
			raise frappe.ValidationError(doc.error)
		return f"supplier invoice {doc.supplier_invoice_no} -> {pi.name}, KRA purchase {cint(doc.kra_purchase_no)}"

	def _need_item(self):
		if not self.item:
			raise frappe.ValidationError("Case 10 (save item) didn't pass.")


def rehearse(company, customer=None):
	frappe.only_for("System Manager")
	if get_settings(company).environment != "Sandbox":
		frappe.throw("The rehearsal creates test records at KRA - run it on a Sandbox company only.")
	return Rehearsal(company, customer).run()
