# apps/backup/backup/epromise_migration/gl_faithful/reconcile.py
"""Reconciliation toolkit for the GL-faithful engine.

Three comparison surfaces, all keyed by ERPNext account (source codes forward-mapped,
goods -> holding account):
    * threeway()        - source TB (report export) | source GL (live) | ERPNext
    * monthwise_verify()- ERPNext vs source GL, cumulative per month (proves faithfulness)
    * per_voucher_diff()- one account, per (TRC, VR), with the ERPNext doc that posted it
    * gross_drcr()      - Dr / Cr turnover per account (net can tie while gross differs)
    * dedup_by_trc_vr() - remove duplicate ERPNext docs sharing a source (TRC, VR)

Lesson: dedup MUST key on (TRC, VR) together -- source ERPs reuse VR numbers across TRC
codes, so keying on VR alone collapses distinct vouchers.
"""
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

import frappe
from frappe.utils import flt, getdate, get_last_day

from . import source as src


class Reconciler:
    def __init__(self, cfg, resolver):
        self.cfg = cfg
        self.r = resolver

    def _acct(self, code: str, name: str = "") -> Optional[str]:
        if self.cfg.is_goods(code):
            return self.cfg.srbnb_account
        return self.r.fwd(code, name)

    # ---- source GL (live) aggregated to ERPNext accounts ----
    def source_gl_by_account(self, conn) -> Dict[str, float]:
        cur = conn.cursor(as_dict=True)
        cur.execute(
            "SELECT ad.ACC_CODE code, ROUND(SUM(CASE WHEN ad.ACC_SIGN=1 THEN ad.report_amt "
            "ELSE -ad.report_amt END),3) net "
            "FROM DICADDATA ad JOIN DICHDATA dh ON dh.TRC_CODE=ad.TRC_CODE AND dh.VR_NO=ad.VR_NO "
            "WHERE dh.POSTED_IND='Y' AND CAST(dh.VR_DATE AS DATE) BETWEEN %s AND %s "
            "GROUP BY ad.ACC_CODE", (self.cfg.from_date, self.cfg.to_date))
        names = src.account_names(conn)
        out: Dict[str, float] = defaultdict(float)
        for row in cur.fetchall():
            code = str(row["code"]).strip()
            a = self._acct(code, names.get(code, ""))
            if a:
                out[a] += flt(row["net"])
        return out

    def erpnext_by_account(self) -> Dict[str, float]:
        out: Dict[str, float] = defaultdict(float)
        for row in frappe.db.sql(
            "SELECT account, ROUND(SUM(debit-credit),3) net FROM `tabGL Entry` "
            "WHERE company=%s AND is_cancelled=0 AND posting_date BETWEEN %s AND %s GROUP BY account",
            (self.cfg.company, self.cfg.from_date, self.cfg.to_date), as_dict=True):
            out[row.account] += flt(row.net)
        return out

    # ---- three-way ----
    def threeway(self, conn, tb_by_account: Optional[Dict[str, float]] = None,
                 tolerance: float = 1.0) -> List[Dict]:
        gl = self.source_gl_by_account(conn)
        erp = self.erpnext_by_account()
        tb = tb_by_account or {}
        rows = []
        for a in sorted(set(gl) | set(erp) | set(tb)):
            g = round(gl.get(a, 0), 2); e = round(erp.get(a, 0), 2); t = round(tb.get(a, 0), 2)
            rows.append({
                "account": a, "root": self.r.root.get(a, ""),
                "tb": t, "gl": g, "erp": e,
                "gl_erp": round(g - e, 2), "tb_gl": round(t - g, 2),
                "matched": abs(g - e) <= tolerance,
            })
        return rows

    # ---- month-wise ERPNext vs source GL ----
    def monthwise_verify(self, conn, tolerance: float = 1.0,
                         exclude=("Stock Received But Not Billed", "VAT Transit")) -> List[Dict]:
        def excl(a):
            return (not a) or any(x in a for x in exclude)
        names = src.account_names(conn)
        cur = conn.cursor(as_dict=True)
        cur.execute(
            "SELECT ad.ACC_CODE code, MONTH(dh.VR_DATE) m, ROUND(SUM(CASE WHEN ad.ACC_SIGN=1 "
            "THEN ad.report_amt ELSE -ad.report_amt END),2) net "
            "FROM DICADDATA ad JOIN DICHDATA dh ON dh.TRC_CODE=ad.TRC_CODE AND dh.VR_NO=ad.VR_NO "
            "WHERE dh.POSTED_IND='Y' AND CAST(dh.VR_DATE AS DATE) BETWEEN %s AND %s "
            "GROUP BY ad.ACC_CODE, MONTH(dh.VR_DATE)", (self.cfg.from_date, self.cfg.to_date))
        epm = defaultdict(lambda: defaultdict(float))
        for row in cur.fetchall():
            a = self._acct(str(row["code"]).strip(), names.get(str(row["code"]).strip(), ""))
            if a and not excl(a):
                epm[a][int(row["m"])] += flt(row["net"])
        erpm = defaultdict(lambda: defaultdict(float))
        for row in frappe.db.sql(
            "SELECT account, MONTH(posting_date) m, ROUND(SUM(debit-credit),2) net FROM `tabGL Entry` "
            "WHERE company=%s AND is_cancelled=0 AND posting_date BETWEEN %s AND %s "
            "GROUP BY account, MONTH(posting_date)",
            (self.cfg.company, self.cfg.from_date, self.cfg.to_date), as_dict=True):
            if not excl(row.account):
                erpm[row.account][int(row.m)] += flt(row.net)
        allacc = set(epm) | set(erpm)
        out = []
        for M in range(1, 13):
            matched = off = 0; resid = 0.0
            for a in allacc:
                ec = round(sum(epm[a][mm] for mm in range(1, M + 1)), 2)
                rc = round(sum(erpm[a][mm] for mm in range(1, M + 1)), 2)
                if abs(ec - rc) > tolerance:
                    off += 1; resid += abs(ec - rc)
                elif abs(ec) > 0.005 or abs(rc) > 0.005:
                    matched += 1
            if matched or off:
                out.append({"month": M, "matched": matched, "off": off, "residual": round(resid, 2)})
        return out

    # ---- per-voucher diff for one account ----
    def per_voucher_diff(self, conn, source_code: str, tolerance: float = 0.005) -> List[Dict]:
        cur = conn.cursor(as_dict=True)
        cur.execute(
            "SELECT dh.TRC_CODE trc, ad.VR_NO vr, ROUND(SUM(CASE WHEN ad.ACC_SIGN=1 THEN ad.report_amt "
            "ELSE -ad.report_amt END),3) net "
            "FROM DICADDATA ad JOIN DICHDATA dh ON dh.TRC_CODE=ad.TRC_CODE AND dh.VR_NO=ad.VR_NO "
            "WHERE ad.ACC_CODE=%s AND dh.POSTED_IND='Y' AND CAST(dh.VR_DATE AS DATE) BETWEEN %s AND %s "
            "GROUP BY dh.TRC_CODE, ad.VR_NO", (source_code, self.cfg.from_date, self.cfg.to_date))
        ep = {(str(r["trc"]).strip(), str(r["vr"]).strip()): flt(r["net"]) for r in cur.fetchall()}
        acct = self.r.fwd(source_code)
        erp = defaultdict(float)
        if acct:
            for dt in ("Sales Invoice", "Purchase Invoice", "Payment Entry", "Journal Entry"):
                for nm, trc, vr in frappe.get_all(
                    dt, filters={"company": self.cfg.company, "docstatus": 1}, as_list=1,
                    fields=["name", "epromise_trc_code", "epromise_vr_no"]):
                    if not vr:
                        continue
                    n = frappe.db.sql(
                        "SELECT ROUND(SUM(debit-credit),3) FROM `tabGL Entry` "
                        "WHERE voucher_no=%s AND account=%s AND is_cancelled=0", (nm, acct))[0][0]
                    if n:
                        erp[(str(trc).strip(), str(vr).strip())] += flt(n)
        out = []
        for k in set(ep) | set(erp):
            d = round(ep.get(k, 0) - erp.get(k, 0), 3)
            if abs(d) > tolerance:
                out.append({"trc": k[0], "vr": k[1], "source": round(ep.get(k, 0), 3),
                            "erpnext": round(erp.get(k, 0), 3), "diff": d})
        out.sort(key=lambda x: -abs(x["diff"]))
        return out

    # ---- gross Dr/Cr turnover ----
    def gross_drcr(self, conn, tolerance: float = 1.0) -> List[Dict]:
        names = src.account_names(conn)
        cur = conn.cursor(as_dict=True)
        cur.execute(
            "SELECT ad.ACC_CODE code, ROUND(SUM(CASE WHEN ad.ACC_SIGN=1 THEN ad.report_amt ELSE 0 END),3) dr, "
            "ROUND(SUM(CASE WHEN ad.ACC_SIGN<>1 THEN ad.report_amt ELSE 0 END),3) cr "
            "FROM DICADDATA ad JOIN DICHDATA dh ON dh.TRC_CODE=ad.TRC_CODE AND dh.VR_NO=ad.VR_NO "
            "WHERE dh.POSTED_IND='Y' AND CAST(dh.VR_DATE AS DATE) BETWEEN %s AND %s GROUP BY ad.ACC_CODE",
            (self.cfg.from_date, self.cfg.to_date))
        epd = defaultdict(float); epc = defaultdict(float)
        for row in cur.fetchall():
            a = self._acct(str(row["code"]).strip(), names.get(str(row["code"]).strip(), ""))
            if a:
                epd[a] += flt(row["dr"]); epc[a] += flt(row["cr"])
        out = []
        for row in frappe.db.sql(
            "SELECT account, ROUND(SUM(debit),3) dr, ROUND(SUM(credit),3) cr FROM `tabGL Entry` "
            "WHERE company=%s AND is_cancelled=0 AND posting_date BETWEEN %s AND %s GROUP BY account",
            (self.cfg.company, self.cfg.from_date, self.cfg.to_date), as_dict=True):
            dd = round(epd.get(row.account, 0) - flt(row.dr), 2)
            cd = round(epc.get(row.account, 0) - flt(row.cr), 2)
            if abs(dd) > tolerance or abs(cd) > tolerance:
                out.append({"account": row.account, "dr_diff": dd, "cr_diff": cd})
        out.sort(key=lambda x: -(abs(x["dr_diff"]) + abs(x["cr_diff"])))
        return out

    # ---- dedup duplicate docs sharing a source (TRC, VR) ----
    def dedup_by_trc_vr(self, doctype: str, trc_codes: Optional[List[str]] = None,
                        dry_run: bool = True) -> Dict:
        filters = {"company": self.cfg.company, "docstatus": 1, "epromise_vr_no": ["is", "set"]}
        if trc_codes:
            filters["epromise_trc_code"] = ["in", trc_codes]
        groups = defaultdict(list)
        for nm, trc, vr in frappe.get_all(
            doctype, filters=filters, order_by="creation",
            fields=["name", "epromise_trc_code", "epromise_vr_no"], as_list=1):
            groups[(str(trc).strip(), str(vr).strip())].append(nm)
        removed = 0; dups = 0
        for names in groups.values():
            if len(names) <= 1:
                continue
            dups += 1
            for nm in names[1:]:           # keep earliest by creation
                if dry_run:
                    removed += 1
                    continue
                try:
                    doc = frappe.get_doc(doctype, nm)
                    if doc.docstatus == 1:
                        doc.cancel()
                    frappe.delete_doc(doctype, nm, force=1, ignore_permissions=True)
                    removed += 1
                except Exception as e:
                    self.cfg.log(f"dedup {nm}: {str(e)[:80]}")
            if not dry_run and removed % 100 == 0:
                frappe.db.commit()
        if not dry_run:
            frappe.db.commit()
        return {"duplicate_groups": dups, "removed": removed, "dry_run": dry_run}


def read_source_tb_xls(path: str) -> List[Dict]:
    """Parse a source-ERP Trial Balance .xls export (BIFF/OLE) -> [{code, name, dr, cr, net}].

    Requires xlrd (reads legacy .xls). Assumes columns: A/c Code, Account Name, Debit,
    Credit, Net Balance with a 2-3 row header. Adjust header offset per export.
    """
    import xlrd
    wb = xlrd.open_workbook(path)
    sh = wb.sheet_by_index(0)
    header = 0
    for r in range(min(sh.nrows, 8)):
        cells = [str(sh.cell_value(r, c)).strip().lower() for c in range(sh.ncols)]
        if any("code" in c for c in cells) and any("debit" in c for c in cells):
            header = r + 1
            break
    rows = []
    for r in range(header, sh.nrows):
        code = sh.cell_value(r, 0); name = sh.cell_value(r, 1)
        if code == "" and name == "":
            continue
        code = str(code).replace(".0", "") if isinstance(code, float) else str(code).strip()
        rows.append({"code": code.strip(), "name": str(name).strip(),
                     "dr": flt(sh.cell_value(r, 2)), "cr": flt(sh.cell_value(r, 3)),
                     "net": flt(sh.cell_value(r, 4)) if sh.ncols > 4 else flt(sh.cell_value(r, 2)) + flt(sh.cell_value(r, 3))})
    return rows
