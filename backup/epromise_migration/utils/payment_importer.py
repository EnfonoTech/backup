"""
Imports Payment Entries from ePromise into ERPNext.
  003 (Cash Payment Voucher) → Payment Entry (Pay) — supplier identified from DICADDATA GL lines (acc_code starts '22')
  004 (Cash Receipt Voucher) → Payment Entry (Receive) — customer identified from DICADDATA GL lines (acc_code starts '1303')
For each payment, attempts to allocate against oldest outstanding invoices of the party.
Custom field epromise_vr_no on Payment Entry for dedup.

Also handles:
  020 (Bank/Cash Adjustment) → Journal Entry
  007 (Journal Voucher)      → Journal Entry
"""

import frappe
from frappe.utils import now_datetime, flt, getdate
from backup.epromise_migration.utils.bak_parser import connect_mssql
from backup.epromise_migration.utils.gl_map import load_gl_map, resolve_account

CASH_PAYMENT_TRC  = ("003",)   # Cash Payment Voucher → Payment Entry (Pay) or Journal
CASH_RECEIPT_TRC  = ("004",)   # Cash Receipt Voucher → Payment Entry (Receive)
JOURNAL_TRC       = ("020", "007")  # Bank/Cash Adjustment, Journal Voucher → Journal Entry
ALL_VOUCHER_TRC   = CASH_PAYMENT_TRC + CASH_RECEIPT_TRC + JOURNAL_TRC
BATCH_SIZE        = 10   # commit every 10 — payment entries are few, keep log live


def _get_settings():
    return frappe.get_single("ePromise Settings")


def _ensure_custom_fields():
    fields = [
        ("Payment Entry", "epromise_vr_no",  "ePromise Voucher No",  "naming_series", 1),
        ("Payment Entry", "epromise_trc_code","ePromise TRC Code",    "epromise_vr_no", 0),
        ("Journal Entry", "epromise_vr_no",  "ePromise Voucher No",  "title",          1),
        ("Journal Entry", "epromise_trc_code","ePromise TRC Code",    "epromise_vr_no", 0),
    ]
    for dt, fieldname, label, insert_after, search_index in fields:
        if not frappe.db.exists("Custom Field", {"dt": dt, "fieldname": fieldname}):
            frappe.get_doc({
                "doctype": "Custom Field", "dt": dt,
                "label": label, "fieldname": fieldname,
                "fieldtype": "Data", "insert_after": insert_after,
                "read_only": 1, "search_index": search_index,
            }).insert(ignore_permissions=True)
    frappe.db.commit()


def _preload_account_cache(company):
    """
    Build account lookup: {epromise_code: erpnext_account_name}.
    Priority order per code:
      1. GL Mapping Excel (explicit cross-mapping for codes that changed in ERPNext)
      2. account_number field match in tabAccount (when code stayed the same)
    """
    # 1. GL mapping Excel (authoritative)
    cache = dict(load_gl_map())   # str(ep_code) → full ERPNext account name

    # 2. account_number field in ERPNext (fill gaps not in the GL map)
    rows = frappe.db.sql("""
        SELECT account_number, name FROM `tabAccount`
        WHERE company=%s AND COALESCE(account_number,'') != ''
    """, company, as_dict=True)
    for r in rows:
        if r.account_number not in cache:
            cache[r.account_number] = r.name

    # 3. Party ledgers: map ePromise party codes (Receivable 1303* / Payable 2201*) to
    #    their ERPNext per-party ledger via the ePromise account master (DICADMAS) name.
    #    Without this, party codes absent from the GL map fall back to the default cash
    #    account and payments get mis-posted to the bank instead of the supplier/customer.
    try:
        _settings = _get_settings()
        if getattr(_settings, "mssql_host", None):
            _conn = connect_mssql(_settings); _cur = _conn.cursor()
            _cur.execute("SELECT ACC_CODE, ACC_NAME FROM DICADMAS WHERE ACC_CODE LIKE '1303%' OR ACC_CODE LIKE '2201%'")
            _adm = {str(row["ACC_CODE"]).strip(): (row["ACC_NAME"] or "").strip() for row in _cur.fetchall()}
            _conn.close()
            _byname = {}
            for a in frappe.get_all("Account", filters={"company": company, "is_group": 0}, fields=["name", "account_name"]):
                _byname[(a.account_name or "").strip().lower()] = a.name
            for _code, _nm in _adm.items():
                _led = _byname.get(_nm.lower())
                if _led:
                    cache[_code] = _led   # authoritative for party codes
    except Exception as _e:
        frappe.log_error(str(_e)[:200], "party cache preload")

    return cache


def _get_default_cash_account(company):
    """Return first available Cash or Bank account for the company."""
    acc = frappe.db.get_value("Account",
        {"company": company, "account_type": ["in", ["Cash", "Bank"]], "is_group": 0},
        "name", order_by="account_type asc")
    return acc


def _get_account_for_payment(acc_code, account_cache, company, settings):
    """
    Resolve an ePromise acc_code to an ERPNext account name.
    Priority: GL map / account_number match → settings default → first Cash/Bank account.
    """
    if not acc_code:
        return None
    found = account_cache.get(str(acc_code).strip())
    if found:
        return found
    # Fall back to default cash account from settings or auto-detect
    default = getattr(settings, "default_cash_account", None) or \
              getattr(settings, "default_paid_from_account", None)
    if default and frappe.db.exists("Account", default):
        return default
    return _get_default_cash_account(company)


def _find_customer_from_acc_code(acc_code):
    return frappe.db.get_value("Customer", {"epromise_acc_code": acc_code}, "name")


def _find_supplier_from_acc_code(acc_code):
    return frappe.db.get_value("Supplier", {"epromise_acc_code": acc_code}, "name")


def _iter_vouchers(settings, trc_codes):
    if not settings.mssql_host:
        frappe.throw("Payment/Journal import requires a live SQL Server connection.")

    from_date = settings.invoice_from_date or None
    to_date   = settings.invoice_to_date   or None
    trc_ph    = "','".join(trc_codes)

    conn = connect_mssql(settings)
    cur  = conn.cursor()

    date_filter, params = "", []
    if from_date:
        date_filter += f" AND CAST(VR_DATE AS DATE) >= '{str(from_date)[:10]}'"
    if to_date:
        date_filter += f" AND CAST(VR_DATE AS DATE) <= '{str(to_date)[:10]}'"

    cur.execute(
        f"SELECT * FROM DICHDATA WHERE TRC_CODE IN ('{trc_ph}') AND POSTED_IND='Y'{date_filter} ORDER BY VR_NO",
        params,
    )
    hdrs = {}
    for r in cur:
        row = {k.lower(): v for k, v in dict(r).items()}
        hdrs[(row["trc_code"], str(row["vr_no"]))] = row

    from collections import defaultdict

    # DICADDATA: GL account lines (for journal entry fallback)
    gl_map = defaultdict(list)
    cur.execute(
        f"SELECT * FROM DICADDATA WHERE TRC_CODE IN ('{trc_ph}'){date_filter} ORDER BY VR_NO, SR_NO",
        params,
    )
    for r in cur:
        row = {k.lower(): v for k, v in dict(r).items()}
        gl_map[(row["trc_code"], str(row["vr_no"]))].append(row)

    # DICSDATA: bill settlement table — party account + exact invoice being paid
    bill_map = defaultdict(list)
    cur.execute(
        f"SELECT TRC_CODE, VR_NO, ASR_NO, SR_NO, ACC_CODE, BILL_NO, ACC_AMT, ACC_SIGN, "
        f"       REF_TRC_CODE, REF_VR_NO "
        f"FROM DICSDATA "
        f"WHERE TRC_CODE IN ('{trc_ph}'){date_filter} "
        f"ORDER BY VR_NO, ASR_NO, SR_NO",
        params,
    )
    for r in cur:
        row = {k.lower(): v for k, v in dict(r).items()}
        bill_map[(row["trc_code"], str(row["vr_no"]))].append(row)

    conn.close()
    for _key, hdr in hdrs.items():
        yield hdr, gl_map.get(_key, []), bill_map.get(_key, [])


# ─── Payment Entry builder ─────────────────────────────────────────────────────

def _get_invoice_refs_from_dicsdata(conn, trc_code, vr_no, doctype):
    """
    Use DICSDATA (ePromise bill settlement table) to find exact invoices
    this payment voucher is settling. Returns Payment Entry reference dicts.

    DICSDATA.REF_VR_NO = VR_NO of the invoice being settled.
    DICSDATA.ACC_AMT   = amount allocated from this payment to that invoice.
    """
    refs = []
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT REF_TRC_CODE, REF_VR_NO, ACC_AMT, BILL_NO, ACC_CODE
            FROM DICSDATA
            WHERE TRC_CODE=%s AND VR_NO=%s AND REF_VR_NO IS NOT NULL AND REF_VR_NO != 0
            ORDER BY ASR_NO, SR_NO
        """, (trc_code, vr_no))
        rows = [{k.lower(): v for k, v in dict(r).items()} for r in cur]
        for row in rows:
            ref_vr = str(row.get("ref_vr_no") or "").strip()
            alloc  = flt(row.get("acc_amt") or 0)
            if not ref_vr or not alloc:
                continue
            # Find the ERPNext invoice by epromise_vr_no
            inv_name = frappe.db.get_value(doctype, {"epromise_vr_no": ref_vr}, "name")
            if inv_name:
                grand_total = flt(frappe.db.get_value(doctype, inv_name, "grand_total") or alloc)
                outstanding = flt(frappe.db.get_value(doctype, inv_name, "outstanding_amount") or alloc)
                refs.append({
                    "doctype": "Payment Entry Reference",
                    "reference_doctype": doctype,
                    "reference_name": inv_name,
                    "total_amount": grand_total,
                    "outstanding_amount": outstanding,
                    "allocated_amount": min(alloc, outstanding) if outstanding > 0 else alloc,
                })
    except Exception:
        pass
    return refs


def _get_outstanding_invoices(party_type, party, amount, doctype):
    """
    Fallback: find outstanding invoices for a party (oldest first) when
    DICSDATA linking is unavailable or returned no matches.
    """
    refs = []
    if not party:
        return refs
    try:
        party_field = "supplier" if party_type == "Supplier" else "customer"
        outstanding = frappe.db.get_all(
            doctype,
            filters={party_field: party, "docstatus": 1, "outstanding_amount": [">", 0]},
            fields=["name", "outstanding_amount", "grand_total"],
            order_by="posting_date asc",
            limit=10,
        )
        remaining = amount
        for inv in outstanding:
            if remaining <= 0:
                break
            alloc = min(flt(inv.outstanding_amount), remaining)
            refs.append({
                "doctype": "Payment Entry Reference",
                "reference_doctype": doctype,
                "reference_name": inv.name,
                "total_amount": flt(inv.grand_total),
                "outstanding_amount": flt(inv.outstanding_amount),
                "allocated_amount": alloc,
            })
            remaining -= alloc
    except Exception:
        pass
    return refs


def _build_refs_from_bill_rows(bill_rows, inv_doctype, total_amount, inv_cache=None):
    """
    Build Payment Entry references from pre-fetched DICSDATA rows.
    Uses inv_cache {epromise_vr_no: (erp_name, grand_total, outstanding)} — zero DB queries.
    """
    refs = []
    remaining = flt(total_amount)
    for row in bill_rows:
        ref_vr = str(row.get("ref_vr_no") or "").strip()
        alloc  = flt(row.get("acc_amt") or 0)
        if not ref_vr or not alloc or remaining <= 0:
            continue
        # Fast cache lookup — no DB query
        cached = (inv_cache or {}).get(ref_vr)
        if cached:
            inv_name, grand_total, outstanding = cached
        else:
            # Fallback DB lookup (only if not in cache)
            inv_name = frappe.db.get_value(inv_doctype, {"epromise_vr_no": ref_vr}, "name")
            if not inv_name:
                continue
            grand_total = flt(frappe.db.get_value(inv_doctype, inv_name, "grand_total") or alloc)
            outstanding = flt(frappe.db.get_value(inv_doctype, inv_name, "outstanding_amount") or alloc)
        actual_alloc = min(alloc, remaining)
        refs.append({
            "doctype": "Payment Entry Reference",
            "reference_doctype": inv_doctype,
            "reference_name": inv_name,
            "total_amount": grand_total,
            "outstanding_amount": outstanding,
            "allocated_amount": min(actual_alloc, outstanding) if outstanding > 0 else actual_alloc,
        })
        remaining -= actual_alloc
    return refs


def _build_payment_entry_from_dicsdata(hdr, bill_rows, gl_lines, settings, account_cache,
                                       inv_cache=None, default_payable=None,
                                       default_receivable=None, default_cash=None):
    """
    Primary builder — uses DICSDATA as the authoritative source for:
      - party account (supplier 2201... or customer 1303...)
      - invoice bill linkage (REF_VR_NO)
    The DICHDATA header ACC_CODE is the cash/bank account.

    003 Cash Payment: paid_from=cash, paid_to=payable, party=Supplier
    004 Cash Receipt: paid_from=receivable, paid_to=cash, party=Customer
    Falls back to None (→ journal entry) when no party is found in DICSDATA.
    """
    trc_code  = hdr.get("trc_code", "")
    vr_no     = str(hdr.get("vr_no") or "").strip()
    cash_acc  = (hdr.get("acc_code") or "").strip()   # cash/bank account on DICHDATA header
    currency  = (hdr.get("cur_code") or "BHD").strip()
    amount    = flt(hdr.get("acc_amt") or 0)
    narration = (hdr.get("particulars") or "").strip()
    company   = settings.erpnext_company

    try:
        posting_date = getdate(str(hdr.get("vr_date") or "")[:10])
    except Exception:
        posting_date = getdate("2024-01-01")

    if not vr_no or not amount:
        return None

    # ── Identify party from DICSDATA rows ────────────────────────────────────
    party_acc = None
    for row in bill_rows:
        acc = (row.get("acc_code") or "").strip()
        # Supplier accounts start with 22; customer AR accounts start with 1303
        if acc.startswith("22") or acc.startswith("1303"):
            party_acc = acc
            break

    # Fallback: check DICADDATA GL lines if DICSDATA has no party
    if not party_acc:
        for gl in gl_lines:
            acc = (gl.get("acc_code") or "").strip()
            if acc.startswith("22") or acc.startswith("1303"):
                party_acc = acc
                break

    if not party_acc:
        return None  # no identifiable party → caller falls back to journal entry

    is_supplier = party_acc.startswith("22")
    # Use pre-cached default accounts — zero DB queries
    cash_erpnext = (account_cache.get(cash_acc)
                    or default_cash
                    or _get_default_cash_account(company))

    if is_supplier:
        party = _find_supplier_from_acc_code(party_acc)
        if not party:
            return None
        payment_type = "Pay"
        paid_from = cash_erpnext
        paid_to   = frappe.db.get_value("Party Account",
                        {"parent": party, "parenttype": "Supplier", "company": company}, "account") \
                    or default_payable or settings.default_payable_account or \
                    frappe.db.get_value("Account", {"company": company, "account_type": "Payable", "is_group": 0}, "name")
        party_type  = "Supplier"
        inv_doctype = "Purchase Invoice"
    else:
        party = _find_customer_from_acc_code(party_acc)
        if not party:
            return None
        payment_type = "Receive"
        paid_from = frappe.db.get_value("Party Account",
                        {"parent": party, "parenttype": "Customer", "company": company}, "account") \
                    or default_receivable or settings.default_debit_account or \
                    frappe.db.get_value("Account", {"company": company, "account_type": "Receivable", "is_group": 0}, "name")
        paid_to   = cash_erpnext
        party_type  = "Customer"
        inv_doctype = "Sales Invoice"

    pe = {
        "doctype": "Payment Entry",
        "payment_type": payment_type,
        "company": company,
        "posting_date": posting_date,
        "party_type": party_type,
        "party": party,
        "paid_from": paid_from,
        "paid_to": paid_to,
        "paid_from_account_currency": currency,
        "paid_to_account_currency": currency,
        "paid_amount": amount,
        "received_amount": amount,
        "source_exchange_rate": flt(hdr.get("cur_rate") or 1) or 1,
        "target_exchange_rate": flt(hdr.get("cur_rate") or 1) or 1,
        "reference_no": vr_no,
        "reference_date": posting_date,
        "remarks": narration or f"ePromise {trc_code}/{vr_no}",
        "epromise_vr_no": vr_no,
        "epromise_trc_code": trc_code,
    }

    # ── Bill linkage from DICSDATA — use pre-cached inv_cache for speed ────────
    refs = _build_refs_from_bill_rows(bill_rows, inv_doctype, amount, inv_cache)
    if not refs:
        refs = _get_outstanding_invoices(party_type, party, amount, inv_doctype)
    if refs:
        pe["references"] = refs

    return ("payment_entry", pe)


# Keep old names as aliases so existing call sites still work
def _build_cash_payment_entry(hdr, gl_lines, settings, account_cache, conn=None, bill_rows=None):
    return _build_payment_entry_from_dicsdata(hdr, bill_rows or [], gl_lines, settings, account_cache) \
        or _build_journal_entry_from_voucher(hdr, gl_lines, settings, account_cache)


def _build_cash_receipt_entry(hdr, gl_lines, settings, account_cache, conn=None, bill_rows=None):
    return _build_payment_entry_from_dicsdata(hdr, bill_rows or [], gl_lines, settings, account_cache) \
        or _build_journal_entry_from_voucher(hdr, gl_lines, settings, account_cache)


def _build_journal_entry_from_voucher(hdr, gl_lines, settings, account_cache, default_cash=None):
    """Build a Journal Entry from voucher header + GL lines.
    Amounts use report_amt (BHD base) — NEVER acc_amt (the foreign transaction amount),
    which otherwise inflates every foreign-currency (SAR/USD/AED) voucher."""
    trc_code   = hdr.get("trc_code", "")
    vr_no      = str(hdr.get("vr_no") or "").strip()
    currency   = "BHD"
    narration  = (hdr.get("particulars") or "").strip()
    acc_code   = (hdr.get("acc_code") or "").strip()

    def _bhd(row):
        if not row:
            return 0.0
        for k in ("report_amt", "local_cur_amt", "acc_amt"):
            v = row.get(k)
            if v is not None and flt(v) != 0:
                return flt(v)
        return 0.0

    try:
        posting_date = getdate(str(hdr.get("vr_date") or "")[:10])
    except Exception:
        posting_date = getdate("2024-01-01")
    if not vr_no:
        return None

    company = settings.erpnext_company
    _cash = default_cash or _get_default_cash_account(company)
    accounts = []

    # Build entirely from the source GL lines (DICADDATA); each carries its own sign and
    # report_amt (BHD). This is the complete, balanced set for a posted voucher.
    for gl in (gl_lines or []):
        gl_acc_code = (gl.get("acc_code") or "").strip()
        gl_account = account_cache.get(gl_acc_code) or _cash
        if not gl_account:
            continue
        gl_amt = _bhd(gl)
        if gl_amt == 0:
            continue
        gl_sign = str(gl.get("acc_sign") or "1")
        gl_part = (gl.get("particulars") or narration or "").strip()
        if flt(gl_sign) >= 0:
            accounts.append({
                "account": gl_account,
                "debit_in_account_currency": gl_amt,
                "credit_in_account_currency": 0,
                "account_currency": currency,
                "user_remark": gl_part,
            })
        else:
            accounts.append({
                "account": gl_account,
                "debit_in_account_currency": 0,
                "credit_in_account_currency": gl_amt,
                "account_currency": currency,
                "user_remark": gl_part,
            })

    # Fallback: no usable GL detail -> post header account against cash/suspense.
    if not accounts:
        amount = _bhd(hdr)
        hdr_account = account_cache.get(acc_code) or _cash
        if hdr_account and amount:
            is_receipt = trc_code in CASH_RECEIPT_TRC
            accounts.append({
                "account": hdr_account,
                "debit_in_account_currency":  amount if is_receipt else 0,
                "credit_in_account_currency": 0 if is_receipt else amount,
                "account_currency": currency,
                "user_remark": narration or f"ePromise {trc_code}/{vr_no}",
            })

    if not accounts:
        return None

    if len(accounts) == 1:
        suspense = default_cash or _get_default_cash_account(company)
        if suspense and suspense != accounts[0]["account"]:
            first = accounts[0]
            accounts.append({
                "account": suspense,
                "debit_in_account_currency":  first["credit_in_account_currency"],
                "credit_in_account_currency": first["debit_in_account_currency"],
                "account_currency": currency,
                "user_remark": f"[Auto suspense] {narration or vr_no}",
            })

    voucher_type_map = {
        "003": "Cash Entry", "004": "Cash Entry",
        "020": "Bank Entry", "007": "Journal Entry",
    }
    jv = {
        "doctype": "Journal Entry",
        "company": company,
        "posting_date": posting_date,
        "voucher_type": voucher_type_map.get(trc_code, "Journal Entry"),
        "user_remark": narration or f"ePromise {trc_code}/{vr_no}",
        "accounts": accounts,
        "epromise_vr_no": vr_no,
        "epromise_trc_code": trc_code,
    }
    return ("journal_entry", jv)


# ─── background worker ────────────────────────────────────────────────────────

def _run_voucher_import(log_name, trc_codes, migration_type="Payment Entry"):
    settings = _get_settings()
    log = frappe.get_doc("ePromise Migration Log", log_name)
    log.status = "Running"
    log.save(ignore_permissions=True)
    frappe.db.commit()

    _ensure_custom_fields()
    account_cache = _preload_account_cache(settings.erpnext_company)
    company = settings.erpnext_company

    # ── Pre-cache invoice references — avoids per-row frappe.db.get_value ────
    # {epromise_vr_no: (erp_name, grand_total, outstanding_amount)}
    inv_cache = {}
    for dt in ("Sales Invoice", "Purchase Invoice"):
        try:
            rows = frappe.db.get_all(dt,
                filters={"epromise_vr_no": ["!=", ""], "docstatus": 1},
                fields=["name", "epromise_vr_no", "grand_total", "outstanding_amount"])
            for r in rows:
                inv_cache[r.epromise_vr_no] = (r.name, flt(r.grand_total), flt(r.outstanding_amount))
        except Exception:
            pass

    # ── Pre-cache default accounts ─────────────────────────────────────────────
    abbr = frappe.db.get_value("Company", company, "abbr") or "K"
    _default_cash     = _get_default_cash_account(company)
    _default_payable  = (settings.default_payable_account
        or frappe.db.get_value("Account", {"company": company, "account_type": "Payable", "is_group": 0}, "name")
        or f"Creditors - {abbr}")
    _default_receive  = (settings.default_debit_account
        or frappe.db.get_value("Account", {"company": company, "account_type": "Receivable", "is_group": 0}, "name")
        or f"Debtors - {abbr}")

    existing = set()
    if settings.skip_existing:
        for dt in ("Payment Entry", "Journal Entry"):
            try:
                rows = frappe.db.get_all(dt, filters={"epromise_vr_no": ["!=", ""]},
                    fields=["epromise_vr_no", "epromise_trc_code"])
                existing.update((r.epromise_trc_code, r.epromise_vr_no) for r in rows)
            except Exception:
                pass

    total = success = skipped = errors = 0
    log_lines = []
    frappe.flags.in_import = True
    frappe.flags.ignore_account_permission = True

    try:
        for hdr, gl_lines, bill_rows in _iter_vouchers(settings, trc_codes):
            total += 1
            vr_no    = str(hdr.get("vr_no") or "").strip()
            trc_code = hdr.get("trc_code", "")
            acc_name = (hdr.get("acc_name") or "").strip()

            if not vr_no:
                skipped += 1
                log_lines.append(f"[SKIP] {trc_code}/? — {acc_name}: missing vr_no")
                continue

            if total % 50 == 0:
                if frappe.db.get_value("ePromise Migration Log", log.name, "status") == "Stop Requested":
                    frappe.db.commit()
                    log.reload()
                    log.status = "Stopped"
                    log.total_records = total; log.success_count = success
                    log.skipped_count = skipped; log.error_count = errors
                    log.completed_at = now_datetime()
                    log.log_details = "\n".join(log_lines[-500:])
                    log.save(ignore_permissions=True)
                    frappe.db.commit()
                    return

            if settings.skip_existing and (trc_code, vr_no) in existing:
                skipped += 1
                log_lines.append(f"[SKIP] {trc_code}/{vr_no} — {acc_name}: already imported")
                continue

            try:
                if trc_code in CASH_PAYMENT_TRC or trc_code in CASH_RECEIPT_TRC:
                    result = _build_payment_entry_from_dicsdata(
                        hdr, bill_rows, gl_lines, settings, account_cache,
                        inv_cache=inv_cache,
                        default_payable=_default_payable,
                        default_receivable=_default_receive,
                        default_cash=_default_cash)
                    if not result:
                        result = _build_journal_entry_from_voucher(hdr, gl_lines, settings, account_cache,
                            default_cash=_default_cash)
                else:
                    result = _build_journal_entry_from_voucher(hdr, gl_lines, settings, account_cache,
                        default_cash=_default_cash)

                if not result:
                    skipped += 1
                    # Diagnose why the builder returned None
                    has_supplier = any((gl.get("acc_code") or "").startswith("22") for gl in gl_lines)
                    has_customer = any((gl.get("acc_code") or "").startswith("1303") for gl in gl_lines)
                    has_cash     = any((gl.get("acc_code") or "").startswith("13") for gl in gl_lines)
                    reason = []
                    if not gl_lines:
                        reason.append("no GL lines in DICADDATA")
                    else:
                        if trc_code in CASH_PAYMENT_TRC and not has_supplier:
                            reason.append("no supplier GL line (acc_code starting 22)")
                        if trc_code in CASH_RECEIPT_TRC and not has_customer:
                            reason.append("no customer GL line (acc_code starting 1303)")
                        cash_acc = (hdr.get("acc_code") or "").strip()
                        if not cash_acc:
                            reason.append("no cash account on header")
                    log_lines.append(
                        f"[SKIP] {trc_code}/{vr_no} — {acc_name}: "
                        f"could not build entry ({'; '.join(reason) or 'builder returned None'})"
                    )
                    continue

                doc_type_hint, doc_dict = result
                doc = frappe.get_doc(doc_dict)
                doc.flags.ignore_permissions = True
                doc.flags.ignore_mandatory   = True
                doc.flags.ignore_links       = True
                doc.flags.ignore_validate    = True
                doc.flags.ignore_version     = True
                doc.insert(ignore_permissions=True)

                success += 1
                existing.add((trc_code, vr_no))
                log_lines.append(f"[OK] {trc_code}/{vr_no} — {acc_name} | amt={hdr.get('acc_amt')}")

                # Commit and update log progress after every BATCH_SIZE records
                if (success + errors) % BATCH_SIZE == 0 or total <= 20:
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
        pass  # dicsdata_conn removed — DICSDATA now fetched in _iter_vouchers
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
def import_payment_vouchers():
    """003 (Cash Payment) + 004 (Cash Receipt) → Payment Entry with supplier/customer party."""
    settings = _get_settings()
    if not settings.erpnext_company:
        frappe.throw("Please configure ePromise Settings before importing.")
    if not settings.mssql_host:
        frappe.throw("Requires a live SQL Server connection.")

    log = frappe.get_doc({
        "doctype": "ePromise Migration Log",
        "migration_type": "Payment Entry",
        "status": "Queued",
        "started_at": now_datetime(),
    })
    log.insert(ignore_permissions=True)
    frappe.db.commit()

    frappe.enqueue(
        "backup.epromise_migration.utils.payment_importer._run_voucher_import",
        log_name=log.name,
        trc_codes=list(CASH_PAYMENT_TRC + CASH_RECEIPT_TRC),
        migration_type="Payment Entry",
        queue="long", timeout=7200,
        job_name=f"epromise-pay-{log.name}",
    )
    return {"log_name": log.name, "status": "queued",
            "message": f"Payment Vouchers import queued. Track in {log.name}."}


@frappe.whitelist()
def import_cash_vouchers():
    """020 (Bank/Cash Adj) + 007 (Journal Voucher) → Journal Entry."""
    settings = _get_settings()
    if not settings.erpnext_company:
        frappe.throw("Please configure ePromise Settings before importing.")
    if not settings.mssql_host:
        frappe.throw("Requires a live SQL Server connection.")

    log = frappe.get_doc({
        "doctype": "ePromise Migration Log",
        "migration_type": "Journal Entry",
        "status": "Queued",
        "started_at": now_datetime(),
    })
    log.insert(ignore_permissions=True)
    frappe.db.commit()

    frappe.enqueue(
        "backup.epromise_migration.utils.payment_importer._run_voucher_import",
        log_name=log.name,
        trc_codes=list(JOURNAL_TRC),
        migration_type="Journal Entry",
        queue="long", timeout=7200,
        job_name=f"epromise-jv-{log.name}",
    )
    return {"log_name": log.name, "status": "queued",
            "message": f"Journal Vouchers import queued. Track in {log.name}."}


@frappe.whitelist()
def import_payment_entries():
    """
    003 (Cash Payment Voucher) → Payment Entry (Pay to Supplier)
    004 (Cash Receipt Voucher) → Payment Entry (Receive from Customer)
    Alias for import_payment_vouchers — preferred entry point from migration page.
    """
    return import_payment_vouchers()


@frappe.whitelist()
def stop_import(log_name):
    """Request a running payment/journal import to stop after the current batch."""
    status = frappe.db.get_value("ePromise Migration Log", log_name, "status")
    if status not in ("Running", "Queued"):
        return {"ok": False, "message": f"Cannot stop — current status is '{status}'"}
    frappe.db.set_value("ePromise Migration Log", log_name, "status", "Stop Requested")
    frappe.db.commit()
    return {"ok": True, "message": "Stop requested — will halt after current batch."}
