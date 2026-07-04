# GL-Faithful Migration Engine

Rebuild ERPNext documents (Sales Invoice / Purchase Invoice / Payment Entry / Journal
Entry) so that the **GL each document posts equals the source ERP's posted GL, line for
line** — then reconcile source-TB vs source-GL vs ERPNext. Generalised from the Steel
Force Trading Bahrain **ePromise → ERPNext** migration (2026).

Unlike a "doc-build" importer (which reconstructs business documents and lets ERPNext
re-derive the GL), this engine is **GL-first**: it reads each source voucher's ledger
lines and shapes an ERPNext document that reproduces exactly those debits and credits.
Result: the trial balance ties to the source at any date, with **zero plug/adjustment
entries**.

## Modules

| Module | What it does |
|---|---|
| `config.py` | `GLFaithfulConfig` — company, date range, goods codes, party prefixes, TRC→doctype map, round-off account, tolerances. `GLFaithfulConfig.for_epromise()` ships ePromise defaults. |
| `source.py` | Source-ERP (MSSQL/ePromise) access: connection from `ePromise Settings`, `fetch_voucher_gl`, `fetch_item_lines`, `iter_headers`, `load_gl_map`. |
| `resolve.py` | `AccountResolver` — code→account (`account_number` **first**, then `gl_map`, then **name-match**), whitespace-normalising `real_acct`, and `party_of` from existing GL + create-if-missing. |
| `builders.py` | `DocBuilder` — `build_je`, `build_pe`, `build_pi`, `build_pi_realitems`, `build_si`. Each returns `(doc, None)` or `(None, reason)`. |
| `reconcile.py` | `Reconciler` — `threeway`, `monthwise_verify`, `per_voucher_diff`, `gross_drcr`, `dedup_by_trc_vr`; plus `read_source_tb_xls`. |
| `engine.py` | `Engine` — routes each voucher through a fallback chain, submits **commit-per-doc**, supports safe re-import with **guard-before-rebuild**. |

## Usage

```python
from backup.epromise_migration.gl_faithful import GLFaithfulConfig, Engine

cfg = GLFaithfulConfig.for_epromise(
    company="My Company", from_date="2026-01-01", to_date="2026-06-30", logger=print)
eng = Engine(cfg)

eng.run(dry_run=True)                 # preview which builder each voucher uses
eng.run()                             # build + submit
eng.run(trc_codes=["350","IP"])       # only purchase vouchers
eng.run(reimport=True)                # delete existing then rebuild (guarded)
eng.trial_balance_ok()

rec = eng.reconciler
rec.monthwise_verify(eng.conn)        # ERPNext vs source GL per month
rec.threeway(eng.conn, tb_by_account) # source-TB | source-GL | ERPNext
rec.dedup_by_trc_vr("Journal Entry", dry_run=False)
```

## The techniques (why each builder is shaped the way it is)

- **JE** — one ERPNext line per source GL line; goods legs remapped to the holding
  account; a sub-tolerance imbalance (source rounding) is absorbed into the round-off
  account, never a larger plug.
- **PE** — payment direction is inferred from the **sign of the party leg** (credit to a
  party ⇒ money received). Only clean 2-leg party↔cash vouchers become a PE; anything
  else falls back to a JE.
- **PI** — landing costs (freight/customs) post as **"Deduct" Actual taxes** so they
  capitalise into item value; input VAT as **"Add"**; the supplier credit auto-balances.
- **PI (real items)** — rebuilds the real item lines from the source item table plus a
  single **reconciliation line** = `goods_total − Σ(item lines)`. Taxes are appended
  **inline before the one `insert`** (a post-insert `save` wipes Actual taxes).
- **SI** — cash sales use `is_pos` payments straight to the cash account (no spurious
  debtor turnover); returns use `is_return` with negative quantities.
- **Everywhere** — cost center and warehouse are set on every item line and every GL leg
  (branch-resolved from the source branch code), and `update_stock=0` (stock is migrated
  in a separate phase; goods sit in the holding account meanwhile).

## Hard-won lessons (baked into the code)

1. **Dedup on `(TRC, VR)` together, never VR alone** — source ERPs reuse VR numbers
   across transaction codes; VR-only dedup collapses distinct vouchers and drops money.
2. **`account_number` before `gl_map`** in resolution — a freshly created account by
   number then overrides a stale gl_map fallback.
3. **Bank/COA accounts get renumbered** per the client chart — never query the source by
   the ERPNext account number; always forward-map (`fwd`).
4. **Guard before rebuild** — on re-import, only build the replacement **after** the
   existing docs are confirmed deleted, and skip if a target already exists. A caught
   delete-exception followed by a build double-posts (SI **and** JE both live).
5. **Commit per document**, not per batch — one bad doc must not roll back 100 good ones.
6. **Goods remap by source CODE**, not by resolved account, so inventory/COGS never leak
   into adjustments.
7. **Name-match fallback** for parties coded at group level in the source TB — they tie
   to full ERPNext party ledgers by name even when the code doesn't map.
8. **A source "Trial Balance" report may not equal the source GL** — reconcile ERPNext to
   the transaction **ledger** (`DICADDATA`), not the TB export, which can carry
   forex-revaluation / settlement-view figures the posted ledger does not.
9. **Net-tie ≠ gross-tie** — an account can net-match while its Dr/Cr turnover differs
   (e.g. cash sales routed through a debtor). Check `gross_drcr` when turnover matters.
10. **Post-insert `save` wipes Actual taxes** — for docs needing a reconciliation line,
    append taxes inline and insert once.
11. **Round-off cost center** must be set on the company (or a per-line fallback) or
    P&L round-off lines throw "Cost Center required".
12. **A source TB export is a point-in-time report** — reconcile against a source GL
    pulled at the *same* moment, or per-account differences will look like migration gaps
    when they are just report timing.

## Scope / not included

- Opening balances (pre-period brought-forward) — load as a dated opening JE separately.
- Stock / GRN flow — migrate item receipts/issues to clear the holding account and put
  COGS on the P&L; until then goods sit in the holding account (net-zero to real ledgers).
- Master data (customers, suppliers, items) — handled by the existing importer suite.
