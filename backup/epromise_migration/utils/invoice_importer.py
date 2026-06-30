"""
Imports Sales Invoices from ePromise into ERPNext.

Supports two source modes (set in ePromise Settings):

  LIVE SQL Server (mssql_host filled):
    DICHDATA    — invoice header (exact amounts, dates)
    SALES_DATA  — line items for both S01 (credit) and S06 (POS) invoices
    DICIHMAS    — item master (names, UOM)
    DICADMAS    — customer master

  Backup file (.bak):
    Same tables but read via `strings` INSERT extraction + binary page reader.
    Amounts may be 0 for binary-page-only invoices (text extraction limitation).

Behaviour:
  - Both S01 (credit) and S06 (POS) invoices are imported.
  - Customers and Items missing in ERPNext are auto-created.
  - Invoices with no line data get a single placeholder line.
  - Duplicates detected via epromise_vr_no custom field on Sales Invoice.
"""

import frappe
from frappe.utils import now_datetime, flt, getdate

from backup.epromise_migration.utils.bak_parser import extract_table_rows, connect_mssql

SALES_TRC_CODES = ("S01", "S06")
SALES_RETURN_TRC_CODES = ("R01", "R04")   # R01=Credit Return, R04=POS Return

# TRC → ERPNext label/series
_TRC_META = {
    "S01": ("Credit Invoice (S01)",     "ACC-SINV-CR-.YYYY.-",      False),
    "S06": ("POS Invoice (S06)",         "ACC-SINV-POS-.YYYY.-",     False),
    "R01": ("Credit Return (R01)",       "ACC-SINV-RET-.YYYY.-",     True),
    "R04": ("POS Return (R04)",          "ACC-SINV-RET-.YYYY.-",     True),
}

# ePromise UOM → ERPNext UOM
UOM_MAP = {
    "NOS": "Nos", "NO": "Nos", "PCS": "Nos", "PC": "Nos",
    "KG": "Kg", "KGS": "Kg",
    "MTR": "Metre", "MT": "Metre", "M": "Metre",
    "SQM": "Square Meter", "SQF": "Square Foot",
    "LTR": "Litre", "L": "Litre",
    "SET": "Set", "SETS": "Set",
    "BOX": "Box", "ROLL": "Roll",
    "TON": "MT", "TONS": "MT",
    "SHEET": "Nos", "SHT": "Nos",
    "BAR": "Nos", "ROD": "Nos",
    "LENGTH": "Nos", "LEN": "Nos",
    "PKT": "Nos", "PAIR": "Nos",
}


# ─── configurable field mappings ──────────────────────────────────────────────

def _load_active_mappings(target_doctype):
    """
    Return {SOURCE_FIELD_UPPER: target_field} for all enabled ePromise Field Mapping
    records that target the given doctype from DICHDATA.
    Skips child table fields (table fieldtype) to avoid overwriting lists with strings.
    """
    # Fields that are child tables — never overwrite these via string mapping
    SKIP_FIELDS = {"items", "taxes", "sales_team", "payment_schedule",
                   "pricing_rules", "packed_items"}
    try:
        rows = frappe.db.get_all(
            "ePromise Field Mapping",
            filters={
                "source_table": "DICHDATA",
                "target_doctype": target_doctype,
                "enabled": 1,
            },
            fields=["source_field", "target_field"],
        )
        return {r.source_field.upper(): r.target_field
                for r in rows if r.target_field not in SKIP_FIELDS}
    except Exception:
        # DocType may not exist yet (first migration before bench migrate)
        return {}


# ─── helpers ──────────────────────────────────────────────────────────────────

def _get_settings():
    return frappe.get_single("ePromise Settings")


def _map_uom(epromise_uom):
    if not epromise_uom:
        return "Nos"
    u = epromise_uom.strip().upper()
    return UOM_MAP.get(u, "Nos")


def _ensure_uom(uom_name):
    if uom_name and not frappe.db.exists("UOM", uom_name):
        frappe.get_doc({"doctype": "UOM", "uom_name": uom_name}).insert(ignore_permissions=True)
    return uom_name


def _ensure_custom_fields():
    """Add ePromise traceability fields to Sales Invoice and Sales Invoice Item."""
    sinv_fields = [
        {
            "dt": "Sales Invoice", "fieldname": "epromise_vr_no",
            "label": "ePromise Voucher No", "fieldtype": "Data",
            "insert_after": "naming_series", "read_only": 1, "search_index": 1,
        },
        {
            "dt": "Sales Invoice", "fieldname": "epromise_trc_code",
            "label": "ePromise TRC Code", "fieldtype": "Data",
            "insert_after": "epromise_vr_no", "read_only": 1,
        },
        {
            "dt": "Sales Invoice", "fieldname": "epromise_invoice_type",
            "label": "Invoice Type", "fieldtype": "Select",
            "options": "\nCredit Invoice (S01)\nPOS Invoice (S06)\nCredit Return (R01)\nPOS Return (R04)",
            "insert_after": "epromise_trc_code", "read_only": 1,
            "in_list_view": 1, "bold": 1,
        },
        {
            "dt": "Sales Invoice", "fieldname": "epromise_bill_no",
            "label": "ePromise Bill No", "fieldtype": "Data",
            "insert_after": "epromise_invoice_type", "read_only": 1,
        },
    ]
    item_fields = [
        {
            "dt": "Sales Invoice Item", "fieldname": "epromise_ite_code",
            "label": "ePromise Item Code", "fieldtype": "Data",
            "insert_after": "item_code", "read_only": 1, "in_list_view": 1,
        },
    ]
    for f in sinv_fields + item_fields:
        if not frappe.db.exists("Custom Field", {"dt": f["dt"], "fieldname": f["fieldname"]}):
            frappe.get_doc({"doctype": "Custom Field", **f}).insert(ignore_permissions=True)
    frappe.db.commit()


def _ensure_naming_series():
    """Add credit, POS and return naming series to Sales Invoice if not already present."""
    options = frappe.db.get_value(
        "DocField", {"parent": "Sales Invoice", "fieldname": "naming_series"}, "options"
    ) or ""
    new = [s for s in ["ACC-SINV-CR-.YYYY.-", "ACC-SINV-POS-.YYYY.-", "ACC-SINV-RET-.YYYY.-"] if s not in options]
    if new:
        frappe.db.set_value(
            "DocField",
            {"parent": "Sales Invoice", "fieldname": "naming_series"},
            "options",
            options + "\n" + "\n".join(new),
        )
        frappe.db.commit()


def _preload_customer_cache():
    """Return {epromise_acc_code: customer_name} for all existing customers."""
    rows = frappe.db.get_all("Customer", filters={"epromise_acc_code": ["!=", ""]},
        fields=["name", "epromise_acc_code"])
    return {r.epromise_acc_code: r.name for r in rows if r.epromise_acc_code}


def _preload_item_cache():
    """Return set of all existing item_codes in ERPNext."""
    rows = frappe.db.get_all("Item", fields=["item_code"])
    return {r.item_code for r in rows}


def _preload_item_name_cache():
    """Return {item_code: item_name} — avoids per-line frappe.db.get_value calls."""
    rows = frappe.db.get_all("Item", fields=["item_code", "item_name"])
    return {r.item_code: r.item_name for r in rows}


def _get_or_create_customer(acc_code, acc_name, settings, customer_cache):
    """Return ERPNext customer name, always creating if not found."""
    # Use acc_code as the name if acc_name is blank
    display_name = (acc_name or acc_code or "Unknown Customer").strip()

    if acc_code in customer_cache:
        if frappe.db.exists("Customer", customer_cache[acc_code]):
            return customer_cache[acc_code]

    existing = frappe.db.get_value("Customer", {"epromise_acc_code": acc_code}, "name")
    if existing:
        customer_cache[acc_code] = existing
        return existing

    if frappe.db.exists("Customer", display_name):
        # Link existing customer to this acc_code
        frappe.db.set_value("Customer", display_name, "epromise_acc_code", acc_code)
        customer_cache[acc_code] = display_name
        return display_name

    try:
        doc = frappe.get_doc({
            "doctype": "Customer",
            "customer_name": display_name,
            "customer_type": "Company",
            "customer_group": settings.default_customer_group or "Commercial",
            "territory": settings.default_territory or "All Territories",
            "epromise_acc_code": acc_code,
        })
        doc.insert(ignore_permissions=True)
        frappe.db.commit()
        customer_cache[acc_code] = doc.name
        return doc.name
    except Exception:
        frappe.db.rollback()
        # Last resort: return acc_code itself as customer name
        customer_cache[acc_code] = display_name
        return display_name


def _get_or_create_item(ite_code, item_master_map, settings, item_cache, unified_map=None):
    """
    Return ERPNext item_code (= unified_code), auto-creating the Item if needed.
    unified_map: {str(ite_code): {unified_code, ite_name, ite_unit}} from unified_code_map.py
    """
    if not ite_code:
        return settings.placeholder_item_code or "ePromise-Import-Item"

    # Resolve: unified_code is the authoritative ERPNext item_code
    uni = (unified_map or {}).get(str(ite_code))
    unified_code = uni["unified_code"] if uni else str(ite_code)

    if unified_code in item_cache:
        return unified_code

    if frappe.db.exists("Item", unified_code):
        item_cache.add(unified_code)
        return unified_code

    # Name + UOM: prefer unified_map (more authoritative), fallback to DICIHMAS
    if uni and uni.get("ite_name"):
        item_name = uni["ite_name"]
        uom = _ensure_uom(_map_uom(uni.get("ite_unit") or "NOS"))
    else:
        master = item_master_map.get(str(ite_code), {})
        item_name = (master.get("ite_name") or unified_code).strip()
        uom = _ensure_uom(_map_uom(master.get("base_uom") or "NOS"))

    try:
        doc = frappe.get_doc({
            "doctype": "Item",
            "item_code": unified_code,
            "item_name": item_name,
            "item_group": settings.default_item_group or "Products",
            "stock_uom": uom,
            "is_stock_item": 1,
            "is_sales_item": 1,
            "is_purchase_item": 1,
            "description": item_name,
        })
        doc.insert(ignore_permissions=True)
        frappe.db.commit()
    except Exception:
        frappe.db.rollback()
        if not frappe.db.exists("Item", unified_code):
            raise
    item_cache.add(unified_code)
    return unified_code


def _ensure_placeholder_item(settings):
    """Create the placeholder item for invoices with no line data."""
    code = settings.placeholder_item_code or "ePromise-Import-Item"
    if not frappe.db.exists("Item", code):
        frappe.get_doc({
            "doctype": "Item",
            "item_code": code,
            "item_name": "ePromise Import (No Item Detail)",
            "item_group": settings.default_item_group or "Products",
            "stock_uom": "Nos",
            "is_stock_item": 0,
            "is_sales_item": 1,
            "description": "Placeholder item for ePromise invoices without item-level detail.",
        }).insert(ignore_permissions=True)
        frappe.db.commit()
    return code


def _get_debit_account(currency, settings):
    """
    Return the receivable account that matches the invoice currency.
    Uses settings.default_debit_account for the configured currency (BHD).
    For other currencies, auto-creates a currency-specific receivable account.
    """
    abbr = frappe.db.get_value("Company", settings.erpnext_company, "abbr") or "K"

    if not currency:
        return settings.default_debit_account or f"Debtors - {abbr}"

    # If invoice currency matches the configured debit account currency, use it
    if settings.default_debit_account:
        acc_currency = frappe.db.get_value("Account", settings.default_debit_account, "account_currency")
        if acc_currency == currency:
            return settings.default_debit_account

    # Look for an existing receivable account with this currency
    existing = frappe.db.get_value(
        "Account",
        {"company": settings.erpnext_company, "account_type": "Receivable", "account_currency": currency},
        "name",
    )
    if existing:
        return existing

    # Auto-create one under the same parent as the configured debit account
    base_debit = settings.default_debit_account or f"Debtors - {abbr}"
    parent = frappe.db.get_value("Account", base_debit, "parent_account") or \
             frappe.db.get_value("Account",
                 {"company": settings.erpnext_company, "account_type": "Receivable", "is_group": 1},
                 "name") or f"Accounts Receivable - {abbr}"
    acc_name = f"Debtors {currency}"
    new_account = frappe.get_doc({
        "doctype": "Account",
        "account_name": acc_name,
        "parent_account": parent,
        "company": settings.erpnext_company,
        "account_type": "Receivable",
        "account_currency": currency,
        "is_group": 0,
    })
    new_account.insert(ignore_permissions=True)
    frappe.db.commit()
    return new_account.name


def _set_doc_totals(inv, conversion_rate=1.0):
    """
    Manually compute and set all total fields on a Sales Invoice / Purchase Invoice dict.
    Required because ignore_validate=True bypasses ERPNext's own calculate_taxes_and_totals().
    """
    cr = flt(conversion_rate) or 1.0
    items = inv.get("items") or []
    taxes = inv.get("taxes") or []

    # ── Item-level totals ──────────────────────────────────────────────────────
    item_total = 0.0
    for it in items:
        qty  = flt(it.get("qty") or 1)
        rate = flt(it.get("rate") or 0)
        disc = flt(it.get("disc_percent") or it.get("discount_percentage") or 0)
        amt  = qty * rate * (1 - disc / 100) if disc else qty * rate
        it["amount"]          = flt(amt, 9)
        it["base_amount"]     = flt(amt * cr, 9)
        it["net_amount"]      = flt(amt, 9)
        it["base_net_amount"] = flt(amt * cr, 9)
        item_total += amt

    # ── Tax totals ─────────────────────────────────────────────────────────────
    tax_total = sum(flt(t.get("tax_amount") or 0) for t in taxes)

    net_total   = flt(item_total, 9)
    grand_total = flt(item_total + tax_total, 9)

    inv["total"]                    = net_total
    inv["net_total"]                = net_total
    inv["total_taxes_and_charges"]  = flt(tax_total, 9)
    inv["grand_total"]              = grand_total
    inv["rounded_total"]            = grand_total
    inv["outstanding_amount"]       = grand_total
    inv["base_total"]               = flt(net_total   * cr, 9)
    inv["base_net_total"]           = flt(net_total   * cr, 9)
    inv["base_grand_total"]         = flt(grand_total * cr, 9)
    inv["base_rounded_total"]       = flt(grand_total * cr, 9)
    inv["in_words"]                 = ""
    inv["base_in_words"]            = ""
    return inv


def _get_output_tax_account(settings):
    """
    Return the output (sales) VAT account.
    Prefers settings.default_tax_account; falls back to auto-detecting
    a Tax-type account under Liabilities for the company.
    """
    if settings.default_tax_account:
        return settings.default_tax_account
    return frappe.db.get_value(
        "Account",
        {"company": settings.erpnext_company, "account_type": "Tax", "root_type": "Liability", "is_group": 0},
        "name",
    )


def _get_tax_rows(vat_amount, tax_account):
    """Build taxes child table for a known VAT amount (actual value, not %)."""
    if not vat_amount or not tax_account or flt(vat_amount) == 0:
        return []
    return [{
        "charge_type": "Actual",
        "account_head": tax_account,
        "description": "Output VAT",
        "tax_amount": flt(vat_amount),
        "included_in_print_rate": 0,
    }]


# ─── data loading ─────────────────────────────────────────────────────────────

def _load_item_master(bak_path):
    """Return {ite_code: row} from dicihmas (backup file mode)."""
    master = {}
    for row in extract_table_rows(bak_path, "dicihmas"):
        code = row.get("ite_code")
        if code and code not in master:
            master[code] = row
    return master


def _load_item_master_live(conn):
    """Return {ite_code: row} from DICIHMAS (live SQL Server mode). Keys lowercased."""
    cur = conn.cursor()
    cur.execute("SELECT ITE_CODE, ITE_NAME, ITE_UNIT FROM DICIHMAS")
    master = {}
    for row in cur:
        d = {k.lower(): v for k, v in dict(row).items()}
        code = (d.get("ite_code") or "").strip()
        if code:
            # normalise: use ite_unit as the UOM key expected by _get_or_create_item
            d["base_uom"] = d.get("ite_unit") or ""
            master[code] = d
    return master


def _load_invoice_lines(bak_path):
    """Return {(trc_code, fy_code, vr_no): [line_row, ...]} deduplicated."""
    from collections import defaultdict
    raw = {}
    for row in extract_table_rows(bak_path, "sales_data"):
        if row.get("trc_code") not in SALES_TRC_CODES:
            continue
        key = (row.get("trc_code"), row.get("fy_code"), row.get("vr_no"), row.get("sr_no"))
        raw[key] = row

    grouped = defaultdict(list)
    for (trc, fy, vr, _sr), row in raw.items():
        grouped[(trc, fy, vr)].append(row)
    return grouped


def _load_invoice_headers(bak_path, from_date=None, to_date=None):
    """
    Return {(trc_code, fy_code, vr_no): header_row} deduplicated.
    Only includes invoices where posted_ind = 'Y' (submitted in ePromise).
    Optionally further filtered by date range.
    """
    headers = {}
    for row in extract_table_rows(bak_path, "dichdata"):
        if row.get("trc_code") not in SALES_TRC_CODES:
            continue
        # Only submitted invoices
        if (row.get("posted_ind") or "").strip() != "Y":
            continue
        vr_date = str(row.get("vr_date") or "")[:10]
        if from_date and vr_date and vr_date < str(from_date):
            continue
        if to_date and vr_date and vr_date > str(to_date):
            continue
        key = (row.get("trc_code"), row.get("fy_code"), row.get("vr_no"))
        headers[key] = row   # last wins — most recent version
    return headers


def _iter_invoices(settings, trc_codes=None):
    """
    Yield (header_row, [line_rows]) for each unique submitted invoice.
    trc_codes: tuple of TRC codes to fetch — defaults to SALES_TRC_CODES.
    """
    from_date = settings.invoice_from_date or None
    to_date   = settings.invoice_to_date   or None
    if trc_codes is None:
        trc_codes = SALES_TRC_CODES

    trc_ph = "','".join(trc_codes)

    if settings.mssql_host:
        conn = connect_mssql(settings)
        cur = conn.cursor()

        hdr_date_filter = ""
        join_date_filter = ""
        params = []
        if from_date:
            hdr_date_filter  += f" AND CAST(VR_DATE AS DATE) >= '{str(from_date)[:10]}'"
            join_date_filter += f" AND CAST(dh.VR_DATE AS DATE) >= '{str(from_date)[:10]}'"
        if to_date:
            hdr_date_filter  += f" AND CAST(VR_DATE AS DATE) <= '{str(to_date)[:10]}'"
            join_date_filter += f" AND CAST(dh.VR_DATE AS DATE) <= '{str(to_date)[:10]}'"

        cur.execute(
            f"SELECT * FROM DICHDATA "
            f"WHERE TRC_CODE IN ('{trc_ph}') AND POSTED_IND='Y'{hdr_date_filter} "
            f"ORDER BY FY_CODE, VR_NO",
            params,
        )
        hdr_rows = {}
        for r in cur:
            row = {k.lower(): v for k, v in dict(r).items()}
            key = (row["trc_code"], str(row["vr_no"]))
            hdr_rows[key] = row

        from collections import defaultdict
        lines = defaultdict(list)

        # Line items from SALES_DATA (DICZDATA) — used for returns too
        cur.execute(
            f"""
            SELECT
                sd.TRC_CODE, sd.VR_NO, sd.SR_NO,
                sd.ITE_CODE, sd.ITE_QTY, sd.ITE_RATE,
                im.ITE_UNIT AS X_UNIT, sd.DISC_PERCENT, sd.VAT_RATE,
                im.ITE_NAME, im.ITE_UNIT AS BASE_UOM
            FROM DICZDATA sd
            INNER JOIN DICHDATA dh
                ON dh.TRC_CODE = sd.TRC_CODE AND dh.VR_NO = sd.VR_NO
            LEFT JOIN DICIHMAS im ON im.ITE_CODE = sd.ITE_CODE
            WHERE sd.TRC_CODE IN ('{trc_ph}')
              AND dh.POSTED_IND = 'Y'{join_date_filter}
            """,
            params,
        )
        for r in cur:
            row = {k.lower(): v for k, v in dict(r).items()}
            if not row.get("x_unit") and row.get("base_uom"):
                row["x_unit"] = row["base_uom"]
            key = (row["trc_code"], str(row["vr_no"]))
            lines[key].append(row)

        # Also check SALES_DATA for S01/S06
        if any(t in trc_codes for t in SALES_TRC_CODES):
            sales_trc_ph = "','".join(t for t in trc_codes if t in SALES_TRC_CODES)
            cur.execute(
                f"""
                SELECT
                    sd.TRC_CODE, sd.VR_NO, sd.SR_NO,
                    sd.ITE_CODE, sd.ITE_QTY, sd.ITE_RATE,
                    sd.X_UNIT, sd.DISC_PERCENT, sd.VAT_RATE,
                    im.ITE_NAME, im.ITE_UNIT AS BASE_UOM
                FROM SALES_DATA sd
                INNER JOIN DICHDATA dh
                    ON dh.TRC_CODE = sd.TRC_CODE AND dh.VR_NO = sd.VR_NO
                LEFT JOIN DICIHMAS im ON im.ITE_CODE = sd.ITE_CODE
                WHERE sd.TRC_CODE IN ('{sales_trc_ph}')
                  AND dh.POSTED_IND = 'Y'{join_date_filter}
                """,
                params,
            )
            for r in cur:
                row = {k.lower(): v for k, v in dict(r).items()}
                if not row.get("x_unit") and row.get("base_uom"):
                    row["x_unit"] = row["base_uom"]
                key = (row["trc_code"], str(row["vr_no"]))
                if key not in lines or not lines[key]:
                    lines[key] = [row]
                else:
                    lines[key].append(row)

        conn.close()
        for (trc, vr), hdr in hdr_rows.items():
            yield hdr, lines.get((trc, vr), [])
        return

    bak = settings.backup_file_path

    # ── Source 1: INSERT statements (full data) ──────────────────────────────
    insert_headers = _load_invoice_headers(bak, from_date=from_date, to_date=to_date)
    insert_vrnos = {vr for (_, _, vr) in insert_headers}

    # ── Source 2: binary SQL Server pages (partial data) ────────────────────
    try:
        from backup.epromise_migration.utils.page_reader import extract_page_invoices
        page_rows = extract_page_invoices(bak)
    except Exception:
        page_rows = {}

    # ── Merge: page rows for invoices NOT already in INSERT statements ────────
    invoice_lines = _load_invoice_lines(bak)

    # Yield INSERT-statement invoices first (full data)
    for (trc, fy, vr), hdr in insert_headers.items():
        yield hdr, invoice_lines.get((trc, fy, vr), [])

    # Yield binary-page-only invoices (partial data, amt=0)
    for (trc, vr), page_row in page_rows.items():
        if vr in insert_vrnos:
            continue  # already yielded above
        if page_row.get("posted_ind") != "Y":
            continue
        # Apply date filter
        vr_date = page_row.get("vr_date", "")[:10]
        if from_date and vr_date and vr_date < str(from_date):
            continue
        if to_date and vr_date and vr_date > str(to_date):
            continue
        # Build a minimal header dict compatible with _build_invoice
        hdr = {
            "trc_code"  : trc,
            "fy_code"   : "10",
            "vr_no"     : vr,
            "vr_date"   : page_row.get("vr_date", "2026-01-01"),
            "acc_code"  : page_row.get("acc_code", ""),
            "acc_name"  : page_row.get("acc_name", "") or page_row.get("acc_code", ""),
            "cur_code"  : page_row.get("cur_code", "BHD"),
            "acc_amt"   : 0.0,
            "vat_amt"   : 0.0,
            "total_vat" : 0.0,
            "bill_no"   : page_row.get("bill_no", ""),
            "posted_ind": "Y",
            "cur_rate"  : 1.0,
            "_partial"  : True,   # flag: amounts not available from backup
        }
        yield hdr, []


# ─── invoice builder ──────────────────────────────────────────────────────────

def _build_invoice(hdr, lines, item_master_map, placeholder_code, settings, customer_cache, item_cache, item_name_cache, sales_mappings=None, unified_map=None):
    """
    Map ePromise header + lines to an ERPNext Sales Invoice dict.
    Returns None if the header cannot be mapped.
    """
    trc_code = hdr.get("trc_code", "")
    vr_no = str(hdr.get("vr_no") or "").strip()
    fy_code = str(hdr.get("fy_code") or "").strip()
    acc_code = (hdr.get("acc_code") or "").strip()
    acc_name = (hdr.get("acc_name") or acc_code or "Unknown").strip()
    currency = (hdr.get("cur_code") or settings.default_currency or "BHD").strip()
    vat_amt = flt(hdr.get("vat_amt") or 0)
    acc_amt = flt(hdr.get("acc_amt") or 0)     # total including VAT
    net_amt = acc_amt - vat_amt                 # net (excluding VAT)
    bill_no = (hdr.get("bill_no") or "").strip()

    vr_date = str(hdr.get("vr_date") or "")[:10]
    try:
        posting_date = getdate(vr_date)
    except Exception:
        posting_date = getdate("2024-01-01")

    if not acc_code or not vr_no:
        return None

    # Resolve customer
    customer = _get_or_create_customer(acc_code, acc_name, settings, customer_cache)

    # Default warehouse for stock items
    _abbr = frappe.db.get_value("Company", settings.erpnext_company, "abbr") or "SFTB"
    default_warehouse = getattr(settings, "default_warehouse", None) or f"Stores - {_abbr}"

    # Determine invoice type, naming series, and whether this is a return
    meta = _TRC_META.get(trc_code, ("Invoice", "ACC-SINV-CR-.YYYY.-", False))
    invoice_type_label, naming_series, is_return = meta

    # Build item lines
    invoice_items = []
    if lines:
        for line in lines:
            orig_ite_code = (line.get("ite_code") or "").strip()
            ite_code = _get_or_create_item(orig_ite_code, item_master_map, settings, item_cache, unified_map=unified_map)
            uom = _ensure_uom(_map_uom(line.get("x_unit")))
            qty = flt(line.get("ite_qty") or 1)
            rate = flt(line.get("ite_rate") or 0)
            uni = (unified_map or {}).get(str(orig_ite_code))
            item_name = item_name_cache.get(ite_code) or \
                (uni and uni.get("ite_name")) or \
                (item_master_map.get(orig_ite_code) or {}).get("ite_name") or orig_ite_code
            item_name_cache[ite_code] = item_name
            invoice_items.append({
                "item_code": ite_code,
                "item_name": item_name,
                "epromise_ite_code": orig_ite_code,
                "qty": qty if qty else 1,
                "rate": rate,
                "uom": uom,
                "warehouse": default_warehouse,
                "income_account": settings.default_income_account,
                "description": item_name,
            })
    else:
        is_partial = hdr.get("_partial", False)
        rate = net_amt if net_amt > 0 else acc_amt
        ref_desc = (
            f"[AMOUNT UNAVAILABLE — update manually] Ref: {bill_no or vr_no} | Customer: {acc_name}"
            if is_partial
            else f"Ref: {bill_no or vr_no} | Customer: {acc_name}"
        )
        invoice_items.append({
            "item_code": placeholder_code,
            "epromise_ite_code": "",
            "qty": 1,
            "rate": rate,
            "uom": "Nos",
            "income_account": settings.default_income_account,
            "description": ref_desc,
        })

    # Output VAT tax rows (liability — collected from customer)
    taxes = _get_tax_rows(vat_amt, _get_output_tax_account(settings))

    inv = {
        "doctype": "Sales Invoice",
        "naming_series": naming_series,
        "company": settings.erpnext_company,
        "customer": customer,
        "posting_date": posting_date,
        "due_date": posting_date,
        "currency": currency,
        "conversion_rate": flt(hdr.get("cur_rate") or 1) or 1,
        "items": invoice_items,
        "epromise_vr_no": vr_no,
        "epromise_trc_code": trc_code,
        "epromise_invoice_type": invoice_type_label,
        "epromise_bill_no": bill_no,
        "set_posting_time": 1,
        "disable_rounded_total": 1,
        "is_return": 1 if is_return else 0,
    }

    if bill_no:
        inv["po_no"] = bill_no

    if taxes:
        inv["taxes"] = taxes

    # Pick receivable account matching the invoice currency
    inv["debit_to"] = _get_debit_account(currency, settings)

    # For returns: negate qty on all items and link to original invoice
    if is_return:
        for it in inv.get("items") or []:
            it["qty"] = -abs(flt(it.get("qty") or 1))

        ref_vr = str(hdr.get("ref_vr_no") or "").strip()
        if ref_vr:
            # Search by vr_no only — original may be S01 or S06 regardless of exact trc match
            orig = frappe.db.get_value("Sales Invoice", {"epromise_vr_no": ref_vr}, "name")
            if orig:
                inv["return_against"] = orig

    # Apply configurable field mappings
    if sales_mappings:
        for src_field, tgt_field in sales_mappings.items():
            val = hdr.get(src_field.lower()) or hdr.get(src_field)
            if val:
                val = str(val).strip()
                if tgt_field in ("contact_email", "email_id") and "@" not in val:
                    continue  # skip non-email values (phone numbers etc.)
                inv[tgt_field] = val

    # Store original invoice reference in remarks when return_against not found
    if is_return and not inv.get("return_against"):
        ref_vr = str(hdr.get("ref_vr_no") or "").strip()
        ref_trc = str(hdr.get("ref_trc_code") or "").strip()
        if ref_vr:
            inv["remarks"] = f"Return of ePromise {ref_trc}/{ref_vr}"

    _set_doc_totals(inv, flt(hdr.get("cur_rate") or 1))
    return inv


@frappe.whitelist()
def import_sales_returns():
    """Enqueues import of Sales Returns (R01=Credit Return, R04=POS Return)."""
    settings = _get_settings()
    if not settings.erpnext_company:
        frappe.throw("Please configure ePromise Settings before importing.")

    log = frappe.get_doc({
        "doctype": "ePromise Migration Log",
        "migration_type": "Sales Return",
        "status": "Queued",
        "started_at": now_datetime(),
    })
    log.insert(ignore_permissions=True)
    frappe.db.commit()

    frappe.enqueue(
        "backup.epromise_migration.utils.invoice_importer._run_sales_import",
        log_name=log.name,
        trc_codes=SALES_RETURN_TRC_CODES,
        queue="long",
        timeout=7200,
        job_name=f"epromise-returns-{log.name}",
    )
    return {"log_name": log.name, "status": "queued",
            "message": f"Sales Returns import queued. Track in {log.name}."}


# ─── main entry ───────────────────────────────────────────────────────────────

@frappe.whitelist()
def import_sales_invoices():
    """
    Called from the migration page — enqueues the actual import as a background job
    so it is not killed by the gunicorn 120s request timeout.
    Returns immediately with the log name so the UI can poll it.
    """
    settings = _get_settings()
    if not settings.erpnext_company:
        frappe.throw("Please configure ePromise Settings before importing.")
    if not settings.backup_file_path and not settings.mssql_host:
        frappe.throw("Set backup_file_path or SQL Server credentials in ePromise Settings.")

    # Create the log now so the UI gets a name to link to immediately
    log = frappe.get_doc({
        "doctype": "ePromise Migration Log",
        "migration_type": "Sales Invoice",
        "status": "Queued",
        "started_at": now_datetime(),
    })
    log.insert(ignore_permissions=True)
    frappe.db.commit()

    frappe.enqueue(
        "backup.epromise_migration.utils.invoice_importer._run_sales_import",
        log_name=log.name,
        queue="long",
        timeout=7200,
        job_name=f"epromise-sales-{log.name}",
    )
    return {"log_name": log.name, "status": "queued",
            "message": f"Import queued as background job. Track progress in {log.name}."}


@frappe.whitelist()
def stop_import(log_name):
    """Request a running import to stop after the current batch."""
    status = frappe.db.get_value("ePromise Migration Log", log_name, "status")
    if status not in ("Running", "Queued"):
        return {"ok": False, "message": f"Cannot stop — current status is '{status}'"}
    frappe.db.set_value("ePromise Migration Log", log_name, "status", "Stop Requested")
    frappe.db.commit()
    return {"ok": True, "message": "Stop requested — will halt after current batch."}


def _validate_date_range(settings):
    """Raise if from_date > to_date — prevents reversed range imports."""
    f = settings.invoice_from_date
    t = settings.invoice_to_date
    if f and t and str(f) > str(t):
        frappe.throw(
            f"Invalid date range: From ({f}) is after To ({t}). "
            "Please correct in ePromise Settings before importing."
        )


def _run_sales_import(log_name, trc_codes=None):
    """Background worker entry — does the actual import work."""
    settings = _get_settings()
    log = frappe.get_doc("ePromise Migration Log", log_name)
    log.status = "Running"
    log.save(ignore_permissions=True)
    frappe.db.commit()

    if not settings.erpnext_company:
        frappe.throw("Please configure ePromise Settings before importing.")
    if not settings.backup_file_path and not settings.mssql_host:
        frappe.throw("Set backup_file_path or SQL Server credentials in ePromise Settings.")
    _validate_date_range(settings)

    _ensure_custom_fields()
    _ensure_naming_series()
    placeholder_code = _ensure_placeholder_item(settings)

    # Pre-load item master for fast lookup (name + UOM)
    if settings.mssql_host:
        _conn = connect_mssql(settings)
        item_master_map = _load_item_master_live(_conn)
        _conn.close()
    else:
        item_master_map = _load_item_master(settings.backup_file_path)

    # Load unified item code map: ite_code → unified_code (authoritative ERPNext item_code)
    from backup.epromise_migration.utils.unified_code_map import load_unified_map
    unified_map = load_unified_map()

    # Pre-load in-memory caches — avoids one DB query per invoice/item
    customer_cache  = _preload_customer_cache()
    item_cache      = _preload_item_cache()
    item_name_cache = _preload_item_name_cache()

    # Load configurable field mappings once (DICHDATA → Sales Invoice)
    sales_mappings = _load_active_mappings("Sales Invoice")

    # Pre-load existing vr_no set to avoid per-invoice exists() checks
    existing_vr_nos = set()
    if settings.skip_existing:
        rows = frappe.db.get_all("Sales Invoice",
            filters={"epromise_vr_no": ["!=", ""]},
            fields=["epromise_vr_no", "epromise_trc_code"])
        existing_vr_nos = {(r.epromise_trc_code, r.epromise_vr_no) for r in rows}

    BATCH_SIZE = 500
    total = success = skipped = errors = 0
    log_lines = []
    frappe.flags.in_import = True
    frappe.flags.ignore_account_permission = True

    try:
        for hdr, lines in _iter_invoices(settings, trc_codes=trc_codes):
            total += 1
            vr_no = str(hdr.get("vr_no") or "").strip()
            trc_code = hdr.get("trc_code", "")
            acc_name = (hdr.get("acc_name") or "").strip()

            if not vr_no:
                skipped += 1
                continue

            # Check stop flag every 50 records
            if total % 50 == 0:
                current_status = frappe.db.get_value("ePromise Migration Log", log.name, "status")
                if current_status == "Stop Requested":
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

            # Skip already imported (in-memory check)
            if settings.skip_existing and (trc_code, vr_no) in existing_vr_nos:
                skipped += 1
                continue

            try:
                inv_dict = _build_invoice(hdr, lines, item_master_map, placeholder_code,
                                          settings, customer_cache, item_cache, item_name_cache,
                                          sales_mappings=sales_mappings, unified_map=unified_map)
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

                if settings.submit_invoices:
                    inv_doc.submit()

                success += 1
                existing_vr_nos.add((trc_code, vr_no))

                # Batch commit + progress update every N invoices
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
    frappe.db.commit()  # flush final batch
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

    return {
        "log_name": log.name,
        "total": total,
        "success": success,
        "skipped": skipped,
        "errors": errors,
    }
