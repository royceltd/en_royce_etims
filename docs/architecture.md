# Royce eTIMS — Architecture Reference

Status: **in progress**. Foundation (Settings/Branch/Log), Item sync, and receipt sync (POS
Invoice + gated Sales Invoice) are implemented. Captures the decisions made so far so we don't
re-litigate them. Update this file as decisions change — it's meant to stay current, not to be a
one-time snapshot.

## Critical correction: the original API surface was wrong

The app was first built from `eTIMS-OSCU-Integrator-Automated-Testing-Sandbox.json`, a Postman
collection targeting `sbx.kra.go.ke/etims-oscu/api/v1` with an Apigee OAuth2 client-credentials
layer in front (an "Access Token" request, `apigee_client_id`/`secret`, `Authorization: Bearer`).
That host is real and responds (a clean HTTP 400), which read as confirmation at the time.

It wasn't. Cross-checked against two independent sources - KRA's own **official OSCU
Specification Document v2.0**, and **navariltd/kenya-compliance** (an ERPNext OSCU integration
actually tested against the KRA sandbox in 2024, cloned locally for study) - both agree on a
different picture:

- **Correct base URL:** `https://etims-api-sbx.kra.go.ke/etims-api` (sandbox),
  `https://etims-api.kra.go.ke/etims-api` (production) - a different host entirely, not a typo of
  the original.
- **No OAuth layer at all.** kenya-compliance's Settings doctype has no client_id/secret/token
  field, and its whole codebase has zero bearer-token code. Every call authenticates with
  `tin`/`bhfId`/`cmcKey` headers only - the device credential *is* the auth, no separate token
  step in front of it.
- **Most endpoint paths differ**, not just the host - e.g. `saveTrnsSalesOsdc` (not
  `sendSalesTransaction`, the call our entire receipt-signing feature makes), `selectInitOsdcInfo`
  (not `initialize`), `selectBhfList` (not `branchList`). Only `saveItem`, `selectCodeList`,
  `selectNoticeList`, `saveItemComposition` happened to match.

Both `sbx.kra.go.ke` and `etims-api-sbx.kra.go.ke` are genuinely live, cert-valid, KRA-owned hosts
- this wasn't a dead/fake endpoint, it was a *different real one*, most likely a legacy or
unrelated program sharing superficially similar naming. A host responding is not the same as it
being *the* documented, currently-correct one.

**What changed as a result** (see `git log` for the exact commit): `utils/config.py`'s URLs,
`utils/api_client.py`'s auth (OAuth flow removed entirely), `eTIMS Settings` (Apigee fields
dropped - nothing left to hold), `eTIMS Branch` (added `sdc_id`, alongside `cmcKey`, both
confirmed returned by `selectInitOsdcInfo`), every endpoint name in `etims_sync/`, and new fields
on Sales Invoice/POS Invoice for KRA's confirmed `saveTrnsSalesOsdc` response
(`rcptSign`/`curRcptNo`/`totRcptNo`/`intrlData`/`sdcDateTime`) plus real QR code generation from
it - all resolving prior TODOs that had been honestly flagged as guesses (`_extract_cmc_key`'s
"best-effort" shape, the raw-response dump with no QR code) rather than treated as settled.

**What this doesn't change:** the payload *shapes* we'd already built (item fields, tax bucketing,
`saveItem`'s field names) turned out to match kenya-compliance's real, tested payloads closely -
the correction is entirely in the transport layer (host, paths, auth), not the business logic.

**Still unverified:** none of this has completed a live round-trip against KRA from this
environment - the corrected host resets unauthenticated/unregistered connections at the network
level (consistent with IP-whitelisted sandbox access, not evidence the correction is wrong).
Verified instead by mocking the network boundary and exercising the real code paths against the
confirmed response shapes. Real sandbox credentials would be the next level of confidence beyond
this.

## Decisions locked so far

- **Device model:** start with **OSCU** (online, real-time signing). VSCU (offline-tolerant
  signing) is a candidate v2 once we pull its spec and diff it against OSCU — the two are not
  assumed to be a drop-in swap.
- **Tenancy:** one Frappe **site per client**, all on the same bench. Site-level isolation gives us
  tenant data separation for free; `royce_etims` itself doesn't need to know it's multi-tenant.
- **Registration granularity:** eTIMS credentials are **not** flat per-site. A taxpayer (Company /
  TIN) can have several registered branches (`bhfId`), and KRA issues a separate device
  (`dvcSrlNo` → `cmcKey`) **per branch**, not per company. The data model reflects that split:
  - `eTIMS Settings` — one per **Company**: TIN, environment (Sandbox/Production), overall status.
    No credentials fields - there's nothing to hold; see the correction note above.
  - `eTIMS Branch` — one per **Branch** (KRA's `bhfId`) under a Company: device serial, `cmcKey`,
    `sdc_id`, device status. Reuses ERPNext's existing `Branch` doctype as the anchor rather than
    inventing a parallel one.
- **KRA-side onboarding (applying for TIN registration, getting a device serial number
  (`dvcSrlNo`) issued):** not automated for now. The app presents it as a checklist step; client
  either does it themselves or we do it for them as a paid-assist service. Revisit once/if we
  pursue KRA "verified third-party integrator" status.
- **Receipt sync is asynchronous.** Submission in ERPNext is never blocked on KRA's API. Sync
  happens as a background job with a visible status field and automatic retry.
- **What gets signed: receipts, not invoices — for now.** KRA's OSCU API has one call for this,
  `sendSalesTransaction` — there's no separate "sign invoice" vs "sign receipt" endpoint. What we
  control is which ERPNext event triggers it. Two doctypes can, gated independently per company on
  `eTIMS Settings`:
  - **POS Invoice** (`sign_pos_invoices`, **on by default**) — point-of-sale, payment collected
    immediately. Closest match to a fiscal receipt: final, no credit/cancellation complexity.
  - **Sales Invoice** (`sign_sales_invoices`, **off by default**) — general/credit invoice, can be
    issued unpaid. Deliberately not signed yet — credit invoices raise timing/amendment questions
    (see Open items below) that haven't been resolved. Turning this on is meant to be a deliberate
    per-company decision, not a default.

- **Reference data as real doctypes, item codes as a mapping table, not flat fields.** Patterns
  borrowed from `navari_csf_ke`'s `etims` module (a data-model scaffold for eTIMS - not a working
  KRA connector; it has no HTTP calls and no doc_events wiring anything to KRA, so this was borrowed
  for shape/ideas only, not code):
  - `eTIMS Item Classification`, `eTIMS Taxation Type` (carries `rate`), `eTIMS Item Type`,
    `eTIMS Packaging Unit`, `eTIMS Quantity Unit`, `eTIMS Country of Origin` — Link-able reference
    doctypes instead of free-text/Select fields on Item. Only Taxation Type and Item Type are
    seeded (from real values in the sandbox collection) — the rest are deliberately empty pending
    real `selectCodeList`/`selectItemClass` sync, not filled with guesses.
  - **`eTIMS ID Mapping`** (generic child table: `setup_doctype` + `setup_docname` + `etims_id`) —
    fixes the multi-company limitation flagged earlier: itemCd is assigned per taxpayer
    registration, not globally to the Item, so it lives in a child table keyed by company
    (`eTIMS Settings`) rather than a flat `etims_item_code` field. Reusable for Customer/Supplier
    later without a schema change.
  - Tax rate for `sendSalesTransaction`'s `taxRtA..E` now comes live from `eTIMS Taxation Type`,
    replacing what was a hardcoded `TAX_RATE_BY_CODE` dict in `etims_sync/receipt.py`.
  - `prevent_etims_submission` escape hatch added to Item, Sales Invoice, and POS Invoice.

## Open / not yet decided

- Whether v1 needs multi-branch support day one or can ship single-branch first (leaning toward
  building the model correctly now since retrofitting is expensive, but scope of the *UI* for it
  can be trimmed).
- VSCU spec diff — not yet pulled. Worth re-checking against kenya-compliance too, now that it's
  cloned locally, rather than the OSCU spec PDF alone.
- Whether Royce Technologies pursues KRA third-party integrator certification.
- Payroll-compliance side of the product — separate workstream, not covered by this doc.
- Production QR-verification host (`PRODUCTION_QR_VERIFY_BASE_URL`) is inferred by pattern
  (sbx-suffix removed), not independently confirmed the way the other corrected URLs were -
  confirm before going live.
- No live round-trip against KRA yet from any environment - see the correction note above. Real
  sandbox credentials are the natural next step once available.
- `selectCodeList`/`selectItemClass`/`branchList` reference-data sync — the task this correction
  interrupted. Now unblocked with confirmed endpoint names (`selectCodeList` was already right;
  `selectItemClass` should be `selectItemClsList`, `branchList` should be `selectBhfList`) - still
  to be built.

---

## 1. Multi-tenant deployment

```mermaid
flowchart TB
    subgraph Bench["Frappe Bench (Docker)"]
        subgraph SiteA["Site: clienta.example.com"]
            ERPA[ERPNext]
            EtimsA[royce_etims app]
            ERPA --- EtimsA
        end
        subgraph SiteB["Site: clientb.example.com"]
            ERPB[ERPNext]
            EtimsB[royce_etims app]
            ERPB --- EtimsB
        end
        subgraph SiteN["Site: new client on onboarding..."]
            ERPN[ERPNext]
            EtimsN[royce_etims app]
            ERPN --- EtimsN
        end
    end

    EtimsA -->|HTTPS, own TIN + credentials| KRA[(KRA eTIMS OSCU API)]
    EtimsB -->|HTTPS, own TIN + credentials| KRA
    EtimsN -->|HTTPS, own TIN + credentials| KRA
```

Each site is a fully isolated tenant (own database). Onboarding a client = new site +
`install-app royce_etims`, handled by provisioning tooling outside this app.

## 2. Data model — Company / Branch / device

```mermaid
erDiagram
    COMPANY ||--o| ETIMS_SETTINGS : "has one"
    COMPANY ||--o{ BRANCH : "has many"
    BRANCH ||--o| ETIMS_BRANCH : "registers as device"

    COMPANY {
        string name
        string tax_id
    }
    ETIMS_SETTINGS {
        Link company
        string tin
        select environment "Sandbox / Production"
        select status "Draft / Active"
    }
    BRANCH {
        string name
        Link company
    }
    ETIMS_BRANCH {
        Link branch
        string bhf_id
        string dvc_srl_no
        password cmc_key
        string sdc_id
        select device_status "Not Registered / Registered / Active"
    }
```

`ETIMS_SETTINGS` carries what's shared across the whole taxpayer (TIN, environment). `ETIMS_BRANCH`
carries what's specific to a physical outlet — because that's the actual grain KRA's
`selectInitOsdcInfo` call operates at (`tin` + `bhfId` + `dvcSrlNo` → `cmcKey` + `sdcId`).

## 3. Onboarding flow

```mermaid
flowchart TD
    A["Client applies for eTIMS on KRA portal\n(self, or Royce assists for a fee)"] --> B["Client receives TIN +\na device serial number (dvcSrlNo) per branch"]
    B --> C["Enter TIN + environment in eTIMS Settings (Company)"]
    C --> D["Add Branch record: bhfId + dvcSrlNo"]
    D --> E["Register device\nPOST /selectInitOsdcInfo"]
    E -- fail --> D
    E -- success --> F["Store cmcKey + sdcId\nBranch device_status = Registered"]
    F --> G["Bootstrap reference data\n(code list, item classification, branch list)"]
    G --> H["Sync existing Items\n(saveItem)"]
    H --> I["Mark Branch Active — Go Live"]
    I --> J["Sales Invoice submissions now sync to eTIMS"]
```

No separate credentials-test step — there's no OAuth layer in front of the real API (see the
correction note above), so device registration is itself the first genuine connectivity check.
Each branch under a company repeats steps D–I independently — a company with 3 branches does 3
device registrations, each gated by its own confirm step (irreversible, environment-sensitive
action).

## 4. Runtime — receipt sync (POS Invoice by default; Sales Invoice if enabled)

```mermaid
sequenceDiagram
    participant U as Cashier / Accountant
    participant D as POS Invoice (or Sales Invoice, if enabled)
    participant Q as Background Job Queue
    participant API as eTIMS API Client
    participant KRA as KRA eTIMS OSCU

    U->>D: Submit
    D-->>U: Submitted (eTIMS Status = Pending)
    D->>Q: enqueue sync job (royce_etims.etims_sync.receipt)
    Q->>API: saveTrnsSalesOsdc(payload)
    API->>KRA: POST /saveTrnsSalesOsdc
    alt success
        KRA-->>API: 200 + rcptSign/curRcptNo/totRcptNo/intrlData/sdcDateTime
        API-->>D: eTIMS Status = Sent, QR code generated from rcptSign
    else failure or timeout
        KRA-->>API: error / timeout
        API-->>D: eTIMS Status = Failed
        Q->>Q: scheduled retry sweep, every 15 min, up to 5 attempts
    end
```

Submission in ERPNext never blocks on KRA. Failure surfaces as a status the accountant can see
and a retry worker chases automatically. Both doctypes share one handler
(`royce_etims/etims_sync/receipt.py`) since KRA's per-device invoice sequence (`invcNo`) has to
stay monotonic regardless of which ERPNext document triggered it. The QR code encodes a
verification URL built from `tin` + `bhfId` + `rcptSign` against KRA's public receipt-verification
host - a third host, distinct from both the API host and the two above (confirmed from
kenya-compliance's QR-generation code).
