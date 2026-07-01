# ePromise → ERPNext · Production Migration Guide

**Company:** Steel Force Trading Bahrain (SFTB) | **Currency:** BHD | **Inventory:** Perpetual  
**Export file:** `epromise_export_SFTB_2026-07-01.xlsx`  
**Date range:** 2026-01-01 → 2026-06-30  
**ePromise DB:** `SteelForce_Bahrain_26` @ `37.224.24.154:14335` (user: `sa`)

---

## What Changed (Latest Updates)

| # | Change | Impact |
|---|---|---|
| 1 | **ePromise DB** renamed `SteelForce_Bahrain_2026` → `SteelForce_Bahrain_26` | Update `mssql_database` in ePromise Settings |
| 2 | **Date range** set to 2026-01-01 → 2026-06-30 | All import steps filter to this window |
| 3 | **Item deduplication** — duplicate item_codes in one invoice now merged (qty summed) | Prevents duplicate item rows in SI/PI |
| 4 | **Cost centers** — `0002 - SFTB` (SFWH) added alongside `0001` and `0003` | All three branches map correctly |
| 5 | **Debit To / Credit To** from party master's Default Accounts, currency-matched | Correct AR/AP ledger per invoice currency |
| 6 | **Taxes** — `charge_type = On Net Total`, `rate = 10%` | ERPNext shows 10% VAT rate; amount comes from ePromise |
| 7 | **Tax accounts** — Sales: `22040200002 - VAT Output A/c - SFTB`; Purchase: `13120100001 - VAT Input - SFTB` | Correct VAT posting |
| 8 | **Update Stock = OFF** on all Sales Invoices | Stock is not updated from SI; use Stock Entry or DN separately |
| 9 | **Purchase Receipt removed** from import | Only Purchase Invoice imported; no GRN receipts |
| 10 | **Item Master import** added (Step 1c) | Items pre-loaded from Bahrain Master XLS before invoices |
| 11 | **SQL credentials** in `site_config.json` (not only in DB) | Credentials survive database restores |

---

## Prerequisites

Before starting, confirm all of the following:

- [ ] SSH access to the production server with sudo rights
- [ ] Frappe bench installed and running on production
- [ ] **Company "Steel Force Trading Bahrain"** created in ERPNext (abbr: `SFTB`, currency: `BHD`)
- [ ] COA imported from `COA_ERPNext_Import_SteelForce_Bahrain.xlsx`
- [ ] `backup` app source code on production
- [ ] `Copy of Bahrain Master 16.6.26 (1) (1).xls` in `[bench]/apps/backup/`
- [ ] `epromise_export_SFTB_2026-07-01.xlsx` on production server (Excel fallback only)
- [ ] Full production database backup: `bench --site [site] backup --with-files`

---

## Phase 1 — Install the App

```bash
# Copy app + item master to production
scp -r /home/gym/new-bench/apps/backup  user@[prod]:[bench]/apps/backup
scp "Copy of Bahrain Master 16.6.26 (1) (1).xls"  user@[prod]:[bench]/apps/backup/

# Install
cd [bench]
bench --site [site] install-app backup
bench --site [site] migrate
bench build --app backup
bench --site [site] clear-cache
```

**Verify:** `https://[site]/app/epromise-migration` must load without 404.

---

## Phase 2 — Import the Chart of Accounts

Skip if `1303 - Accounts Receivables - SFTB` already exists in Accounts.

1. **Accounting → Chart of Accounts → Import Chart of Accounts**
2. Upload `COA_ERPNext_Import_SteelForce_Bahrain.xlsx`, company = *Steel Force Trading Bahrain*

**Must exist after import:**

| Account | Purpose |
|---|---|
| `1303 - Accounts Receivables - SFTB` | AR group — individual customer ledgers under this |
| `130301 - Accounts Receivable - SFTB` | AR control |
| `2201 - Accounts Payable - SFTB` | AP group — individual supplier ledgers under this |
| `22040100002 - Accounts Payable Control Account - SFTB` | AP control |
| `22040200002 - VAT Output A/c - SFTB` | **Output VAT** — posted on Sales Invoices |
| `13120100001 - VAT Input - SFTB` | **Input VAT** — posted on Purchase Invoices |

---

## Phase 3 — Pre-Flight Setup Script

```bash
bench --site [site] execute backup.epromise_migration.setup_production.run_setup
```

Creates:
- Perpetual inventory enabled
- Warehouses: confirms `Stores - SFTB`
- Cost Centers: **`0001 - SFTB`** (SFSB), **`0002 - SFTB`** (SFWH), **`0003 - SFTB`** (SFSS), `Main - SFTB`
- Item Groups, UOMs, Customer Groups, Territories, Supplier Groups, Modes of Payment
- All custom fields (`epromise_vr_no`, `epromise_trc_code`, `epromise_acc_code`, `epromise_ite_code`, etc.)
- Verifies VAT accounts

Any `MISSING` line in the output must be resolved before importing.

### 3.1  Perpetual inventory stock accounts

Go to **Accounting → Company → Steel Force Trading Bahrain** and set:

| Field | Account |
|---|---|
| Stock Received But Not Billed | (liability account from COA) |
| Stock Adjustment Account | (expense/income account from COA) |
| Default Expense Account | (main expense account from COA) |

Then **Stock → Warehouse → Stores - SFTB** → set Account to the stock-in-hand GL account.

### 3.2  Verify custom fields

Search `epromise` in **Settings → Custom Fields**. Expected:

```
Customer              → epromise_acc_code
Supplier              → epromise_acc_code
Item                  → epromise_ite_code
Sales Invoice         → epromise_vr_no, epromise_trc_code, epromise_invoice_type
Sales Invoice Item    → epromise_ite_code
Purchase Invoice      → epromise_vr_no, epromise_trc_code, epromise_invoice_type
Purchase Invoice Item → epromise_ite_code
Payment Entry         → epromise_vr_no
Journal Entry         → epromise_vr_no
```

---

## Phase 4 — Configure ePromise Settings

Go to **ePromise Settings**.

### 4.1  SQL Server connection

| Field | Value |
|---|---|
| MSSQL Host | `37.224.24.154` |
| MSSQL Port | `14335` |
| **MSSQL Database** | **`SteelForce_Bahrain_26`** ← new database name |
| MSSQL Username | `sa` |
| MSSQL Password | *(as provided)* |

Then store credentials safely in `site_config.json` (survives DB restores):

```bash
bench --site [site] set-config epromise_mssql_host     "37.224.24.154"
bench --site [site] set-config epromise_mssql_port     14335
bench --site [site] set-config epromise_mssql_database "SteelForce_Bahrain_26"
bench --site [site] set-config epromise_mssql_username "sa"
bench --site [site] set-config epromise_mssql_password "your-password"

# Verify:
bench --site [site] execute backup.epromise_migration.export_settings.verify_connection
```

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
| Default Tax Account (Output) | `22040200002 - VAT Output A/c - SFTB` |
| Default Input Tax Account | `13120100001 - VAT Input - SFTB` |

### 4.3  Date range

Navigate to **`/app/epromise-migration`** → **Import Date Range** card:

- **From Date:** `2026-01-01`
- **To Date:** `2026-06-30`
- Click **Apply & Save Dates**

All import steps (Customers, Sales Invoices, Purchase Invoices, Payments, Journals) filter to this range.

---

## Phase 5 — Live SQL Import (Recommended)

Navigate to **`/app/epromise-migration`**. Run each step in order.

### Step 1a — Import Customer Master
- Source: `DICADMAS` (sub_head = D), filtered to date range
- Creates customers; auto-creates Receivable ledger under `1303 - Accounts Receivables - SFTB`
- Ledger linked into Customer → Accounting tab → Default Accounts

### Step 1b — Import Supplier Master
- Source: `DICADMAS` (sub_head = C)
- Creates suppliers; auto-creates Payable ledger under `2201 - Accounts Payable - SFTB`
- Ledger linked into Supplier → Accounting tab → Default Accounts

### Step 1c — Import Item Master
- Source: `Copy of Bahrain Master 16.6.26 (1) (1).xls`
- **Unified Code** → `item_code`, **ERP NEXT Item Name** → `item_name`, **Unit** → `stock_uom`
- `is_stock_item = 1` on all items
- `epromise_ite_code` = Resource Code (traceability)
- Skips already-existing items (idempotent)
- **Run before invoices** — invoice import auto-creates missing items but this pre-loads all 4,832

### Step 2 — Import Sales Invoices
- TRC **S01** = Credit Invoice → `ACC-SINV-CR-.YYYY.-`
- TRC **S06** = POS Invoice → `ACC-SINV-POS-.YYYY.-`
- **`update_stock = 0`** — stock NOT updated by Sales Invoice
- Items deduplicated per invoice (same item_code → qty summed, no duplicate rows)
- `debit_to` = Customer's linked receivable account (currency-matched from Default Accounts)
- **Output VAT:** `22040200002 - VAT Output A/c - SFTB`, charge type **On Net Total**, rate **10%**
- Warehouse: `Stores - SFTB` on all item lines
- Cost centers: `0001 - SFTB`, `0002 - SFTB`, `0003 - SFTB` per ePromise branch code
- `disable_rounded_total = 1`

### Step 2b — Import Sales Returns
- TRC **R01**, **R04** → Sales Invoice (`is_return = 1`, linked to original)
- Run after Step 2

### Step 3 — Import Purchase Invoices
- TRC **350** = Item-wise Purchase Invoice (items from `PURCHASE_INVOICE_DETAIL`)
- TRC **111** = Direct Purchase (standalone)
- TRC **IP** = Import Purchase (freight/customs as service items)
- `credit_to` = Supplier's linked payable account (currency-matched from Default Accounts)
- **Input VAT:** `13120100001 - VAT Input - SFTB`, charge type **On Net Total**, rate **10%**
- Warehouse: `Stores - SFTB` on all stock item lines
- ⚠️ **No Purchase Receipt import** — GRN/GR are not imported; PI imports stand-alone

### Step 3b — Import Purchase Returns
- TRC **PR** → Purchase Invoice (`is_return = 1`, linked to original)
- Run after Step 3

### Step 4 — Import Payment Vouchers
- TRC **003** = Cash Payment → Payment Entry (Pay to Supplier) or Journal Entry
- TRC **004** = Cash Receipt → Payment Entry (Receive from Customer)
- Run after invoices → reconcile via **Accounting → Payment Reconciliation**

### Step 5 — Import Journal & Adjustment Vouchers
- TRC **020** = Bank/Cash Adjustment → Journal Entry
- TRC **007** = Journal Voucher → Journal Entry

---

## Phase 6 — Excel Import (Offline Fallback)

> Use when the production server cannot reach the ePromise SQL Server directly.

### 6.1  Start the background worker

```bash
sudo supervisorctl status frappe-worker-long
# or:
bench worker --queue long &
```

### 6.2  Open the import page

`https://[site]/app/epromise-import`

### 6.3  Import sheets in order

Upload `epromise_export_SFTB_2026-07-01.xlsx` and import:

| Order | Sheet | ERPNext DocType | Dedup field |
|---|---|---|---|
| 1 | Customers | Customer | epromise_acc_code |
| 2 | Suppliers | Supplier | epromise_acc_code |
| 3 | Sales_Invoices | Sales Invoice | epromise_vr_no |
| 4 | Purchase_Invoices | Purchase Invoice | epromise_vr_no |
| 5 | Payment_Entries | Payment Entry | epromise_vr_no |
| 6 | Journal_Entries | Journal Entry | epromise_vr_no |

> Note: Excel export does not include Purchase Receipts — GRN/GR not imported.

---

## Phase 7 — Post-Import Verification

```python
# bench --site [site] console
print("Items (ePromise):", frappe.db.count("Item",            {"epromise_ite_code": ["!=", ""]}))
print("Customers:",        frappe.db.count("Customer",         {"epromise_acc_code": ["!=", ""]}))
print("Suppliers:",        frappe.db.count("Supplier",         {"epromise_acc_code": ["!=", ""]}))
print("Sales Inv:",        frappe.db.count("Sales Invoice",    {"epromise_vr_no": ["!=", ""], "docstatus": 1}))
print("Purchase Inv:",     frappe.db.count("Purchase Invoice", {"epromise_vr_no": ["!=", ""], "docstatus": 1}))
print("Payments:",         frappe.db.count("Payment Entry",    {"epromise_vr_no": ["!=", ""], "docstatus": 1}))
print("Journals:",         frappe.db.count("Journal Entry",    {"epromise_vr_no": ["!=", ""], "docstatus": 1}))
```

**Spot-check a Sales Invoice:**
- `update_stock` must be **unchecked**
- Items table: no duplicate item rows
- `debit_to` = customer's specific ledger (e.g. `Salmabad Welding... - SFTB`)
- Taxes: charge type = **On Net Total**, rate = **10%**, account = `22040200002 - VAT Output A/c - SFTB`

**Spot-check a Purchase Invoice:**
- `credit_to` = supplier's specific ledger
- Taxes: `13120100001 - VAT Input - SFTB`, On Net Total, 10%

**Verify cost centers:**
All three must exist: `0001 - SFTB`, `0002 - SFTB`, `0003 - SFTB`

**Reconcile payments:**
**Accounting → Payment Reconciliation** → select party → Get Unreconciled Entries → Allocate → Reconcile

---

## Troubleshooting

| Error | Cause | Fix |
|---|---|---|
| Login failed for user 'sa' | Wrong database name or password | Confirm `mssql_database = SteelForce_Bahrain_26` in Settings |
| Account does not exist | Account in invoice not in COA | Import COA (Phase 2) or create manually |
| `0002 - SFTB` not found | Cost center not created | Re-run setup script (Phase 3) |
| Item already exists | Item created earlier with same code | Normal — skipped, idempotent |
| Duplicate items in invoice | Old staging data | Live SQL import deduplicates; re-import if Excel-imported |
| Party Account "No Data" | Customer/supplier created before fix | Run backfill script (see below) |
| Job stays Queued | Background worker not running | `bench worker --queue long &` |
| Stock account not set | Perpetual inventory not configured | Phase 3.1 — set company stock accounts |
| Trial balance doesn't balance | GL lines skipped | Check Migration Log errors |

### Backfill Party Account links

```python
# bench --site [site] console
from backup.epromise_migration.utils.account_utils import (
    _create_account, _link_party_account, AR_PARENT, AP_PARENT, COMPANY
)
for c in frappe.db.sql(
    "SELECT name, customer_name FROM `tabCustomer` WHERE epromise_acc_code != '' "
    "AND NOT EXISTS (SELECT 1 FROM `tabParty Account` WHERE parent=name AND parenttype='Customer' AND company=%s)",
    (COMPANY,), as_dict=True):
    acct = _create_account(c.customer_name, AR_PARENT, "Receivable")
    if acct: _link_party_account(c.name, "Customer", acct)

for s in frappe.db.sql(
    "SELECT name, supplier_name FROM `tabSupplier` WHERE epromise_acc_code != '' "
    "AND NOT EXISTS (SELECT 1 FROM `tabParty Account` WHERE parent=name AND parenttype='Supplier' AND company=%s)",
    (COMPANY,), as_dict=True):
    acct = _create_account(s.supplier_name, AP_PARENT, "Payable")
    if acct: _link_party_account(s.name, "Supplier", acct)

frappe.db.commit()
```

---

## What the App Does Automatically

| Behaviour | Detail |
|---|---|
| Title Case | Customer/Supplier names enforced on every save |
| Ledger creation | AR/AP account auto-created on new Customer/Supplier (`after_insert`) and linked to Default Accounts |
| Deduplication | `epromise_vr_no` / `epromise_acc_code` / `epromise_ite_code` checked before every insert |
| Item deduplication | Same item_code appearing twice in one invoice → qty summed, one row |
| Unified Code | Resource Code (ePromise) → Unified Code via Bahrain Master XLS |
| Perpetual inventory | `enable_perpetual_inventory = 1`; warehouse accounts must be set |
| Update Stock | `update_stock = 0` on all Sales Invoices — stock managed separately |
| Warehouse | `Stores - SFTB` on all SI/PI item lines |
| Cost centers | `0001`/`0002`/`0003` → `0001 - SFTB` / `0002 - SFTB` / `0003 - SFTB` |
| Output VAT | `22040200002 - VAT Output A/c - SFTB`, On Net Total, 10% |
| Input VAT | `13120100001 - VAT Input - SFTB`, On Net Total, 10% |
| Debit To / Credit To | Taken from party's Default Accounts (currency-matched) |
| No rounding | `disable_rounded_total = 1` — exact BHD amounts |
| Packages | `openpyxl`, `xlrd`, `pymssql` auto-installed via `after_install` hook |
| SQL credentials | `site_config.json` takes priority over DB-stored credentials |

---

## Files Reference

| File | Purpose |
|---|---|
| `backup/epromise_migration/setup_production.py` | Pre-flight setup — run first |
| `backup/epromise_migration/utils/item_importer.py` | Item Master import from Bahrain Master XLS |
| `backup/epromise_migration/utils/invoice_importer.py` | Sales Invoice importer (live SQL) |
| `backup/epromise_migration/utils/purchase_importer.py` | Purchase Invoice importer (live SQL) |
| `backup/epromise_migration/utils/account_utils.py` | Customer/Supplier ledger hooks |
| `backup/epromise_migration/utils/unified_code_map.py` | Resource Code → Unified Code map |
| `backup/epromise_migration/utils/bak_parser.py` | SQL connection (`_get_mssql_credentials` reads site_config first) |
| `backup/epromise_migration/export_settings.py` | Print production `bench set-config` commands |
| `backup/epromise_migration/api.py` | Excel import API (`/app/epromise-import`) |
| `export_to_excel.py` | Generate Excel export from staging ERPNext |
| `Copy of Bahrain Master 16.6.26 (1) (1).xls` | Item master source (Resource Code → Unified Code) |
| `epromise_export_SFTB_2026-07-01.xlsx` | Production Excel import file |
| `PRODUCTION_SETUP.md` | This file |
