"""
Imports Purchase Invoices from ePromise (live SQL Server) into ERPNext.

ePromise TRC → ERPNext mapping:
  350  — Purchase Invoice Item Wise  → Purchase Invoice (items from PURCHASE_INVOICE_DETAIL, linked to GRN Purchase Receipt)
  111  — Direct Purchase             → Purchase Invoice (standalone, items from PURCHASE_DATA)
  IP   — Import Purchase             → Purchase Invoice (items from PURCHASE_DATA + expense service items from DICADDATA acct 5...)
  PR   — Purchase Return             → Purchase Invoice (is_return=1, return_against=original PI)

Note: GRN and GR are handled by receipt_importer.py → Purchase Receipt.
Suppliers from DICADMAS sub_head = 'C'.
"""

import frappe
from frappe.utils import now_datetime, flt, getdate
from backup.epromise_migration.utils.bak_parser import connect_mssql
from backup.epromise_migration.utils.invoice_importer import (
    UOM_MAP, _map_uom, _ensure_uom, _ensure_placeholder_item,
    _load_item_master_live, _preload_item_cache, _preload_item_name_cache,
    _resolve_branch,
)

# GRN/GR removed — they go to receipt_importer.py → Purchase Receipt
PURCHASE_INVOICE_TRC_CODES = ("350", "111", "IP")
PURCHASE_RETURN_TRC_CODES  = ("PR",)
ALL_PURCHASE_TRC = PURCHASE_INVOICE_TRC_CODES + PURCHASE_RETURN_TRC_CODES

BATCH_SIZE = 500


# ─── helpers ──────────────────────────────────────────────────────────────────

def _get_settings():
    return frappe.get_single("ePromise Settings")


def _ensure_custom_fields():
    fields = [
        {"dt": "Purchase Invoice", "fieldname": "epromise_vr_no",      "label": "ePromise Voucher No",   "insert_after": "naming_series",    "search_index": 1},
        {"dt": "Purchase Invoice", "fieldname": "epromise_trc_code",    "label": "ePromise TRC Code",     "insert_after": "epromise_vr_no"},
        {"dt": "Purchase Invoice", "fieldname": "epromise_invoice_type","label": "Invoice Type",          "insert_after": "epromise_trc_code"},
        {"dt": "Purchase Invoice", "fieldname": "epromise_bill_no",     "label": "ePromise Bill No",      "insert_after": "epromise_invoice_type"},
    ]
    item_fields = [
        {"dt": "Purchase Invoice Item", "fieldname": "epromise_ite_code", "label": "ePromise Item Code", "insert_after": "item_code"},
    ]
    for f in fields + item_fields:
        if not frappe.db.exists("Custom Field", {"dt": f["dt"], "fieldname": f["fieldname"]}):
            frappe.get_doc({
                "doctype": "Custom Field",
                "dt": f["dt"],
                "label": f["label"],
                "fieldname": f["fieldname"],
                "fieldtype": "Data",
                "insert_after": f["insert_after"],
                "read_only": 1,
                "search_index": f.get("search_index", 0),
                "in_list_view": 1 if f["fieldname"] == "epromise_ite_code" else 0,
            }).insert(ignore_permissions=True)
    frappe.db.commit()


def _ensure_naming_series():
    options = frappe.db.get_value(
        "DocField", {"parent": "Purchase Invoice", "fieldname": "naming_series"}, "options"
    ) or ""
    new = [s for s in ["ACC-PINV-PI-.YYYY.-", "ACC-PINV-DIR-.YYYY.-",
                       "ACC-PINV-IMP-.YYYY.-", "ACC-PINV-RET-.YYYY.-",
                       "ACC-PINV-350-.YYYY.-"] if s not in options]
    if new:
        frappe.db.set_value(
            "DocField", {"parent": "Purchase Invoice", "fieldname": "naming_series"},
            "options", options + "\n" + "\n".join(new),
        )
        frappe.db.commit()


def _ensure_supplier_custom_field():
    if not frappe.db.exists("Custom Field", {"dt": "Supplier", "fieldname": "epromise_acc_code"}):
        frappe.get_doc({
            "doctype": "Custom Field", "dt": "Supplier",
            "label": "ePromise Account Code", "fieldname": "epromise_acc_code",
            "fieldtype": "Data", "insert_after": "supplier_name",
            "read_only": 1, "search_index": 1,
        }).insert(ignore_permissions=True)
        frappe.db.commit()


def _preload_supplier_cache():
    rows = frappe.db.get_all("Supplier", filters={"epromise_acc_code": ["!=", ""]},
        fields=["name", "epromise_acc_code"])
    return {r.epromise_acc_code: r.name for r in rows if r.epromise_acc_code}


def _ensure_suppliers_from_epromise(settings):
    conn = connect_mssql(settings)
    cur = conn.cursor()
    cur.execute("SELECT ACC_CODE, ACC_NAME FROM DICADMAS WHERE SUB_HEAD='C' AND ACC_NAME IS NOT NULL")
    rows = [{k.lower(): v for k, v in dict(r).items()} for r in cur]
    conn.close()

    existing = {r.epromise_acc_code for r in
        frappe.db.get_all("Supplier", filters={"epromise_acc_code": ["!=", ""]},
        fields=["epromise_acc_code"])}

    for row in rows:
        acc_code = (row.get("acc_code") or "").strip()
        acc_name = (row.get("acc_name") or "").strip()
        if not acc_code or not acc_name or acc_code in existing:
            continue
        if frappe.db.exists("Supplier", acc_name):
            frappe.db.set_value("Supplier", acc_name, "epromise_acc_code", acc_code)
            existing.add(acc_code)
            continue
        try:
            frappe.get_doc({
                "doctype": "Supplier", "supplier_name": acc_name,
                "supplier_type": "Company",
                "supplier_group": settings.default_supplier_group or "All Supplier Groups",
                "epromise_acc_code": acc_code,
            }).insert(ignore_permissions=True)
            existing.add(acc_code)
        except Exception:
            frappe.db.rollback()
    frappe.db.commit()


def _get_or_create_supplier(acc_code, acc_name, settings, supplier_cache):
    """Return ERPNext supplier name, always creating if not found."""
    display_name = (acc_name or acc_code or "Unknown Supplier").strip()

    if acc_code in supplier_cache:
        if frappe.db.exists("Supplier", supplier_cache[acc_code]):
            return supplier_cache[acc_code]
    existing = frappe.db.get_value("Supplier", {"epromise_acc_code": acc_code}, "name")
    if existing:
        supplier_cache[acc_code] = existing
        return existing
    if frappe.db.exists("Supplier", display_name):
        frappe.db.set_value("Supplier", display_name, "epromise_acc_code", acc_code)
        supplier_cache[acc_code] = display_name
        return display_name
    try:
        doc = frappe.get_doc({
            "doctype": "Supplier", "supplier_name": display_name,
            "supplier_type": "Company",
            "supplier_group": settings.default_supplier_group or "All Supplier Groups",
            "epromise_acc_code": acc_code,
        })
        doc.insert(ignore_permissions=True)
        frappe.db.commit()
        supplier_cache[acc_code] = doc.name
        return doc.name
    except Exception:
        frappe.db.rollback()
        supplier_cache[acc_code] = display_name
        return display_name


def _get_or_create_item(ite_code, item_master_map, settings, item_cache, unified_map=None):
    """Return ERPNext item_code (= unified_code), auto-creating the Item if needed."""
    if not ite_code:
        return settings.placeholder_item_code or "ePromise-Import-Item"

    uni = (unified_map or {}).get(str(ite_code))
    unified_code = uni["unified_code"] if uni else str(ite_code)

    if unified_code in item_cache:
        return unified_code
    if frappe.db.exists("Item", unified_code):
        item_cache.add(unified_code)
        return unified_code

    if uni and uni.get("ite_name"):
        item_name = uni["ite_name"]
        uom = _ensure_uom(_map_uom(uni.get("ite_unit") or "NOS"))
    else:
        master = item_master_map.get(str(ite_code), {})
        item_name = (master.get("ite_name") or unified_code).strip()
        uom = _ensure_uom(_map_uom(master.get("base_uom") or "NOS"))

    try:
        doc = frappe.get_doc({
            "doctype": "Item", "item_code": unified_code, "item_name": item_name,
            "item_group": settings.default_item_group or "Products",
            "stock_uom": uom, "is_stock_item": 1,
            "is_sales_item": 1, "is_purchase_item": 1, "description": item_name,
        })
        doc.insert(ignore_permissions=True)
        frappe.db.commit()
    except Exception:
        frappe.db.rollback()
        if not frappe.db.exists("Item", unified_code):
            raise
    item_cache.add(unified_code)
    return unified_code


def _get_or_create_service_item(acc_code, acc_name, settings, item_cache):
    """Get or create a service item for expense accounts (freight, customs, etc.)."""
    # Use account code as item code prefix
    item_code = f"EXP-{acc_code}"
    if item_code in item_cache:
        return item_code
    if frappe.db.exists("Item", item_code):
        item_cache.add(item_code)
        return item_code
    item_name = (acc_name or acc_code or "Expense Item").strip()[:140]
    try:
        frappe.get_doc({
            "doctype": "Item", "item_code": item_code, "item_name": item_name,
            "item_group": settings.default_item_group or "Products",
            "stock_uom": "Nos", "is_stock_item": 0,
            "is_sales_item": 0, "is_purchase_item": 1, "description": item_name,
        }).insert(ignore_permissions=True)
        frappe.db.commit()
    except Exception:
        frappe.db.rollback()
        if not frappe.db.exists("Item", item_code):
            raise
    item_cache.add(item_code)
    return item_code


def _get_payable_account(currency, settings):
    abbr = frappe.db.get_value("Company", settings.erpnext_company, "abbr") or "K"
    default = settings.default_payable_account or f"Creditors - {abbr}"
    if not currency:
        return default
    if default:
        acc_currency = frappe.db.get_value("Account", default, "account_currency")
        if acc_currency == currency:
            return default
    existing = frappe.db.get_value(
        "Account",
        {"company": settings.erpnext_company, "account_type": "Payable", "account_currency": currency},
        "name",
    )
    if existing:
        return existing
    parent = frappe.db.get_value("Account", default, "parent_account") or \
             frappe.db.get_value("Account",
                 {"company": settings.erpnext_company, "account_type": "Payable", "is_group": 1},
                 "name") or f"Accounts Payable - {abbr}"
    new_account = frappe.get_doc({
        "doctype": "Account", "account_name": f"Creditors {currency}",
        "parent_account": parent, "company": settings.erpnext_company,
        "account_type": "Payable", "account_currency": currency, "is_group": 0,
    })
    new_account.insert(ignore_permissions=True)
    frappe.db.commit()
    return new_account.name


# ─── data loading ─────────────────────────────────────────────────────────────

def _iter_purchase_invoices(settings, trc_codes=None):
    """Yield (header_row, item_rows, expense_rows) for each purchase invoice."""
    if trc_codes is None:
        trc_codes = PURCHASE_INVOICE_TRC_CODES
    if not settings.mssql_host:
        frappe.throw("Purchase Invoice import requires a live SQL Server connection.")

    from_date = settings.invoice_from_date or None
    to_date   = settings.invoice_to_date   or None
    trc_ph    = "','".join(trc_codes)

    conn = connect_mssql(settings)
    cur  = conn.cursor()

    hdr_filter, join_filter = "", ""
    params = []  # kept for compatibility but no longer used
    if from_date:
        hdr_filter  += f" AND CAST(VR_DATE AS DATE) >= '{str(from_date)[:10]}'"
        join_filter += f" AND CAST(dh.VR_DATE AS DATE) >= '{str(from_date)[:10]}'"
    if to_date:
        hdr_filter  += f" AND CAST(VR_DATE AS DATE) <= '{str(to_date)[:10]}'"
        join_filter += f" AND CAST(dh.VR_DATE AS DATE) <= '{str(to_date)[:10]}'"

    # Headers
    cur.execute(
        f"SELECT * FROM DICHDATA WHERE TRC_CODE IN ('{trc_ph}') AND POSTED_IND='Y'{hdr_filter} ORDER BY VR_NO",
        params,
    )
    hdrs = {(str(r["TRC_CODE"]), str(r["VR_NO"])): {k.lower(): v for k, v in dict(r).items()} for r in cur}

    from collections import defaultdict
    lines     = defaultdict(list)   # invoice item lines
    expenses  = defaultdict(list)   # expense lines for IP

    # 350: items from PURCHASE_INVOICE_DETAIL (with GRN link)
    if "350" in trc_codes:
        cur.execute(
            f"""
            SELECT pid.TRC_CODE, pid.VR_NO, pid.SR_NO,
                   pid.ITE_CODE, pid.ITE_QTY, pid.ITE_RATE,
                   pid.DISC_PERCENT, pid.REF_TRC_CODE, pid.REF_VR_NO,
                   pid.CUR_CODE,
                   im.ITE_NAME, im.ITE_UNIT AS BASE_UOM
            FROM PURCHASE_INVOICE_DETAIL pid
            INNER JOIN DICHDATA dh ON dh.TRC_CODE=pid.TRC_CODE AND dh.VR_NO=pid.VR_NO
            LEFT JOIN DICIHMAS im ON im.ITE_CODE=pid.ITE_CODE
            WHERE pid.TRC_CODE='350' AND dh.POSTED_IND='Y'{join_filter}
            """,
        )
        for r in cur:
            row = {k.lower(): v for k, v in dict(r).items()}
            lines[(row["trc_code"], str(row["vr_no"]))].append(row)

    # 111, IP, PR: items from PURCHASE_DATA
    other_trc = [t for t in trc_codes if t != "350"]
    if other_trc:
        other_ph = "','".join(other_trc)
        cur.execute(
            f"""
            SELECT pd.TRC_CODE, pd.VR_NO, pd.SR_NO,
                   pd.ITE_CODE, pd.ITE_QTY, pd.ITE_RATE,
                   pd.CUR_CODE, pd.DISC_PERCENT,
                   im.ITE_NAME, im.ITE_UNIT AS BASE_UOM
            FROM PURCHASE_DATA pd
            INNER JOIN DICHDATA dh ON dh.TRC_CODE=pd.TRC_CODE AND dh.VR_NO=pd.VR_NO
            LEFT JOIN DICIHMAS im ON im.ITE_CODE=pd.ITE_CODE
            WHERE pd.TRC_CODE IN ('{other_ph}') AND dh.POSTED_IND='Y'{join_filter}
            """,
        )
        for r in cur:
            row = {k.lower(): v for k, v in dict(r).items()}
            lines[(row["trc_code"], str(row["vr_no"]))].append(row)

    # IP expense lines from DICADDATA (accounts starting with 5)
    if "IP" in trc_codes:
        cur.execute(
            f"""
            SELECT da.TRC_CODE, da.VR_NO, da.ACC_CODE, da.PARTICULARS,
                   da.ACC_AMT, da.CUR_CODE
            FROM DICADDATA da
            INNER JOIN DICHDATA dh ON dh.TRC_CODE=da.TRC_CODE AND dh.VR_NO=da.VR_NO
            WHERE da.TRC_CODE='IP' AND dh.POSTED_IND='Y'
              AND LEFT(da.ACC_CODE,1)='5'{join_filter}
            """,
        )
        for r in cur:
            row = {k.lower(): v for k, v in dict(r).items()}
            expenses[(row["trc_code"], str(row["vr_no"]))].append(row)

    conn.close()
    for _k, hdr in hdrs.items():
        yield hdr, lines.get(_k, []), expenses.get(_k, [])


# ─── invoice builder ──────────────────────────────────────────────────────────

_TRC_PINV_META = {
    "350": ("PI (Invoice Item Wise)",  "ACC-PINV-PI-.YYYY.-",  False),
    "111": ("Direct Purchase (111)",   "ACC-PINV-DIR-.YYYY.-", False),
    "IP":  ("IP (Import Purchase)",    "ACC-PINV-IMP-.YYYY.-", False),
    "PR":  ("Purchase Return (PR)",    "ACC-PINV-RET-.YYYY.-", True),
}


def _build_purchase_invoice(hdr, item_lines, expense_lines, item_master_map,
                             placeholder_code, settings, supplier_cache,
                             item_cache, item_name_cache, grn_pr_map=None, unified_map=None):
    trc_code  = hdr.get("trc_code", "")
    vr_no     = str(hdr.get("vr_no") or "").strip()
    acc_code  = (hdr.get("acc_code") or "").strip()
    acc_name  = (hdr.get("acc_name") or acc_code or "Unknown").strip()
    # ePromise foreign vouchers hold item rates / amounts in the TRANSACTION currency
    # (e.g. SAR). Convert everything to BHD (base) via cur_rate and post a pure-BHD invoice.
    _crate    = flt(hdr.get("cur_rate") or 1) or 1
    currency  = "BHD"
    vat_amt   = flt(hdr.get("vat_amt") or 0) * _crate
    acc_amt   = flt(hdr.get("acc_amt") or 0) * _crate
    net_amt   = acc_amt - vat_amt
    bill_no   = (hdr.get("bill_no") or "").strip()
    narration = (hdr.get("particulars") or "").strip()

    try:
        posting_date = getdate(str(hdr.get("vr_date") or "")[:10])
    except Exception:
        posting_date = getdate("2024-01-01")

    if not acc_code or not vr_no:
        return None

    meta = _TRC_PINV_META.get(trc_code, ("Purchase Invoice", "ACC-PINV-DIR-.YYYY.-", False))
    invoice_type_label, naming_series, is_return = meta

    supplier = _get_or_create_supplier(acc_code, acc_name, settings, supplier_cache)

    expense_account = settings.default_expense_account or settings.default_income_account

    # Default warehouse and cost center (overridden per-invoice by branch code)
    _abbr = frappe.db.get_value("Company", settings.erpnext_company, "abbr") or "SFTB"
    default_warehouse = getattr(settings, "default_warehouse", None) or f"Stores - {_abbr}"
    default_cc = getattr(settings, "default_cost_center", None) or f"Main - {_abbr}"

    # Resolve branch → cost center + warehouse from ePromise CC_NO / BRANCH_NO
    cost_center, branch_warehouse = _resolve_branch(hdr, default_cc, default_warehouse)

    invoice_items = []

    # Stock/inventory items
    for line in item_lines:
        orig_ite = (line.get("ite_code") or "").strip()
        ite_code  = _get_or_create_item(orig_ite, item_master_map, settings, item_cache, unified_map=unified_map)
        uom       = _ensure_uom(_map_uom(line.get("base_uom") or line.get("x_unit")))
        qty       = flt(line.get("ite_qty") or 1)
        rate      = flt(line.get("ite_rate") or 0) * _crate
        uni = (unified_map or {}).get(str(orig_ite))
        item_name = item_name_cache.get(ite_code) or \
            (uni and uni.get("ite_name")) or \
            (item_master_map.get(orig_ite) or {}).get("ite_name") or orig_ite
        item_name_cache[ite_code] = item_name

        item_row = {
            "item_code": ite_code, "item_name": item_name,
            "epromise_ite_code": orig_ite,
            "qty": qty or 1, "rate": rate, "uom": uom,
            "warehouse": branch_warehouse,
            "cost_center": cost_center,
            "expense_account": expense_account,
            "description": item_name,
        }

        invoice_items.append(item_row)

    # Expense service items for IP (freight, customs, etc.)
    for exp in expense_lines:
        exp_acc_code = (exp.get("acc_code") or "").strip()
        exp_amt      = flt(exp.get("acc_amt") or 0) * _crate
        particulars  = (exp.get("particulars") or exp_acc_code or "Expense").strip()
        if not exp_amt:
            continue
        # Resolve the expense sub-account: gl_map first (maps ePromise COGS/landing codes
        # e.g. 51010300004 -> "51010400004 - Freight Charges - SFTB"), then by number.
        from backup.epromise_migration.utils.gl_map import resolve_account as _resolve_acc
        acc_name_exp = None
        _m = _resolve_acc(exp_acc_code)
        if _m and frappe.db.exists("Account", _m):
            acc_name_exp = _m
        if not acc_name_exp:
            acc_name_exp = frappe.db.get_value("Account",
                {"account_number": exp_acc_code, "company": settings.erpnext_company}, "name")
        if not acc_name_exp:
            acc_name_exp = expense_account
        svc_item = _get_or_create_service_item(exp_acc_code, particulars, settings, item_cache)
        invoice_items.append({
            "item_code": svc_item,
            "item_name": particulars[:140],
            "epromise_ite_code": exp_acc_code,
            "qty": 1,
            "rate": exp_amt,
            "uom": "Nos",
            "expense_account": acc_name_exp or expense_account,
            "description": f"Expense: {particulars}",
        })

    if not invoice_items:
        rate = net_amt if net_amt > 0 else acc_amt
        invoice_items.append({
            "item_code": placeholder_code,
            "epromise_ite_code": "",
            "qty": 1, "rate": rate, "uom": "Nos",
            "expense_account": expense_account,
            "description": f"Ref: {bill_no or vr_no} | {acc_name}",
        })

    from backup.epromise_migration.utils.invoice_importer import (
        INPUT_VAT_ACCOUNT, VAT_RATE, _get_party_account_for_invoice,
    )
    # Input VAT account by transaction type:
    #   IP (import)        -> 13120100002 VAT Paid at Customs/ Import
    #   350/111/PR (local) -> 13120100001 Input VAT A/C (LOCAL)
    _vat_num = "13120100002" if (trc_code or "").strip() == "IP" else "13120100001"
    input_tax_account = frappe.db.get_value(
        "Account", {"company": settings.erpnext_company, "account_number": _vat_num, "is_group": 0}, "name")
    if not input_tax_account:
        input_tax_account = frappe.db.get_value(
            "Account",
            {"company": settings.erpnext_company, "account_type": "Tax", "root_type": "Asset", "is_group": 0},
            "name",
        ) or settings.default_tax_account

    taxes = []
    if vat_amt and input_tax_account and flt(vat_amt) != 0:
        taxes.append({
            "charge_type": "On Net Total",
            "account_head": input_tax_account,
            "description": "Input VAT",
            "rate": VAT_RATE,
            "tax_amount": flt(vat_amt),
        })

    inv = {
        "doctype": "Purchase Invoice",
        "naming_series": naming_series,
        "company": settings.erpnext_company,
        "supplier": supplier,
        "posting_date": posting_date,
        "bill_date": posting_date,
        "due_date": posting_date,
        "currency": currency,
        "conversion_rate": 1,
        "items": invoice_items,
        "epromise_vr_no": vr_no,
        "epromise_trc_code": trc_code,
        "epromise_invoice_type": invoice_type_label,
        "epromise_bill_no": bill_no,
        "set_posting_time": 1,
        "disable_rounded_total": 1,
        "update_stock": 0,
        "posting_time": "00:00:00",
        "credit_to": _get_party_account_for_invoice(
            supplier, "Supplier", currency, settings.erpnext_company,
            lambda: _get_payable_account(currency, settings),
        ),
        "is_return": 1 if is_return else 0,
        "remarks": narration,
    }

    if bill_no:
        inv["bill_no"] = bill_no

    if taxes:
        inv["taxes"] = taxes

    if is_return:
        ref_vr  = str(hdr.get("ref_vr_no") or "").strip()
        ref_trc = str(hdr.get("ref_trc_code") or "").strip()
        if ref_vr:
            orig = frappe.db.get_value("Purchase Invoice",
                {"epromise_vr_no": ref_vr}, "name")
            if orig:
                inv["return_against"] = orig
            else:
                inv["remarks"] = f"Return of ePromise {ref_trc}/{ref_vr}"

    from backup.epromise_migration.utils.invoice_importer import _set_doc_totals
    _set_doc_totals(inv, flt(hdr.get("cur_rate") or 1))
    return inv


# ─── background worker ────────────────────────────────────────────────────────

def _run_purchase_import(log_name, trc_codes=None):
    settings = _get_settings()
    log = frappe.get_doc("ePromise Migration Log", log_name)
    log.status = "Running"
    log.save(ignore_permissions=True)
    frappe.db.commit()

    from backup.epromise_migration.utils.invoice_importer import _validate_date_range
    _validate_date_range(settings)

    if trc_codes is None:
        trc_codes = list(PURCHASE_INVOICE_TRC_CODES)

    _ensure_supplier_custom_field()
    _ensure_custom_fields()
    _ensure_naming_series()
    placeholder_code = _ensure_placeholder_item(settings)

    frappe.db.sql("UPDATE `tabItem` SET is_purchase_item=1 WHERE is_purchase_item=0")
    frappe.db.commit()

    _ensure_suppliers_from_epromise(settings)

    conn = connect_mssql(settings)
    item_master_map = _load_item_master_live(conn)
    conn.close()

    # Load unified item code map: ite_code → unified_code (authoritative ERPNext item_code)
    from backup.epromise_migration.utils.unified_code_map import load_unified_map
    unified_map = load_unified_map()

    supplier_cache  = _preload_supplier_cache()
    item_cache      = _preload_item_cache()
    item_name_cache = _preload_item_name_cache()

    # Pre-load GRN→Purchase Receipt name map for 350 item linking
    grn_pr_map = {}
    if "350" in trc_codes:
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
        rows = frappe.db.get_all("Purchase Invoice",
            filters={"epromise_vr_no": ["!=", ""]},
            fields=["epromise_vr_no", "epromise_trc_code"])
        existing = {(r.epromise_trc_code, r.epromise_vr_no) for r in rows}

    total = success = skipped = errors = 0
    log_lines = []
    frappe.flags.in_import = True
    frappe.flags.ignore_account_permission = True

    try:
        for hdr, item_lines, expense_lines in _iter_purchase_invoices(settings, trc_codes=trc_codes):
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
                inv_dict = _build_purchase_invoice(
                    hdr, item_lines, expense_lines, item_master_map,
                    placeholder_code, settings, supplier_cache, item_cache, item_name_cache,
                    grn_pr_map=grn_pr_map, unified_map=unified_map,
                )
                if not inv_dict:
                    skipped += 1
                    continue

                inv_doc = frappe.get_doc(inv_dict)
                inv_doc.flags.ignore_permissions = True
                inv_doc.flags.ignore_mandatory = True
                inv_doc.flags.ignore_links = True
                inv_doc.flags.ignore_validate = True
                inv_doc.flags.ignore_version = True
                inv_doc.flags.ignore_feed = True
                inv_doc.insert(ignore_permissions=True)

                success += 1
                existing.add((trc_code, vr_no))

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


# ─── public entry points ──────────────────────────────────────────────────────

@frappe.whitelist()
def import_purchase_invoices():
    """350 (Invoice Item Wise), 111 (Direct Purchase), IP (Import Purchase) → Purchase Invoice."""
    settings = _get_settings()
    if not settings.erpnext_company:
        frappe.throw("Please configure ePromise Settings before importing.")
    if not settings.mssql_host:
        frappe.throw("Requires a live SQL Server connection.")

    log = frappe.get_doc({
        "doctype": "ePromise Migration Log",
        "migration_type": "Purchase Invoice",
        "status": "Queued",
        "started_at": now_datetime(),
    })
    log.insert(ignore_permissions=True)
    frappe.db.commit()

    frappe.enqueue(
        "backup.epromise_migration.utils.purchase_importer._run_purchase_import",
        log_name=log.name,
        trc_codes=list(PURCHASE_INVOICE_TRC_CODES),
        queue="long", timeout=7200,
        job_name=f"epromise-pinv-{log.name}",
    )
    return {"log_name": log.name, "status": "queued",
            "message": f"Purchase Invoices import queued. Track in {log.name}."}


@frappe.whitelist()
def import_purchase_returns():
    """PR → Purchase Invoice (is_return=1)."""
    settings = _get_settings()
    if not settings.erpnext_company:
        frappe.throw("Please configure ePromise Settings before importing.")
    if not settings.mssql_host:
        frappe.throw("Requires a live SQL Server connection.")

    log = frappe.get_doc({
        "doctype": "ePromise Migration Log",
        "migration_type": "Purchase Return",
        "status": "Queued",
        "started_at": now_datetime(),
    })
    log.insert(ignore_permissions=True)
    frappe.db.commit()

    frappe.enqueue(
        "backup.epromise_migration.utils.purchase_importer._run_purchase_import",
        log_name=log.name,
        trc_codes=list(PURCHASE_RETURN_TRC_CODES),
        queue="long", timeout=7200,
        job_name=f"epromise-pret-{log.name}",
    )
    return {"log_name": log.name, "status": "queued",
            "message": f"Purchase Returns import queued. Track in {log.name}."}
