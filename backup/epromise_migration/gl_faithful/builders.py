# apps/backup/backup/epromise_migration/gl_faithful/builders.py
"""GL-faithful document builders.

Each builder turns one source voucher's GL lines into an ERPNext document whose posted
GL equals the source line-for-line. Builders return (doc, None) on success or
(None, reason) so the caller can fall back to the next builder (PI -> generic PI -> JE).

Techniques proven on the ePromise->ERPNext migration:
  * JE  : one line per source GL line; goods legs -> SRBNB; sub-tolerance imbalance
          absorbed to the round-off account (never plug more than balance_tolerance).
  * PE  : payment direction inferred from the party leg's sign (Cr party -> Receive).
  * PI  : landing costs (freight/customs) posted as "Deduct" Actual taxes so they
          capitalise into the item value; input VAT as "Add"; supplier auto-balances.
  * PI (real items): rebuild real item lines from the source item table + a single
          reconciliation line = goods_total - sum(item lines); taxes appended INLINE
          before the one insert (a post-insert save wipes Actual taxes).
  * SI  : cash sales via is_pos payments straight to the cash account (so no spurious
          debtor turnover); returns use is_return with negative qty.
"""
from typing import List, Dict, Optional, Tuple

import frappe
from frappe.utils import flt, getdate


class DocBuilder:
    def __init__(self, cfg, resolver, item_mapper=None):
        self.cfg = cfg
        self.r = resolver
        self.item_mapper = item_mapper      # callable(source_item_code) -> ERPNext item, optional
        self._generic_item = None

    # ---- helpers ----
    def _amt(self, row: Dict) -> float:
        for k in self.cfg.amount_fields:
            v = row.get(k)
            if v not in (None, ""):
                return flt(v)
        return 0.0

    def _net(self, row: Dict, flip: int = 1) -> float:
        return (self._amt(row) if row["sign"] == 1 else -self._amt(row)) * flip

    def _branch_cc(self, br) -> str:
        if br:
            v = str(br).strip()
            for cand in (f"{v} - {self.cfg.abbr}", v):
                if frappe.db.exists("Cost Center", cand):
                    return cand
        return self.cfg.default_cost_center

    def _branch_wh(self, br) -> Optional[str]:
        if br:
            cand = f"{str(br).strip()} - {self.cfg.abbr}"
            if frappe.db.exists("Warehouse", cand):
                return cand
        return frappe.db.get_value("Warehouse", {"company": self.cfg.company, "is_group": 0}, "name")

    def generic_item(self) -> str:
        if self._generic_item:
            return self._generic_item
        nm = "MIGRATED-GOODS"
        if not frappe.db.exists("Item", nm):
            frappe.get_doc({
                "doctype": "Item", "item_code": nm, "item_name": "Migrated Goods (holding)",
                "item_group": frappe.db.get_value("Item Group", {"is_group": 0}, "name"),
                "stock_uom": "Nos", "is_stock_item": 0, "is_purchase_item": 1,
            }).insert(ignore_permissions=True)
        self._generic_item = nm
        return nm

    def _acct_for(self, code: str) -> Optional[str]:
        return self.cfg.srbnb_account if self.cfg.is_goods(code) else self.r.fwd(code)

    # ---- Journal Entry (fully general; the universal fallback) ----
    def build_je(self, hdr: Dict, gl: List[Dict]) -> Tuple[Optional[object], Optional[str]]:
        vrno = str(hdr["vrno"]); trc = hdr["trc"]; pdate = getdate(str(hdr["vr_date"])[:10])
        cc = self._branch_cc(hdr.get("br")); eps = self.cfg.line_epsilon; dp = self.cfg.round_dp
        je = frappe.new_doc("Journal Entry")
        je.voucher_type = "Journal Entry"; je.company = self.cfg.company; je.posting_date = pdate
        je.cheque_no = vrno; je.cheque_date = pdate
        je.user_remark = f"Migrated {trc}/{vrno}"
        je.epromise_vr_no = vrno; je.epromise_trc_code = trc
        tot = 0.0
        for row in gl:
            net = self._net(row)
            if abs(net) < eps:
                continue
            acct = self._acct_for(row["code"])
            if not acct:
                return None, f"unmapped {row['code']}"
            line = {"account": acct, "cost_center": cc}
            if net > 0:
                line["debit_in_account_currency"] = round(net, dp)
            else:
                line["credit_in_account_currency"] = round(-net, dp)
            if self.r.needs_party(acct, row["code"]):
                pt, party = self.r.party_of(acct, row["code"])
                if not (pt and party):
                    return None, f"unresolved party {acct}"
                line["party_type"] = pt; line["party"] = party
            je.append("accounts", line); tot += net
        if abs(round(tot, 2)) > self.cfg.balance_tolerance:
            return None, f"unbalanced {tot:.2f}"
        if abs(round(tot, dp)) > 0.0005:                 # absorb sub-tolerance rounding
            ro = self.r.by_num.get(self.cfg.roundoff_account_number) \
                or self.r.head.get(self.cfg.roundoff_account_number)
            if not ro:
                return None, "no round-off account"
            line = {"account": ro, "cost_center": cc}
            if tot > 0:
                line["credit_in_account_currency"] = round(tot, dp)
            else:
                line["debit_in_account_currency"] = round(-tot, dp)
            je.append("accounts", line)
        if len(je.accounts) < 2:
            return None, "too few lines"
        return je, None

    # ---- Payment Entry (simple 2-leg party<->cash) ----
    def build_pe(self, hdr: Dict, gl: List[Dict]) -> Tuple[Optional[object], Optional[str]]:
        vrno = str(hdr["vrno"]); trc = hdr["trc"]; pdate = getdate(str(hdr["vr_date"])[:10])
        cc = self._branch_cc(hdr.get("br")); eps = self.cfg.line_epsilon
        party_lines = []; other = []
        for row in gl:
            net = self._net(row)
            if abs(net) < eps:
                continue
            a = self.r.fwd(row["code"])
            (party_lines if self.r.needs_party(a, row["code"]) else other).append((row["code"], a, net))
        if len(party_lines) != 1 or len(other) != 1:
            return None, "non-simple -> JE"
        pcode, pacct, pnet = party_lines[0]; _, cash_acct, cash_net = other[0]
        if not pacct or not cash_acct:
            return None, "unmapped -> JE"
        if abs(pnet + cash_net) > 0.02:
            return None, "unbalanced -> JE"
        pt, party = self.r.party_of(pacct, pcode)
        if not party:
            return None, f"no party {pacct}"
        amt = abs(pnet)
        pe = frappe.new_doc("Payment Entry")
        pe.company = self.cfg.company; pe.posting_date = pdate
        pe.party_type = pt; pe.party = party; pe.cost_center = cc
        pe.reference_no = vrno; pe.reference_date = pdate
        pe.epromise_vr_no = vrno; pe.epromise_trc_code = trc
        if pnet < 0:                       # Cr party -> money received
            pe.payment_type = "Receive"; pe.paid_from = pacct; pe.paid_to = cash_acct
        else:                              # Dr party -> money paid
            pe.payment_type = "Pay"; pe.paid_from = cash_acct; pe.paid_to = pacct
        pe.paid_amount = amt; pe.received_amount = amt
        pe.paid_from_account_currency = self.cfg.default_currency
        pe.paid_to_account_currency = self.cfg.default_currency
        return pe, None

    # ---- Purchase Invoice (generic single-line goods + landing/VAT taxes) ----
    def build_pi(self, hdr: Dict, gl: List[Dict]) -> Tuple[Optional[object], Optional[str]]:
        vrno = str(hdr["vrno"]); trc = hdr["trc"]; pdate = getdate(str(hdr["vr_date"])[:10])
        cc = self._branch_cc(hdr.get("br")); wh = self._branch_wh(hdr.get("br")); eps = self.cfg.line_epsilon
        items = []; add_tax = []; deduct = []; party_lines = []
        for row in gl:
            c = row["code"]; net = self._net(row)
            if abs(net) < eps:
                continue
            a = self.r.fwd(c)
            if self.r.needs_party(a, c):
                party_lines.append((a, net)); continue
            if self.cfg.is_vat_input(c):
                (add_tax if net > 0 else deduct).append((a, net if net > 0 else -net)); continue
            if net > 0:
                items.append((self.cfg.srbnb_account if self.cfg.is_goods(c) else a, net))
            else:
                deduct.append((a, -net))
        cr_party = [(a, -n) for a, n in party_lines if n < 0]
        dr_party = [1 for a, n in party_lines if n > 0]
        if dr_party or len(cr_party) != 1:
            return None, "party shape -> JE"
        supplier_acc, _ = cr_party[0]
        if not supplier_acc or not items:
            return None, "no supplier/items"
        if any(a is None for a, _ in items + add_tax + deduct):
            return None, "unmapped -> JE"
        pt, supplier = self.r.party_of(supplier_acc, "".join(self.cfg.supplier_prefix[:1]) or "0")
        if not supplier:
            return None, f"no supplier for {supplier_acc}"
        pi = self._new_pi(hdr, supplier, supplier_acc, pdate, vrno, trc)
        for acct, amt in items:
            pi.append("items", {"item_code": self.generic_item(), "item_name": "Migrated",
                                "description": f"Migrated {trc}/{vrno}", "qty": 1, "rate": amt,
                                "uom": "Nos", "expense_account": acct, "cost_center": cc, "warehouse": wh})
        self._append_taxes(pi, add_tax, deduct, cc)
        return pi, None

    # ---- Purchase Invoice with real item lines + reconciliation line ----
    def build_pi_realitems(self, hdr: Dict, gl: List[Dict], items_src: List[Dict],
                           conv_rate: float) -> Tuple[Optional[object], Optional[str]]:
        if not self.item_mapper:
            return None, "no item mapper"
        vrno = str(hdr["vrno"]); trc = hdr["trc"]; pdate = getdate(str(hdr["vr_date"])[:10])
        cc = self._branch_cc(hdr.get("br")); wh = self._branch_wh(hdr.get("br")); eps = self.cfg.line_epsilon
        goods = 0.0; party = []; add_tax = []; deduct = []
        for row in gl:
            c = row["code"]; net = self._net(row)
            if abs(net) < eps:
                continue
            if self.cfg.is_goods(c):
                goods += net; continue
            a = self.r.fwd(c)
            if self.r.needs_party(a, c):
                party.append((a, net)); continue
            (add_tax if net > 0 else deduct).append((a, net if net > 0 else -net))
        cr = [(a, -n) for a, n in party if n < 0]; drp = [1 for a, n in party if n > 0]
        if drp or len(cr) != 1 or goods <= 0 or not items_src:
            return None, "shape -> JE"
        supplier_acc = cr[0][0]
        if supplier_acc is None or any(x is None for x, _ in add_tax + deduct):
            return None, "unmapped -> JE"
        pt, supplier = self.r.party_of(supplier_acc, "".join(self.cfg.supplier_prefix[:1]) or "0")
        if not supplier:
            return None, "no supplier -> JE"
        lines = []; isum = 0.0
        for z in items_src:
            it = self.item_mapper(z["code"])
            if not it:
                return None, f"no item {z['code']} -> JE"
            if flt(z["qty"]) == 0:
                continue
            rate = round(flt(z["rate"]) * conv_rate, 6)
            isum = round(isum + round(flt(z["qty"]) * rate, self.cfg.round_dp), self.cfg.round_dp)
            lines.append((it, flt(z["qty"]), rate))
        if not lines:
            return None, "no items -> JE"
        recon = round(goods - isum, self.cfg.round_dp)
        if recon < -0.50:
            return None, "recon<0 -> JE"
        pi = self._new_pi(hdr, supplier, supplier_acc, pdate, vrno, trc)
        for it, qty, rate in lines:
            pi.append("items", {"item_code": it, "qty": qty, "rate": rate, "uom": "Nos",
                                "expense_account": self.cfg.srbnb_account, "cost_center": cc, "warehouse": wh})
        if abs(recon) > eps:               # landed-cost reconciliation line
            pi.append("items", {"item_code": self.generic_item(), "item_name": "Customs/Freight (landed cost)",
                                "description": f"Landed cost {trc}/{vrno}", "qty": 1, "rate": recon,
                                "uom": "Nos", "expense_account": self.cfg.srbnb_account,
                                "cost_center": cc, "warehouse": wh})
        self._append_taxes(pi, add_tax, deduct, cc)
        return pi, None

    # ---- Sales Invoice (credit + cash/POS; returns via is_return) ----
    def build_si(self, hdr: Dict, gl: List[Dict]) -> Tuple[Optional[object], Optional[str]]:
        vrno = str(hdr["vrno"]); trc = hdr["trc"]; pdate = getdate(str(hdr["vr_date"])[:10])
        cc = self._branch_cc(hdr.get("br")); wh = self._branch_wh(hdr.get("br")); eps = self.cfg.line_epsilon
        is_ret = trc in self.cfg.return_trc
        flip = -1 if is_ret else 1         # returns: work with positive magnitudes, flip on write
        dr_party = []; cash_dr = []; income = []; taxes = []
        for row in gl:
            c = row["code"]
            if self.cfg.is_goods(c):
                continue
            net = self._net(row, flip)
            if abs(net) < eps:
                continue
            a = self.r.fwd(c)
            if not a:
                return None, f"unmapped {c}"
            if net > 0:                    # debit side: customer or cash
                if self.r.atype.get(a) == "Receivable" or self.r.needs_party(a, c):
                    dr_party.append((c, a, net))
                else:
                    cash_dr.append((a, net))
            else:                          # credit side: sales / VAT
                if self.r.atype.get(a) == "Tax" or "VAT" in (a or ""):
                    taxes.append((a, -net))
                else:
                    income.append((a, -net))
        if not income:
            return None, "no income"
        si = frappe.new_doc("Sales Invoice")
        si.company = self.cfg.company; si.posting_date = pdate; si.set_posting_time = 1
        si.currency = self.cfg.default_currency; si.conversion_rate = 1
        si.update_stock = 0; si.disable_rounded_total = 1
        si.epromise_vr_no = vrno; si.epromise_trc_code = trc; si.is_return = 1 if is_ret else 0
        if len(dr_party) == 1:
            pc, pa, _ = dr_party[0]
            _, party = self.r.party_of(pa, pc)
            si.customer = party or self._walkin(); si.debit_to = pa
        elif not dr_party and cash_dr:
            si.customer = self._walkin()
        else:
            return None, f"dr_party={len(dr_party)} -> JE"
        for a, amt in income:
            si.append("items", {"item_code": self.generic_item(), "item_name": "Sale",
                                "description": f"Migrated {trc}/{vrno}", "qty": 1,
                                "rate": (-amt if is_ret else amt), "uom": "Nos",
                                "income_account": a, "cost_center": cc, "warehouse": wh})
        for a, amt in taxes:
            si.append("taxes", {"charge_type": "Actual", "account_head": a, "description": "tax",
                                "tax_amount": (-amt if is_ret else amt), "cost_center": cc})
        if cash_dr:                        # cash sale: pay straight to the cash account (no debtor turnover)
            si.is_pos = 1
            for a, amt in cash_dr:
                si.append("payments", {"mode_of_payment": self._ensure_mop(a), "account": a,
                                       "amount": (-amt if is_ret else amt)})
        return si, None

    def _ensure_mop(self, acct: str) -> str:
        mop = "MIG-" + acct.split(" - ")[0].strip()
        if not frappe.db.exists("Mode of Payment", mop):
            d = frappe.get_doc({"doctype": "Mode of Payment", "mode_of_payment": mop, "type": "Cash",
                                "accounts": [{"company": self.cfg.company, "default_account": acct}]})
            d.flags.ignore_permissions = True; d.insert()
        else:
            mp = frappe.get_doc("Mode of Payment", mop)
            if not any(a.company == self.cfg.company for a in mp.accounts):
                mp.append("accounts", {"company": self.cfg.company, "default_account": acct})
                mp.flags.ignore_permissions = True; mp.save()
        return mop

    def _walkin(self) -> str:
        return self.r._ensure_customer("Walk-In Customer Migration")

    def _new_pi(self, hdr, supplier, supplier_acc, pdate, vrno, trc):
        pi = frappe.new_doc("Purchase Invoice")
        pi.company = self.cfg.company; pi.supplier = supplier; pi.posting_date = pdate
        pi.set_posting_time = 1; pi.currency = self.cfg.default_currency; pi.conversion_rate = 1
        pi.update_stock = 0; pi.credit_to = supplier_acc; pi.disable_rounded_total = 1
        pi.bill_no = vrno; pi.bill_date = pdate
        pi.epromise_vr_no = vrno; pi.epromise_trc_code = trc
        return pi

    def _append_taxes(self, pi, add_tax, deduct, cc):
        for a, amt in add_tax:
            pi.append("taxes", {"charge_type": "Actual", "account_head": a, "description": "tax",
                                "tax_amount": amt, "add_deduct_tax": "Add", "category": "Total", "cost_center": cc})
        for a, amt in deduct:
            pi.append("taxes", {"charge_type": "Actual", "account_head": a, "description": "capitalized",
                                "tax_amount": amt, "add_deduct_tax": "Deduct", "category": "Total", "cost_center": cc})
