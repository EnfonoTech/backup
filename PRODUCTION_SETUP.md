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
- [ ] `epromise_export_SFTB_2026-06-30.xlsx` copied to production server
- [ ] Full production database backup taken: `bench --site [site] backup --with-files`

---

## Phase 1 — Install the App

### 1.1  Copy the app to production

```bash
# From staging server or local machine:
scp -r /home/gym/new-bench/apps/backup  user@[prod-server]:[bench-path]/apps/backup
```

### 1.2  Install into the production site

```bash
cd [bench-path]
bench --site [site-name] install-app backup
bench --site [site-name] migrate
bench build --app backup
bench --site [site-name] clear-cache
```

**Verify:** Open `https://[site]/app/epromise-import` — it must load without a 404.  
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

---

## Phase 3 — Run the Pre-Flight Setup Script

This single command:
- Enables **perpetual inventory** (stock movements auto-create GL entries)
- Creates **Warehouse** `Main Warehouse - SFTB`
- Creates **Cost Center** `Main - SFTB` (referenced by every imported invoice line)
- Creates **Item Groups**: Products, Raw Materials, Services
- Creates all required **UOMs**: Nos, Kg, Metre, Set, Box, Roll, MT, etc.
- Creates **Customer Groups**: Commercial, Individual, Retail
- Creates **Territories**: Bahrain, Saudi Arabia, UAE, Kuwait, Oman, Qatar
- Creates **Supplier Groups**: Trading Suppliers, Service Suppliers, Local Suppliers
- Creates **Modes of Payment**: Cash, Bank Transfer, Cheque
- Creates all **custom fields** (epromise_vr_no, epromise_trc_code, epromise_acc_code, etc.)
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

> Without these, submitting Sales/Purchase Invoices will fail with "Account not set" errors.

### 3.2  Verify custom fields

Go to **Settings → Custom Fields** and search `epromise`. You should see:

```
Customer             →  epromise_acc_code
Supplier             →  epromise_acc_code
Sales Invoice        →  epromise_vr_no, epromise_trc_code, epromise_invoice_type
Sales Invoice Item   →  epromise_ite_code
Purchase Invoice     →  epromise_vr_no, epromise_trc_code
Purchase Invoice Item→  epromise_ite_code
Payment Entry        →  epromise_vr_no
Journal Entry        →  epromise_vr_no
```

---

## Phase 4 — Configure ePromise Settings (If Importing from SQL)

> Skip this phase if you are using the **Excel import only** (recommended for production).

Go to **ePromise Settings** and fill:

| Field | Value |
|---|---|
| Default Company | Steel Force Trading Bahrain |
| Default Customer Group | Commercial |
| Default Supplier Group | Trading Suppliers |
| Default Territory | Bahrain |
| Default Item Group | Products |
| Default Cost Center | Main - SFTB |

---

## Phase 5 — Run the Excel Import

> Import order is critical — masters (Customers, Suppliers) must exist before transactions.

### 5.1  Ensure the background worker is running

```bash
# Check supervisor:
sudo supervisorctl status frappe-worker-long

# Or start manually:
bench worker --queue long &
```

### 5.2  Open the Import page

Navigate to: `https://[site]/app/epromise-import`

### 5.3  Upload the Excel file

Drag and drop `epromise_export_SFTB_2026-06-30.xlsx` into the upload area.  
The page will detect 6 sheets automatically.

### 5.4  Import sheets in order

Click **Import All Sheets in Sequence**, or import one sheet at a time:

| Order | Sheet | ERPNext DocType | Dedup field |
|---|---|---|---|
| 1 | Customers | Customer | epromise_acc_code |
| 2 | Suppliers | Supplier | epromise_acc_code |
| 3 | Sales_Invoices | Sales Invoice | epromise_vr_no |
| 4 | Purchase_Invoices | Purchase Invoice | epromise_vr_no |
| 5 | Payment_Entries | Payment Entry | epromise_vr_no |
| 6 | Journal_Entries | Journal Entry | epromise_vr_no |

Each sheet shows live progress: `X created / Y skipped / Z errors`.

**Already-imported records are automatically skipped** (idempotent), so you can safely re-run a sheet after fixing errors.

### 5.5  Check for errors

Open **List → ePromise Migration Log** and filter by sheet name.  
Each log shows the exact error for each failed record.

---

## Phase 6 — Post-Import Verification

### 6.1  Check record counts

```python
# In bench console: bench --site [site] console
print("Customers:",    frappe.db.count("Customer",         {"epromise_acc_code": ["!=", ""]}))
print("Suppliers:",    frappe.db.count("Supplier",         {"epromise_acc_code": ["!=", ""]}))
print("Sales Inv:",    frappe.db.count("Sales Invoice",    {"epromise_vr_no": ["!=", ""], "docstatus": 1}))
print("Purchase Inv:", frappe.db.count("Purchase Invoice", {"epromise_vr_no": ["!=", ""], "docstatus": 1}))
print("Payments:",     frappe.db.count("Payment Entry",    {"epromise_vr_no": ["!=", ""], "docstatus": 1}))
print("Journals:",     frappe.db.count("Journal Entry",    {"epromise_vr_no": ["!=", ""], "docstatus": 1}))
```

### 6.2  Spot-check a Sales Invoice

Open any Sales Invoice with an `epromise_vr_no`. Confirm:
- Correct customer, posting date, items, amounts
- Status = **Submitted**
- GL entries visible under the "Accounting Entries" button

### 6.3  Verify customer/supplier ledgers

Go to **Accounting → Chart of Accounts**. Expand:
- `1303 - Accounts Receivables - SFTB` → individual customer accounts should appear
- `2201 - Accounts Payable - SFTB` → individual supplier accounts should appear

(These are auto-created by the `after_insert` hook on Customer/Supplier.)

### 6.4  Trial Balance

**Accounting → Trial Balance** → Company: Steel Force Trading Bahrain → Date: 2026-01-01 to 2026-05-31  
Debits must equal credits.

### 6.5  Reconcile payments

Payment Entries are imported without invoice links. Reconcile via:  
**Accounting → Accounts → Payment Reconciliation** → select party → Get Unreconciled Entries → Allocate → Reconcile

---

## Troubleshooting

| Error | Cause | Fix |
|---|---|---|
| Account does not exist | Account in invoice not in production COA | Import COA (Phase 2) or create the account manually |
| Customer does not exist | Invoice imported before customers | Re-run Customers sheet first, then re-run SI sheet |
| Item Group not found | "Products" group missing | Run setup script (Phase 3) |
| Custom field missing | Phase 3 not run | Re-run `run_setup` in bench console |
| Import page returns 404 | App not installed or assets not built | `bench migrate` → `bench build --app backup` → clear cache |
| Job stays Queued forever | Background worker not running | `bench worker --queue long &` |
| Naming series error | Series not created | Re-run setup script; check Settings → Naming Series |
| Trial balance doesn't balance | GL lines skipped due to missing accounts | Check Migration Log errors, fix accounts, delete and re-import affected JEs |

---

## What the app does automatically

- **Title Case** — Customer and Supplier names are title-cased on save (hooks.py `validate`)
- **Ledger creation** — An Account under the AR/AP group is auto-created on each new Customer/Supplier (`after_insert` hook)
- **Deduplication** — Every import checks `epromise_vr_no` / `epromise_acc_code` before creating — safe to re-run
- **Item codes** — `ite_code` is mapped to `unified_code` via `trading inv (2).xlsx` (≈170 items differ)
- **Perpetual inventory** — `enable_perpetual_inventory = 1`. Every submitted SI/PI creates GL entries for stock (COGS debit, Stock in Hand credit). Warehouse accounts must be linked before importing.
- **Stock items** — All ePromise items are created with `is_stock_item = 1` (Maintain Stock ticked). The warehouse `Stores - SFTB` is set on every SI/PI item line. The export includes a `Warehouse (Items)` column pre-filled with this value.
- **Cost centers** — ePromise codes `0001` and `0003` are mapped to `0001 - SFTB` and `0003 - SFTB` in the export. The setup script creates these cost centers.

---

## Files Reference

| File | Purpose |
|---|---|
| `backup/epromise_migration/setup_production.py` | Pre-flight setup — run this first |
| `backup/epromise_migration/utils/invoice_importer.py` | Sales Invoice importer (SQL source) |
| `backup/epromise_migration/utils/purchase_importer.py` | Purchase Invoice importer (SQL source) |
| `backup/epromise_migration/utils/account_utils.py` | Customer/Supplier account hooks |
| `backup/epromise_migration/utils/unified_code_map.py` | ite_code → unified_code mapping |
| `backup/epromise_migration/api.py` | Excel import API (used by /app/epromise-import) |
| `export_to_excel.py` | Generates the export Excel from staging ERPNext |
| `PRODUCTION_SETUP.md` | This file |
