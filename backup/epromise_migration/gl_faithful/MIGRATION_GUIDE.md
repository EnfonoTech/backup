# GL-Faithful Migration — Guide & Changelog

End-to-end playbook for the `backup.epromise_migration.gl_faithful` engine: what was
added, when to use it, how to run a full migration, how to configure it for a new client,
and how to reconcile the result. Companion to the module `README.md` (which is the API
reference); this file is the operational guide.

Origin: generalised from the Steel Force Trading Bahrain **ePromise → ERPNext** migration
(2026). Committed to `EnfonoTech/backup` → `develop` (`e4efd46`).

---

## 1. What changed

Added a new, self-contained submodule **`backup/epromise_migration/gl_faithful/`** — a
reusable, client-agnostic engine that rebuilds ERPNext documents so their posted GL
equals the source ERP's GL line-for-line, plus a reconciliation toolkit.

| File | Role |
|---|---|
| `config.py` | `GLFaithfulConfig` (+ `.for_epromise()` factory) — all client-specific knobs |
| `source.py` | Source-ERP (ePromise/MSSQL) access via `ePromise Settings` |
| `resolve.py` | `AccountResolver` — code→account + party resolution |
| `builders.py` | `DocBuilder` — `build_je / build_pe / build_pi / build_pi_realitems / build_si` |
| `reconcile.py` | `Reconciler` — three-way TB, month-wise, per-voucher, gross Dr/Cr, dedup; `read_source_tb_xls` |
| `engine.py` | `Engine` — orchestrator (fallback chain, commit-per-doc, guard-before-rebuild) |
| `README.md` | API reference + 12 hard-won lessons |
| `test_gl_faithful.py` | Unit tests (classification + amount/sign math) |

It **complements** the existing `utils/*_importer.py` doc-build suite — it does not
replace it. Masters (customers, suppliers, items) still come from the importer suite; this
engine handles the transactional GL.

No schema change: it reuses the `epromise_trc_code` / `epromise_vr_no` custom fields
already present on Sales Invoice / Purchase Invoice / Payment Entry / Journal Entry.

---

## 2. GL-faithful vs doc-build — when to use which

| | Doc-build importer (`utils/*_importer.py`) | GL-faithful engine (`gl_faithful/`) |
|---|---|---|
| Approach | Rebuild the business document; let ERPNext derive the GL | Read the source GL; shape a document that reproduces it |
| Ties to source TB | Approximately (derivation differences) | Exactly, at any date, **zero plug entries** |
| Best for | Clean source, forward operations | Audit-grade handover, "make ERPNext = old system" |
| Stock | Posts stock | `update_stock=0`; goods parked in a holding account, migrated later |

Use GL-faithful when the client (or auditor) requires the ERPNext trial balance to match
the legacy system's trial balance transaction-by-transaction.

---

## 3. End-to-end workflow

Run everything via `bench --site <site> execute` or a `bench console`.

**Step 0 — prerequisites**
- `ePromise Settings` filled in (MSSQL host/port/user/password/database).
- `gl_map` populated (accountant's source-code → ERPNext-account map).
- ERPNext COA created; masters (customers/suppliers/items) imported.
- Custom fields `epromise_trc_code`, `epromise_vr_no` exist on SI/PI/PE/JE (they do).
- `Company.cost_center` and `Company.round_off_cost_center` set.

**Step 1 — configure** (see §4)
```python
from backup.epromise_migration.gl_faithful import GLFaithfulConfig, Engine
cfg = GLFaithfulConfig.for_epromise(
    company="My Company", from_date="2026-01-01", to_date="2026-06-30", logger=print)
eng = Engine(cfg)
```

**Step 2 — dry run** (no writes; shows which builder each voucher routes to)
```python
print(eng.run(dry_run=True))
# {'total': N, 'built': {'JE': .., 'PI(items)': .., 'PI': .., 'PE': .., 'SI': ..}, 'skipped': .., 'failed': ..}
```
Investigate any `failed` before the real run (the `logger` prints the reason per voucher).

**Step 3 — run** (build + submit, commit-per-doc)
```python
print(eng.run())                       # everything in trc_map
print(eng.run(trc_codes=["350","IP"])) # or one class at a time
```

**Step 4 — verify the trial balance**
```python
print(eng.trial_balance_ok())          # {'debit':X,'credit':X,'balanced':True}
```

**Step 5 — reconcile** (see §5)
```python
rec = eng.reconciler
for m in rec.monthwise_verify(eng.conn): print(m)
```

**Step 6 — fix residuals**
```python
eng.run(trc_codes=["007"], reimport=True)         # rebuild a class (guarded delete)
rec.dedup_by_trc_vr("Journal Entry", dry_run=False)  # remove accidental duplicates
```

**Step 7 — later phases (out of scope of this engine)**
- Opening balances: post a dated opening JE for pre-period brought-forward balances.
- Stock / GRN flow: migrate receipts/issues to clear the holding account and put COGS on the P&L.
- Sales/PI real-item rebuild if item-level detail is required for the JE-converted vouchers.

---

## 4. Configuring for a new client

`GLFaithfulConfig.for_epromise()` ships sensible ePromise defaults; override per client.
How to derive each field from the source:

| Field | How to determine |
|---|---|
| `company`, `from_date`, `to_date` | The ERPNext company + the migration period |
| `goods_exact`, `goods_prefix` | Source COGS + inventory account codes. If stock is NOT migrated, these are remapped to `srbnb_account`. |
| `srbnb_account` | Holding account (defaults to `Stock Received But Not Billed - <abbr>`) |
| `vat_input_prefix` | Source input/recoverable VAT code prefixes |
| `customer_prefix`, `supplier_prefix` | Source party group-code prefixes (receivable/payable) |
| `roundoff_account_number` | ERPNext account_number of the round-off account |
| `trc_map` | Source transaction code → `"SI"|"PI"|"PE"|"JE"|"SKIP"` |
| `return_trc` | Which TRCs are sales returns (built as `is_return`) |

Example (overriding a couple of defaults):
```python
cfg = GLFaithfulConfig.for_epromise(
    company="Acme WLL",
    from_date="2025-01-01", to_date="2025-12-31",
    goods_prefix=("1309", "1310"),
    roundoff_account_number="52990001",
    trc_map={"SAL": "SI", "PUR": "PI", "RCP": "PE", "PAY": "PE", "JV": "JE"},
    return_trc=("SRT",),
    logger=print,
)
```

To point at a non-ePromise source, build `GLFaithfulConfig(...)` directly (all fields) and
supply your own `source.py`-equivalent readers to `Engine`.

---

## 5. Reconciliation cookbook

All comparisons are keyed by ERPNext account (source codes forward-mapped, goods → holding).

**Month-wise (ERPNext vs source GL) — proves migration faithfulness**
```python
for m in rec.monthwise_verify(eng.conn):
    print(m)   # {'month':6,'matched':245,'off':5,'residual':18.62}
```
`off` accounts differ only by sub-currency rounding; residual should be tiny.

**Three-way (source TB export vs source GL vs ERPNext)** — when the client hands you a TB
```python
from backup.epromise_migration.gl_faithful import read_source_tb_xls
tb_rows = read_source_tb_xls("/path/SF TB 30-06-2026.xls")
tb_by_acct = {}
for r in tb_rows:
    a = rec._acct(r["code"], r["name"])
    if a: tb_by_acct[a] = tb_by_acct.get(a, 0) + r["net"]
for row in rec.threeway(eng.conn, tb_by_acct):
    if not row["matched"] or abs(row["tb_gl"]) > 1:
        print(row)   # account, tb, gl, erp, gl_erp, tb_gl
```
Lesson: a source **TB report** can differ from the source **GL** (forex revaluation /
settlement view). Reconcile ERPNext to the GL; the TB is the client's report layer.

**Per-voucher drill (one account)**
```python
for d in rec.per_voucher_diff(eng.conn, "13020100024"):
    print(d)   # {'trc','vr','source','erpnext','diff'}
```

**Gross Dr/Cr turnover (net ties but columns differ)**
```python
for d in rec.gross_drcr(eng.conn):
    print(d)   # {'account','dr_diff','cr_diff'}
```

**Dedup (remove duplicate docs sharing a source TRC+VR)**
```python
print(rec.dedup_by_trc_vr("Journal Entry", dry_run=True))   # preview
print(rec.dedup_by_trc_vr("Journal Entry", dry_run=False))  # apply
```

---

## 6. Troubleshooting — symptom → cause → fix

| Symptom | Cause | Fix |
|---|---|---|
| Money missing after re-import | Dedup keyed on VR only | Dedup on `(TRC, VR)` — source reuses VR across codes (built-in) |
| Account "could not be found" | gl_map fallback stale | `resolve()` checks account_number first — create the account by number |
| Bank balances way off | Queried source by the ERPNext number | Banks get renumbered per COA — always `fwd()` (built-in) |
| A voucher posts twice (SI **and** JE) | Rebuilt after a failed delete | `Engine` guards: build only if delete succeeded + no existing doc |
| One bad doc rolled back a whole batch | Batch commit | `Engine` commits per document |
| COGS leaked into an adjustment | Remapped by resolved account | Goods remapped by source **code**, before resolution |
| A party shows on the TB but won't map | Coded at group level in the TB | Name-match fallback in `fwd(code, name)` |
| P&L round-off "Cost Center required" | No round-off CC | Set `Company.round_off_cost_center` |
| PI landing costs not capitalising | Posted as items, not taxes | Landing → "Deduct" Actual taxes (built-in) |
| Real-item PI loses its taxes | Post-insert `save` wiped Actual taxes | Taxes appended inline before the single insert (built-in) |
| Net ties but Dr/Cr columns differ | Cash sale routed through a debtor | Use `build_si` POS payment to the cash account; check `gross_drcr` |
| ERPNext ≠ client TB but = source GL | TB report ≠ posted ledger | Reconcile to the GL; treat TB divergence as a client report-layer question |

---

## 7. Scope boundaries (not handled by this engine)

- **Opening balances** (pre-period brought-forward) — load as a separate dated opening JE.
- **Stock / GRN flow** — migrate receipts/issues to clear the holding account + post COGS.
- **Master data** — customers/suppliers/items come from the existing importer suite.

---

## 8. Deploy & push notes

- The engine runs on the migration bench via `bench execute` / `bench console`.
- **Pushing to GitHub must be done from a machine that has credentials** — the migration
  box has none (no SSH key, no credential helper). Push from a workstation with `gh`
  authenticated:
  ```bash
  gh auth setup-git
  gh repo clone EnfonoTech/backup /tmp/backup -- --branch develop --depth 3
  cd /tmp/backup && git am /path/to/change.patch && git push origin develop
  ```
  (A patch of a box-local commit: `git format-patch -1 HEAD --stdout` on the box.)
- To generate a fresh docs site from the app: `bash scripts/docs-generate.sh <app-path>`.
