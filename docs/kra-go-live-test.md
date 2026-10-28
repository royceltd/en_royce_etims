# KRA Go-Live test (Automated App Testing) — plan

Written 2026-10-28. Source of truth for what KRA tests: the GavaConnect **Validation** screen
(developer.go.ke → My Apps → Validation Test Cases) and KRA's Postman collection
`eTIMS-OSCU-Integrator-Automated-Testing-Sandbox.json`. Confirmed API rules (rounding, field limits,
call order) stay in [architecture.md](architecture.md).

## The test

- 23 test cases, run against the **Application Test PIN `P600004665A`** (company "KRA Go-Live Test"
  on etims.localhost, eTIMS Branch "KRA Go-Live Test-00"). Integrator PIN is ours, `P051909825V`.
- All 23 must pass within **one hour** of starting. The next two hours are for uploading: item
  creation screenshot, invoice generation screenshot, invoice copy, credit note copy.
- The clock can't be paused, so every case is rehearsed on branch 00 first.
- The Validation screen still names KRA's old endpoints. The collection has the current ones; the
  table below maps them.

## Test cases → endpoints → royce_etims

| # | Test case (screen) | Endpoint we call | royce_etims today |
|---|---|---|---|
| 1 | OSCU initialization | `initialize` | ✅ eTIMS Branch → Register Device. Device on 00 is already active — see open question 1 |
| 2 | Look up list of code | `selectCodeList` | ✅ Sync KRA Reference Data |
| 3 | Look up item classification | `selectItemClass` | ✅ Sync KRA Reference Data |
| 4 | Look up branch list | `branchList` | ❌ |
| 5 | Look up notices list | `selectNoticeList` | ❌ |
| 6 | Save customer branch | `branchSendCustomerInfo` | ✅ Customer registration (RC-######## custNo) |
| 7 | Save branch user account | `branchUserAccount` | ❌ |
| 8 | Save branch insurances | `branchInsuranceInfo` | ❌ |
| 9 | Look up product list | `itemInfo` | ✅ used to pick the next item code; not shown to the user |
| 10 | Save item | `saveItem` | ✅ Item → Sync to eTIMS (KE2NTBA0000003 on 00, 2026-10-28) |
| 11 | Save item composition | `saveItemComposition` | ❌ |
| 12 | Look up imported item list | `importedItemInfo` | ❌ |
| 13 | Update imported items | `importedItemConvertedInfo` | ❌ |
| 14 | Save sales transaction | `sendSalesTransaction` | ✅ invoices (KRA invoices 4, 5 on 00). Credit note built, not yet signed live |
| 15 | Look up purchases-sales list | `getPurchaseTransactionInfo` | ❌ |
| 16 | Save purchases information | `sendPurchaseTransactionInfo` | ❌ |
| 17 | Save stock-master information | `save/stockMaster` | ✅ |
| 18 | Look up stock movement | `selectStockMoveLists` | ❌ |
| 19 | Save stock in/out | `insert/stockIO` | ✅ |
| 20 | Look up invoice details | `selectInvoiceDetail` | ❌ |
| 21 | Look up transaction sales list | `selectSalesTransactions` | ❌ |
| 22 | Look up customer list | `customerPinInfo` | ❌ |
| 23 | Look up tax payer info | `selectTaxpayerInfo` | ✅ Test Connection |

**10 built, 13 to build.** Ten of the 13 are lookups (`tin` + `bhfId` + `lastReqDt` in, a list out)
and are small. The three that need real design are purchases (16), item composition (11) and
imports (13).

## The flow, from deployment to a credit note

This is the order a new client goes through, and the order to rehearse. KRA enforces some of it
(e.g. `insert/stockIO` is refused until `selectItemClass` has been called).

| Stage | What happens in Royce ERP | Test cases |
|---|---|---|
| **0. Connect** | eTIMS Settings (PIN, sandbox/production, GavaConnect keys) → eTIMS Branch → Register Device → Test Connection | 1, 23 |
| **1. Fetch from KRA** | Sync KRA Reference Data: code lists, item classifications. Add: branch list, notices | 2, 3, 4, 5 |
| **2. Set up the branch** | Register customers. Add: branch users, branch insurers | 6, 7, 8, 22 |
| **3. Sync items** | Item → Sync to eTIMS (code from KRA's sequence). Add: composition for manufactured items (from the BOM), imported items | 9, 10, 11, 12, 13 |
| **4. Sync stock** | Opening stock / receipts / deliveries → stock in/out + stock master. Add: read back KRA's movement list | 17, 18, 19 |
| **5. Buy** | Add: fetch purchases suppliers signed to our PIN, confirm them as Purchase Invoices | 15, 16 |
| **6. Sell** | Sales/POS Invoice → signed, QR printed. Add: read the invoice and sales list back from KRA | 14, 20, 21 |
| **7. Credit note** | Return / Credit Note against the signed invoice → signed with `rcptTyCd "R"`, `orgInvcNo` | 14 |

## What to build, in order

1. **Lookups (4, 5, 15, 18, 20, 21, 22, 12).** One shared helper; each on a button or report so a
   person can see the result (also gives screenshots). Store branch list and notices.
2. **Branch users and insurers (7, 8).** Small doctypes or a child table on eTIMS Branch, sent on save.
3. **Credit note live on 00** against ACC-SINV-2026-00011 (KRA invoice 5) — code exists, never signed.
4. **Purchases (15, 16).** Sign a sale on the test PIN with `custTin` = our PIN, then read it back on
   our side, and design the Purchase Invoice confirmation from the real response.
5. **Item composition (11)** from the item's default BOM.
6. **Imports (12, 13)** — read, map to an Item, send back status.
7. **Rehearsal script** that runs all 23 in order on 00 and prints pass/fail per case, then a dry run
   timed against the one hour.

## Open questions

1. **Initialization during the test.** The device on test PIN + 00 is already active. Does
   `initialize` inside the session return "already installed", and does the screen count that as a
   pass? Could it issue a new cmcKey? Rehearse on a fresh branch id first, and store a new cmcKey if
   one comes back.
2. **Which branch.** The screen shows Branch Id 02, but on the test PIN only 00 has a device.
   Probably it just shows our own registration — confirm before starting the clock.
3. **What starts a session and what counts.** 0/23 despite real calls on 2026-10-27/28, so only calls
   inside a started session count. Unknown whether calls must come through our app (apigee_app_id
   header) — we always send it.
4. **`customerPinInfo`** takes no customer PIN in the collection, only tin/bhfId/lastReqDt — so it
   lists customers rather than validating a PIN. Check the live response.
5. **`selectNoticeList`** comment says `lastReqDt` must be within the last hour.

## Walk-through on a fresh site, 2026-10-28

New site `golive.localhost` (frappe, erpnext, kenyan_accountant, royce_etims), company "KRA Go-Live
Test", test PIN `P600004665A`, branch 00. KRA's side wasn't fresh (items 1-3, invoices 1-5, stock
from etims.localhost), which is also what a client moving from another system looks like.

| Stage | Result |
|---|---|
| 0. Setup wizard → Kenyan Accountant setup + activate → eTIMS Settings + Branch → Test Connection | ✅ Device key copied from etims.localhost (no re-initialize on an active device) |
| 1. Sync KRA Reference Data | ✅ 252 countries, 43 qty units, 52 packaging units, 13 refund reasons, 5 bands, 26 item classes (the sandbox's whole list) |
| 3. Two items (16% soap, exempt maize) → Sync to eTIMS | ✅ KE2NTBA0000004, …0005 — codes continued KRA's sequence |
| 4. Opening stock (Stock Reconciliation 50 + 80) | ❌→✅ **Bug fixed**: nothing was sent (see below). Then sarNo resynced 1 → 4, stockIO + stockMaster accepted |
| 2. Customer with PIN P051909825V | ✅ RC-00000001 |
| 6. Sales Invoice, both items, update stock | ❌→✅ **Bug fixed**: refused for float totals (see below). Then invcNo resynced 1 → 6, signed as KRA invoice 6; stock out sarNo 5 |
| 7. Credit note, 1 soap, reason 03 Damaged | ✅ **First live credit note**: KRA invoice 7, `rcptTyCd R`, `orgInvcNo 6`; return stock in sarNo 6 (type 03) |
| Cancel the signed invoice | ✅ Refused, points to a credit note |

Bugs found and fixed:
- **Stock Reconciliation never reached KRA.** ERPNext's ledger rows for a reconciliation carry the new
  balance with `actual_qty` 0, so the change looked like nothing. Opening stock is the first thing
  every client enters. Now taken from the reconciliation's own rows (qty minus current qty).
- **Invoices with two VAT bands were refused**: `totTaxblAmt 1762.0700000000002` ("More than 2
  decimal places"). Every earlier test invoice had one band. Band and invoice totals are now
  rounded to the cent.

Friction for the client guide / onboarding:
- Kenya Accounting Settings doesn't exist after the setup wizard; it has to be created before setup.
- eTIMS Branch needs an ERPNext Branch first.
- Each item needs five eTIMS fields (classification, type, origin, packaging, quantity unit).
- An invoice that fails a local check leaves no eTIMS Log; the reason is only in eTIMS Error on the
  invoice.
