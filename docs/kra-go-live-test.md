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

## How KRA counts stock for its sale check (found 2026-10-29)

KRA has no call that returns a stock balance (`itemInfo` has no quantity; `selectStockMoveLists`
only lists stock sent to us by others). The sale check's rejection names it, so a sale for
1,000,000 units reads the balance without signing anything (counter unchanged). Read on
golive.localhost after the walk-through and the user's purchase test:

| Item | ERPNext | KRA | Movements sent |
|---|---|---|---|
| Bar Soap 1kg | 47 | 47 | opening +50 (06), signed sale 4 + stock-out 4 (11), signed credit note 1 + stock-in 1 (03) |
| Maize Flour 2kg | 75 | 75 | opening +80 (06), signed sale 5 + stock-out 5 (11) |
| Soko maize mean | 1 | 0 | opening +1 (06), signed sale 1 with no stock-out, purchase receipt +1 (02), delivery note stock-out 1 (11) |

The only reading that fits all three, plus "0 remaining" before the delivery note: **KRA's sellable
balance = adjustments (type 06) − signed sales + signed credit notes.** Signing a sale deducts it;
our stock-outs (11) and returns (03) don't change it again (no double count), and a purchase
stock-in (02) doesn't add to it. Stock bought must presumably reach KRA through its purchase flow
(`sendPurchaseTransactionInfo`) to become sellable — so purchases are required for go-live.
Not yet confirmed by KRA; next check: a Material Receipt (06) for Soko should make it 1.

## Purchases — what KRA does (found 2026-10-29)

**`getPurchaseTransactionInfo`** returns `saleList`: every signed sale another taxpayer made with
our PIN as `custTin`. Per sale: `spplrTin`, `spplrNm`, `spplrBhfId`, `spplrInvcNo`, `spplrSdcId`,
`spplrMrcNo`, `rcptTyCd`, `pmtTyCd`, `salesDt`, band totals, and `itemList` with the **supplier's**
`itemCd`/`itemClsCd`/`itemNm`, units, `qty`, `prc`, `taxTyCd`, amounts.
- Our PIN (P051909825V) sees the test PIN's invoices 6, 8, 9 — all sales made to it. The credit
  note (invoice 7) is **not** listed; only `rcptTyCd "S"` came back.
- The test PIN sees sales **from our PIN's branch 02, invoices 6-10, "Completed by Automated User",
  2026-09-23 13:52** — KRA's certification harness signed invoices on our branch 02. That is why
  branch 02 says "Invoice number already exists" for 1 while its sequence check expects 1. Send
  this to KRA support.

**`sendPurchaseTransactionInfo`** confirms one of those purchases. Accepted on the test PIN for
supplier invoice 6 as purchase `invcNo` 1 (own counter, KRA's `lastPchsInvcNo`):
- `regTyCd "A"` (from KRA's list), `pchsTyCd "N"`, `rcptTyCd "P"`, `pchsSttsCd "02"`,
  `spplrTin`/`spplrBhfId`/`spplrNm`/`spplrInvcNo` from the list.
- Each line carries **our** `itemCd`/`itemClsCd`/`itemNm` plus the supplier's as
  `spplrItemCd`/`spplrItemClsCd`/`spplrItemNm` — the mapping supplier item → our item is ours to make.
- Amounts are **recomputed** KRA's way from `qty` × `prc`, like sales: KRA's own list had
  `splyAmt` 8308 and `taxblAmt` 8308 for a 9637.24 line and refused both ("Expected: 9637.24",
  "Expected: 8307.97"). Line `taxblAmt`/`taxAmt` = `kra_split(qty × prc)`, totals summed and rounded.
- **Effect: the confirmed quantities became sellable** (Soko 1 → 2, Maize Flour 75 → 76). A Purchase
  Receipt's stock-in (type 02) does not do this. So: stock bought from an eTIMS supplier is sellable
  at KRA only after the purchase is confirmed.

Open: suppliers not on eTIMS (`regTyCd "M"`, as in KRA's sample with `spplrTin` P000000000D);
rejecting a purchase (`pchsSttsCd` other codes); supplier credit notes; how the purchase list
pages (`lastReqDt`).

## Purchases feature — PENDING (parked by the founder 2026-10-29)

Proposed design, not started:
1. **eTIMS Purchase inbox** — scheduled + "Fetch from KRA" pull of `getPurchaseTransactionInfo` per
   branch; status New → Matched → Confirmed / Rejected.
2. **Supplier** found by PIN (Tax ID) or created from KRA's name + PIN.
3. **Item matching** remembered per supplier + supplier itemCd → our Item; one-click "register as
   new item".
4. **Create Purchase Invoice** (draft) from the inbox with KRA's quantities, prices, VAT.
5. **Confirm on submit** via `sendPurchaseTransactionInfo` in a background job with retries; own
   purchase counter on eTIMS Branch (resync like invcNo); status + KRA purchase number on the PI.
6. Guard rails: amounts must match KRA's record; reject a purchase that isn't ours; Compliance
   Status lists unconfirmed purchases.
7. Later: non-eTIMS suppliers (`regTyCd "M"`), supplier credit notes, imports.

Open decision: confirm on **Purchase Invoice** (recommended) or on **Purchase Receipt**.
Until built, stock bought on a Purchase Receipt/Invoice isn't sellable at KRA; workaround is a
Material Receipt (type 06), which misstates purchases as adjustments — sandbox only.

## Item codes: two rules found 2026-10-29

- **One sequence per PIN.** With KE2NTBA…0000006 registered, `KE2NTKG0000001` was refused
  ("Expected sequence ending with ********7"); `KE2NTKG0000007` was accepted. The code used to
  restart at 1 for every new prefix, so the first item with a new unit or packaging always failed.
- **Quantity unit must be 2 characters.** Every form tried for U (pieces) and LTR (litres) was
  refused with "The ItemCd isn't made up of correct QtyUnitCd": `KE2NTU…`, `KE2NTXU…` (the shape
  of KRA's own harness items), `KE2NTLTR…`, `KE2NTLT…`, 7 and 8 digit tails. KG and NO were
  accepted. Sync to eTIMS now refuses a non-2-letter unit with a plain message, and Nos maps to
  NO (Number). **Ask KRA how litres, grams, metres and tonnes are coded** — fuel stations need
  litres.

## Item form (2026-10-29)

KRA fields moved to their own **KRA eTIMS** tab (the old section after Item Group swallowed
ERPNext's Default Unit of Measure, Maintain Stock…). Plain labels; the KRA Item Code table is
read-only; the six code fields are hidden (the dropdowns show them); category, type, origin,
packaging and unit lock once registered. New items fill empty fields: Kenya, Finished Product
(stock) / Service (non-stock), Net packaging, quantity unit from the UOM's new *KRA Quantity
Unit*, category from the Item Group's new *KRA Product Category* (nearest parent group).
