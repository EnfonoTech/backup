"""
Imports Purchase Receipts from ePromise into ERPNext.
  GRN (Goods Receiving Note) → Purchase Receipt
  GR  (Goods Return)         → Purchase Receipt (is_return=1, return_against=original)
Items from PURCHASE_DATA. Suppliers from DICADMAS (sub_head=C).
"""

import frappe
from frappe.utils import now_datetime, flt, getdate
from backup.epromise_migration.utils.bak_parser import connect_mssql
from backup.epromise_migration.utils.invoice_importer import (
    _map_uom, _ensure_uom, _preload_item_cache, _preload_item_name_cache,
    _get_or_create_item, _load_item_master_live, _ensure_placeholder_item,
)
from backup.epromise_migration.utils.purchase_importer import (
    _ensure_supplier_custom_field, _preload_supplier_cache,
    _ensure_suppliers_from_epromise, _get_or_create_supplier,
)

GRN_TRC_CODES    = ("GRN",)
RETURN_TRC_CODES = ("GR",)
ALL_RECEIPT_TRC  = GRN_TRC_CODES + RETURN_TRC_CODES
BATCH_SIZE       = 500

# TRC → (epromise_invoice_type label, is_return)
_TRC_PR_META = {
    "GRN": ("GRN (Goods Received)", False),
    "GR":  ("GR (Goods Return)",    True),
}


def _get_settings():
    return frappe.get_single("ePromise Settings")


def _ensure_custom_fields():
    """Add ePromise traceability fields to Purchase Receipt and Purchase Receipt Item."""
    pr_fields = [
        {
            "dt": "Purchase Receipt", "fieldname": "epromise_vr_no",
            "label": "ePromise Voucher No", "fieldtype": "Data",
            "insert_after": "naming_series", "read_only": 1, "search_index": 1,
        },
        {
            "dt": "Purchase Receipt", "fieldname": "epromise_trc_code",
            "label": "ePromise TRC Code", "fieldtype": "Data",
            "insert_after": "epromise_vr_no", "read_only": 1,
        },
        {
            "dt": "Purchase Receipt", "fieldname": "epromise_invoice_type",
            "label": "Invoice Type", "fieldtype": "Select",
            "options": "\nGRN (Goods Received)\nGR (Goods Return)",
            "insert_after": "epromise_trc_code", "read_only": 1,
            "in_list_view": 1, "bold": 1,
        },
    ]
    item_fields = [
        {
            "dt": "Purchase Receipt Item", "fieldname": "epromise_ite_code",
            "label": "ePromise Item Code", "fieldtype": "Data",
            "insert_after": "item_code", "read_only": 1, "in_list_view": 1,
        },
    ]
    for f in pr_fields + item_fields:
        if not frappe.db.exists("Custom Field", {"dt": f["dt"], "fieldname": f["fieldname"]}):
            cf = {
                "doctype": "Custom Field",
                "dt": f["dt"],
                "label": f["label"],
                "fieldname": f["fieldname"],
                "fieldtype": f.get("fieldtype", "Data"),
                "insert_after": f["insert_after"],
                "read_only": f.get("read_only", 0),
                "search_index": f.get("search_index", 0),
                "in_list_view": 1 if f.get("in_list_view") else 0,
                "bold": 1 if f.get("bold") else 0,
            }
            if f.get("options"):
                cf["options"] = f["options"]
            frappe.get_doc(cf).insert(ignore_permissions=True)
    frappe.db.commit()


def _ensure_default_warehouse_field():
    """Ensure default_warehouse field exists on ePromise Settings (as Custom Field if needed)."""
    if not frappe.db.exists("Custom Field", {"dt": "ePromise Settings", "fieldname": "default_warehouse"}):
        # Check if it's already in the core DocType JSON (it won't be, so add it)
        if not frappe.db.get_value("DocField",
                {"parent": "ePromise Settings", "fieldname": "default_warehouse"}, "name"):
            frappe.get_doc({
                "doctype": "Custom Field",
                "dt": "ePromise Settings",
                "label": "Default Warehouse",
                "fieldname": "default_warehouse",
                "fieldtype": "Link",
                "options": "Warehouse",
                "insert_after": "default_expense_account",
                "description": "Default warehouse for Purchase Receipt items. Leave blank to auto-detect.",
            }).insert(ignore_permissions=True)
            frappe.db.commit()


def _get_default_warehouse(settings):
    """Return a usable warehouse name from settings or by auto-detecting from company."""
    wh = getattr(settings, "default_warehouse", None)
    if wh and frappe.db.exists("Warehouse", wh):
        return wh
    company = settings.erpnext_company
    if company:
        abbr = frappe.db.get_value("Company", company, "abbr") or "K"
        # Prefer "Stores - <abbr>" if it exists
        stores = f"Stores - {abbr}"
        if frappe.db.exists("Warehouse", stores):
            return stores
        # Fall back to first non-group warehouse for this company
        default_wh = frappe.db.get_value(
            "Warehouse",
            {"company": company, "is_group": 0},
            "name",
            order_by="creation asc",
        )
        if default_wh:
            return default_wh
        return stores
    abbr = "K"
    return f"Stores - {abbr}"


def _iter_receipts(settings, trc_codes=None):
    """Yield (header_row, [item_rows]) for each GRN/GR purchase receipt."""
    if trc_codes is None:
        trc_codes = ALL_RECEIPT_TRC
    if not settings.mssql_host:
        frappe.throw("Purchase Receipt import requires a live SQL Server connection.")

    from_date = settings.invoice_from_date or None
    to_date   = settings.invoice_to_date   or None

    conn = connect_mssql(settings)
    cur  = conn.cursor()
    trc_ph = "','".join(trc_codes)

    hdr_filter, join_filter, params = "", "", []
    if from_date:
        hdr_filter  += f" AND CAST(VR_DATE AS DATE) >= '{str(from_date)[:10]}'"
        join_filter += f" AND CAST(dh.VR_DATE AS DATE) >= '{str(from_date)[:10]}'"
    if to_date:
        hdr_filter  += f" AND CAST(VR_DATE AS DATE) <= '{str(to_date)[:10]}'"
        join_filter += f" AND CAST(dh.VR_DATE AS DATE) <= '{str(to_date)[:10]}'"

    cur.execute(
        f"SELECT * FROM DICHDATA WHERE TRC_CODE IN ('{trc_ph}') AND POSTED_IND='Y'{hdr_filter} ORDER BY VR_NO",
        params,
    )
    hdrs = {}
    for r in cur:
        row = {k.lower(): v for k, v in dict(r).items()}
        hdrs[str(row["vr_no"])] = row

    from collections import defaultdict
    lines = defaultdict(list)

    cur.execute(
        f"""
        SELECT
            pd.TRC_CODE, pd.VR_NO, pd.SR_NO,
            pd.ITE_CODE, pd.ITE_QTY, pd.ITE_RATE,
            pd.X_UNIT, pd.VAT_RATE,
            im.ITE_NAME, im.ITE_UNIT AS BASE_UOM
        FROM PURCHASE_DATA pd
        INNER JOIN DICHDATA dh ON dh.TRC_CODE=pd.TRC_CODE AND dh.VR_NO=pd.VR_NO
        LEFT JOIN DICIHMAS im ON im.ITE_CODE=pd.ITE_CODE
        WHERE pd.TRC_CODE IN ('{trc_ph}')
          AND dh.POSTED_IND='Y'{join_filter}
        """,
        params,
    )
    for r in cur:
        row = {k.lower(): v for k, v in dict(r).items()}
        if not row.get("x_unit") and row.get("base_uom"):
            row["x_unit"] = row["base_uom"]
        lines[str(row["vr_no"])].append(row)

    conn.close()
    for vr_no, hdr in hdrs.items():
        yield hdr, lines.get(vr_no, [])


def _build_receipt(hdr, item_lines, item_master_map, placeholder_code,
                   settings, supplier_cache, item_cache, item_name_cache,
                   warehouse, grn_pr_map=None):
    """Map ePromise header + lines to an ERPNext Purchase Receipt dict."""
    trc_code  = hdr.get("trc_code", "")
    vr_no     = str(hdr.get("vr_no") or "").strip()
    acc_code  = (hdr.get("acc_code") or "").strip()
    acc_name  = (hdr.get("acc_name") or acc_code or "Unknown").strip()
    currency  = (hdr.get("cur_code") or settings.default_currency or "BHD").strip()
    vat_amt   = flt(hdr.get("vat_amt") or 0)
    acc_amt   = flt(hdr.get("acc_amt") or 0)
    net_amt   = acc_amt - vat_amt
    bill_no   = (hdr.get("bill_no") or "").strip()

    try:
        posting_date = getdate(str(hdr.get("vr_date") or "")[:10])
    except Exception:
        posting_date = getdate("2024-01-01")

    if not acc_code or not vr_no:
        return None

    meta = _TRC_PR_META.get(trc_code, ("GRN (Goods Received)", False))
    invoice_type_label, is_return = meta

    supplier = _get_or_create_supplier(acc_code, acc_name, settings, supplier_cache)

    expense_account = settings.default_expense_account or settings.default_income_account

    receipt_items = []
    for line in item_lines:
        orig_ite  = (line.get("ite_code") or "").strip()
        ite_code  = _get_or_create_item(orig_ite, item_master_map, settings, item_cache)
        uom       = _ensure_uom(_map_uom(line.get("x_unit") or line.get("base_uom")))
        qty       = flt(line.get("ite_qty") or 1)
        rate      = flt(line.get("ite_rate") or 0)
        item_name = item_name_cache.get(ite_code) or \
            (item_master_map.get(orig_ite) or {}).get("ite_name") or orig_ite
        item_name_cache[ite_code] = item_name

        receipt_items.append({
            "item_code": ite_code,
            "item_name": item_name,
            "epromise_ite_code": orig_ite,
            "accepted_qty": qty or 1,
            "rejected_qty": 0,
            "qty": qty or 1,
            "rate": rate,
            "uom": uom,
            "stock_uom": uom,
            "warehouse": warehouse,
            "expense_account": expense_account,
            "description": item_name,
        })

    if not receipt_items:
        rate = net_amt if net_amt > 0 else acc_amt
        receipt_items.append({
            "item_code": placeholder_code,
            "item_name": "ePromise Import (No Item Detail)",
            "epromise_ite_code": "",
            "accepted_qty": 1,
            "rejected_qty": 0,
            "qty": 1,
            "rate": rate,
            "uom": "Nos",
            "stock_uom": "Nos",
            "warehouse": warehouse,
            "expense_account": expense_account,
            "description": f"Ref: {bill_no or vr_no} | {acc_name}",
        })

    taxes = []
    if vat_amt and settings.default_tax_account and flt(vat_amt) != 0:
        taxes.append({
            "charge_type": "Actual",
            "account_head": settings.default_tax_account,
            "description": "VAT",
            "tax_amount": flt(vat_amt),
        })

    doc = {
        "doctype": "Purchase Receipt",
        "naming_series": "MAT-PRE-.YYYY.-",
        "company": settings.erpnext_company,
        "supplier": supplier,
        "posting_date": posting_date,
        "set_posting_time": 1,
        "currency": currency,
        "conversion_rate": flt(hdr.get("cur_rate") or 1) or 1,
        "items": receipt_items,
        "epromise_vr_no": vr_no,
        "epromise_trc_code": trc_code,
        "epromise_invoice_type": invoice_type_label,
        "is_return": 1 if is_return else 0,
        "disable_rounded_total": 1,
    }

    if bill_no:
        doc["bill_no"] = bill_no
        doc["bill_date"] = posting_date

    if taxes:
        doc["taxes"] = taxes

    if is_return:
        ref_vr = str(hdr.get("ref_vr_no") or "").strip()
        if ref_vr:
            orig = (grn_pr_map or {}).get(ref_vr) or frappe.db.get_value(
                "Purchase Receipt", {"epromise_vr_no": ref_vr}, "name")
            if orig:
                doc["return_against"] = orig
            else:
                doc["remarks"] = f"Return of ePromise GRN/{ref_vr}"

    # Calculate totals manually (ignore_validate=True bypasses ERPNext calculation)
    items = doc.get("items") or []
    cr = flt(hdr.get("cur_rate") or 1) or 1.0
    total = sum(flt(it.get("qty") or 0) * flt(it.get("rate") or 0) for it in items)
    for it in items:
        qty  = flt(it.get("qty") or 0)
        rate = flt(it.get("rate") or 0)
        amt  = qty * rate
        it["amount"]      = flt(amt, 9)
        it["base_amount"] = flt(amt * cr, 9)
    doc["total"]           = flt(total, 9)
    doc["net_total"]       = flt(total, 9)
    doc["grand_total"]     = flt(total, 9)
    doc["base_total"]      = flt(total * cr, 9)
    doc["base_net_total"]  = flt(total * cr, 9)
    doc["base_grand_total"]= flt(total * cr, 9)
    return doc


def _run_receipt_import(log_name):
    settings = _get_settings()
    log = frappe.get_doc("ePromise Migration Log", log_name)
    log.status = "Running"
    log.save(ignore_permissions=True)
    frappe.db.commit()

    from backup.epromise_migration.utils.invoice_importer import _validate_date_range
    _validate_date_range(settings)

    _ensure_supplier_custom_field()
    _ensure_custom_fields()
    _ensure_default_warehouse_field()
    _ensure_suppliers_from_epromise(settings)

    placeholder_code = _ensure_placeholder_item(settings)
    warehouse        = _get_default_warehouse(settings)

    conn = connect_mssql(settings)
    item_master_map = _load_item_master_live(conn)
    conn.close()

    frappe.db.sql("UPDATE `tabItem` SET is_purchase_item=1 WHERE is_purchase_item=0")
    frappe.db.commit()

    supplier_cache  = _preload_supplier_cache()
    item_cache      = _preload_item_cache()
    item_name_cache = _preload_item_name_cache()

    # Pre-load GRN→PR name map for GR return linking
    grn_pr_map = {}
    grn_rows = frappe.db.get_all(
        "Purchase Receipt",
        filters={"epromise_vr_no": ["!=", ""], "epromise_trc_code": "GRN"},
        fields=["name", "epromise_vr_no"],
    )
    for r in grn_rows:
        if r.epromise_vr_no:
            grn_pr_map[str(r.epromise_vr_no)] = r.name

    existing = set()
    if settings.skip_existing:
        rows = frappe.db.get_all(
            "Purchase Receipt",
            filters={"epromise_vr_no": ["!=", ""]},
            fields=["epromise_vr_no", "epromise_trc_code"],
        )
        existing = {(r.epromise_trc_code, r.epromise_vr_no) for r in rows}

    total = success = skipped = errors = 0
    log_lines = []
    frappe.flags.in_import = True
    frappe.flags.ignore_account_permission = True

    try:
        for hdr, item_lines in _iter_receipts(settings):
            total += 1
            vr_no    = str(hdr.get("vr_no") or "").strip()
            trc_code = hdr.get("trc_code", "")
            acc_name = (hdr.get("acc_name") or "").strip()

            if not vr_no:
                skipped += 1
                continue

            if total % 50 == 0:
                if frappe.db.get_value("ePromise Migration Log", log.name, "status") == "Stop Requested":
                    frappe.db.commit()
                    log.reload()
                    log.status = "Stopped"
                    log.total_records = total
                    log.success_count = success
                    log.skipped_count = skipped
                    log.error_count = errors
                    log.completed_at = now_datetime()
                    log.log_details = "\n".join(log_lines[-500:])
                    log.save(ignore_permissions=True)
                    frappe.db.commit()
                    return

            if settings.skip_existing and (trc_code, vr_no) in existing:
                skipped += 1
                continue

            try:
                doc_dict = _build_receipt(
                    hdr, item_lines, item_master_map, placeholder_code,
                    settings, supplier_cache, item_cache, item_name_cache,
                    warehouse, grn_pr_map=grn_pr_map,
                )
                if not doc_dict:
                    skipped += 1
                    continue

                pr_doc = frappe.get_doc(doc_dict)
                pr_doc.flags.ignore_permissions = True
                pr_doc.flags.ignore_mandatory = True
                pr_doc.flags.ignore_links = True
                pr_doc.flags.ignore_validate = True
                pr_doc.flags.ignore_version = True
                pr_doc.flags.ignore_feed = True
                pr_doc.insert(ignore_permissions=True)

                success += 1
                existing.add((trc_code, vr_no))
                # Update live map so subsequent GR returns can link to newly inserted GRN
                if trc_code == "GRN":
                    grn_pr_map[vr_no] = pr_doc.name

                if success % BATCH_SIZE == 0:
                    frappe.db.commit()
                    frappe.db.set_value("ePromise Migration Log", log.name, {
                        "success_count": success, "error_count": errors,
                        "total_records": total, "skipped_count": skipped,
                    })
                    frappe.db.commit()

            except Exception as e:
                errors += 1
                frappe.db.rollback()
                log_lines.append(f"[ERR] {trc_code}/{vr_no} — {acc_name}: {e}")

    except Exception as e:
        frappe.flags.in_import = False
        frappe.flags.ignore_account_permission = False
        frappe.db.commit()
        log.reload()
        log.status = "Failed"
        log.log_details = f"Fatal error: {e}\n" + "\n".join(log_lines[-200:])
        log.total_records = total
        log.success_count = success
        log.skipped_count = skipped
        log.error_count = errors
        log.completed_at = now_datetime()
        log.save(ignore_permissions=True)
        frappe.db.commit()
        return

    frappe.flags.in_import = False
    frappe.flags.ignore_account_permission = False
    frappe.db.commit()
    log.reload()
    log.status = "Completed"
    log.total_records = total
    log.success_count = success
    log.skipped_count = skipped
    log.error_count = errors
    log.completed_at = now_datetime()
    log.log_details = "\n".join(log_lines)
    log.save(ignore_permissions=True)
    frappe.db.commit()


@frappe.whitelist()
def import_purchase_receipts():
    """GRN (Goods Receiving Note) and GR (Goods Return) → Purchase Receipt."""
    settings = _get_settings()
    if not settings.erpnext_company:
        frappe.throw("Please configure ePromise Settings before importing.")
    if not settings.mssql_host:
        frappe.throw("Purchase Receipt import requires a live SQL Server connection.")

    log = frappe.get_doc({
        "doctype": "ePromise Migration Log",
        "migration_type": "Purchase Receipt",
        "status": "Queued",
        "started_at": now_datetime(),
    })
    log.insert(ignore_permissions=True)
    frappe.db.commit()

    frappe.enqueue(
        "backup.epromise_migration.utils.receipt_importer._run_receipt_import",
        log_name=log.name,
        queue="long",
        timeout=7200,
        job_name=f"epromise-pr-{log.name}",
    )
    return {
        "log_name": log.name,
        "status": "queued",
        "message": f"Purchase Receipts import queued. Track in {log.name}.",
    }


@frappe.whitelist()
def stop_import(log_name):
    """Request a running receipt import to stop after the current batch."""
    status = frappe.db.get_value("ePromise Migration Log", log_name, "status")
    if status not in ("Running", "Queued"):
        return {"ok": False, "message": f"Cannot stop — current status is '{status}'"}
    frappe.db.set_value("ePromise Migration Log", log_name, "status", "Stop Requested")
    frappe.db.commit()
    return {"ok": True, "message": "Stop requested — will halt after current batch."}
