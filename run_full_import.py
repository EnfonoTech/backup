"""
Full Sequential ePromise → ERPNext Import Runner
=================================================
Runs all 9 import steps in the correct order, one at a time.

RESUMABLE: skips any step whose migration type already has a
           "Completed" log in ERPNext (safe to re-run at any time).

Usage:
    cd /home/gym/new-bench
    ./env/bin/python apps/backup/run_full_import.py

    # Force a specific step to re-run even if already completed:
    ./env/bin/python apps/backup/run_full_import.py --force-step 2

Output:
    Prints live progress to stdout.
    Tee to a log file: ... 2>&1 | tee logs/epromise_import.log
"""

import os
import sys
import time
import argparse

os.chdir("/home/gym/new-bench")
sys.path.insert(0, "/home/gym/new-bench/apps/frappe")
sys.path.insert(0, "/home/gym/new-bench/apps/erpnext")
sys.path.insert(0, "/home/gym/new-bench/apps/backup")

import frappe
from frappe.utils import now_datetime

frappe.init(site="ksa", sites_path="/home/gym/new-bench/sites")
frappe.connect()
frappe.set_user("Administrator")

parser = argparse.ArgumentParser(description="Full ePromise import runner")
parser.add_argument("--force-step", type=str, default=None,
    help="Step label to force-rerun even if already completed (e.g. '2' or '5')")
args = parser.parse_args()
FORCE_STEP = args.force_step


# ─── helpers ──────────────────────────────────────────────────────────────────

def banner(msg):
    print("\n" + "=" * 68)
    print(f"  {msg}")
    print("=" * 68)


def step_header(step_id, label):
    print(f"\n{'─' * 68}")
    print(f"  STEP {step_id}: {label}")
    print(f"{'─' * 68}")


def print_result(r):
    if not r:
        return
    total   = r.get("total", 0)
    success = r.get("success", 0)
    skipped = r.get("skipped", 0)
    errors  = r.get("errors", 0)
    log     = r.get("log_name", "")
    icon    = "✅" if errors == 0 else "⚠️ "
    print(f"  {icon} {success:,} created  |  {skipped:,} skipped  |  {errors:,} errors  |  total {total:,}")
    if log:
        print(f"     Log: {log}")


def already_done(migration_type, force=False):
    """Return True if this migration type already has a Completed log."""
    if force:
        return False
    done = frappe.db.get_value(
        "ePromise Migration Log",
        {"migration_type": migration_type, "status": "Completed"},
        "name",
    )
    return bool(done)


def make_log(migration_type):
    log = frappe.get_doc({
        "doctype": "ePromise Migration Log",
        "migration_type": migration_type,
        "status": "Queued",
        "started_at": now_datetime(),
    })
    log.insert(ignore_permissions=True)
    frappe.db.commit()
    return log.name


def run_step(step_id, label, migration_type, runner_fn, force=False):
    """Run one import step with resume-check, timing, and result printing."""
    step_header(step_id, label)

    if already_done(migration_type, force=force):
        prev = frappe.db.get_value(
            "ePromise Migration Log",
            {"migration_type": migration_type, "status": "Completed"},
            ["name", "success_count", "error_count", "skipped_count"],
            as_dict=True,
        )
        print(f"  ⏭  Already completed — skipping.")
        print(f"     Previous log: {prev.name}  |  "
              f"{prev.success_count or 0} created, {prev.skipped_count or 0} skipped, "
              f"{prev.error_count or 0} errors")
        return

    t0 = time.time()
    try:
        result = runner_fn()
        if result:
            print_result(result)
        print(f"  Time: {int(time.time()-t0)}s")
    except Exception as e:
        print(f"  ❌ FAILED: {e}")
        print(f"  Time: {int(time.time()-t0)}s")
        raise


# ─── lazy imports (avoid loading all modules at startup) ──────────────────────

banner("ePromise → ERPNext Full Import  |  Steel Force Trading Bahrain")
print(f"  Started: {now_datetime()}")
print(f"  Resume mode: {'ON (skips completed steps)' if not FORCE_STEP else f'Force step {FORCE_STEP}'}")


# ─── STEP 1a — Customers ──────────────────────────────────────────────────────

def _run_customers():
    from backup.epromise_migration.utils.customer_importer import import_customers
    return import_customers()

run_step("1a", "Import Customer Master (DICADMAS sub_head=D)",
         "Customer Master", _run_customers,
         force=(FORCE_STEP == "1a"))


# ─── STEP 1b — Suppliers ─────────────────────────────────────────────────────

def _run_suppliers():
    from backup.epromise_migration.utils.supplier_importer import import_suppliers
    return import_suppliers()

run_step("1b", "Import Supplier Master (DICADMAS sub_head=C)",
         "Supplier Master", _run_suppliers,
         force=(FORCE_STEP == "1b"))


# ─── STEP 2 — Sales Invoices (S01, S06) ──────────────────────────────────────

def _run_sinv():
    from backup.epromise_migration.utils.invoice_importer import (
        _run_sales_import, SALES_TRC_CODES,
        _ensure_custom_fields, _ensure_naming_series,
    )
    _ensure_custom_fields()
    _ensure_naming_series()
    log_name = make_log("Sales Invoice")
    _run_sales_import(log_name, trc_codes=SALES_TRC_CODES)
    log = frappe.get_doc("ePromise Migration Log", log_name)
    return {"total": log.total_records, "success": log.success_count,
            "skipped": log.skipped_count, "errors": log.error_count, "log_name": log_name}

run_step("2", "Import Sales Invoices (S01=Credit, S06=POS)",
         "Sales Invoice", _run_sinv,
         force=(FORCE_STEP == "2"))


# ─── STEP 2b — Sales Returns (R01, R04) ──────────────────────────────────────

def _run_sret():
    from backup.epromise_migration.utils.invoice_importer import (
        _run_sales_import, SALES_RETURN_TRC_CODES,
    )
    log_name = make_log("Sales Return")
    _run_sales_import(log_name, trc_codes=SALES_RETURN_TRC_CODES)
    log = frappe.get_doc("ePromise Migration Log", log_name)
    return {"total": log.total_records, "success": log.success_count,
            "skipped": log.skipped_count, "errors": log.error_count, "log_name": log_name}

run_step("2b", "Import Sales Returns (R01=Credit Return, R04=POS Return)",
         "Sales Return", _run_sret,
         force=(FORCE_STEP == "2b"))


# ─── STEP 3 — Purchase Receipts (GRN, GR) ────────────────────────────────────

# STEP 3 — Purchase Receipts SKIPPED: creates stock ledger entries, not needed for financial migration
step_header("3", "Purchase Receipts — SKIPPED (stock impact not required)")
print("  ⏭  Skipped by design: Purchase Receipts create stock entries. Import PI directly.")


# ─── STEP 4 — Purchase Invoices (350, 111, IP) ───────────────────────────────

def _run_pinv():
    from backup.epromise_migration.utils.purchase_importer import (
        _run_purchase_import, PURCHASE_INVOICE_TRC_CODES,
    )
    log_name = make_log("Purchase Invoice")
    _run_purchase_import(log_name, trc_codes=list(PURCHASE_INVOICE_TRC_CODES))
    log = frappe.get_doc("ePromise Migration Log", log_name)
    return {"total": log.total_records, "success": log.success_count,
            "skipped": log.skipped_count, "errors": log.error_count, "log_name": log_name}

run_step("4", "Import Purchase Invoices (350=Item-wise, 111=Direct, IP=Import)",
         "Purchase Invoice", _run_pinv,
         force=(FORCE_STEP == "4"))


# ─── STEP 4b — Purchase Returns (PR) ─────────────────────────────────────────

def _run_pret():
    from backup.epromise_migration.utils.purchase_importer import (
        _run_purchase_import, PURCHASE_RETURN_TRC_CODES,
    )
    log_name = make_log("Purchase Return")
    _run_purchase_import(log_name, trc_codes=list(PURCHASE_RETURN_TRC_CODES))
    log = frappe.get_doc("ePromise Migration Log", log_name)
    return {"total": log.total_records, "success": log.success_count,
            "skipped": log.skipped_count, "errors": log.error_count, "log_name": log_name}

run_step("4b", "Import Purchase Returns (PR)",
         "Purchase Return", _run_pret,
         force=(FORCE_STEP == "4b"))


# ─── STEP 5 — Payment Vouchers (003, 004) ────────────────────────────────────

def _run_pay():
    from backup.epromise_migration.utils.payment_importer import _run_voucher_import
    log_name = make_log("Payment Entry")
    _run_voucher_import(log_name, trc_codes=["003", "004"], migration_type="Payment Entry")
    log = frappe.get_doc("ePromise Migration Log", log_name)
    return {"total": log.total_records, "success": log.success_count,
            "skipped": log.skipped_count, "errors": log.error_count, "log_name": log_name}

run_step("5", "Import Payment Vouchers (003=Cash Payment, 004=Cash Receipt)",
         "Payment Entry", _run_pay,
         force=(FORCE_STEP == "5"))


# ─── STEP 6 — Journal Vouchers (020, 007) ────────────────────────────────────

def _run_jv():
    from backup.epromise_migration.utils.payment_importer import _run_voucher_import
    log_name = make_log("Journal Entry")
    _run_voucher_import(log_name, trc_codes=["020", "007"], migration_type="Journal Entry")
    log = frappe.get_doc("ePromise Migration Log", log_name)
    return {"total": log.total_records, "success": log.success_count,
            "skipped": log.skipped_count, "errors": log.error_count, "log_name": log_name}

run_step("6", "Import Journal Vouchers (020=Cash Adjustment, 007=Journal)",
         "Journal Entry", _run_jv,
         force=(FORCE_STEP == "6"))


# ─── SUMMARY ──────────────────────────────────────────────────────────────────

banner("IMPORT COMPLETE")
logs = frappe.db.get_all(
    "ePromise Migration Log",
    fields=["migration_type", "status", "success_count", "error_count",
            "skipped_count", "total_records", "started_at", "completed_at"],
    order_by="started_at asc",
)

# Keep only the last log per migration_type
seen = {}
for l in logs:
    seen[l.migration_type] = l
logs = list(seen.values())

print(f"\n  {'Step':<28} {'Status':<14} {'Created':>8} {'Errors':>7} {'Skipped':>8}")
print(f"  {'-'*28} {'-'*14} {'-'*8} {'-'*7} {'-'*8}")
all_ok = True
for l in logs:
    ok = l.status == "Completed" and (l.error_count or 0) == 0
    icon = "✅" if ok else ("⚠️ " if l.error_count else "❌")
    if not ok:
        all_ok = False
    print(f"  {icon} {l.migration_type:<26} {l.status:<14} "
          f"{(l.success_count or 0):>8,} {(l.error_count or 0):>7,} {(l.skipped_count or 0):>8,}")

print()
if all_ok:
    print("  All steps completed with 0 errors.")
    print("  → Now run:  ./env/bin/python apps/backup/export_to_excel.py")
else:
    print("  Some steps had errors — check the Migration Logs in ERPNext for details.")
    print("  → Re-run failed steps with:  --force-step <step_id>")
print()

frappe.destroy()
