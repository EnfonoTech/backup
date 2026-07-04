# apps/backup/backup/epromise_migration/gl_faithful/source.py
"""Source-ERP (ePromise / MSSQL) access layer for the GL-faithful engine.

Reads connection settings from the `ePromise Settings` single doctype (password via the
encrypted field). All queries are parameterised. Schema references:
    DICADDATA  - GL detail lines (ACC_CODE, ACC_SIGN 1=Dr, report_amt, LOCAL_CUR_AMT, ACC_AMT, COST_CENTRE)
    DICHDATA   - voucher headers (TRC_CODE, VR_NO, VR_DATE, POSTED_IND, SOURCE_BR_CODE, CUR_RATE)
    DICZDATA   - item lines (ITE_CODE, ITE_QTY, ITE_RATE)
"""
from typing import List, Dict, Optional

import frappe
from frappe.utils import flt


def source_connection():
    import pymssql
    s = frappe.get_doc("ePromise Settings")
    try:
        pw = s.get_password("mssql_password")
    except Exception:
        pw = s.mssql_password
    return pymssql.connect(server=s.mssql_host, port=str(s.mssql_port), user=s.mssql_username,
                           password=pw, database=s.mssql_database, timeout=300, login_timeout=30)


def load_gl_map() -> Dict[str, str]:
    """Account-code -> ERPNext account-name map maintained by the app (accountant-provided)."""
    try:
        from backup.epromise_migration.utils.gl_map import load_gl_map as _load
        return _load()
    except Exception:
        return {}


def preload_account_cache(company: str) -> Dict[str, str]:
    try:
        from backup.epromise_migration.utils import payment_importer as piu
        try:
            return piu._preload_account_cache(company)
        except TypeError:
            return piu._preload_account_cache()
    except Exception:
        return {}


def fetch_voucher_gl(conn, trc: str, vrno: str) -> List[Dict]:
    cur = conn.cursor(as_dict=True)
    cur.execute(
        "SELECT ACC_CODE, ACC_SIGN, report_amt, LOCAL_CUR_AMT, ACC_AMT, COST_CENTRE "
        "FROM DICADDATA WHERE TRC_CODE=%s AND VR_NO=%s", (trc, vrno))
    return [{"code": str(r["ACC_CODE"]).strip(), "sign": r["ACC_SIGN"], "report_amt": r["report_amt"],
             "local_cur_amt": r["LOCAL_CUR_AMT"], "acc_amt": r["ACC_AMT"], "cost_centre": r["COST_CENTRE"]}
            for r in cur.fetchall()]


def fetch_item_lines(conn, trc: str, vrno: str) -> List[Dict]:
    cur = conn.cursor(as_dict=True)
    cur.execute("SELECT ITE_CODE, ITE_QTY, ITE_RATE FROM DICZDATA WHERE TRC_CODE=%s AND VR_NO=%s", (trc, vrno))
    return [{"code": str(r["ITE_CODE"]).strip(), "qty": flt(r["ITE_QTY"]), "rate": flt(r["ITE_RATE"])}
            for r in cur.fetchall()]


def iter_headers(conn, cfg, trc_codes: Optional[List[str]] = None) -> List[Dict]:
    """Posted voucher headers in the configured date range, optionally filtered to TRC codes."""
    cur = conn.cursor(as_dict=True)
    sql = ("SELECT TRC_CODE, VR_NO, VR_DATE, SOURCE_BR_CODE, CUR_RATE FROM DICHDATA "
           "WHERE POSTED_IND='Y' AND CAST(VR_DATE AS DATE) BETWEEN %s AND %s")
    params = [cfg.from_date, cfg.to_date]
    if trc_codes:
        sql += " AND TRC_CODE IN (" + ",".join(["%s"] * len(trc_codes)) + ")"
        params += list(trc_codes)
    cur.execute(sql, tuple(params))
    return [{"trc": str(r["TRC_CODE"]).strip(), "vrno": str(r["VR_NO"]).strip(),
             "vr_date": r["VR_DATE"], "br": r["SOURCE_BR_CODE"], "cur_rate": flt(r["CUR_RATE"]) or 1}
            for r in cur.fetchall()]


def account_names(conn) -> Dict[str, str]:
    cur = conn.cursor(as_dict=True)
    cur.execute("SELECT ACC_CODE, ACC_NAME FROM DICADMAS")
    return {str(r["ACC_CODE"]).strip(): (r["ACC_NAME"] or "").strip() for r in cur.fetchall()}
