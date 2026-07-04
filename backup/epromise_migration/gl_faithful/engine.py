# apps/backup/backup/epromise_migration/gl_faithful/engine.py
"""Orchestrator for the GL-faithful migration.

Routes each source voucher to a builder chain (falling back to a plain Journal Entry so
no voucher is ever dropped), submits with COMMIT-PER-DOC (one bad doc never rolls back a
whole batch), and supports safe re-import with GUARD-BEFORE-REBUILD.

    chain by TRC route:
      SI -> build_si -> build_je
      PI -> build_pi_realitems -> build_pi -> build_je
      PE -> build_pe -> build_je
      JE -> build_je

Guard-before-rebuild (hard lesson): when re-importing a voucher, only build the
replacement AFTER the existing docs are confirmed deleted, and skip if a target doc
already exists -- otherwise a failed delete leaves the original AND a new doc double-posting.
"""
from typing import Dict, List, Optional, Callable

import frappe
from frappe.utils import flt

from .config import GLFaithfulConfig
from .resolve import AccountResolver
from .builders import DocBuilder
from .reconcile import Reconciler
from . import source as src

DOCTYPES = ("Sales Invoice", "Purchase Invoice", "Payment Entry", "Journal Entry")


def default_item_mapper(source_code: str) -> Optional[str]:
    return (frappe.db.get_value("Item", {"epromise_ite_code": source_code}, "name")
            or frappe.db.get_value("Item", {"item_code": source_code}, "name"))


class Engine:
    def __init__(self, cfg: GLFaithfulConfig, item_mapper: Optional[Callable] = None):
        self.cfg = cfg
        self.resolver = AccountResolver(cfg, gl_map=src.load_gl_map(),
                                        cache=src.preload_account_cache(cfg.company))
        self.builder = DocBuilder(cfg, self.resolver, item_mapper=item_mapper or default_item_mapper)
        self.reconciler = Reconciler(cfg, self.resolver)
        self.conn = None

    def _connect(self):
        if self.conn is None:
            self.conn = src.source_connection()
        return self.conn

    # ---- build one voucher via its fallback chain ----
    def build(self, hdr: Dict, gl: List[Dict]):
        route = self.cfg.trc_map.get(hdr["trc"], "JE")
        if route == "SKIP":
            return None, "skip", "trc skipped by config"
        if route == "SI":
            doc, err = self.builder.build_si(hdr, gl)
            if doc:
                return doc, "SI", None
        elif route == "PI":
            dicz = src.fetch_item_lines(self._connect(), hdr["trc"], hdr["vrno"])
            if dicz:
                doc, err = self.builder.build_pi_realitems(hdr, gl, dicz, hdr.get("cur_rate", 1))
                if doc:
                    return doc, "PI(items)", None
            doc, err = self.builder.build_pi(hdr, gl)
            if doc:
                return doc, "PI", None
        elif route == "PE":
            doc, err = self.builder.build_pe(hdr, gl)
            if doc:
                return doc, "PE", None
        doc, err = self.builder.build_je(hdr, gl)     # universal fallback
        if doc:
            return doc, "JE", None
        return None, "fail", err

    # ---- guard-before-rebuild ----
    def _has_doc(self, trc: str, vr: str) -> bool:
        return any(frappe.db.exists(dt, {"company": self.cfg.company, "docstatus": 1,
                                         "epromise_trc_code": trc, "epromise_vr_no": vr})
                   for dt in DOCTYPES)

    def _clear_existing(self, trc: str, vr: str) -> bool:
        ok = True
        for dt in DOCTYPES:
            for nm in frappe.get_all(dt, filters={"company": self.cfg.company,
                                     "epromise_trc_code": trc, "epromise_vr_no": vr}, pluck="name"):
                try:
                    doc = frappe.get_doc(dt, nm)
                    if doc.docstatus == 1:
                        doc.cancel()
                    frappe.delete_doc(dt, nm, force=1, ignore_permissions=True)
                except Exception as e:
                    ok = False
                    self.cfg.log(f"clear {dt} {nm}: {str(e)[:80]}")
        return ok

    # ---- run ----
    def run(self, trc_codes: Optional[List[str]] = None, reimport: bool = False,
            submit: bool = True, dry_run: bool = False, limit: Optional[int] = None) -> Dict:
        conn = self._connect()
        headers = src.iter_headers(conn, self.cfg, trc_codes)
        stats = {"total": len(headers), "built": {}, "skipped": 0, "failed": 0}
        done = 0
        for hdr in headers:
            trc, vr = hdr["trc"], hdr["vrno"]
            if reimport:
                if not self._clear_existing(trc, vr):     # failed delete -> never rebuild
                    frappe.db.rollback(); stats["skipped"] += 1
                    self.cfg.log(f"skip (delete failed) {trc}/{vr}"); continue
                frappe.db.commit()
            elif self._has_doc(trc, vr):
                stats["skipped"] += 1; continue
            gl = src.fetch_voucher_gl(conn, trc, vr)
            if not gl:
                stats["skipped"] += 1; continue
            doc, kind, err = self.build(hdr, gl)
            if not doc:
                stats["failed"] += 1
                self.cfg.log(f"FAIL {trc}/{vr}: {err}"); continue
            if dry_run:
                stats["built"][kind] = stats["built"].get(kind, 0) + 1; continue
            try:
                doc.insert(ignore_permissions=True)
                if submit:
                    doc.submit()
                frappe.db.commit()                          # commit-per-doc
                stats["built"][kind] = stats["built"].get(kind, 0) + 1
            except Exception as e:
                frappe.db.rollback(); stats["failed"] += 1
                self.cfg.log(f"ERR {trc}/{vr}: {str(e)[:120]}")
            done += 1
            if limit and done >= limit:
                break
        return stats

    def trial_balance_ok(self) -> Dict:
        tb = frappe.db.sql(
            "SELECT ROUND(SUM(debit),2), ROUND(SUM(credit),2) FROM `tabGL Entry` "
            "WHERE company=%s AND is_cancelled=0", (self.cfg.company,))[0]
        dr, cr = flt(tb[0]), flt(tb[1])
        return {"debit": dr, "credit": cr, "balanced": abs(dr - cr) < 0.01}
