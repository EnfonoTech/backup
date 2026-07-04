# apps/backup/backup/epromise_migration/gl_faithful/config.py
"""Configuration for the GL-faithful migration engine.

The engine rebuilds ERPNext documents (Sales Invoice / Purchase Invoice / Payment
Entry / Journal Entry) so that the GL each document posts equals the source ERP's
posted GL line-for-line. Everything client-specific (company, account remaps, which
source codes are "goods", party-code prefixes, TRC->doctype routing) lives here so the
engine itself stays generic and reusable across migrations.

Generalised from the Steel Force Trading Bahrain ePromise->ERPNext migration (2026).
"""
from dataclasses import dataclass, field
from typing import Callable, Optional, Tuple, Dict

import frappe


@dataclass
class GLFaithfulConfig:
    company: str
    # period of the migration (source voucher date range)
    from_date: str = "2000-01-01"
    to_date: str = "2100-12-31"
    # --- goods handling: source GL codes whose value lands in a holding account ---
    # (used when stock is NOT migrated: inventory / COGS postings are parked in SRBNB
    #  and cleared later by the stock/GRN phase, so the P&L/BS still reconcile)
    goods_exact: Tuple[str, ...] = ()          # exact source codes treated as goods
    goods_prefix: Tuple[str, ...] = ()         # source-code prefixes treated as goods
    srbnb_account: Optional[str] = None        # holding account; defaults to SRBNB - <abbr>
    # --- account classification (source-code prefixes) ---
    vat_input_prefix: Tuple[str, ...] = ()     # input / recoverable VAT
    customer_prefix: Tuple[str, ...] = ()      # source prefixes that map to a Customer
    supplier_prefix: Tuple[str, ...] = ()      # source prefixes that map to a Supplier
    roundoff_account_number: str = ""          # ERPNext account_number of the round-off account
    # --- amounts: order to read the base-currency amount from a source GL line ---
    amount_fields: Tuple[str, ...] = ("report_amt", "local_cur_amt", "acc_amt")
    # --- TRC (source transaction code) -> target ERPNext doctype tag ---
    #   "SI" | "PI" | "PE" | "JE" | "SKIP"
    trc_map: Dict[str, str] = field(default_factory=dict)
    return_trc: Tuple[str, ...] = ()           # TRCs that are sales returns (is_return)
    # --- misc ---
    default_currency: Optional[str] = None
    round_dp: int = 3
    balance_tolerance: float = 0.10            # max source imbalance absorbed to round-off
    line_epsilon: float = 0.005                # ignore GL lines smaller than this
    logger: Optional[Callable[[str], None]] = None

    def __post_init__(self):
        self.abbr = frappe.db.get_value("Company", self.company, "abbr")
        if not self.abbr:
            frappe.throw(f"Company not found: {self.company}")
        if not self.srbnb_account:
            self.srbnb_account = f"Stock Received But Not Billed - {self.abbr}"
        if not self.default_currency:
            self.default_currency = frappe.db.get_value("Company", self.company, "default_currency")
        self.default_cost_center = frappe.db.get_value("Company", self.company, "cost_center")

    def log(self, msg: str) -> None:
        if self.logger:
            self.logger(msg)

    def is_goods(self, code: str) -> bool:
        code = str(code).strip()
        return code in self.goods_exact or (bool(self.goods_prefix) and code.startswith(self.goods_prefix))

    def is_vat_input(self, code: str) -> bool:
        return bool(self.vat_input_prefix) and str(code).strip().startswith(self.vat_input_prefix)

    @classmethod
    def for_epromise(cls, company: str, **overrides) -> "GLFaithfulConfig":
        """Defaults matching the ePromise source schema (DICADDATA / DICHDATA / DICZDATA)."""
        defaults = dict(
            goods_exact=("51010100001", "51010100003"),   # COGS / trading-purchase legs
            goods_prefix=("13090",),                       # trading inventory
            vat_input_prefix=("1311", "1312"),
            customer_prefix=("1303", "130302", "130304", "130306"),
            supplier_prefix=("2201", "220102", "220104", "220105"),
            roundoff_account_number="52010300018",
            trc_map={
                "S01": "SI", "S06": "SI", "R01": "SI", "R04": "SI",
                "350": "PI", "IP": "PI", "111": "PI",
                "003": "PE", "004": "PE",
                "007": "JE", "020": "JE", "025": "JE", "011": "JE", "BA": "JE",
            },
            return_trc=("R01", "R04"),
        )
        defaults.update(overrides)
        return cls(company=company, **defaults)
