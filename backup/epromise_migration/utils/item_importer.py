"""
Imports Item Master records from the Bahrain Master Excel into ERPNext.

Source:  Copy of Bahrain Master 16.6.26 (1) (1).xls
Mapping:
  Unified Code        → item_code   (ERPNext identifier)
  ERP NEXT Item Name  → item_name
  Unit                → stock_uom
  Resource Code       → epromise_ite_code (custom field — traceability)

Items where Resource Code == Unified Code (no consolidation) are inserted once.
Items that have already been inserted are skipped (idempotent).
"""

import frappe
from frappe.utils import now_datetime

from backup.epromise_migration.utils.unified_code_map import load_unified_map
from backup.epromise_migration.utils.invoice_importer import _map_uom, _ensure_uom

BATCH_SIZE = 200


def _ensure_item_custom_field():
    """Create epromise_ite_code on Item for traceability back to ePromise Resource Code."""
    if not frappe.db.exists("Custom Field", {"dt": "Item", "fieldname": "epromise_ite_code"}):
        frappe.get_doc({
            "doctype": "Custom Field",
            "dt": "Item",
            "fieldname": "epromise_ite_code",
            "label": "ePromise Resource Code",
            "fieldtype": "Data",
            "insert_after": "item_code",
            "read_only": 1,
            "search_index": 1,
        }).insert(ignore_permissions=True)
        frappe.db.commit()


def _get_settings():
    return frappe.get_single("ePromise Settings")


def _run_item_import(log_name):
    settings  = _get_settings()
    log       = frappe.get_doc("ePromise Migration Log", log_name)
    log.status = "Running"
    log.save(ignore_permissions=True)
    frappe.db.commit()

    try:
        _ensure_item_custom_field()

        unified_map = load_unified_map()
        if not unified_map:
            log.reload()
            log.status = "Failed"
            log.log_details = (
                "Bahrain Master file not found. Place "
                "'Copy of Bahrain Master 16.6.26 (1) (1).xls' "
                "in the apps/backup/ directory and retry."
            )
            log.completed_at = now_datetime()
            log.save(ignore_permissions=True)
            frappe.db.commit()
            return

        item_group = settings.default_item_group or "Products"

        # Build a de-duplicated set of (unified_code, row) — unified_code is the ERPNext key
        seen_codes = set()
        to_create  = []
        for resource_code, row in unified_map.items():
            unified_code = row["unified_code"]
            if unified_code in seen_codes:
                continue
            seen_codes.add(unified_code)
            to_create.append((resource_code, unified_code, row))

        total   = len(to_create)
        success = skipped = errors = 0
        log_lines = []

        # Pre-load existing items to avoid repeated DB hits
        existing_items = set(
            frappe.db.sql_list("SELECT name FROM `tabItem`")
        )

        for idx, (resource_code, unified_code, row) in enumerate(to_create, 1):
            if idx % 50 == 0:
                # Check for stop request
                if frappe.db.get_value("ePromise Migration Log", log.name, "status") == "Stop Requested":
                    frappe.db.commit()
                    log.reload()
                    log.status   = "Stopped"
                    log.total_records = total
                    log.success_count = success
                    log.skipped_count = skipped
                    log.error_count   = errors
                    log.completed_at  = now_datetime()
                    log.log_details   = "\n".join(log_lines[-200:])
                    log.save(ignore_permissions=True)
                    frappe.db.commit()
                    return

            if unified_code in existing_items:
                skipped += 1
                continue

            item_name = (row.get("ite_name") or unified_code).strip()
            uom       = _ensure_uom(_map_uom(row.get("ite_unit") or "NOS"))

            try:
                doc = frappe.get_doc({
                    "doctype": "Item",
                    "item_code": unified_code,
                    "item_name": item_name,
                    "item_group": item_group,
                    "stock_uom": uom,
                    "is_stock_item": 1,
                    "is_sales_item": 1,
                    "is_purchase_item": 1,
                    "description": item_name,
                    "epromise_ite_code": resource_code,
                })
                doc.insert(ignore_permissions=True)
                existing_items.add(unified_code)
                success += 1

                if success % BATCH_SIZE == 0:
                    frappe.db.commit()
                    frappe.db.set_value("ePromise Migration Log", log.name, {
                        "success_count": success,
                        "error_count": errors,
                        "total_records": total,
                        "skipped_count": skipped,
                    })
                    frappe.db.commit()

            except Exception as e:
                errors += 1
                frappe.db.rollback()
                log_lines.append(f"[ERR] {unified_code} — {item_name}: {e}")

        frappe.db.commit()
        log.reload()
        log.status        = "Completed"
        log.total_records = total
        log.success_count = success
        log.skipped_count = skipped
        log.error_count   = errors
        log.completed_at  = now_datetime()
        log.log_details   = "\n".join(log_lines) if log_lines else f"Done. {success} created, {skipped} skipped."
        log.save(ignore_permissions=True)
        frappe.db.commit()

    except Exception as e:
        frappe.db.commit()
        log.reload()
        log.status     = "Failed"
        log.log_details = f"Fatal error: {e}"
        log.completed_at = now_datetime()
        log.save(ignore_permissions=True)
        frappe.db.commit()


@frappe.whitelist()
def import_item_master():
    """
    Bulk-import Item records from the Bahrain Master Excel file into ERPNext.
    Runs in the background queue; returns a log_name to track progress.
    """
    settings = _get_settings()
    if not settings.erpnext_company:
        frappe.throw("Please configure ePromise Settings (Company) before importing items.")

    log = frappe.get_doc({
        "doctype": "ePromise Migration Log",
        "migration_type": "Item Master",
        "status": "Queued",
        "started_at": now_datetime(),
    })
    log.insert(ignore_permissions=True)
    frappe.db.commit()

    frappe.enqueue(
        "backup.epromise_migration.utils.item_importer._run_item_import",
        log_name=log.name,
        queue="long",
        timeout=3600,
        job_name=f"epromise-items-{log.name}",
    )
    return {
        "log_name": log.name,
        "status":   "queued",
        "message":  f"Item Master import queued. Track in {log.name}.",
    }
