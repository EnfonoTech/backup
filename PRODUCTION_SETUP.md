# ePromise → ERPNext · Production Migration Guide

**Company:** Steel Force Trading Bahrain (SFTB) | **Currency:** BHD | **Inventory:** Perpetual  
**Export file:** `epromise_export_SFTB_2026-07-01.xlsx`  
**Date range:** 2026-01-01 → 2026-06-30  
**ePromise DB:** `SteelForce_Bahrain_26` @ `37.224.24.154:14335` (user: `sa`)

---

## What Changed (All Sessions)

| # | Change | Impact |
|---|---|---|
| 1 | **ePromise DB** is `SteelForce_Bahrain_26` | Set `mssql_database` in ePromise Settings |
| 2 | **Date range** 2026-01-01 → 2026-06-30 | All steps filter to this window |
| 3 | **Item deduplication** — duplicate item_codes in one invoice merged (qty summed) | No duplicate rows in SI/PI |
| 4 | **Branch cost centers** `0001 - SFTB` (SFSB), `0002 - SFTB` (SFWH), `0003 - SFTB` (SFSS) | All three mapped from ePromise `SOURCE_BR_CODE` |
| 5 | **Branch warehouses** same names as cost centers, children of `Stores - SFTB` | Each branch posts stock to its own warehouse |
| 6 | **Debit To / Credit To** from party Default Accounts (currency-matched) | Customer/supplier-specific AR/AP ledger |
| 7 | **Taxes** — `On Net Total`, rate `10%` | Correct VAT presentation |
| 8 | **Tax accounts** — Sales: `22040200002 - VAT Output A/c - SFTB`; Purchase: `13120100001 - VAT Input - SFTB` | Correct VAT GL posting |
| 9 | **Update Stock = OFF** on all Sales Invoices | Stock managed separately |
| 10 | **No Purchase Receipt** — only Purchase Invoice imported | GRN/GR not migrated |
| 11 | **Item Master pre-load** (Step 1c) from Bahrain Master XLS | All 4,800+ items loaded before invoices |
| 12 | **Unified Code only** — items with no Bahrain Master mapping use placeholder, never created with raw resource code | Clean item master; no legacy codes |
| 13 | **GL Mapping** (`GL Mapping of E Promise to ERP Next.xlsx`) — resolves all payment/journal/income/expense accounts | 241 explicit ePromise → ERPNext account mappings |
| 14 | **SQL credentials** in `site_config.json` via `bench set-config` | Survive database restores |
| 15 | **Remove duplicate COA groups** — ERPNext default root groups deleted, only numbered COA kept | Clean Chart of Accounts |

---

## Prerequisites

Before starting, confirm all of the following:

- [ ] SSH access to the production server with sudo rights
- [ ] Frappe bench installed and site created
- [ ] **Company "Steel Force Trading Bahrain"** created (abbr: `SFTB`, currency: `BHD`, precision: 3 decimal places — BHD = Fils, 1000 Fils per Dinar, symbol `د.ب`)
- [ ] `backup` app source deployed to `[bench]/apps/backup/`
- [ ] `Copy of Bahrain Master 16.6.26 (1) (1).xls` in `[bench]/apps/backup/`
- [ ] `GL Mapping of E Promise to ERP Next.xlsx` in `[bench]/apps/backup/`
- [ ] `epromise_export_SFTB_2026-07-01.xlsx` on server (Excel fallback only)
- [ ] Full database backup before starting: `bench --site [site] backup --with-files`

---

## Phase 1 — Install the App

```bash
# Copy app + required files to production
scp -r /path/to/backup                                user@[prod]:[bench]/apps/backup
scp "Copy of Bahrain Master 16.6.26 (1) (1).xls"     user@[prod]:[bench]/apps/backup/
scp "GL Mapping of E Promise to ERP Next.xlsx"        user@[prod]:[bench]/apps/backup/

# Install
cd [bench]
bench --site [site] install-app backup
bench --site [site] migrate
bench build --app backup
bench --site [site] clear-cache
```

**Verify:** `https://[site]/app/epromise-migration` loads without 404.

---

## Phase 2 — Import the Chart of Accounts

1. **Accounting → Chart of Accounts → Import Chart of Accounts**
2. Upload `COA_ERPNext_Import_SteelForce_Bahrain.xlsx`, company = *Steel Force Trading Bahrain*

**Must exist after import:**

| Account | Purpose |
|---|---|
| `1303 - Accounts Receivables - SFTB` | AR group — customer ledgers created under this |
| `130301 - Accounts Receivable - SFTB` | AR control account |
| `2201 - Accounts Payable - SFTB` | AP group — supplier ledgers created under this |
| `22040100002 - Accounts Payable Control Account - SFTB` | AP control account |
| `22040200002 - VAT Output A/c - SFTB` | Output VAT — posted on Sales Invoices |
| `13120100001 - VAT Input - SFTB` | Input VAT — posted on Purchase Invoices |

### 2.1 — Remove duplicate ERPNext default COA groups

When ERPNext creates a company it auto-generates generic root groups (`Application of Funds`,
`Source of Funds`, `Equity`, `Income`, `Expenses`). After importing the numbered COA these
become empty duplicates. Remove them:

```bash
bench --site [site] execute backup.epromise_migration.setup_production.remove_duplicate_coa
```

Expected output — one `DELETED` line per group. If any shows `SKIP (children)`, delete
the child accounts manually first (they should be empty if no transactions have been posted).

---

## Phase 3 — Pre-Flight Setup Script

```bash
bench --site [site] execute backup.epromise_migration.setup_production.run_setup
```

This single command creates / verifies:

| Item | Detail |
|---|---|
| Perpetual inventory | `enable_perpetual_inventory = 1` on company |
| `Stores - SFTB` | Primary warehouse (created if missing) |
| Branch warehouses | `0001 - SFTB`, `0002 - SFTB`, `0003 - SFTB` as children of `Stores - SFTB` |
| Cost centers | `0001 - SFTB` (SFSB), `0002 - SFTB` (SFWH), `0003 - SFTB` (SFSS), `Main - SFTB` |
| Item Groups | Products, Raw Materials, Services |
| UOMs | Nos, Kg, Metre, Square Meter, Litre, Set, Box, Roll, MT |
| Customer Groups | Commercial, Individual, Retail |
| Territories | Bahrain, Saudi Arabia, UAE, Kuwait, Oman, Qatar |
| Supplier Groups | Trading Suppliers, Service Suppliers, Local Suppliers |
| Custom fields | All `epromise_*` fields on Customer, Supplier, Item, SI, PI, PE, JE |
| VAT accounts | Checks `22040200002` and `13120100001` exist |
| Fiscal Year | Checks 2026 fiscal year exists |

Any `MISSING` line in the output must be resolved before importing.

### 3.1 — Set warehouse GL accounts

Since `update_stock = 0` is set on all Sales Invoices and no Purchase Receipts are imported,
perpetual inventory stock movements are not triggered during migration. ERPNext still requires
a GL Account on every warehouse. Go to **Stock → Warehouse** and set the account on each:

| Warehouse | Set Account to |
|---|---|
| `Stores - SFTB` | Stock-in-hand GL account from COA |
| `0001 - SFTB` | Same stock-in-hand GL account |
| `0002 - SFTB` | Same stock-in-hand GL account |
| `0003 - SFTB` | Same stock-in-hand GL account |

**Do not configure "Stock Received But Not Billed"** — that account is not used in this migration.

### 3.2 — Verify custom fields

Search `epromise` in **Settings → Custom Fields**. All of these must exist:

```
Customer              → epromise_acc_code
Supplier              → epromise_acc_code
Item                  → epromise_ite_code
Sales Invoice         → epromise_vr_no, epromise_trc_code, epromise_invoice_type
Sales Invoice Item    → epromise_ite_code
Purchase Invoice      → epromise_vr_no, epromise_trc_code, epromise_invoice_type
Purchase Invoice Item → epromise_ite_code
Payment Entry         → epromise_vr_no, epromise_trc_code
Journal Entry         → epromise_vr_no, epromise_trc_code
```

---

## Phase 4 — Configure ePromise Settings

Go to **ePromise Settings** (`/app/epromise-settings`).

### 4.1 — SQL Server connection

| Field | Value |
|---|---|
| MSSQL Host | `37.224.24.154` |
| MSSQL Port | `14335` |
| MSSQL Database | `SteelForce_Bahrain_26` |
| MSSQL Username | `sa` |
| MSSQL Password | *(as provided)* |

Store credentials in `site_config.json` so they survive database restores:

```bash
bench --site [site] set-config epromise_mssql_host     "37.224.24.154"
bench --site [site] set-config epromise_mssql_port     14335
bench --site [site] set-config epromise_mssql_database "SteelForce_Bahrain_26"
bench --site [site] set-config epromise_mssql_username "sa"
bench --site [site] set-config epromise_mssql_password "Force#2026#313"

# Confirm the connection works (should print row count):
bench --site [site] execute backup.epromise_migration.export_settings.verify_connection
```

### 4.2 — Master data settings

| Field | Value |
|---|---|
| Company | Steel Force Trading Bahrain |
| Customer Group | Commercial |
| Supplier Group | Trading Suppliers |
| Territory | Bahrain |
| Item Group | Products |
| Tax Account (Output VAT) | `22040200002 - VAT Output A/c - SFTB` |
| Input Tax Account | `13120100001 - VAT Input - SFTB` |

> **Warehouse and Cost Center are NOT set here.** Every invoice line resolves its own
> warehouse and cost center from the ePromise `SOURCE_BR_CODE` field:
> `0001` → `0001 - SFTB`, `0002` → `0002 - SFTB`, `0003` → `0003 - SFTB`.
> Any voucher whose `SOURCE_BR_CODE` is missing or unrecognised will be flagged in the Migration Log — do not import it with a generic fallback.

### 4.3 — Date range

Go to **`/app/epromise-migration`** → **Import Date Range** card:

- **From Date:** `2026-01-01`
- **To Date:** `2026-06-30`
- Click **Apply & Save Dates**

All import steps respect this range.

---

## Phase 5 — Live SQL Import (Recommended)

Navigate to **`/app/epromise-migration`** and run each step in order. Each step is idempotent — safe to re-run.

### Step 1a — Customers
- Source: `DICADMAS` (sub_head = D)
- Creates Customer; auto-creates individual AR ledger under `1303 - Accounts Receivables - SFTB`
- Links ledger into Customer → Accounting tab → **Default Accounts (Party Account child table)**
- This is the source for `debit_to` on all Sales Invoices — the party's own ledger, not a system account

### Step 1b — Suppliers
- Source: `DICADMAS` (sub_head = C)
- Creates Supplier; auto-creates individual AP ledger under `2201 - Accounts Payable - SFTB`
- Links ledger into Supplier → Accounting tab → **Default Accounts (Party Account child table)**
- This is the source for `credit_to` on all Purchase Invoices — the party's own ledger, not a system account

### Step 1c — Item Master
- Source: `Copy of Bahrain Master 16.6.26 (1) (1).xls`
- **Unified Code** → `item_code` | **ERP NEXT Item Name** → `item_name` | **Unit** → `stock_uom`
- `is_stock_item = 1`; `epromise_ite_code` = Resource Code
- Items **not** in this master are never created with raw resource codes — invoice lines use the placeholder item instead
- Run before invoices to pre-load all ~4,800 items

### Step 2 — Sales Invoices
- TRC **S01** → Credit Invoice (`ACC-SINV-CR-.YYYY.-`)
- TRC **S06** → POS Invoice (`ACC-SINV-POS-.YYYY.-`)
- `update_stock = 0` — stock not touched by SI
- Same `item_code` appearing twice in one voucher → qty summed, single row
- `debit_to` = customer's individual AR ledger from the party's **Default Accounts** (Party Account child table, currency-matched)
- Output VAT: `22040200002 - VAT Output A/c - SFTB`, **On Net Total**, **10%**
- Item line warehouse and cost center: resolved exclusively from ePromise `SOURCE_BR_CODE`
  - `0001` → `0001 - SFTB` | `0002` → `0002 - SFTB` | `0003` → `0003 - SFTB`
  - Vouchers with an unrecognised `SOURCE_BR_CODE` are logged and skipped — not imported with a generic warehouse
- `disable_rounded_total = 1` — BHD amounts kept exact (3 decimal places, no rounding to nearest Fil)

### Step 2b — Sales Returns
- TRC **R01**, **R04** → Sales Invoice (`is_return = 1`, linked to original)
- Run after Step 2

### Step 3 — Purchase Invoices
- TRC **350** → Item-wise PI (items from `PURCHASE_INVOICE_DETAIL`)
- TRC **111** → Direct Purchase (standalone)
- TRC **IP** → Import Purchase (freight/customs as service items)
- `credit_to` = supplier's individual AP ledger from the party's **Default Accounts** (Party Account child table, currency-matched)
- Input VAT: `13120100001 - VAT Input - SFTB`, **On Net Total**, **10%**
- Item lines: warehouse and cost center resolved from `SOURCE_BR_CODE` exactly as Sales Invoices
- Expense/income accounts resolved via **`GL Mapping of E Promise to ERP Next.xlsx`** — 241 explicit mappings; any ePromise code not in the Excel is logged as an error and the line is skipped
- No Purchase Receipt — GRN/GR not imported

### Step 3b — Purchase Returns
- TRC **PR** → Purchase Invoice (`is_return = 1`, linked to original)
- Run after Step 3

### Step 4 — Payment Vouchers
- TRC **003** → Cash Payment → Payment Entry (Pay to Supplier) or Journal Entry
- TRC **004** → Cash Receipt → Payment Entry (Receive from Customer)
- Cash/bank accounts resolved via **`GL Mapping of E Promise to ERP Next.xlsx`** — the Excel is the sole source of truth; no guessing from account numbers
- Run after invoices; reconcile via **Accounting → Payment Reconciliation**

### Step 5 — Journal & Adjustment Vouchers
- TRC **020** → Bank/Cash Adjustment → Journal Entry
- TRC **007** → Journal Voucher → Journal Entry
- All GL line accounts resolved via **`GL Mapping of E Promise to ERP Next.xlsx`** — ePromise code → ERPNext full account name; unmapped codes are logged and skipped

---

## Phase 6 — Excel Import (Offline Fallback)

> Use only when the production server cannot reach the ePromise SQL Server directly.
> The live import (Phase 5) is preferred — it is more complete and handles edge cases.

### 6.1 — Start the long-queue worker

```bash
sudo supervisorctl status frappe-worker-long
# If not running:
bench worker --queue long &
```

### 6.2 — Open the import page

`https://[site]/app/epromise-import`

### 6.3 — Import sheets in order

Upload `epromise_export_SFTB_2026-07-01.xlsx` and import each sheet:

| Order | Sheet | ERPNext DocType | Key dedup field |
|---|---|---|---|
| 1 | Customers | Customer | epromise_acc_code |
| 2 | Suppliers | Supplier | epromise_acc_code |
| 3 | Sales_Invoices | Sales Invoice | epromise_vr_no |
| 4 | Purchase_Invoices | Purchase Invoice | epromise_vr_no |
| 5 | Payment_Entries | Payment Entry | epromise_vr_no |
| 6 | Journal_Entries | Journal Entry | epromise_vr_no |

**What the Excel file contains (as of 2026-07-01 export):**

| Sheet | Rows | Notes |
|---|---|---|
| Customers | 323 | One row per customer |
| Suppliers | 180 | One row per supplier |
| Sales_Invoices | 84,149 | Jan–Jun 2026; each item on its own row |
| Purchase_Invoices | 2,008 | Jan–Jun 2026 |
| Payment_Entries | 1,170 | — |
| Journal_Entries | 1,194 | — |

**What the Excel already has correct:**
- `debit_to` / `credit_to` — each party's individual ledger from their Default Accounts (Party Account child table)
- `warehouse` — branch-specific (`0001/0002/0003 - SFTB`) from ePromise `SOURCE_BR_CODE`
- `cost_center` — matching branch cost center
- `income_account` / `expense_account` — mapped via GL Mapping Excel
- `paid_from` / `paid_to` — mapped via GL Mapping Excel
- Journal `account` — mapped via GL Mapping Excel
- Item codes — unified codes only; unmapped items use placeholder

---

## Phase 7 — Post-Import Verification

```python
# bench --site [site] console
print("Items:",        frappe.db.count("Item",            {"epromise_ite_code": ["!=", ""]}))
print("Customers:",    frappe.db.count("Customer",         {"epromise_acc_code": ["!=", ""]}))
print("Suppliers:",    frappe.db.count("Supplier",         {"epromise_acc_code": ["!=", ""]}))
print("Sales Inv:",    frappe.db.count("Sales Invoice",    {"epromise_vr_no": ["!=", ""], "docstatus": 1}))
print("Purchase Inv:", frappe.db.count("Purchase Invoice", {"epromise_vr_no": ["!=", ""], "docstatus": 1}))
print("Payments:",     frappe.db.count("Payment Entry",    {"epromise_vr_no": ["!=", ""], "docstatus": 1}))
print("Journals:",     frappe.db.count("Journal Entry",    {"epromise_vr_no": ["!=", ""], "docstatus": 1}))
```

**Spot-check a Sales Invoice:**
- `update_stock` = unchecked
- `disable_rounded_total` = checked
- No duplicate item rows
- `debit_to` = the customer's individual AR ledger (e.g. `Al Mansoori Trading - SFTB`) — NOT a generic "Accounts Receivable"
- Items: `warehouse` = one of `0001 - SFTB` / `0002 - SFTB` / `0003 - SFTB` — never `Stores - SFTB`
- Items: `cost_center` = matching branch (`0001/0002/0003 - SFTB`)
- Items: `item_code` = unified code from Bahrain Master (never a raw resource code)
- Taxes: **On Net Total**, **10%**, `22040200002 - VAT Output A/c - SFTB`
- Amount precision: 3 decimal places (BHD / Fils), no rounded total

**Spot-check a Purchase Invoice:**
- `credit_to` = the supplier's individual AP ledger — NOT a generic "Accounts Payable"
- Taxes: `13120100001 - VAT Input - SFTB`, On Net Total, 10%
- `expense_account` = ERPNext account name from GL Mapping Excel (not a raw ePromise code)

**Spot-check a Journal Entry:**
- Each `account` line = full ERPNext account name (e.g. `13020100001 - National Bank of Bahrain - SFTB`)
- Not a raw ePromise code

**Verify COA:**
- Accounting → Chart of Accounts: only numbered root groups visible (1-Asset, 2-Liabilities, 3-Capital, 4-Revenue, 5-Expenditure)
- No `Application of Funds`, `Source of Funds`, `Equity`, `Income`, `Expenses` groups

**Reconcile payments:**
Accounting → Payment Reconciliation → select party → Get Unreconciled Entries → Allocate → Reconcile

---

## Troubleshooting

| Error | Cause | Fix |
|---|---|---|
| Login failed for user 'sa' | Wrong DB name or password | Confirm `mssql_database = SteelForce_Bahrain_26` |
| Account does not exist | Account not in COA or GL Mapping | Import COA (Phase 2); verify entry exists in GL Mapping Excel |
| `0002 - SFTB` warehouse not found | Branch warehouses not created | Re-run setup script (Phase 3) |
| Warehouse GL account missing | GL account not set on warehouse | Phase 3.1 |
| Item uses raw resource code | Bahrain Master XLS missing from `apps/backup/` | Copy file to server, re-run Step 1c |
| Duplicate root COA groups still showing | `remove_duplicate_coa` not run | Phase 2.1 |
| `GL Mapping` file not found | File not copied to production | `scp "GL Mapping..." user@[prod]:[bench]/apps/backup/` |
| `debit_to` shows generic Accounts Receivable | Party Account not linked | Run backfill (see below) |
| `credit_to` shows generic Accounts Payable | Party Account not linked | Run backfill (see below) |
| Party Account "No Data" | Customer/supplier created before hook fix | Run backfill (see below) |
| Job stays Queued | Long worker not running | `bench worker --queue long &` |
| Trial balance doesn't balance | GL lines skipped due to missing mapping | Check Migration Log; add missing code to GL Mapping Excel |

### Backfill Party Account links (if needed)

```python
# bench --site [site] console
from backup.epromise_migration.utils.account_utils import (
    _create_account, _link_party_account, AR_PARENT, AP_PARENT, COMPANY
)
for c in frappe.db.sql(
    "SELECT name, customer_name FROM `tabCustomer` WHERE epromise_acc_code != '' "
    "AND NOT EXISTS (SELECT 1 FROM `tabParty Account` "
    "WHERE parent=name AND parenttype='Customer' AND company=%s)",
    (COMPANY,), as_dict=True):
    acct = _create_account(c.customer_name, AR_PARENT, "Receivable")
    if acct: _link_party_account(c.name, "Customer", acct)

for s in frappe.db.sql(
    "SELECT name, supplier_name FROM `tabSupplier` WHERE epromise_acc_code != '' "
    "AND NOT EXISTS (SELECT 1 FROM `tabParty Account` "
    "WHERE parent=name AND parenttype='Supplier' AND company=%s)",
    (COMPANY,), as_dict=True):
    acct = _create_account(s.supplier_name, AP_PARENT, "Payable")
    if acct: _link_party_account(s.name, "Supplier", acct)

frappe.db.commit()
```

---

## What the App Does Automatically

| Behaviour | Detail |
|---|---|
| Ledger creation | AR/AP account auto-created on new Customer/Supplier and linked to party's Default Accounts (Party Account child table) |
| Title case | Customer/Supplier names normalised on every save |
| Deduplication | `epromise_vr_no` / `epromise_acc_code` / `epromise_ite_code` checked before every insert |
| Item deduplication | Same item_code in one voucher → qty summed, one row |
| Unified Code only | Items not in Bahrain Master → placeholder; never created with raw resource code |
| Branch warehouse | `SOURCE_BR_CODE` `0001`/`0002`/`0003` → `0001 - SFTB` / `0002 - SFTB` / `0003 - SFTB`; unrecognised code → logged and skipped |
| Branch cost center | Same `SOURCE_BR_CODE` → matching `0001 - SFTB` / `0002 - SFTB` / `0003 - SFTB` cost center |
| GL account mapping | All payment/journal/income/expense accounts resolved exclusively via `GL Mapping of E Promise to ERP Next.xlsx`; unmapped codes logged |
| Debit To | Customer's individual AR ledger from party master Default Accounts (Party Account child table, currency-matched) |
| Credit To | Supplier's individual AP ledger from party master Default Accounts (Party Account child table, currency-matched) |
| Output VAT | `22040200002 - VAT Output A/c - SFTB`, On Net Total, 10% |
| Input VAT | `13120100001 - VAT Input - SFTB`, On Net Total, 10% |
| Update Stock | `update_stock = 0` on all Sales Invoices — no stock movement during migration |
| No rounding | `disable_rounded_total = 1` — BHD amounts kept to 3 decimal places (Fils); no ERPNext rounding |
| Number format | BHD: 3 decimal places, 1000 Fils = 1 Dinar, symbol `د.ب` |
| SQL credentials | `site_config.json` takes priority over DB-stored credentials |
| Packages | `openpyxl`, `xlrd`, `pymssql` auto-installed via `after_install` hook |

---

## Production Reset (Start Fresh)

If you need to clear all migrated data and re-run from scratch:

```python
# bench --site [site] console  — CAUTION: deletes all migrated records
import frappe
frappe.set_user("Administrator")

for dt in ["Sales Invoice", "Purchase Invoice", "Payment Entry", "Journal Entry"]:
    for name in frappe.db.get_all(dt, filters={"epromise_vr_no": ["!=", ""]}, pluck="name"):
        try:
            doc = frappe.get_doc(dt, name)
            if doc.docstatus == 1: doc.cancel()
            frappe.delete_doc(dt, name, ignore_permissions=True, force=True)
        except: pass

frappe.db.sql("DELETE FROM `tabCustomer` WHERE epromise_acc_code != ''")
frappe.db.sql("DELETE FROM `tabSupplier` WHERE epromise_acc_code != ''")
frappe.db.sql("DELETE FROM `tabItem`     WHERE epromise_ite_code != ''")
frappe.db.commit()
```

Then restart from Phase 3 — setup script, ePromise Settings, and import steps.

---

## Files Reference

| File | Purpose |
|---|---|
| `backup/epromise_migration/setup_production.py` | Pre-flight setup + `remove_duplicate_coa()` |
| `backup/epromise_migration/utils/gl_map.py` | GL Mapping Excel loader — used by all importers |
| `backup/epromise_migration/utils/item_importer.py` | Item Master import from Bahrain Master XLS |
| `backup/epromise_migration/utils/invoice_importer.py` | Sales Invoice importer (live SQL) |
| `backup/epromise_migration/utils/purchase_importer.py` | Purchase Invoice importer (live SQL) |
| `backup/epromise_migration/utils/payment_importer.py` | Payment Entry / Journal Entry importer |
| `backup/epromise_migration/utils/account_utils.py` | Customer/Supplier ledger auto-create hooks |
| `backup/epromise_migration/utils/unified_code_map.py` | Resource Code → Unified Code map |
| `backup/epromise_migration/utils/bak_parser.py` | SQL Server connection (`site_config.json` first) |
| `backup/epromise_migration/export_settings.py` | Print `bench set-config` commands for production |
| `backup/epromise_migration/api.py` | Excel import API (`/app/epromise-import`) |
| `export_to_excel.py` | Generate Excel export from staging ERPNext |
| `Copy of Bahrain Master 16.6.26 (1) (1).xls` | Item master — Resource Code → Unified Code |
| `GL Mapping of E Promise to ERP Next.xlsx` | ePromise account code → ERPNext account name |
| `epromise_export_SFTB_2026-07-01.xlsx` | Production Excel import file |
| `PRODUCTION_SETUP.md` | This file |
