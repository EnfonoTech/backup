# apps/backup/backup/epromise_migration/gl_faithful/__init__.py
"""GL-faithful migration engine.

Rebuild ERPNext documents so their posted GL equals the source ERP's GL line-for-line,
then reconcile source-TB / source-GL / ERPNext. Generalised from the Steel Force Trading
Bahrain ePromise->ERPNext migration.

Quick start (run via `bench --site <site> execute` or a console):

    from backup.epromise_migration.gl_faithful import GLFaithfulConfig, Engine

    cfg = GLFaithfulConfig.for_epromise(
        company="My Company",
        from_date="2026-01-01", to_date="2026-06-30",
        logger=print,
    )
    eng = Engine(cfg)
    print(eng.run(dry_run=True))          # preview the builder chain, no writes
    print(eng.run())                      # build + submit, commit-per-doc
    print(eng.trial_balance_ok())         # {'debit':..,'credit':..,'balanced':True}

    rec = eng.reconciler
    print(rec.monthwise_verify(eng.conn)) # ERPNext vs source GL, per month
"""
from .config import GLFaithfulConfig
from .resolve import AccountResolver
from .builders import DocBuilder
from .reconcile import Reconciler, read_source_tb_xls
from .engine import Engine

__all__ = [
    "GLFaithfulConfig", "AccountResolver", "DocBuilder",
    "Reconciler", "read_source_tb_xls", "Engine",
]
