# ePromise → ERPNext Migration Guide

**App:** `backup` · **Site:** `ksa` · **Company:** Steel Force Trading Bahrain (abbr: `SFTB`)  
**ePromise DB:** `SteelForce_Bahrain_2026` on `37.224.24.154:14335`  
**Data Coverage:** 2022-01-02 → 2025-05-29

---

## Overview

This custom Frappe app (`backup`) migrates all historical data from the ePromise ERP system (SQL Server) into ERPNext. It supports:

- **Live SQL Server connection** (recommended — exact amounts, real-time items)
- **Backup file mode** (.bak file — limited, amounts may be 0)

All imports run as **background jobs** (no browser timeout). Progress is tracked live on the migration page.

---

## Quick Start

1. Open `/app/epromise-migration`
2. Set **Import Date Range** (From/To dates)
3. Click **Test Live Connection** to verify SQL Server is reachable
4. Run steps in order (see Import Sequence below)
5. After payments: use **Accounts → Payment Reconciliation** to link payments to invoices
6. View reports at `/app/epromise-mapping-guide`

---

## Import Sequence

| Step | Button | ePromise Source | ERPNext Target | Key Notes |
|------|--------|-----------------|----------------|-----------|
| **1a** | Import Customers | `DICADMAS` sub_head=D | Customer | Auto-creates or links by name |
| **1b** | Import Suppliers | `DICADMAS` sub_head=C | Supplier | Run before purchase steps |
| **2** | Import Sales Invoices | `DICHDATA` S01, S06 | Sales Invoice | Items from `DICZDATA`/`SALES_DATA` |
| **2b** | Import Sales Returns | `DICHDATA` R01, R04 | Sales Invoice (is_return=1) | Negative qty; linked to original |
| **3** | Import Purchase Receipts | `DICHDATA` GRN, GR | Purchase Receipt | **Must run before Step 4** |
| **4** | Import Purchase Invoices | `DICHDATA` 350, 111, IP | Purchase Invoice | 350 linked to GRN receipt |
| **4b** | Import Purchase Returns | `DICHDATA` PR | Purchase Invoice (is_return=1) | Linked to original PI |
| **5** | Import Payment Vouchers | `DICHDATA` 003, 004 | Payment Entry | Party from `DICSDATA`; invoice link from `DICSDATA` |
| **6** | Import Journal Vouchers | `DICHDATA` 020, 007 | Journal Entry | GL lines from `DICADDATA` |

---

## Complete TRC Code → ERPNext Mapping

| TRC | ePromise Name | ERPNext DocType | Series | Items Source | Notes |
|-----|--------------|-----------------|--------|--------------|-------|
| **S01** | Credit Sales | Sales Invoice | `ACC-SINV-CR-.YYYY.-` | `DICZDATA` | Standard credit invoice |
| **S06** | Point of Sale | Sales Invoice | `ACC-SINV-POS-.YYYY.-` | `DICZDATA` | POS cash sale |
| **R01** | Credit Sales Return | Sales Invoice | `ACC-SINV-CR-RET-.YYYY.-` | `DICZDATA` | `is_return=1`; qty negative; `return_against` linked |
| **R04** | POS Sales Return | Sales Invoice | `ACC-SINV-POS-RET-.YYYY.-` | `DICZDATA` | `is_return=1`; qty negative |
| **GRN** | Goods Receiving Note | Purchase Receipt | `MAT-PRE-.YYYY.-` | `PURCHASE_DATA` | Run before 350 |
| **GR** | Goods Return | Purchase Receipt | `MAT-PRE-.YYYY.-` | `PURCHASE_DATA` | `is_return=1`; `return_against` = GRN receipt |
| **350** | Purchase Invoice Item Wise | Purchase Invoice | `ACC-PINV-PI-.YYYY.-` | `PURCHASE_INVOICE_DETAIL` | Each item linked to `purchase_receipt` = GRN |
| **111** | Direct Purchase | Purchase Invoice | `ACC-PINV-DIR-.YYYY.-` | `PURCHASE_DATA` | Standalone; no receipt link |
| **IP** | Import Purchase | Purchase Invoice | `ACC-PINV-IMP-.YYYY.-` | `PURCHASE_DATA` + `DICADDATA` (acct 5xx) | Freight/customs as service items |
| **PR** | Purchase Return | Purchase Invoice | `ACC-PINV-RET-.YYYY.-` | `PURCHASE_DATA` | `is_return=1`; linked to original PI |
| **003** | Cash Payment Voucher | Payment Entry (Pay) | — | `DICSDATA` (bill link) | Supplier from `DICSDATA.ACC_CODE` starts `22`; cash from `DICHDATA` header |
| **004** | Cash Receipt Voucher | Payment Entry (Receive) | — | `DICSDATA` (bill link) | Customer from `DICSDATA.ACC_CODE` starts `1303` |
| **020** | Bank/Cash Adjustment | Journal Entry | `ACC-JV-.YYYY.-` | `DICADDATA` GL lines | |
| **007** | Journal Voucher | Journal Entry | `ACC-JV-.YYYY.-` | `DICADDATA` GL lines | |

---

## Key ePromise Tables

| Table | Purpose |
|-------|---------|
| `DICHDATA` | All transaction headers — TRC_CODE tells you the type |
| `DICZDATA` | Sales line items for S01, S06, R01, R04 |
| `SALES_DATA` | Alternative sales line items (older data) |
| `PURCHASE_DATA` | Purchase line items for GRN, GR, 111, IP, PR |
| `PURCHASE_INVOICE_DETAIL` | Line items for TRC=350 — each row has `REF_VR_NO` pointing to the GRN |
| `DICADDATA` | GL journal lines for ALL transactions (used for payment GL, IP expenses) |
| `DICSDATA` | Bill settlement table — `(TRC_CODE, VR_NO)` → `(REF_TRC_CODE, REF_VR_NO)` links payment to invoice |
| `DICADMAS` | Account master: `sub_head=D` = Customer, `sub_head=C` = Supplier, `sub_head=B` = Bank |
| `DICIHMAS` | Item master (5,378 items) — `ITE_CODE`, `ITE_NAME`, `ITE_UNIT` |

---

## Field-Level Mapping (DICHDATA → Sales/Purchase Invoice)

| ePromise Field | ERPNext Field | Notes |
|----------------|---------------|-------|
| `ACC_CODE` | `customer` / `supplier` | Looked up via `epromise_acc_code` custom field |
| `VR_NO` | `epromise_vr_no` (custom) | Used for deduplication |
| `TRC_CODE` | `epromise_trc_code` (custom) | Identifies invoice type |
| `BILL_NO` | `epromise_bill_no` (custom), `po_no` | Supplier/customer bill reference |
| `VR_DATE` | `posting_date`, `due_date` | |
| `ACC_AMT` | `grand_total` (calculated) | Gross = net + VAT |
| `VAT_AMT` | `taxes[0].tax_amount` | Actual VAT amount |
| `ACC_AMT - VAT_AMT` | `net_total` | Net excluding VAT |
| `CUR_CODE` | `currency` | BHD, SAR, USD, etc. |
| `CUR_RATE` | `conversion_rate` | |
| `LPO_NO` | `po_no` | Local Purchase Order number |
| `CREDIT_PERIOD` | `payment_terms_template` | Auto-creates if missing |
| `SOURCE_BR_CODE` | `cost_center` | Branch/location code |

### Sales Line Items (DICZDATA / SALES_DATA → Sales Invoice Item)

| ePromise Field | ERPNext Field |
|----------------|---------------|
| `ITE_CODE` | `item_code` (auto-created if missing) |
| `ITE_NAME` (from DICIHMAS) | `item_name`, `description` |
| `ITE_QTY` | `qty` (negative for returns) |
| `ITE_RATE` | `rate` |
| `ITE_UNIT` (from DICIHMAS) | `uom` |
| `VAT_RATE` | Item tax rate |

---

## Payment Entry Mapping

### Cash Payment Voucher (003 → Payment Entry "Pay")

```
DICHDATA header  →  paid_from  =  Cash account (ACC_CODE = 1301...)
DICSDATA          →  party      =  Supplier (ACC_CODE starts '22')
                     references =  Purchase Invoice (REF_VR_NO → epromise_vr_no)
Settings         →  paid_to    =  default_payable_account (Creditors - K)
```

### Cash Receipt Voucher (004 → Payment Entry "Receive")

```
DICHDATA header  →  paid_to    =  Cash account (ACC_CODE = 1301...)
DICSDATA          →  party      =  Customer (ACC_CODE starts '1303')
                     references =  Sales Invoice (REF_VR_NO → epromise_vr_no)
Settings         →  paid_from  =  default_debit_account (Debtors BHD - K)
```

### Petty Cash Account Detection

The branch's petty cash account is auto-detected from DICADDATA — it's the `1301...` account debited when S06 POS sales run for that branch. This matches ePromise's own petty cash register exactly.

For example, branch `0001` (Steel Force - SFB) uses account `13010200001` (Petty Cash - SFB).

---

## Daily Collection Report — Total Payments & Receipts Explained

This is the most important concept for understanding the cash position report.

### Total Payments (Petty Cash Payments)

**Source:** `DICADDATA` — all **credit entries** (`ACC_SIGN = -1`) on the branch's petty cash account.

```
Petty Cash Account 13010200001 CREDITS on Jan 2, 2025:
  003 Cash Payment Vouchers      3,011.35   Paid OUT to suppliers/expenses
  020 Bank/Cash Adjustments      2,081.79   Cash transferred to bank / adjustments
  R04 POS Sales Return Refunds     130.05   Cash refunded back to customers
  ─────────────────────────────────────────
  Total Payments                 5,223.19
```

**In ERPNext:**
| TRC | Amount | ERPNext Entry |
|-----|--------|---------------|
| 003 | 3,011.35 | **Payment Entry (Pay)** — `paid_from=Petty Cash`, `paid_to=Creditors`, `party=Supplier` |
| 020 | 2,081.79 | **Journal Entry** — GL lines from DICADDATA |
| R04 | 130.05 | **Sales Invoice (is_return=1)** — cash refund goes out of petty cash |

### Total Receipts (Petty Cash Receipts)

**Source:** `DICADDATA` — all **debit entries** (`ACC_SIGN = +1`) on the branch's petty cash account.

```
Petty Cash Account 13010200001 DEBITS on Jan 2, 2025:
  S06 POS Cash Sales             2,297.46   Cash received at POS register
  004 Customer Cash Collections  2,815.10   Credit customer payments deposited to SFB petty cash
  ─────────────────────────────────────────
  Total Receipts                 5,112.56
```

**In ERPNext:**
| TRC | Amount | ERPNext Entry |
|-----|--------|---------------|
| S06 | 2,297.46 | **Sales Invoice** — POS cash sale (the cash receipt side needs a linked Payment Entry or cash journal) |
| 004 | 2,815.10 | **Payment Entry (Receive)** — `paid_to=Petty Cash`, `paid_from=Debtors`, `party=Customer`, invoice refs from DICSDATA |

### Cash Balance

```
Cash Balance = Total Receipts − Total Payments
             = 5,112.56 − 5,223.19
             = (110.63)  ← negative = cash deficit on that day
```

### Key Distinction: "Cash Received: Credit Sales" vs "Total Receipts"

| Row | Value | What it covers |
|-----|-------|----------------|
| **Cash Received: Credit Sales** | 4,801.91 | ALL 004 vouchers company-wide — total cash collected from ALL credit customers on that day across ALL cash accounts (petty cash + bank) |
| **Total Receipts (Petty Cash)** | 5,112.56 | Only what physically entered the SFB branch petty cash register: POS cash (2,297.46) + 004 deposits to SFB petty cash only (2,815.10) |

The 004 SFB portion = **2,815.10** (out of total 4,801.91). The remaining 1,986.81 was collected into other bank accounts or other branches' petty cash.

---

## Branch Filtering — Complete Reference

### Which TRC Codes Are Branch-Filterable

| TRC | Module | Branch Filter Method | ✓ / ⚠ |
|-----|--------|---------------------|-------|
| S06 | POS Sales | `DICHDATA.SOURCE_BR_CODE` direct | ✅ Full |
| S01 | Credit Sales | `DICHDATA.SOURCE_BR_CODE` direct | ✅ Full |
| R04 | POS Returns | `DICHDATA.SOURCE_BR_CODE` direct | ✅ Full |
| R01 | Credit Returns | `DICHDATA.SOURCE_BR_CODE` direct | ✅ Full |
| GRN | Goods Receipt | `DICHDATA.SOURCE_BR_CODE` direct | ✅ Full |
| GR | Goods Return | `DICHDATA.SOURCE_BR_CODE` direct | ✅ Full |
| 111 | Direct Purchase | `DICHDATA.SOURCE_BR_CODE` direct | ✅ Full |
| IP | Import Purchase | `DICHDATA.SOURCE_BR_CODE` direct | ✅ Full |
| 350 | PI Item Wise | `DICHDATA.SOURCE_BR_CODE` direct | ✅ Full |
| PR | Purchase Return | `DICHDATA.SOURCE_BR_CODE` direct | ✅ Full |
| **003** | Cash Payments | Via petty cash account in DICADDATA | ⚠️ Partial |
| **004** | Cash Receipts | Via petty cash account in DICADDATA | ⚠️ Partial |
| **020** | Cash Adjustment | Via petty cash account in DICADDATA | ⚠️ Partial |
| **007** | Journal Voucher | Via petty cash account in DICADDATA | ⚠️ Partial |
| 001 | Bank Payment | No branch link at all | ❌ None |
| 025 | Electronic Transfer | No branch link at all | ❌ None |

### Root Cause: Why 003/004/020/007 Have No Direct Branch

ePromise stores cash transactions differently depending on payment method:

```
Petty cash transaction (003 example):
  DICHDATA:  TRC=003, VR_NO=102501565, ACC_CODE=13010200002, SOURCE_BR_CODE=''
             ─── ACC_CODE is the cash account; SOURCE_BR_CODE is BLANK ───

  DICADDATA: ACC_CODE=220102I0003 (supplier), ACC_SIGN=+1  (debit supplier)
             ACC_CODE=13010200002 (Petty Cash-SFSS), ACC_SIGN=-1 (credit petty cash)
```

`SOURCE_BR_CODE` is blank because the voucher is entered at company level, not tied to a warehouse or branch code.

### How the System Identifies the Branch

The branch's petty cash account is auto-detected:

```
SELECT TOP 1 da.ACC_CODE
FROM DICADDATA da
INNER JOIN DICHDATA dh ON dh.TRC_CODE=da.TRC_CODE AND dh.VR_NO=da.VR_NO
WHERE dh.TRC_CODE='S06'             ← POS sales definitely have SOURCE_BR_CODE
  AND dh.SOURCE_BR_CODE='0001'      ← the branch we want
  AND LEFT(da.ACC_CODE,4)='1301'    ← cash account family
  AND da.ACC_SIGN=1                 ← debit = cash received
GROUP BY da.ACC_CODE
ORDER BY COUNT(*) DESC
→ Returns: 13010200001  (Petty Cash - SFB)
```

POS sales (S06) always go into the branch's own petty cash register, so the account that gets debited for S06 in DICADDATA is definitively the branch's petty cash account.

### Concrete Example: Branch 0001, January 2, 2025

**Step 1 — Detect petty cash account:**
```
Branch 0001 S06 DICADDATA debits → 13010200001 (Petty Cash - SFB)
```

**Step 2 — Filter 003 by petty cash account:**
```sql
SELECT COUNT(*), SUM(ACC_AMT) FROM DICHDATA d
WHERE d.TRC_CODE='003' AND d.POSTED_IND='Y'
  AND CAST(d.VR_DATE AS DATE) = '2025-01-02'
  AND EXISTS (
      SELECT 1 FROM DICADDATA da
      WHERE da.TRC_CODE=d.TRC_CODE AND da.VR_NO=d.VR_NO
        AND da.ACC_CODE='13010200001'    ← SFB petty cash account
        AND da.ACC_SIGN=-1              ← credit = cash going out
  )
→  Count=12, Amount=3,011.35
```

**Step 3 — What's excluded (company-wide 003 = 4,003.25):**
```
Company-wide 003:            4,003.25
Branch 0001 via petty cash:  3,011.35
─────────────────────────────────────
Excluded (bank payments):      991.90  ← 003 payments from SFSS branch (account 13010200002)
                                         or bank-account payments
```

**Full breakdown by cash account for 003 on Jan 2, 2025:**
```
Account 13010200001 (Petty Cash - SFB)   credit=3,011.35  ← branch 0001 petty cash payments
Account 13010200002 (Petty Cash - SFSS)  credit=991.90    ← branch 0003 petty cash payments
─────────────────────────────────────────────────────────
Total 003 (company-wide)                       4,003.25
```

**This is why** the Import Report shows 003 = **3,011.35** (not 4,003.25) when branch 0001 is selected — it correctly captures only the SFB branch petty cash payments.

### What Cannot Be Identified by Branch

| Transaction Type | Example | Why not identifiable |
|-----------------|---------|---------------------|
| 003 via bank account | Supplier payment via NBB (account `13020100024`) | Bank accounts not branch-tagged |
| 004 deposited to bank | Customer pays into NBB bank | Bank accounts not branch-tagged |
| 001 Bank Payment Voucher | Payment Voucher via bank | Entire TRC has no `SOURCE_BR_CODE` |
| 025 Electronic Transfer | Bank-to-bank wire | Entire TRC has no `SOURCE_BR_CODE` |

**For the Daily Collection Report and Import Report, this is acceptable** because:
- The petty cash register IS the branch's cash position
- Bank transactions are company-wide treasury operations, not branch-specific daily cash

To fully branch-identify bank transactions, a `branch → bank account` mapping would need to be configured manually in ePromise Settings.

---

### Post-Import Reconciliation in ERPNext

After importing all entries, go to **Accounts → Payment Reconciliation** and select the Petty Cash account to formally link:
- Payment Entries (003) → Purchase Invoices
- Payment Entries (004) → Sales Invoices

Most links are pre-populated via DICSDATA `REF_VR_NO` in the Payment Entry `references` child table.

---

## Custom Fields Created in ERPNext

### On Sales Invoice
| Field | Purpose |
|-------|---------|
| `epromise_vr_no` | ePromise Voucher No (dedup key) |
| `epromise_trc_code` | TRC Code (S01/S06/R01/R04) |
| `epromise_invoice_type` | Human-readable type label |
| `epromise_bill_no` | ePromise Bill/Invoice No |

### On Purchase Invoice / Purchase Receipt
Same pattern: `epromise_vr_no`, `epromise_trc_code`, `epromise_invoice_type`, `epromise_bill_no`

### On Sales Invoice Item / Purchase Invoice Item / Purchase Receipt Item
| Field | Purpose |
|-------|---------|
| `epromise_ite_code` | Original ePromise item code |

### On Customer / Supplier
| Field | Purpose |
|-------|---------|
| `epromise_acc_code` | ePromise account code (e.g. `130302A0008`) — used for party lookup |

### On Payment Entry / Journal Entry
| Field | Purpose |
|-------|---------|
| `epromise_vr_no` | Voucher number (dedup key) |
| `epromise_trc_code` | TRC code (003/004/020/007) |

---

## ePromise Settings (Configuration)

Navigate to **ePromise Settings** DocType to configure:

| Setting | Value (Steel Force Trading Bahrain) |
|---------|--------------------------------------|
| SQL Server Host | `37.224.24.154` |
| SQL Server Port | `14335` |
| Database Name | `SteelForce_Bahrain_2026` |
| Company | `Steel Force Trading Bahrain` |
| Default Currency | `BHD` |
| Receivable Account | `130301 - Accounts Receivable - SFTB` |
| Payable Account | `22040100002 - Accounts Payable Control Account - SFTB` |
| Income Account | `41010100001 - Sales Revenue - SFTB` |
| VAT / Tax Account | `22040200002 - VAT Output A/c - SFTB` |
| Expense / COGS Account | `510104 - Local Landing Cost - SFTB` |
| Default Warehouse | `Stores - SFTB` |
| Invoice From Date | `2022-01-02` |
| Invoice To Date | `2025-05-29` |
| Skip Existing Records | ✓ Enabled |
| Submit Invoices | ✗ Draft only |

---

## Architecture

### Performance Optimisations
- **Pre-cached lookups**: Customer, Supplier, Item, Item Name caches loaded once at start
- **Batch commits**: Every 500 records (not per-record)
- **Stop flag**: Check `Migration Log.status == "Stop Requested"` every 50 records
- **No gunicorn timeout**: All imports use `frappe.enqueue` → RQ long-queue worker

### Error Handling
- Each invoice error is caught individually — other invoices continue
- `frappe.db.rollback()` on invoice error only (customer/item creation committed immediately)
- Full error log stored in `ePromise Migration Log.log_details`
- Stuck "Running" logs can be marked Failed via the cleanup script

### Worker Setup

Start the background worker before importing:
```bash
cd /home/gym/new-bench
./env/bin/python -c "
from rq import Worker, Queue
from redis import Redis
r = Redis(host='127.0.0.1', port=11007)
Worker([Queue('frappe:long', connection=r), Queue('frappe:default', connection=r)], connection=r).work()
" >> logs/worker.log 2>> logs/worker.error.log &
```

Redis port is `11007` (see `/home/gym/new-bench/config/redis_queue.conf`).

---

## Reports & Monitoring

### `/app/epromise-mapping-guide`

| Section | Description |
|---------|-------------|
| **Import Status Dashboard** | Live ERPNext counts with `⚡ Refresh` |
| **ePromise → ERPNext Import Report** | Enter date range → counts + amounts per TRC code with progress bars; click any row to see individual vouchers |
| **Daily Collection Report** | Matches ePromise's own Daily Transaction-wise Report format; select branch for branch-specific data |

### Daily Collection Report Structure

```
CASH SALES (NET)              ← S06 net (excl. VAT), branch-filtered
  Gross POS Sales             ← S06 ACC_AMT
  VAT Collected               ← S06 VAT_AMT
CREDIT SALES (NET)            ← S01 net, branch-filtered
  ...
SALES RETURNS                 ← R04/R01 net (excl. VAT refund)
CREDIT PURCHASE               ← GRN + 111 net (branch-filtered); NOT 350
CASH RECEIVED: CREDIT SALES   ← All 004 vouchers (company-wide)
PAYMENTS - PETTY CASH         ← DICADDATA credits on branch petty cash account
RECEIPTS - PETTY CASH         ← DICADDATA debits on branch petty cash account
CASH BALANCE                  = Total Receipts - Total Payments
```

---

## File Structure

```
apps/backup/backup/epromise_migration/
├── utils/
│   ├── bak_parser.py           # SQL Server connection (connect_mssql)
│   ├── connection_test.py      # @whitelist test_connection()
│   ├── customer_importer.py    # DICADMAS sub_head=D → Customer
│   ├── supplier_importer.py    # DICADMAS sub_head=C → Supplier
│   ├── invoice_importer.py     # S01, S06, R01, R04 → Sales Invoice
│   ├── receipt_importer.py     # GRN, GR → Purchase Receipt
│   ├── purchase_importer.py    # 350, 111, IP, PR → Purchase Invoice
│   ├── payment_importer.py     # 003, 004, 020, 007 → Payment Entry / Journal Entry
│   └── mapping_seeder.py       # 40+ field mappings (seed from migration page)
├── doctype/
│   ├── epromise_settings/      # Single DocType — all configuration
│   ├── epromise_field_mapping/ # Field-level mapping rules
│   └── epromise_migration_log/ # Import run log with counts + log_details
└── page/
    ├── epromise_migration/     # Migration dashboard (import buttons)
    └── epromise_mapping_guide/ # Mapping guide + reports
```

---

## Troubleshooting

| Problem | Cause | Fix |
|---------|-------|-----|
| Worker not processing | RQ worker not running | Start worker (see above) |
| Log stuck as "Running" | Worker killed mid-import | Run fix_stuck.py script or mark as Failed in UI |
| "Supplier does not exist" | Supplier not created before invoice import | Run **Import Suppliers** (Step 1b) first |
| "Not marked as purchase item" | Item created during sales import with `is_purchase_item=0` | Run **Import Purchase Invoices** — it bulk-sets `is_purchase_item=1` |
| `'str' object does not support item assignment` | Field mapping maps to child table field (e.g. `sales_team`) | Check **ePromise Field Mapping** — remove any `target_field` = `sales_team`, `items`, `taxes` |
| Import very slow | Too many DB queries | Check worker has latest code (restart worker after code changes) |
| 0 records for date range | Reversed dates (from > to) | Fix dates in **Import Date Range** card on migration page |
| `X_UNIT` invalid column | DICZDATA has no X_UNIT | Already fixed — uses `im.ITE_UNIT AS X_UNIT` in query |
| Payment entry references = 0 | Invoices not imported yet | Import invoices BEFORE payment vouchers |
| Petty cash values don't match | Branch petty cash account not detected | Ensure S06 transactions exist for the branch in the date range |

---

## Post-Migration Steps

1. **Payment Reconciliation**: Go to **Accounts → Payment Reconciliation** to formally link Payment Entries to outstanding invoices
2. **Item Stock Conversion**: If items should be stock items, update `is_stock_item=1` and configure warehouses
3. **Account Number Setup**: Add ePromise account codes to ERPNext Account `account_number` field for better GL matching
4. **Opening Balances**: Import Opening JV (TRC=OJV) records separately if needed
5. **Verify Totals**: Use the **Daily Collection Report** to cross-check imported amounts against ePromise reports

---

*Last updated: 2026-06 · Author: siva@enfono.com*
