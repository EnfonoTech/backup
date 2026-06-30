# ePromise → ERPNext · Production Migration Guide

**Company:** Steel Force Trading Bahrain (SFTB) | **Currency:** BHD | **Inventory:** Perpetual  
**Export file:** `epromise_export_SFTB_2026-06-30.xlsx`

---

## Prerequisites

Before starting, confirm all of the following:

- [ ] SSH access to the production server with sudo rights
- [ ] Frappe bench installed and running on production
- [ ] **Company "Steel Force Trading Bahrain"** created in ERPNext (abbr: `SFTB`, currency: `BHD`)
- [ ] COA imported from `COA_ERPNext_Import_SteelForce_Bahrain.xlsx`
- [ ] `backup` app source code available on production
- [ ] `Copy of Bahrain Master 16.6.26 (1) (1).xls` placed in `[bench-path]/apps/backup/`
- [ ] `epromise_export_SFTB_2026-06-30.xlsx` copied to production server
- [ ] Full production database backup taken: `bench --site [site] backup --with-files`

---

## Phase 1 — Install the App

### 1.1  Copy the app to production

```bash
# From staging server or local machine:
scp -r /home/gym/new-bench/apps/backup  user@[prod-server]:[bench-path]/apps/backup
# Also copy the item master file:
scp "/home/gym/new-bench/apps/backup/Copy of Bahrain Master 16.6.26 (1) (1).xls" \
    user@[prod-server]:[bench-path]/apps/backup/
```

### 1.2  Install into the production site

```bash
cd [bench-path]
bench --site [site-name] install-app backup
bench --site [site-name] migrate
bench build --app backup
bench --site [site-name] clear-cache
```

**Verify:** Open `https://[site]/app/epromise-migration` — it must load without a 404.  
If you get a 404, run `bench --site [site] migrate` again and hard-refresh.

---

## Phase 2 — Import the Chart of Accounts

If the COA is **already imported** (check by searching `1303 - Accounts Receivables - SFTB` in Accounts), skip this phase.

1. Go to **Accounting → Chart of Accounts → Import Chart of Accounts**
2. Upload `COA_ERPNext_Import_SteelForce_Bahrain.xlsx`
3. Select company: *Steel Force Trading Bahrain*
4. Click **Import**

**Verify these accounts exist after import:**

| Account | Purpose |
|---|---|
| `1303 - Accounts Receivables - SFTB` | AR group — customer ledgers created under this |
| `130301 - Accounts Receivable - SFTB` | AR control account on Sales Invoices |
| `2201 - Accounts Payable - SFTB` | AP group — supplier ledgers created under this |
| `22040100002 - Accounts Payable Control Account - SFTB` | AP control account on Purchase Invoices |
| `22040200001 - VAT Payable - SFTB` | Output VAT (Liability/Tax) — used on Sales Invoices |
| `13120100001 - VAT Input - SFTB` | Input VAT (Asset/Tax) — used on Purchase Invoices/Receipts |

---

## Phase 3 — Run the Pre-Flight Setup Script

This single command:
- Enables **perpetual inventory** (stock movements auto-create GL entries)
- Confirms **Warehouse** `Stores - SFTB` exists (auto-created by ERPNext)
- Creates **Cost Centers** `0001 - SFTB`, `0003 - SFTB`, `Main - SFTB`
- Creates **Item Groups**: Products, Raw Materials, Services
- Creates all required **UOMs**: Nos, Kg, Metre, Set, Box, Roll, MT, etc.
- Creates **Customer Groups**: Commercial, Individual, Retail
- Creates **Territories**: Bahrain, Saudi Arabia, UAE, Kuwait, Oman, Qatar
- Creates **Supplier Groups**: Trading Suppliers, Service Suppliers, Local Suppliers
- Creates **Modes of Payment**: Cash, Bank Transfer, Cheque
- Creates all **custom fields** (epromise_vr_no, epromise_trc_code, epromise_acc_code, epromise_ite_code, etc.)
- Verifies tax accounts (Output VAT, Input VAT)
- Verifies critical COA accounts

```bash
bench --site [site-name] execute backup.epromise_migration.setup_production.run_setup
```

Review the output. Any line marked `MISSING` or `WARN` must be resolved before importing.

### 3.1  Fix perpetual inventory accounts (critical)

After running the setup script, check the output for any `MISSING` lines under **[1b] Stock account check** and **[1c] Warehouse account check**.

Go to **Accounting → Company → Steel Force Trading Bahrain** and set:

| Company Field | Account to use |
|---|---|
| Stock Received But Not Billed | (liability account from COA) |
| Stock Adjustment Account | (expense/income account from COA) |
| Default Expense Account | (main expense account from COA) |

Then go to **Stock → Warehouse**, open each leaf warehouse, and set its **Account** to the matching asset account in the COA (e.g., `Stock in Hand - SFTB` or equivalent).

> Without these, submitting Sales/Purchase Invoices and Purchase Receipts will fail with "Account not set" errors.

### 3.2  Verify custom fields

Go to **Settings → Custom Fields** and search `epromise`. You should see:

```
Customer              →  epromise_acc_code
Supplier              →  epromise_acc_code
Item                  →  epromise_ite_code  (Resource Code traceability)
Sales Invoice         →  epromise_vr_no, epromise_trc_code, epromise_invoice_type
Sales Invoice Item    →  epromise_ite_code
Purchase Receipt      →  epromise_vr_no, epromise_trc_code, epromise_invoice_type
Purchase Receipt Item →  epromise_ite_code
Purchase Invoice      →  epromise_vr_no, epromise_trc_code
Purchase Invoice Item →  epromise_ite_code
Payment Entry         →  epromise_vr_no
Journal Entry         →  epromise_vr_no
```

---

## Phase 4 — Configure ePromise Settings

Go to **ePromise Settings** (search from the top bar) and fill in all fields.

### 4.1  Connection settings (for live SQL import)

| Field | Value |
|---|---|
| MSSQL Host | `37.224.24.154` |
| MSSQL Port | `14335` |
| MSSQL Database | `SteelForce_Bahrain_2026` |
| MSSQL User | *(as provided)* |
| MSSQL Password | *(as provided)* |

Click **Test Live Connection** on the Migration page to verify.

### 4.2  Master data settings

| Field | Value |
|---|---|
| Default Company | Steel Force Trading Bahrain |
| Default Customer Group | Commercial |
| Default Supplier Group | Trading Suppliers |
| Default Territory | Bahrain |
| Default Item Group | Products |
| Default Cost Center | Main - SFTB |
| Default Warehouse | Stores - SFTB |
| Default Tax Account (Output) | `22040200001 - VAT Payable - SFTB` |
| Default Input Tax Account | `13120100001 - VAT Input - SFTB` |
| Default Income Account | *(AR control account from COA)* |
| Default Expense Account | *(AP control account from COA)* |

### 4.3  Date range (critical)

The **Import Date Range** card on the Migration page controls which transactions are pulled from ePromise. All import steps (Sales Invoices, Purchase Receipts, Purchase Invoices, Payments, Journals) respect this range.

1. Navigate to **`/app/epromise-migration`**
2. In the blue **Import Date Range** card at the top:
   - Set **From Date**: `2026-01-01` (or your migration start)
   - Set **To Date**: `2026-06-30` (or your cutover date)
3. Click **Apply & Save Dates** — this saves to ePromise Settings
4. The card will confirm: *"✓ Saved — all imports will use this date range"*

> **Rule:** From date must be ≤ To date. The page blocks all import buttons if the dates are invalid.  
> You can change dates at any time and re-run any step — already-imported records are skipped automatically.

---

## Phase 5 — Live SQL Import (Recommended)

> Use this phase if you have a direct network connection to the ePromise SQL Server.  
> If not, skip to **Phase 6** (Excel import from staging export).

Navigate to: **`/app/epromise-migration`**

Run each step in order. Each button queues a background job — the status updates live every 4 seconds.

### Step 1a — Import Customer Master
- Source: `DICADMAS` (sub_head = D)
- Creates all customers not already in ERPNext
- Auto-creates a Receivable ledger under `1303 - Accounts Receivables - SFTB` for each customer
- Links the ledger to the Customer's Default Accounts tab

### Step 1b — Import Supplier Master
- Source: `DICADMAS` (sub_head = C)
- Creates all suppliers not already in ERPNext
- Auto-creates a Payable ledger under `2201 - Accounts Payable - SFTB` for each supplier
- Links the ledger to the Supplier's Default Accounts tab

### Step 1c — Import Item Master
- Source: `Copy of Bahrain Master 16.6.26 (1) (1).xls` (must exist in `apps/backup/`)
- Reads all rows; uses **Unified Code** as `item_code`, **ERP NEXT Item Name** as `item_name`
- Sets `is_stock_item = 1` (Maintain Stock) on all items
- Already-existing items are skipped
- Creates `epromise_ite_code` (Resource Code) on each item for traceability
- **Run this before importing any invoices or receipts**

### Step 2 — Import Sales Invoices
- Source: `DICHDATA` (TRC S01 = Credit Invoice, S06 = POS Invoice) + `SALES_DATA` items
- Items matched via Unified Code map; missing items auto-created
- Each invoice: `Stores - SFTB` warehouse on all item lines
- Output VAT posted to `22040200001 - VAT Payable - SFTB`
- Cost centers: ePromise codes `0001`/`0003` → ERPNext `0001 - SFTB`/`0003 - SFTB`
- `disable_rounded_total = 1` (no rounding adjustment line)

### Step 2b — Import Sales Returns
- TRC R01 = Credit Sales Return, R04 = POS Sales Return
- Creates Sales Invoices with `is_return = 1`
- Links to original Sales Invoice via `return_against`
- **Run after Step 2**

### Step 3 — Import Purchase Receipts (GRN)
- Source: `DICHDATA` (TRC GRN = Goods Receiving Note, GR = Goods Return) + `PURCHASE_DATA` items
- **GRN → Purchase Receipt** (stock received, increases inventory at `Stores - SFTB`)
- **GR → Purchase Receipt** with `is_return = 1`, linked to original GRN
- Items matched via Unified Code map; missing items auto-created with `is_stock_item = 1`
- Input VAT posted to `13120100001 - VAT Input - SFTB`
- **Run before Step 4** — Purchase Invoices link back to GRN receipts

#### How Purchase Receipts work in ERPNext (perpetual inventory):
| Event | GL Entry |
|---|---|
| GRN submitted | Dr Stock in Hand / Cr Stock Received But Not Billed |
| Purchase Invoice submitted (linked to GRN) | Dr Stock Received But Not Billed / Cr Accounts Payable |
| If no GRN linked (direct purchase) | Dr Stock in Hand / Cr Accounts Payable |

### Step 4 — Import Purchase Invoices
- TRC **350** = Purchase Invoice linked to GRN (items from `PURCHASE_INVOICE_DETAIL`)
- TRC **111** = Direct Purchase — standalone invoice (no GRN link)
- TRC **IP** = Import Purchase — includes freight/customs as service items
- Links TRC 350 invoices to their GRN Purchase Receipt automatically
- Input VAT posted to `13120100001 - VAT Input - SFTB`
- **Run after Step 3**

### Step 4b — Import Purchase Returns
- TRC **PR** = Purchase Return → Purchase Invoice (`is_return = 1`)
- Links to original Purchase Invoice
- **Run after Step 4**

### Step 5 — Import Payment Vouchers
- TRC **003** = Cash Payment → Payment Entry (Pay to Supplier) or Journal Entry
- TRC **004** = Cash Receipt → Payment Entry (Receive from Customer)
- Party detected from GL lines in `DICADDATA`
- **Run after invoices** — then use Payment Reconciliation to link payments to invoices

### Step 6 — Import Journal & Adjustment Vouchers
- TRC **020** = Bank/Cash Adjustment → Journal Entry
- TRC **007** = Journal Voucher → Journal Entry
- GL lines from `DICADDATA`

### Monitoring progress

Each step shows live status:
```
⏳ Running — ✅ 342 created, ❌ 2 errors, ⏭ 0 skipped (344 processed) — [View Log]  [■ Stop]
```

To stop a running import gracefully: click **■ Stop** — the job finishes the current batch and halts.  
To view errors: click the log link → open **Log Details** tab for per-record error messages.

---

## Phase 6 — Excel Import (Offline / Staging Export)

> Use this phase when importing from the staging-generated Excel file rather than live SQL.

### 6.1  Ensure the background worker is running

```bash
# Check supervisor:
sudo supervisorctl status frappe-worker-long

# Or start manually:
bench worker --queue long &
```

### 6.2  Open the Import page

Navigate to: `https://[site]/app/epromise-import`

### 6.3  Upload the Excel file

Drag and drop `epromise_export_SFTB_2026-06-30.xlsx` into the upload area.  
The page detects 6 sheets automatically.

### 6.4  Import sheets in order

Click **Import All Sheets in Sequence**, or import one sheet at a time:

| Order | Sheet | ERPNext DocType | Dedup field |
|---|---|---|---|
| 1 | Customers | Customer | epromise_acc_code |
| 2 | Suppliers | Supplier | epromise_acc_code |
| 3 | Sales_Invoices | Sales Invoice | epromise_vr_no |
| 4 | Purchase_Invoices | Purchase Invoice | epromise_vr_no |
| 5 | Payment_Entries | Payment Entry | epromise_vr_no |
| 6 | Journal_Entries | Journal Entry | epromise_vr_no |

> Note: This Excel export does **not** include Purchase Receipts. Use Phase 5 (live SQL) for GRN/GR import.

Each sheet shows live progress. Already-imported records are automatically skipped (idempotent) — safe to re-run after fixing errors.

### 6.5  Check for errors

Open **List → ePromise Migration Log** and filter by migration_type.  
Each log shows the exact error for each failed record in the **Log Details** tab.

---

## Phase 7 — Post-Import Verification

### 7.1  Check record counts

```python
# bench --site [site] console
print("Items (ePromise):", frappe.db.count("Item",            {"epromise_ite_code": ["!=", ""]}))
print("Customers:",        frappe.db.count("Customer",         {"epromise_acc_code": ["!=", ""]}))
print("Suppliers:",        frappe.db.count("Supplier",         {"epromise_acc_code": ["!=", ""]}))
print("Sales Inv:",        frappe.db.count("Sales Invoice",    {"epromise_vr_no": ["!=", ""], "docstatus": 1}))
print("Purch Receipts:",   frappe.db.count("Purchase Receipt", {"epromise_vr_no": ["!=", ""], "docstatus": 0}))
print("Purchase Inv:",     frappe.db.count("Purchase Invoice", {"epromise_vr_no": ["!=", ""], "docstatus": 1}))
print("Payments:",         frappe.db.count("Payment Entry",    {"epromise_vr_no": ["!=", ""], "docstatus": 1}))
print("Journals:",         frappe.db.count("Journal Entry",    {"epromise_vr_no": ["!=", ""], "docstatus": 1}))
```

### 7.2  Spot-check a Sales Invoice

Open any Sales Invoice with an `epromise_vr_no`. Confirm:
- Correct customer, posting date, items with warehouse `Stores - SFTB`, amounts
- Status = **Submitted**
- Output VAT row present in the Taxes table
- GL entries visible under the **Accounting Entries** button

### 7.3  Spot-check a Purchase Receipt

Open any Purchase Receipt. Confirm:
- Status = **Draft** (receipts are imported as Draft; submit after review)
- Correct supplier, posting date, items with warehouse `Stores - SFTB`
- GR returns have `is_return = 1` and a `return_against` link

### 7.4  Verify customer/supplier ledgers

Go to **Accounting → Chart of Accounts**. Expand:
- `1303 - Accounts Receivables - SFTB` → individual customer accounts should appear
- `2201 - Accounts Payable - SFTB` → individual supplier accounts should appear

Also open any customer → **Accounting** tab → Default Accounts should show the ledger.

### 7.5  Trial Balance

**Accounting → Trial Balance** → Company: Steel Force Trading Bahrain → Date range  
Debits must equal credits.

### 7.6  Submit Purchase Receipts

After reviewing, submit GRN receipts in bulk:

```python
# bench --site [site] console
receipts = frappe.db.get_all("Purchase Receipt",
    filters={"epromise_trc_code": "GRN", "docstatus": 0},
    fields=["name"])
for r in receipts:
    frappe.get_doc("Purchase Receipt", r.name).submit()
frappe.db.commit()
```

> Submit GRN before GR (returns), and before Purchase Invoices, so the linking works correctly.

### 7.7  Reconcile payments

Payment Entries are imported without invoice links. Reconcile via:  
**Accounting → Accounts → Payment Reconciliation** → select party → Get Unreconciled Entries → Allocate → Reconcile

---

## Troubleshooting

| Error | Cause | Fix |
|---|---|---|
| Account does not exist | Account in invoice not in production COA | Import COA (Phase 2) or create the account manually |
| Customer does not exist | Invoice imported before customers | Re-run Customer step first, then re-run SI step |
| Item Group not found | "Products" group missing | Run setup script (Phase 3) |
| Custom field missing | Phase 3 not run | Re-run `run_setup` in bench console |
| Bahrain Master file not found | XLS not in apps/backup/ | Copy file to server, restart worker |
| Import page returns 404 | App not installed or assets not built | `bench migrate` → `bench build --app backup` → clear cache |
| Job stays Queued forever | Background worker not running | `bench worker --queue long &` |
| Naming series error | Series not created | Re-run setup script; check Settings → Naming Series |
| Stock account not set | Perpetual inventory accounts not configured | Phase 3.1 — set company stock accounts + warehouse accounts |
| Trial balance doesn't balance | GL lines skipped due to missing accounts | Check Migration Log errors, fix accounts, delete and re-import affected JEs |
| GR return has no return_against | GRN was not imported first | Run Step 3 with GRN only, then run GR |
| Party Account "No Data" | Customer/supplier created before fix | Run backfill script (see below) |

### Backfill Party Account links (if ledgers show "No Data")

```python
# bench --site [site] console
from backup.epromise_migration.utils.account_utils import _create_account, _link_party_account, AR_PARENT, AP_PARENT, COMPANY

for c in frappe.db.sql("SELECT name, customer_name FROM `tabCustomer` WHERE epromise_acc_code != '' AND NOT EXISTS (SELECT 1 FROM `tabParty Account` WHERE parent=name AND parenttype='Customer' AND company=%s)", (COMPANY,), as_dict=True):
    acct = _create_account(c.customer_name, AR_PARENT, "Receivable")
    if acct: _link_party_account(c.name, "Customer", acct)

for s in frappe.db.sql("SELECT name, supplier_name FROM `tabSupplier` WHERE epromise_acc_code != '' AND NOT EXISTS (SELECT 1 FROM `tabParty Account` WHERE parent=name AND parenttype='Supplier' AND company=%s)", (COMPANY,), as_dict=True):
    acct = _create_account(s.supplier_name, AP_PARENT, "Payable")
    if acct: _link_party_account(s.name, "Supplier", acct)

frappe.db.commit()
```

---

## What the app does automatically

- **Title Case** — Customer and Supplier names are title-cased on save (`validate` hook)
- **Ledger creation** — An Account under the AR/AP group is auto-created on each new Customer/Supplier (`after_insert` hook) and linked into the Default Accounts tab
- **Deduplication** — Every import checks `epromise_vr_no` / `epromise_acc_code` / `epromise_ite_code` before creating — safe to re-run
- **Unified Code mapping** — Resource Code (ePromise) → Unified Code (ERPNext `item_code`) via Bahrain Master Excel; falls back to Resource Code if not in map
- **Perpetual inventory** — `enable_perpetual_inventory = 1`. Every submitted SI/PI creates GL entries for stock. Warehouse accounts must be linked before importing.
- **Stock items** — All ePromise items are created with `is_stock_item = 1` (Maintain Stock ticked). The warehouse `Stores - SFTB` is set on every SI/PI/PR item line.
- **Cost centers** — ePromise codes `0001` and `0003` map to `0001 - SFTB` and `0003 - SFTB`. The setup script creates these cost centers.
- **VAT accounts** — Output VAT → `22040200001 - VAT Payable - SFTB` on Sales. Input VAT → `13120100001 - VAT Input - SFTB` on Purchases.
- **No rounding** — `disable_rounded_total = 1` on all imported SI/PI to preserve exact BHD amounts.
- **Package install** — `openpyxl`, `xlrd`, `pymssql` auto-installed via `after_install` hook.

---

## Files Reference

| File | Purpose |
|---|---|
| `backup/epromise_migration/setup_production.py` | Pre-flight setup — run this first |
| `backup/epromise_migration/utils/item_importer.py` | Item Master import from Bahrain Master XLS |
| `backup/epromise_migration/utils/invoice_importer.py` | Sales Invoice importer (SQL source) |
| `backup/epromise_migration/utils/purchase_importer.py` | Purchase Invoice importer (SQL source) |
| `backup/epromise_migration/utils/receipt_importer.py` | Purchase Receipt importer (GRN/GR from SQL) |
| `backup/epromise_migration/utils/account_utils.py` | Customer/Supplier account hooks |
| `backup/epromise_migration/utils/unified_code_map.py` | Resource Code → Unified Code mapping |
| `backup/epromise_migration/api.py` | Excel import API (used by /app/epromise-import) |
| `export_to_excel.py` | Generates the export Excel from staging ERPNext |
| `Copy of Bahrain Master 16.6.26 (1) (1).xls` | Source of truth for item codes and names |
| `PRODUCTION_SETUP.md` | This file |
