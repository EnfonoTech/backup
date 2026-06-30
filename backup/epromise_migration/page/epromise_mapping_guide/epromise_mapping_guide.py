import frappe
import csv
import io


def get_context(context):
    context.no_cache = 1


@frappe.whitelist()
def get_branch_list():
    """Return list of branch codes from DICHDATA for the branch dropdown."""
    from backup.epromise_migration.utils.bak_parser import connect_mssql
    settings = frappe.get_single("ePromise Settings")
    if not settings.mssql_host:
        return []
    conn = connect_mssql(settings)
    cur = conn.cursor()
    cur.execute("""
        SELECT DISTINCT SOURCE_BR_CODE br
        FROM DICHDATA WHERE SOURCE_BR_CODE IS NOT NULL AND SOURCE_BR_CODE != ''
        ORDER BY SOURCE_BR_CODE
    """)
    branches = [{"code": r["br"], "label": r["br"]} for r in cur]
    conn.close()
    return branches


@frappe.whitelist()
def get_daily_collection_report(from_date=None, to_date=None, branch_code=None):
    """
    Daily Transaction-wise / Collection Report matching ePromise format.

    Structure matches ePromise Daily Transaction-wise Report:
      - All main rows show NET amounts (excl. VAT), VAT shown separately
      - Cash Sales = S06 net | Credit Sales = S01 net
      - Returns show net (excl. VAT refund), VAT refund separate
      - Credit Purchase = GRN + Direct Purchase (111) only (not 350/IP — separate)
      - Cash Received: Credit Sales = all 004 Cash Receipt Vouchers
      - Petty Cash Payments/Receipts from DICADDATA debit/credit on petty cash accounts
    """
    from backup.epromise_migration.utils.bak_parser import connect_mssql
    settings = frappe.get_single("ePromise Settings")
    if not settings.mssql_host:
        frappe.throw("Live SQL Server connection not configured in ePromise Settings.")

    conn = connect_mssql(settings)

    date_clause = ""
    if from_date:
        date_clause += f" AND CAST(VR_DATE AS DATE) >= '{str(from_date)[:10]}'"
    if to_date:
        date_clause += f" AND CAST(VR_DATE AS DATE) <= '{str(to_date)[:10]}'"

    branch_clause = f" AND SOURCE_BR_CODE='{branch_code}'" if branch_code else ""

    def q(trc_list, col="ACC_AMT", no_branch=False):
        trc_ph = "','".join(trc_list)
        bc = "" if no_branch else branch_clause
        c = conn.cursor()
        c.execute(
            f"SELECT COALESCE(SUM({col}),0) AS v FROM DICHDATA "
            f"WHERE TRC_CODE IN ('{trc_ph}') AND POSTED_IND='Y'{date_clause}{bc}"
        )
        return float(c.fetchone()["v"] or 0)

    # ── Sales (ePromise shows NET = ACC_AMT - VAT_AMT on main row) ───────────
    s06_gross        = q(["S06"])
    s06_vat          = q(["S06"], "VAT_AMT")
    s06_net          = s06_gross - s06_vat          # what ePromise shows as "CASH SALES"

    s01_gross        = q(["S01"])
    s01_vat          = q(["S01"], "VAT_AMT")
    s01_net          = s01_gross - s01_vat          # "CREDIT SALES"

    # ── Returns (net = gross - VAT_refund) ────────────────────────────────────
    r04_gross        = q(["R04"])
    r04_vat          = q(["R04"], "VAT_AMT")
    r04_net          = r04_gross - r04_vat          # net return cost

    r01_gross        = q(["R01"])
    r01_vat          = q(["R01"], "VAT_AMT")
    r01_net          = r01_gross - r01_vat

    # ── Credit Purchases (GRN + Direct Purchase 111 only, not 350/IP) ────────
    grn_gross        = q(["GRN"])
    grn_vat          = q(["GRN"], "VAT_AMT")
    grn_net          = grn_gross - grn_vat

    dp_gross         = q(["111"])
    dp_vat           = q(["111"], "VAT_AMT")
    dp_net           = dp_gross - dp_vat

    purchase_net     = grn_net + dp_net
    purchase_vat     = grn_vat + dp_vat

    # ── Cash Received: Credit Sales = all 004 Cash Receipt Vouchers ──────────
    cash_recv_credit = q(["004"])                   # matches ePromise "Cash Received: Credit Sales"

    # ── Petty Cash from DICADDATA ─────────────────────────────────────────────
    # Petty cash accounts = ACC_CODE on 003/004 DICHDATA headers (start with 1301)
    # Receipts = DICADDATA debit entries (ACC_SIGN=1) on petty cash accounts
    # Payments = DICADDATA credit entries (ACC_SIGN=-1) on petty cash accounts
    # Discover the branch's petty cash account dynamically:
    # It is the 1301... account debited in DICADDATA when S06 (POS) runs for this branch.
    # For branch 0001 (SFB) → 13010200001 (Petty Cash - SFB)
    dc_ndate = date_clause.replace("VR_DATE", "dh.VR_DATE")
    branch_filter_dh = branch_clause.replace("SOURCE_BR_CODE", "dh.SOURCE_BR_CODE")

    _petty_acc_c = conn.cursor()
    if branch_code:
        _petty_acc_c.execute(
            f"""
            SELECT TOP 1 da.ACC_CODE FROM DICADDATA da
            INNER JOIN DICHDATA dh ON dh.TRC_CODE=da.TRC_CODE AND dh.VR_NO=da.VR_NO
            WHERE dh.TRC_CODE='S06' AND LEFT(da.ACC_CODE,4)='1301' AND da.ACC_SIGN=1
            AND dh.POSTED_IND='Y'{dc_ndate}{branch_filter_dh}
            GROUP BY da.ACC_CODE ORDER BY COUNT(*) DESC
            """
        )
        row = _petty_acc_c.fetchone()
        petty_cash_acc = row["ACC_CODE"] if row else None
    else:
        petty_cash_acc = None  # all branches: use all 1301 accounts

    petty_acc_filter = f" AND da.ACC_CODE='{petty_cash_acc}'" if petty_cash_acc else " AND LEFT(da.ACC_CODE,4)='1301'"

    def q_petty(sign_filter):
        c = conn.cursor()
        c.execute(
            f"""
            SELECT COALESCE(SUM(da.ACC_AMT),0) v
            FROM DICADDATA da
            INNER JOIN DICHDATA dh ON dh.TRC_CODE=da.TRC_CODE AND dh.VR_NO=da.VR_NO
            WHERE da.ACC_SIGN={sign_filter}{petty_acc_filter}
            AND dh.POSTED_IND='Y'{dc_ndate}
            """
        )
        return float(c.fetchone()["v"] or 0)

    petty_receipts   = q_petty(1)    # all debit on petty cash = cash received
    petty_payments   = q_petty(-1)   # all credit on petty cash = cash paid out

    # Cash Received: Credit Sales = ALL 004 vouchers (no branch — 004 has no SOURCE_BR_CODE)
    cash_recv_credit = q(["004"], no_branch=True)

    conn.close()

    # ── Cash Balance ───────────────────────────────────────────────────────────
    # (Cash Sales net) + (Cash Received from Customers) - (Returns net) - (Payments)
    # Cash Balance = Total Petty Cash Receipts − Total Petty Cash Payments
    cash_balance = petty_receipts - petty_payments

    # petty_cash_acc stored so drill-down can use same account
    _petty_acc_str = petty_cash_acc or ""

    def r(label, income=0.0, expense=0.0, bold=False, separator=False, category="", indent=False, drilldown=""):
        return {
            "label": ("    " + label) if indent else label,
            "income": round(income, 3), "expense": round(expense, 3),
            "bold": bold, "separator": separator, "category": category,
            "drilldown": drilldown,  # key passed to get_voucher_detail
        }

    rows = [
        # ── SALES ─────────────────────────────────────────────────────────────
        r("CASH SALES",                               income=s06_net,       bold=True,  category="sales",   drilldown="S06"),
        r("  Gross POS Sales (S06)",                  income=s06_gross,     indent=True, category="sales"),
        r("  VAT Collected on Cash Sales",            income=-s06_vat,      indent=True, category="sales"),

        r("CREDIT SALES",                             income=s01_net,       bold=True,  category="sales",   drilldown="S01"),
        r("  Gross Credit Sales (S01)",               income=s01_gross,     indent=True, category="sales"),
        r("  VAT Applied on Credit Sales",            income=-s01_vat,      indent=True, category="sales"),

        # ── RETURNS ───────────────────────────────────────────────────────────
        r("Sales Return - Cash (POS)",                expense=r04_net,      bold=True,  category="returns", drilldown="R04"),
        r("  Gross Return Cash (R04)",                expense=r04_gross,    indent=True, category="returns"),
        r("  VAT Refund on Cash Returns",             expense=-r04_vat,     indent=True, category="returns"),

        r("Sales Return - Credit Customers",          expense=r01_net,      bold=True,  category="returns", drilldown="R01"),
        r("  Gross Return Credit (R01)",              expense=r01_gross,    indent=True, category="returns"),
        r("  VAT Refund on Credit Returns",           expense=-r01_vat,     indent=True, category="returns"),

        # ── PURCHASES ─────────────────────────────────────────────────────────
        r("Credit Purchase - GRN / DIRECT PURCHASE",  expense=purchase_net, bold=True,  category="purchase", drilldown="GRN_111"),
        r("  Goods Receiving Note (GRN)",             expense=grn_net,      indent=True, category="purchase", drilldown="GRN"),
        r("  Direct Purchase (111)",                  expense=dp_net,       indent=True, category="purchase", drilldown="111"),
        r("  VAT Applied on Purchases",               expense=purchase_vat, indent=True, category="purchase"),

        # ── CASH MOVEMENT ─────────────────────────────────────────────────────
        r("Cash Received : Credit Sales",             income=cash_recv_credit, bold=True, category="cash",  drilldown="004"),
        r("Payments - Petty Cash (Total Payments)",   expense=petty_payments,  bold=True, category="cash",  drilldown="PETTY_OUT"),
        r("Receipts - Petty Cash (Total Receipts)",   income=petty_receipts,   bold=True, category="cash",  drilldown="PETTY_IN"),

        # ── BALANCE ───────────────────────────────────────────────────────────
        r("Cash Balance",
          income=cash_balance if cash_balance >= 0 else 0,
          expense=abs(cash_balance) if cash_balance < 0 else 0,
          bold=True, category="balance"),
    ]

    return {
        "rows": rows,
        "summary": {
            "net_cash_sales":   round(s06_net, 3),
            "net_credit_sales": round(s01_net, 3),
            "net_returns":      round(r04_net + r01_net, 3),
            "credit_purchase":  round(purchase_net, 3),
            "cash_received":    round(cash_recv_credit, 3),
            "petty_payments":   round(petty_payments, 3),
            "petty_receipts":   round(petty_receipts, 3),
            "cash_balance":     round(cash_balance, 3),
        },
        "from_date":       from_date,
        "to_date":         to_date,
        "branch":          branch_code or "All Branches",
        "petty_cash_acc":  _petty_acc_str,
    }


@frappe.whitelist()
def get_voucher_detail(from_date=None, to_date=None, drilldown=None,
                       branch_code=None, petty_cash_acc=None):
    """
    Return individual voucher rows for a clicked report line.
    drilldown: S06 | S01 | R04 | R01 | GRN | 111 | GRN_111 | IP | 004 | PETTY_IN | PETTY_OUT
    """
    from backup.epromise_migration.utils.bak_parser import connect_mssql
    settings = frappe.get_single("ePromise Settings")
    if not settings.mssql_host:
        return []

    conn = connect_mssql(settings)
    cur  = conn.cursor()

    date_clause  = ""
    if from_date: date_clause += f" AND CAST(VR_DATE AS DATE) >= '{str(from_date)[:10]}'"
    if to_date:   date_clause += f" AND CAST(VR_DATE AS DATE) <= '{str(to_date)[:10]}'"
    branch_clause = f" AND SOURCE_BR_CODE='{branch_code}'" if branch_code else ""

    def q_dichdata(trc_list, bc=True):
        trc_ph = "','".join(trc_list)
        bc_str = branch_clause if bc else ""
        cur.execute(f"""
            SELECT VR_NO, VR_DATE, BILL_NO, ACC_CODE, ACC_NAME,
                   ACC_AMT, VAT_AMT, (ACC_AMT - VAT_AMT) NET_AMT,
                   CUR_CODE, TRC_CODE, PARTICULARS
            FROM DICHDATA
            WHERE TRC_CODE IN ('{trc_ph}') AND POSTED_IND='Y'{date_clause}{bc_str}
            ORDER BY VR_DATE, VR_NO
        """)
        return [{"vr_no": str(r["VR_NO"]), "date": str(r["VR_DATE"])[:10],
                 "bill_no": r["BILL_NO"] or "", "acc_code": r["ACC_CODE"] or "",
                 "party": str(r["ACC_NAME"] or "").strip(),
                 "gross": float(r["ACC_AMT"] or 0), "vat": float(r["VAT_AMT"] or 0),
                 "net": float(r["NET_AMT"] or 0), "currency": r["CUR_CODE"] or "BHD",
                 "trc": r["TRC_CODE"], "remarks": str(r["PARTICULARS"] or "").strip()}
                for r in cur]

    def q_dicaddata(sign_filter, acc_filter):
        cur.execute(f"""
            SELECT da.VR_NO, dh.VR_DATE, dh.TRC_CODE, da.ACC_CODE,
                   da.ACC_AMT, da.PARTICULARS, da.ACC_SIGN,
                   dh.ACC_NAME AS PARTY
            FROM DICADDATA da
            INNER JOIN DICHDATA dh ON dh.TRC_CODE=da.TRC_CODE AND dh.VR_NO=da.VR_NO
            WHERE da.ACC_SIGN={sign_filter} {acc_filter}
            AND dh.POSTED_IND='Y'{date_clause.replace('VR_DATE','dh.VR_DATE')}
            ORDER BY dh.VR_DATE, da.VR_NO
        """)
        return [{"vr_no": str(r["VR_NO"]), "date": str(r["VR_DATE"])[:10],
                 "trc": r["TRC_CODE"], "acc_code": r["ACC_CODE"] or "",
                 "net": float(r["ACC_AMT"] or 0), "gross": float(r["ACC_AMT"] or 0),
                 "vat": 0, "currency": "BHD",
                 "party": str(r["PARTY"] or "").strip(),
                 "remarks": str(r["PARTICULARS"] or "").strip()}
                for r in cur]

    trc_map = {
        "S06": (["S06"], True), "S01": (["S01"], True),
        "R04": (["R04"], True), "R01": (["R01"], True),
        "GRN": (["GRN"], True), "111": (["111"], True),
        "GRN_111": (["GRN","111"], True),
        "004": (["004"], False),  # no branch filter for 004
    }

    if drilldown in trc_map:
        trcs, use_branch = trc_map[drilldown]
        rows = q_dichdata(trcs, use_branch)
    elif drilldown in ("PETTY_IN", "PETTY_OUT"):
        sign = 1 if drilldown == "PETTY_IN" else -1
        if petty_cash_acc:
            acc_f = f"AND da.ACC_CODE='{petty_cash_acc}'"
        else:
            acc_f = "AND LEFT(da.ACC_CODE,4)='1301'"
        rows = q_dicaddata(sign, acc_f)
    else:
        rows = []

    conn.close()
    return rows


@frappe.whitelist()
def get_mapping_stats():
    """Return counts of imported records for the mapping guide dashboard."""

    def safe_count(doctype, filters=None):
        try:
            return frappe.db.count(doctype, filters)
        except Exception:
            return 0

    def safe_sql_count(query):
        try:
            result = frappe.db.sql(query)
            return result[0][0] if result else 0
        except Exception:
            return 0

    # Sales Invoices by TRC code (stored in epromise_trc_code custom field)
    sinv_s01 = safe_sql_count(
        "SELECT COUNT(*) FROM `tabSales Invoice` WHERE epromise_trc_code='S01' AND docstatus != 2"
    )
    sinv_s06 = safe_sql_count(
        "SELECT COUNT(*) FROM `tabSales Invoice` WHERE epromise_trc_code='S06' AND docstatus != 2"
    )
    sinv_r01 = safe_sql_count(
        "SELECT COUNT(*) FROM `tabSales Invoice` WHERE epromise_trc_code='R01' AND docstatus != 2"
    )
    sinv_r04 = safe_sql_count(
        "SELECT COUNT(*) FROM `tabSales Invoice` WHERE epromise_trc_code='R04' AND docstatus != 2"
    )
    sinv_total = safe_count("Sales Invoice", {"docstatus": ["!=", 2]})

    # Purchase Receipts by TRC code
    pr_grn = safe_sql_count(
        "SELECT COUNT(*) FROM `tabPurchase Receipt` WHERE epromise_trc_code='GRN' AND docstatus != 2"
    )
    pr_gr = safe_sql_count(
        "SELECT COUNT(*) FROM `tabPurchase Receipt` WHERE epromise_trc_code='GR' AND docstatus != 2"
    )
    pr_total = safe_count("Purchase Receipt", {"docstatus": ["!=", 2]})

    # Purchase Invoices by TRC code
    pinv_350 = safe_sql_count(
        "SELECT COUNT(*) FROM `tabPurchase Invoice` WHERE epromise_trc_code='350' AND docstatus != 2"
    )
    pinv_111 = safe_sql_count(
        "SELECT COUNT(*) FROM `tabPurchase Invoice` WHERE epromise_trc_code='111' AND docstatus != 2"
    )
    pinv_ip = safe_sql_count(
        "SELECT COUNT(*) FROM `tabPurchase Invoice` WHERE epromise_trc_code='IP' AND docstatus != 2"
    )
    pinv_pr = safe_sql_count(
        "SELECT COUNT(*) FROM `tabPurchase Invoice` WHERE epromise_trc_code='PR' AND docstatus != 2"
    )
    pinv_total = safe_count("Purchase Invoice", {"docstatus": ["!=", 2]})

    # Payment Entries by TRC code
    pe_003 = safe_sql_count(
        "SELECT COUNT(*) FROM `tabPayment Entry` WHERE epromise_trc_code='003' AND docstatus != 2"
    )
    pe_004 = safe_sql_count(
        "SELECT COUNT(*) FROM `tabPayment Entry` WHERE epromise_trc_code='004' AND docstatus != 2"
    )
    pe_total = safe_count("Payment Entry", {"docstatus": ["!=", 2]})

    # Journal Entries by TRC code
    je_007 = safe_sql_count(
        "SELECT COUNT(*) FROM `tabJournal Entry` WHERE epromise_trc_code='007' AND docstatus != 2"
    )
    je_020 = safe_sql_count(
        "SELECT COUNT(*) FROM `tabJournal Entry` WHERE epromise_trc_code='020' AND docstatus != 2"
    )
    je_total = safe_count("Journal Entry", {"docstatus": ["!=", 2]})

    # Master data counts
    customer_total = safe_count("Customer")
    supplier_total = safe_count("Supplier")
    item_total = safe_count("Item")

    # Customers imported via ePromise (have epromise_acc_code custom field set)
    customer_epromise = safe_sql_count(
        "SELECT COUNT(*) FROM `tabCustomer` WHERE epromise_acc_code IS NOT NULL AND epromise_acc_code != ''"
    )
    supplier_epromise = safe_sql_count(
        "SELECT COUNT(*) FROM `tabSupplier` WHERE epromise_acc_code IS NOT NULL AND epromise_acc_code != ''"
    )

    # Migration logs
    log_total = safe_count("ePromise Migration Log")
    log_completed = safe_count("ePromise Migration Log", {"status": "Completed"})
    log_errors = safe_count("ePromise Migration Log", {"status": "Failed"})

    return {
        "sales": {
            "s01": sinv_s01,
            "s06": sinv_s06,
            "r01": sinv_r01,
            "r04": sinv_r04,
            "total": sinv_total,
        },
        "purchase_receipts": {
            "grn": pr_grn,
            "gr": pr_gr,
            "total": pr_total,
        },
        "purchase_invoices": {
            "350": pinv_350,
            "111": pinv_111,
            "ip": pinv_ip,
            "pr": pinv_pr,
            "total": pinv_total,
        },
        "payments": {
            "003": pe_003,
            "004": pe_004,
            "total": pe_total,
        },
        "journals": {
            "007": je_007,
            "020": je_020,
            "total": je_total,
        },
        "masters": {
            "customers_total": customer_total,
            "customers_epromise": customer_epromise,
            "suppliers_total": supplier_total,
            "suppliers_epromise": supplier_epromise,
            "items_total": item_total,
        },
        "logs": {
            "total": log_total,
            "completed": log_completed,
            "errors": log_errors,
        },
    }


@frappe.whitelist()
def get_epromise_report(from_date=None, to_date=None, branch_code=None):
    """
    Query the live ePromise SQL Server and return count + total amount for every
    importable document type within the given date range.
    Also returns how many of each type are already imported in ERPNext.
    branch_code: filter by SOURCE_BR_CODE (sales/purchase only — 003/004/020/007 have no branch)
    """
    from backup.epromise_migration.utils.bak_parser import connect_mssql
    settings = frappe.get_single("ePromise Settings")
    if not settings.mssql_host:
        frappe.throw("Live SQL Server connection not configured in ePromise Settings.")

    conn = connect_mssql(settings)

    date_clause = ""
    if from_date:
        date_clause += f" AND CAST(VR_DATE AS DATE) >= '{str(from_date)[:10]}'"
    if to_date:
        date_clause += f" AND CAST(VR_DATE AS DATE) <= '{str(to_date)[:10]}'"

    branch_clause = f" AND SOURCE_BR_CODE='{branch_code}'" if branch_code else ""

    # Detect branch petty cash account (same logic as DCR)
    # 003/004/020/007 have no SOURCE_BR_CODE — filter via DICADDATA petty cash account instead
    petty_cash_acc = None
    if branch_code:
        _c = conn.cursor()
        _c.execute(
            f"""SELECT TOP 1 da.ACC_CODE FROM DICADDATA da
            INNER JOIN DICHDATA dh ON dh.TRC_CODE=da.TRC_CODE AND dh.VR_NO=da.VR_NO
            WHERE dh.TRC_CODE='S06' AND LEFT(da.ACC_CODE,4)='1301' AND da.ACC_SIGN=1
            AND dh.POSTED_IND='Y'{date_clause.replace('VR_DATE','dh.VR_DATE')}
            AND dh.SOURCE_BR_CODE='{branch_code}'
            GROUP BY da.ACC_CODE ORDER BY COUNT(*) DESC"""
        )
        row = _c.fetchone()
        petty_cash_acc = row["ACC_CODE"] if row else None

    def q(trc_list, table="DICHDATA", extra_where="AND POSTED_IND='Y'", no_branch=False):
        """Run a fresh cursor for each query — safe with pymssql."""
        trc_ph = "','".join(trc_list)
        bc = "" if no_branch else branch_clause
        sql = (f"SELECT TRC_CODE, COUNT(*) AS cnt, SUM(ACC_AMT) AS total "
               f"FROM {table} "
               f"WHERE TRC_CODE IN ('{trc_ph}') {extra_where}{date_clause}{bc} "
               f"GROUP BY TRC_CODE")
        c = conn.cursor()
        c.execute(sql)
        result = {}
        for row in c.fetchall():
            result[row["TRC_CODE"]] = {
                "count": int(row["cnt"] or 0),
                "total": float(row["total"] or 0),
            }
        return result

    def q_via_petty(trc_list, sign_filter=None):
        """
        Query 003/004/020/007 filtered via the branch's petty cash account in DICADDATA.
        sign_filter: 1 = debit (receipts), -1 = credit (payments), None = either.
        If no petty_cash_acc detected, falls back to company-wide.
        """
        trc_ph = "','".join(trc_list)
        acc_filter = f" AND da.ACC_CODE='{petty_cash_acc}'" if petty_cash_acc else \
                     " AND LEFT(da.ACC_CODE,4)='1301'"
        sign_f = f" AND da.ACC_SIGN={sign_filter}" if sign_filter is not None else ""
        c = conn.cursor()
        c.execute(f"""
            SELECT d.TRC_CODE, COUNT(*) AS cnt, SUM(d.ACC_AMT) AS total
            FROM DICHDATA d
            WHERE d.TRC_CODE IN ('{trc_ph}') AND d.POSTED_IND='Y'{date_clause}
            {'AND EXISTS (SELECT 1 FROM DICADDATA da WHERE da.TRC_CODE=d.TRC_CODE AND da.VR_NO=d.VR_NO' + acc_filter + sign_f + ')' if petty_cash_acc else ''}
            GROUP BY d.TRC_CODE
        """)
        result = {}
        for row in c.fetchall():
            result[row["TRC_CODE"]] = {
                "count": int(row["cnt"] or 0),
                "total": float(row["total"] or 0),
            }
        return result

    def scalar(sql):
        c = conn.cursor()
        c.execute(sql)
        row = c.fetchone()
        return int(list(row.values())[0]) if row else 0

    # Transaction counts from DICHDATA
    sales    = q(["S01", "S06"])
    returns  = q(["R01", "R04"])
    receipts = q(["GRN", "GR"])
    pinv     = q(["350", "111", "IP"])
    preturn  = q(["PR"])
    # Payments/journals: branch-filtered via petty cash account when branch selected
    payments = q_via_petty(["003", "004"])
    journals = q_via_petty(["007", "020"])

    # Master data counts (no date filter)
    cust_count = scalar("SELECT COUNT(*) AS n FROM DICADMAS WHERE SUB_HEAD='D'")
    supp_count = scalar("SELECT COUNT(*) AS n FROM DICADMAS WHERE SUB_HEAD='C'")
    item_count = scalar("SELECT COUNT(*) AS n FROM DICIHMAS")

    conn.close()

    # Already imported in ERPNext
    def erpnext_count(doctype, trc_code):
        try:
            return frappe.db.count(doctype, {"epromise_trc_code": trc_code, "docstatus": ["!=", 2]})
        except Exception:
            return 0
    def erpnext_sum(doctype, trc_code):
        try:
            r = frappe.db.sql(
                f"SELECT SUM(grand_total) FROM `tab{doctype}` "
                f"WHERE epromise_trc_code=%s AND docstatus != 2",
                trc_code)
            return float(r[0][0] or 0) if r else 0.0
        except Exception:
            return 0.0

    # Structured like the Daily Collection Report — grouped by category
    # (category, trc, ep_name, erp_doctype, data_dict, has_amount, branch_note)
    # branch_note = True means "company-wide (no branch filter)" footnote
    MAPPING = [
        # ── SALES ──────────────────────────────────────────────────────────────
        ("Sales",    "S06",  "Cash Sales (POS)",          "Sales Invoice",    sales,    True,  False),
        ("Sales",    "S01",  "Credit Sales",              "Sales Invoice",    sales,    True,  False),
        ("Returns",  "R04",  "Sales Return - Cash (POS)", "Sales Invoice",    returns,  True,  False),
        ("Returns",  "R01",  "Sales Return - Credit",     "Sales Invoice",    returns,  True,  False),
        # ── PURCHASES ──────────────────────────────────────────────────────────
        ("Purchase", "GRN",  "Goods Receiving Note",      "Purchase Receipt", receipts, True,  False),
        ("Purchase", "GR",   "Goods Return",              "Purchase Receipt", receipts, True,  False),
        ("Purchase", "111",  "Direct Purchase",           "Purchase Invoice", pinv,     True,  False),
        ("Purchase", "IP",   "Import Purchase",           "Purchase Invoice", pinv,     True,  False),
        ("Purchase", "350",  "Purchase Invoice Item Wise","Purchase Invoice", pinv,     True,  False),
        ("Purchase", "PR",   "Purchase Return",           "Purchase Invoice", preturn,  True,  False),
        # ── CASH MOVEMENT (company-wide — no SOURCE_BR_CODE) ───────────────────
        ("Payment",  "004",  "Cash Received (Customer Receipts)", "Payment Entry", payments, True, True),
        ("Payment",  "003",  "Cash Payments (Supplier/Expenses)","Payment Entry",  payments, True, True),
        # ── JOURNALS (company-wide) ────────────────────────────────────────────
        ("Journal",  "020",  "Bank/Cash Adjustment",      "Journal Entry",    journals, True,  True),
        ("Journal",  "007",  "Journal Voucher",           "Journal Entry",    journals, True,  True),
    ]

    rows = []
    for category, trc, ep_name, erp_dt, data_dict, has_amount, no_branch_note in MAPPING:
        ep      = data_dict.get(trc, {"count": 0, "total": 0.0})
        ec      = erpnext_count(erp_dt, trc)
        et      = erpnext_sum(erp_dt, trc) if has_amount else 0.0
        pending = max(0, ep["count"] - ec)
        pct     = round((ec / ep["count"]) * 100) if ep["count"] else 100
        rows.append({
            "category":      category,
            "trc_code":      trc,
            "ep_name":       ep_name,
            "erp_doctype":   erp_dt,
            "ep_count":      ep["count"],
            "ep_total":      ep["total"],
            "erp_count":     ec,
            "erp_total":     et,
            "pending":       pending,
            "pct_done":      pct,
            "has_amount":    has_amount,
            "no_branch":     no_branch_note,  # True = company-wide, not branch-filtered
            "drilldown":     trc,             # used by JS click-to-detail
        })

    return {
        "rows": rows,
        "masters": {
            "customers":   {"ep": cust_count, "erp": frappe.db.count("Customer")},
            "suppliers":   {"ep": supp_count, "erp": frappe.db.count("Supplier")},
            "items":       {"ep": item_count, "erp": frappe.db.count("Item")},
        },
        "from_date":       from_date,
        "to_date":         to_date,
        "branch":          branch_code or "All Branches",
        "petty_cash_acc":  petty_cash_acc or "",
    }


@frappe.whitelist()
def download_mapping_report():
    """Generate and return a CSV mapping report."""
    rows = [
        ["Category", "TRC Code", "ePromise Name", "ERPNext DocType", "Series", "Item Source", "Status", "Notes"],
        # Sales
        ["Sales", "S01", "Credit Sales", "Sales Invoice", "ACC-SINV-CR-.YYYY.-", "SALES_DATA", "Mapped", "Standard credit invoice"],
        ["Sales", "S06", "Point of Sale", "Sales Invoice", "ACC-SINV-POS-.YYYY.-", "SALES_DATA", "Mapped", "POS cash invoice"],
        ["Sales", "R01", "Credit Sales Return", "Sales Invoice (Return)", "ACC-SINV-CR-RET-.YYYY.-", "DICZDATA", "Mapped", "is_return=1; qty negative; return_against linked"],
        ["Sales", "R04", "POS Sales Return", "Sales Invoice (Return)", "ACC-SINV-POS-RET-.YYYY.-", "DICZDATA", "Mapped", "is_return=1; qty negative; return_against linked"],
        # Purchase
        ["Purchase", "GRN", "Goods Receiving Note", "Purchase Receipt", "MAT-PRE-.YYYY.-", "PURCHASE_DATA", "Mapped", "Must run before Purchase Invoice"],
        ["Purchase", "GR", "Goods Return", "Purchase Receipt (Return)", "MAT-PRE-.YYYY.-", "PURCHASE_DATA", "Mapped", "is_return=1; return_against linked to GRN"],
        ["Purchase", "350", "Purchase Invoice Item Wise", "Purchase Invoice", "ACC-PINV-PI-.YYYY.-", "PURCHASE_INVOICE_DETAIL", "Mapped", "Each item linked to GRN purchase_receipt"],
        ["Purchase", "111", "Direct Purchase", "Purchase Invoice", "ACC-PINV-DIR-.YYYY.-", "PURCHASE_DATA", "Mapped", "Standalone; no GRN receipt"],
        ["Purchase", "IP", "Import Purchase", "Purchase Invoice", "ACC-PINV-IMP-.YYYY.-", "PURCHASE_DATA + DICADDATA (5xx)", "Mapped", "Freight/customs as service items"],
        ["Purchase", "PR", "Purchase Return", "Purchase Invoice (Return)", "ACC-PINV-RET-.YYYY.-", "PURCHASE_DATA", "Mapped", "is_return=1; return_against linked"],
        # Payments
        ["Payment", "003", "Cash Payment Voucher", "Payment Entry", "ACC-PAY-.YYYY.-", "DICADDATA GL lines", "Mapped", "Pay to Supplier; cash account from GL"],
        ["Payment", "004", "Cash Receipt Voucher", "Payment Entry", "ACC-REC-.YYYY.-", "DICADDATA GL lines", "Mapped", "Receive from Customer; customer from 1303 GL line"],
        # Journals
        ["Journal", "007", "Journal Voucher", "Journal Entry", "ACC-JV-.YYYY.-", "DICADDATA", "Mapped", "General journal entries"],
        ["Journal", "020", "Bank/Cash Adjustment", "Journal Entry", "ACC-JV-.YYYY.-", "DICADDATA", "Mapped", "Bank and cash adjustments"],
        # Masters
        ["Master", "DICADMAS (D)", "Customer", "Customer", "-", "DICADMAS sub_head=D", "Mapped", "epromise_acc_code stored on Customer"],
        ["Master", "DICADMAS (C)", "Supplier", "Supplier", "-", "DICADMAS sub_head=C", "Mapped", "epromise_acc_code stored on Supplier"],
        ["Master", "DICIHMAS", "Item", "Item", "-", "DICIHMAS", "Mapped", "is_stock_item=0; is_purchase_item=1; is_sales_item=1"],
        # Not yet mapped
        ["Not Mapped", "-", "Customer Address/Phone", "Customer Address", "-", "DICADMAS.ADDRESS / ACC_PHONE", "Not Mapped", "Suggestion: import to Address DocType"],
        ["Not Mapped", "-", "Supplier Credit Terms", "Supplier", "-", "DICADMAS.CREDIT_PERIOD", "Not Mapped", "Suggestion: set payment_terms on Supplier"],
        ["Not Mapped", "-", "Item Specifications", "Item (custom fields)", "-", "DICIHMAS custom fields", "Not Mapped", "Suggestion: length, width, weight as Item custom fields"],
        ["Not Mapped", "-", "Payment-Invoice Reconciliation", "Payment Entry", "-", "DICADDATA.REF_VR_NO / B_R_INT", "Partial", "Needs further exploration"],
        ["Not Mapped", "-", "Sales Order Reference", "Sales Invoice.po_no", "-", "DICHDATA.SO_NO", "Partial", "Currently uses BILL_NO; SO_NO excluded"],
        ["Not Mapped", "-", "Branch/Cost Center Mapping", "Cost Center", "-", "DICHDATA.SOURCE_BR_CODE", "Partial", "Codes need mapping to ERPNext cost center names"],
        ["Not Mapped", "-", "VAT Registration Number", "Customer.tax_id", "-", "DICADMAS.VAT_NO", "Mapped", "Mapped during customer import"],
        ["Not Mapped", "-", "Multi-Currency Debtors", "Account", "-", "Currency on Invoice", "Mapped", "BHD -> Debtors BHD-K; SAR -> Debtors SAR-K"],
        ["Not Mapped", "-", "Stock Items", "Item.is_stock_item", "-", "DICIHMAS", "Not Mapped", "Currently all non-stock; need warehouse config"],
        ["Not Mapped", "-", "Salesman", "Sales Team (child)", "-", "DICHDATA.SALES_MAN", "Not Mapped", "Child table limitation currently excluded"],
    ]

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerows(rows)
    csv_data = output.getvalue()

    frappe.response["filename"] = "epromise_mapping_report.csv"
    frappe.response["filecontent"] = csv_data
    frappe.response["type"] = "download"
    frappe.response["content_type"] = "text/csv"
