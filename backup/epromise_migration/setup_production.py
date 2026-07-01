"""
Production pre-flight setup for the ePromise → ERPNext migration.

Creates all master records (Warehouse, Cost Center, Item Group, UOMs, etc.),
sets the company to periodic inventory mode, and ensures all custom fields
and naming series are in place.

Usage:
    bench --site [site-name] execute backup.epromise_migration.setup_production.run_setup
"""

import frappe

COMPANY  = "Steel Force Trading Bahrain"
ABBR     = "SFTB"
CURRENCY = "BHD"


# ─── utilities ────────────────────────────────────────────────────────────────

def _exists_or_create(doctype, name_or_filters, fields):
    """Insert only when the record does not exist. Returns (doc, created)."""
    if isinstance(name_or_filters, str):
        exists = frappe.db.exists(doctype, name_or_filters)
    else:
        exists = frappe.db.exists(doctype, name_or_filters)

    if exists:
        return frappe.get_doc(doctype, exists), False

    doc = frappe.new_doc(doctype)
    doc.update(fields)
    try:
        doc.insert(ignore_permissions=True)
        frappe.db.commit()
        return doc, True
    except Exception as e:
        frappe.db.rollback()
        frappe.log_error(str(e), f"setup_production: create {doctype}")
        print(f"  WARN  {doctype}: {e}")
        return None, False


def _log(label, name, created):
    status = "CREATED" if created else "exists "
    print(f"  {status}  {label}: {name}")


# ─── 1. Periodic inventory mode ───────────────────────────────────────────────

def setup_periodic_inventory():
    """Enable perpetual inventory — stock movements automatically create GL entries."""
    print("\n[1] Inventory mode")
    company = frappe.get_doc("Company", COMPANY)
    if not company.enable_perpetual_inventory:
        company.enable_perpetual_inventory = 1
        company.save(ignore_permissions=True)
        frappe.db.commit()
        print(f"  UPDATED  Perpetual inventory → ENABLED")
    else:
        print(f"  exists   Perpetual inventory already enabled")

    # Verify required stock accounts are set on the company
    print("\n[1b] Stock account check")
    required = [
        ("stock_received_but_not_billed", "Stock Received But Not Billed"),
        ("stock_adjustment_account",      "Stock Adjustment Account"),
        ("default_expense_account",       "Default Expense Account"),
    ]
    missing_acc = []
    for field, label in required:
        val = frappe.db.get_value("Company", COMPANY, field)
        if val:
            print(f"  OK      {label}: {val}")
        else:
            print(f"  MISSING {label} — set in Company settings")
            missing_acc.append(label)

    if missing_acc:
        print(f"\n  ACTION: Open Accounting → Company → {COMPANY}")
        print(f"  Fill the missing stock accounts before importing transactions.")

    # Verify warehouses have GL accounts linked
    print("\n[1c] Warehouse account check")
    wh_rows = frappe.db.get_all(
        "Warehouse",
        filters={"company": COMPANY, "is_group": 0},
        fields=["name", "account"],
    )
    for wh in wh_rows:
        if wh.account:
            print(f"  OK      {wh.name}  →  {wh.account}")
        else:
            print(f"  MISSING {wh.name} has no GL account — set via Stock → Warehouse → [edit]")


# ─── 2. Warehouse ─────────────────────────────────────────────────────────────

def setup_warehouse():
    """
    ERPNext auto-creates default warehouses (Stores, Finished Goods, etc.) when
    a company is set up. This step just confirms they exist and returns the
    primary storage warehouse name.
    """
    print("\n[2] Warehouse")
    primary = f"Stores - {ABBR}"
    if frappe.db.exists("Warehouse", primary):
        print(f"  exists   Warehouse: {primary}")
    else:
        # Fallback: create it if the company setup didn't auto-create it
        doc, created = _exists_or_create(
            "Warehouse",
            primary,
            {
                "warehouse_name": "Stores",
                "company": COMPANY,
                "is_group": 0,
            },
        )
        _log("Warehouse", primary, created)
    return primary


def setup_branch_warehouses():
    """
    Create branch warehouses matching the ePromise cost centres:
      0001 - SFTB  (STEEL FORCE-SFSB)
      0002 - SFTB  (STEEL FORCE-SFWH)
      0003 - SFTB  (STEEL FORCE-SFSS)

    These are used in invoice item lines so stock moves to the correct
    branch location (mirroring the cost centre mapping).
    Parent: Stores - SFTB (must exist first).
    """
    print("\n[2b] Branch Warehouses")
    parent_wh = f"Stores - {ABBR}"

    # Ensure parent is a group so children can be added
    if frappe.db.exists("Warehouse", parent_wh):
        is_grp = frappe.db.get_value("Warehouse", parent_wh, "is_group")
        if not is_grp:
            frappe.db.set_value("Warehouse", parent_wh, "is_group", 1)
            frappe.db.commit()
            print(f"  UPDATED  {parent_wh} → is_group = 1")
    else:
        print(f"  WARN  Parent warehouse '{parent_wh}' not found — run setup_warehouse() first")
        return

    branches = [
        ("0001", "STEEL FORCE-SFSB"),
        ("0002", "STEEL FORCE-SFWH"),
        ("0003", "STEEL FORCE-SFSS"),
    ]
    for code, label in branches:
        wh_name = f"{code} - {ABBR}"
        doc, created = _exists_or_create(
            "Warehouse",
            wh_name,
            {
                "warehouse_name": code,
                "company": COMPANY,
                "parent_warehouse": parent_wh,
                "warehouse_detail": label,
                "is_group": 0,
            },
        )
        _log(f"Warehouse ({label})", wh_name, created)


# ─── 3. Cost Centre ───────────────────────────────────────────────────────────

def setup_cost_center():
    """
    Create ePromise branch cost centres.
    ePromise codes: 0001=STEEL FORCE-SFSB, 0002=STEEL FORCE-SFWH, 0003=STEEL FORCE-SFSS.
    These become '0001 - SFTB', '0002 - SFTB', '0003 - SFTB' in ERPNext.
    """
    print("\n[3] Cost Centers")
    root_cc = f"{COMPANY} - {ABBR}"

    if not frappe.db.exists("Cost Center", root_cc):
        print(f"  WARN  Root cost center '{root_cc}' not found — company may need setup")
        return

    # ePromise branch codes → ERPNext cost center names
    epromise_branches = [
        ("0001", "Branch 0001 (SFSB)"),
        ("0002", "Branch 0002 (SFWH)"),
        ("0003", "Branch 0003 (SFSS)"),
        ("Main", "Main"),
    ]
    for code, label in epromise_branches:
        cc_name = f"{code} - {ABBR}"
        doc, created = _exists_or_create(
            "Cost Center",
            cc_name,
            {
                "cost_center_name": code,
                "parent_cost_center": root_cc,
                "company": COMPANY,
                "is_group": 0,
            },
        )
        _log("Cost Center", cc_name, created)


# ─── 4. Item Groups ───────────────────────────────────────────────────────────

def setup_item_groups():
    """Ensure required item groups exist."""
    print("\n[4] Item Groups")
    groups = [
        ("Products",       "All Item Groups"),
        ("Raw Materials",  "All Item Groups"),
        ("Services",       "All Item Groups"),
    ]
    for group_name, parent in groups:
        doc, created = _exists_or_create(
            "Item Group",
            group_name,
            {
                "item_group_name": group_name,
                "parent_item_group": parent,
                "is_group": 0,
            },
        )
        _log("Item Group", group_name, created)


# ─── 5. UOMs ──────────────────────────────────────────────────────────────────

def setup_uoms():
    """Ensure all UOMs referenced by ePromise items exist."""
    print("\n[5] UOMs")
    uoms = [
        ("Nos",          False),
        ("Kg",           False),
        ("Metre",        False),
        ("Square Meter", False),
        ("Square Foot",  False),
        ("Litre",        False),
        ("Set",          False),
        ("Box",          False),
        ("Roll",         False),
        ("MT",           True),   # Metric Ton — whole numbers preferred
    ]
    for uom_name, whole in uoms:
        doc, created = _exists_or_create(
            "UOM",
            uom_name,
            {
                "uom_name": uom_name,
                "must_be_whole_number": 1 if whole else 0,
            },
        )
        _log("UOM", uom_name, created)


# ─── 6. Customer Groups & Territories ────────────────────────────────────────

def setup_customer_masters():
    """Create customer groups and territories needed by the importer."""
    print("\n[6] Customer Groups")
    for group_name in ["Commercial", "Individual", "Retail"]:
        doc, created = _exists_or_create(
            "Customer Group",
            group_name,
            {
                "customer_group_name": group_name,
                "parent_customer_group": "All Customer Groups",
                "is_group": 0,
            },
        )
        _log("Customer Group", group_name, created)

    print("\n[7] Territories")
    for territory in ["Bahrain", "Saudi Arabia", "UAE", "Kuwait", "Oman", "Qatar"]:
        doc, created = _exists_or_create(
            "Territory",
            territory,
            {
                "territory_name": territory,
                "parent_territory": "All Territories",
                "is_group": 0,
            },
        )
        _log("Territory", territory, created)


# ─── 7. Supplier Groups ───────────────────────────────────────────────────────

def setup_supplier_groups():
    """Create supplier groups needed by the importer."""
    print("\n[8] Supplier Groups")
    for group_name in ["Trading Suppliers", "Service Suppliers", "Local Suppliers"]:
        doc, created = _exists_or_create(
            "Supplier Group",
            group_name,
            {
                "supplier_group_name": group_name,
                "parent_supplier_group": "All Supplier Groups",
                "is_group": 0,
            },
        )
        _log("Supplier Group", group_name, created)


# ─── 8. Modes of Payment ──────────────────────────────────────────────────────

def setup_modes_of_payment():
    """Create common modes of payment used in ePromise payment entries."""
    print("\n[9] Modes of Payment")

    # Find the Cash account
    cash_account = frappe.db.get_value(
        "Account",
        {"company": COMPANY, "account_type": "Cash", "is_group": 0},
        "name",
    )
    bank_account = frappe.db.get_value(
        "Account",
        {"company": COMPANY, "account_type": "Bank", "is_group": 0},
        "name",
    )

    modes = [
        ("Cash",          "Cash",  cash_account),
        ("Bank Transfer", "Bank",  bank_account),
        ("Cheque",        "Bank",  bank_account),
    ]
    for mop_name, mop_type, account in modes:
        if frappe.db.exists("Mode of Payment", mop_name):
            _log("Mode of Payment", mop_name, False)
            continue

        fields = {
            "mode_of_payment": mop_name,
            "type": mop_type,
        }
        if account:
            fields["accounts"] = [{
                "company": COMPANY,
                "default_account": account,
            }]

        doc = frappe.new_doc("Mode of Payment")
        doc.update(fields)
        try:
            doc.insert(ignore_permissions=True)
            frappe.db.commit()
            _log("Mode of Payment", mop_name, True)
        except Exception as e:
            frappe.db.rollback()
            print(f"  WARN  Mode of Payment '{mop_name}': {e}")


# ─── 9. Custom Fields ─────────────────────────────────────────────────────────

def setup_custom_fields():
    """Ensure all ePromise custom fields exist on every affected DocType."""
    print("\n[10] Custom Fields")

    try:
        from backup.epromise_migration.utils.invoice_importer import (
            _ensure_custom_fields as _si_fields,
            _ensure_naming_series,
        )
        _si_fields()
        print("   Sales Invoice custom fields — OK")
        _ensure_naming_series()
        print("   Sales Invoice naming series — OK")
    except Exception as e:
        print(f"  WARN  Sales Invoice custom fields: {e}")

    try:
        from backup.epromise_migration.utils.purchase_importer import (
            _ensure_custom_fields as _pi_fields,
        )
        _pi_fields()
        print("   Purchase Invoice custom fields — OK")
    except Exception as e:
        print(f"  WARN  Purchase Invoice custom fields: {e}")

    # epromise_acc_code on Customer and Supplier
    for dt in ("Customer", "Supplier"):
        fn = "epromise_acc_code"
        if not frappe.db.exists("Custom Field", {"dt": dt, "fieldname": fn}):
            frappe.get_doc({
                "doctype": "Custom Field",
                "dt": dt,
                "fieldname": fn,
                "label": "ePromise Acc Code",
                "fieldtype": "Data",
                "insert_after": "supplier_name" if dt == "Supplier" else "customer_name",
                "read_only": 1,
                "search_index": 1,
            }).insert(ignore_permissions=True)
            frappe.db.commit()
            print(f"   {dt}.epromise_acc_code — CREATED")
        else:
            print(f"   {dt}.epromise_acc_code — exists")

    # epromise_vr_no on Payment Entry and Journal Entry
    for dt in ("Payment Entry", "Journal Entry"):
        fn = "epromise_vr_no"
        if not frappe.db.exists("Custom Field", {"dt": dt, "fieldname": fn}):
            frappe.get_doc({
                "doctype": "Custom Field",
                "dt": dt,
                "fieldname": fn,
                "label": "ePromise Voucher No",
                "fieldtype": "Data",
                "insert_after": "naming_series",
                "read_only": 1,
                "search_index": 1,
            }).insert(ignore_permissions=True)
            frappe.db.commit()
            print(f"   {dt}.epromise_vr_no — CREATED")
        else:
            print(f"   {dt}.epromise_vr_no — exists")


# ─── 10. Global / accounting settings ───────────────────────────────────────

def setup_global_settings():
    """
    Apply system-wide accounting defaults required for the migration:
      - disable_rounded_total on every SI/PI (set per-document; no global switch in v15)
      - BHD currency symbol
      - Fiscal Year existence check
    """
    print("\n[10] Global / Accounting Settings")

    # BHD currency symbol
    cur_symbol = frappe.db.get_value("Currency", "BHD", "symbol")
    if cur_symbol != "د.ب":
        frappe.db.set_value("Currency", "BHD", "symbol", "د.ب")
        frappe.db.commit()
        print(f"  UPDATED  BHD symbol → د.ب")
    else:
        print(f"  OK       BHD symbol: {cur_symbol}")

    # BHD fraction
    frac = frappe.db.get_value("Currency", "BHD", "fraction_units")
    if not frac or int(frac) != 1000:
        frappe.db.set_value("Currency", "BHD", "fraction_units", 1000)
        frappe.db.set_value("Currency", "BHD", "fraction", "Fils")
        frappe.db.set_value("Currency", "BHD", "smallest_currency_fraction_value", 0.001)
        frappe.db.commit()
        print(f"  UPDATED  BHD fraction → 1000 Fils")
    else:
        print(f"  OK       BHD fraction: 1000 Fils")

    # Fiscal Year covering 2026
    fy = frappe.db.get_value(
        "Fiscal Year",
        {"year_start_date": ["<=", "2026-01-01"], "year_end_date": [">=", "2026-12-31"]},
        "name",
    )
    if fy:
        print(f"  OK       Fiscal Year: {fy}")
    else:
        print(f"  MISSING  Fiscal Year covering 2026-01-01 to 2026-12-31")
        print(f"           Create via: Accounting → Fiscal Year → New")

    # Accounting Period — must be OPEN for Jan-May 2026
    closed = frappe.db.sql("""
        SELECT name FROM `tabAccounting Period`
        WHERE CAST(start_date AS DATE) <= '2026-05-31'
          AND CAST(end_date AS DATE)   >= '2026-01-01'
          AND closed = 1
        LIMIT 1
    """)
    if closed:
        print(f"  WARN     An Accounting Period covering Jan-May 2026 is CLOSED — re-open it before importing")
    else:
        print(f"  OK       Accounting Period Jan-May 2026 is open (or no period set)")


def check_tax_accounts():
    """Verify input and output VAT accounts exist for the company."""
    print("\n[11] VAT Accounts")

    output_vat = frappe.db.get_value(
        "Account",
        {"company": COMPANY, "account_type": "Tax", "root_type": "Liability", "is_group": 0},
        ["name", "account_type"],
        as_dict=True,
    )
    if output_vat:
        print(f"  OK      Output VAT (Sales): {output_vat.name}")
    else:
        print(f"  MISSING Output VAT account (Tax type, Liability root) — create in COA")
        print(f"          Used as: Sales Invoice → taxes → Output VAT")

    input_vat = frappe.db.get_value(
        "Account",
        {"company": COMPANY, "account_type": "Tax", "root_type": "Asset", "is_group": 0},
        ["name", "account_type"],
        as_dict=True,
    )
    if input_vat:
        print(f"  OK      Input VAT (Purchase): {input_vat.name}")
    else:
        print(f"  MISSING Input VAT account (Tax type, Asset root) — create in COA")
        print(f"          Used as: Purchase Invoice → taxes → Input VAT")

    if output_vat and input_vat:
        print(f"\n  NOTE: Set 'default_tax_account' in ePromise Settings to: {output_vat.name}")
        print(f"  The purchase importer will auto-detect the input account: {input_vat.name}")


# ─── 12. COA — ensure key accounts exist ─────────────────────────────────────

def check_coa_accounts():
    """Print status of critical accounts the importer references."""
    print("\n[12] COA — Critical Account Check")
    required = [
        ("1303 - Accounts Receivables - SFTB",                "AR group (parent for customer ledgers)"),
        ("130301 - Accounts Receivable - SFTB",               "AR control account on Sales Invoices"),
        ("2201 - Accounts Payable - SFTB",                    "AP group (parent for supplier ledgers)"),
        ("22040100002 - Accounts Payable Control Account - SFTB", "AP control account on Purchase Invoices"),
    ]
    missing = []
    for account, note in required:
        if frappe.db.exists("Account", account):
            print(f"  OK      {account}")
        else:
            print(f"  MISSING {account}  ← {note}")
            missing.append(account)

    if missing:
        print(f"\n  ACTION REQUIRED: Import COA from COA_ERPNext_Import_SteelForce_Bahrain.xlsx")
        print(f"  Path: Accounting → Chart of Accounts → Import Chart of Accounts")
    else:
        print(f"\n  All critical accounts present.")


# ─── 13. Remove duplicate ERPNext default COA root groups ────────────────────

def remove_duplicate_coa():
    """
    ERPNext auto-creates generic root account groups when a company is first set up.
    If a custom numbered COA (1-Asset, 2-Liabilities, etc.) was imported afterwards,
    the default groups become empty duplicates.  This function deletes them.

    Safe to run multiple times — skips groups that don't exist or still have children.

    Execute standalone:
        bench --site [site] execute backup.epromise_migration.setup_production.remove_duplicate_coa
    """
    print("\n[13] Remove duplicate ERPNext default COA root groups")

    default_roots = [
        "Application of Funds (Assets)",
        "Source of Funds (Liabilities)",
        "Equity",
        "Income",
        "Expenses",
        # ERPNext sometimes also creates these variants:
        "Current Assets",
        "Current Liabilities",
        "Fixed Assets",
        "Reserves and Surplus",
    ]

    deleted = 0
    for root_name in default_roots:
        full_name = f"{root_name} - {ABBR}"
        if not frappe.db.exists("Account", full_name):
            continue

        children = frappe.db.count("Account", {"parent_account": full_name})
        gl_entries = frappe.db.count("GL Entry", {"account": full_name})

        if children > 0:
            print(f"  SKIP    {full_name}  ({children} child accounts — remove children first)")
            continue
        if gl_entries > 0:
            print(f"  SKIP    {full_name}  ({gl_entries} GL entries — cannot delete)")
            continue

        try:
            frappe.delete_doc("Account", full_name, ignore_permissions=True, force=True)
            frappe.db.commit()
            print(f"  DELETED {full_name}")
            deleted += 1
        except Exception as e:
            frappe.db.rollback()
            print(f"  ERROR   {full_name}: {e}")

    if deleted == 0:
        print("  Nothing to delete (all groups either absent, have children, or have GL entries)")
    else:
        print(f"\n  Removed {deleted} duplicate root group(s). Reload the COA page to verify.")


# ─── Main entry point ─────────────────────────────────────────────────────────

def run_setup():
    """
    Run all pre-flight setup steps for the ePromise production migration.

    Execute with:
        bench --site [site-name] execute backup.epromise_migration.setup_production.run_setup
    """
    print("=" * 60)
    print("ePromise Migration — Production Pre-Flight Setup")
    print(f"Company: {COMPANY}  ({ABBR})")
    print("=" * 60)

    if not frappe.db.exists("Company", COMPANY):
        print(f"\nERROR: Company '{COMPANY}' not found.")
        print("Create the company first: Accounting → Company → New")
        return

    setup_periodic_inventory()
    setup_warehouse()
    setup_branch_warehouses()
    setup_cost_center()
    setup_item_groups()
    setup_uoms()
    setup_customer_masters()
    setup_supplier_groups()
    setup_modes_of_payment()
    setup_custom_fields()
    setup_global_settings()
    check_tax_accounts()
    check_coa_accounts()

    frappe.db.commit()
    print("\n" + "=" * 60)
    print("Setup complete. Review any WARN / MISSING items above.")
    print("Next step: open /app/epromise-import and upload the Excel file.")
    print("=" * 60)
