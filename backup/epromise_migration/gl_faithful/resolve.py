# apps/backup/backup/epromise_migration/gl_faithful/resolve.py
"""Account + party resolution for the GL-faithful engine.

Resolution order for a source GL code -> ERPNext account (`fwd`):
    1. an external cache (e.g. payment_importer._preload_account_cache), if supplied
    2. `resolve()`  -> account_number match FIRST, then gl_map (with number-prefix fallback)
    3. name-match fallback (for source rows coded at group level, e.g. parties)
Every candidate is run through `real_acct()` which normalises whitespace and maps a
bare "<number> - <name>" or head string onto the actual leaf account name.

Lesson baked in: check account_number BEFORE gl_map, so an account created by number
overrides a stale gl_map fallback. Bank accounts are often RENUMBERED per the client
COA, so never assume the ERPNext account_number equals the source code -- always fwd().
"""
import re
from typing import Optional, Tuple, Dict, Callable

import frappe


class AccountResolver:
    def __init__(self, cfg, gl_map: Optional[Dict[str, str]] = None,
                 cache: Optional[Dict[str, str]] = None):
        self.cfg = cfg
        self.company = cfg.company
        self.abbr = cfg.abbr
        self.gl_map = gl_map or {}
        self._cache = cache or {}
        accs = frappe.get_all(
            "Account",
            filters={"company": self.company, "is_group": 0},
            fields=["name", "account_number", "account_type", "root_type"],
        )
        self.by_num: Dict[str, str] = {a.account_number: a.name for a in accs if a.account_number}
        self.real = {a.name for a in accs}
        self.norm: Dict[str, str] = {self._norm(a.name): a.name for a in accs}
        self.head: Dict[str, str] = {}
        for a in accs:
            self.head.setdefault(a.name.split(" - ")[0].strip(), a.name)
            if a.account_number:
                self.head.setdefault(a.account_number.strip(), a.name)
        self.atype: Dict[str, str] = {a.name: a.account_type for a in accs}
        self.root: Dict[str, str] = {a.name: a.root_type for a in accs}
        # party ledger -> (party_type, party) learned from existing GL (most reliable)
        self.party_map: Dict[str, Tuple[str, str]] = {}
        for r in frappe.db.sql(
            "SELECT account, party_type, party FROM `tabGL Entry` "
            "WHERE ifnull(party,'')!='' AND company=%s GROUP BY account, party_type, party",
            (self.company,), as_dict=True,
        ):
            self.party_map.setdefault(r.account, (r.party_type, r.party))
        # party-name indexes for the create-if-missing fallback
        self._cust_by_name: Dict[str, str] = {}
        for c in frappe.get_all("Customer", fields=["name", "customer_name"]):
            self._cust_by_name[self._norm(c.name)] = c.name
            if c.customer_name:
                self._cust_by_name[self._norm(c.customer_name)] = c.name
        self._supp_by_name: Dict[str, str] = {}
        for s in frappe.get_all("Supplier", fields=["name", "supplier_name"]):
            self._supp_by_name[self._norm(s.name)] = s.name
            if s.supplier_name:
                self._supp_by_name[self._norm(s.supplier_name)] = s.name

    @staticmethod
    def _norm(s: str) -> str:
        return re.sub(r"\s+", " ", (s or "")).strip().lower()

    # ---- account resolution ----
    def real_acct(self, a: Optional[str]) -> Optional[str]:
        if not a:
            return None
        if a in self.real:
            return a
        head = a.split(" - ")[0].strip()
        return self.head.get(head) or self.norm.get(self._norm(a))

    def resolve(self, code: str) -> Optional[str]:
        code = str(code).strip()
        if code in self.by_num:            # account_number FIRST
            return self.by_num[code]
        v = self.gl_map.get(code)
        if v and frappe.db.exists("Account", v):
            return v
        if v:                              # gl_map value like "5201 - Foo": fall back to its number
            m = re.match(r"^(\d+)", v)
            if m and m.group(1) in self.by_num:
                return self.by_num[m.group(1)]
        return None

    def fwd(self, code: str, name: Optional[str] = None) -> Optional[str]:
        code = str(code).strip()
        a = self.real_acct(self._cache.get(code) or self.resolve(code))
        if a:
            return a
        if name:                           # name-match fallback (group-coded source rows)
            return self.norm.get(self._norm(name)) or self.head.get(name.split(" - ")[0].strip())
        return None

    # ---- party resolution ----
    def needs_party(self, acct: Optional[str], code: str) -> bool:
        if self.atype.get(acct) in ("Receivable", "Payable"):
            return True
        code = str(code).strip()
        return code.startswith(self.cfg.customer_prefix) or code.startswith(self.cfg.supplier_prefix)

    def party_of(self, acct: str, code: str, create_missing: bool = True) -> Tuple[Optional[str], Optional[str]]:
        if acct in self.party_map:
            return self.party_map[acct]
        code = str(code).strip()
        at = self.atype.get(acct)
        nm = re.sub(rf"\s*-\s*{re.escape(self.abbr)}$", "", acct).strip()
        is_cust = at == "Receivable" or code.startswith(self.cfg.customer_prefix)
        is_supp = at == "Payable" or code.startswith(self.cfg.supplier_prefix)
        if is_cust and not is_supp:
            p = self._cust_by_name.get(self._norm(nm)) or frappe.db.get_value(
                "Party Account", {"account": acct, "parenttype": "Customer"}, "parent")
            if not p and create_missing:
                p = self._ensure_customer(nm)
            if p:
                self.party_map[acct] = ("Customer", p)
                return "Customer", p
        if is_supp:
            p = self._supp_by_name.get(self._norm(nm)) or frappe.db.get_value(
                "Party Account", {"account": acct, "parenttype": "Supplier"}, "parent")
            if not p and create_missing:
                p = self._ensure_supplier(nm)
            if p:
                self.party_map[acct] = ("Supplier", p)
                return "Supplier", p
        return None, None

    def _ensure_customer(self, nm: str) -> str:
        p = self._cust_by_name.get(self._norm(nm))
        if p:
            return p
        cg = frappe.db.get_value("Customer Group", {"is_group": 0}, "name")
        tr = frappe.db.get_value("Territory", {"is_group": 0}, "name")
        d = frappe.get_doc({"doctype": "Customer", "customer_name": nm,
                            "customer_group": cg, "territory": tr})
        d.flags.ignore_permissions = True
        d.insert()
        self._cust_by_name[self._norm(nm)] = d.name
        return d.name

    def _ensure_supplier(self, nm: str) -> str:
        p = self._supp_by_name.get(self._norm(nm))
        if p:
            return p
        sg = frappe.db.get_value("Supplier Group", {"is_group": 0}, "name")
        d = frappe.get_doc({"doctype": "Supplier", "supplier_name": nm, "supplier_group": sg})
        d.flags.ignore_permissions = True
        d.insert()
        self._supp_by_name[self._norm(nm)] = d.name
        return d.name
