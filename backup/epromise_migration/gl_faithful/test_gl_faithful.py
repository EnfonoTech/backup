# apps/backup/backup/epromise_migration/gl_faithful/test_gl_faithful.py
"""Unit tests for the GL-faithful engine's pure logic (classification + amount/sign math).

Full build/reconcile paths are integration-level (need a source MSSQL + a fully set-up
company), so those run against a live migration bench, not CI. These cover the
deterministic helpers and skip cleanly when the test site has no Company.
"""
import frappe
from frappe.tests.utils import FrappeTestCase

from backup.epromise_migration.gl_faithful import GLFaithfulConfig, DocBuilder, read_source_tb_xls


class TestGLFaithful(FrappeTestCase):
    def _cfg(self):
        company = frappe.db.get_value("Company", {}, "name")
        if not company:
            self.skipTest("no Company in test site")
        return GLFaithfulConfig.for_epromise(
            company=company, from_date="2026-01-01", to_date="2026-06-30")

    def test_goods_classification(self):
        cfg = self._cfg()
        self.assertTrue(cfg.is_goods("13090100001"))   # inventory prefix
        self.assertTrue(cfg.is_goods("51010100001"))   # COGS exact
        self.assertFalse(cfg.is_goods("41010100001"))  # sales revenue

    def test_vat_input_classification(self):
        cfg = self._cfg()
        self.assertTrue(cfg.is_vat_input("13110000001"))   # prefix 1311
        self.assertFalse(cfg.is_vat_input("23010700002"))  # output VAT

    def test_amount_fallback_and_sign(self):
        cfg = self._cfg()
        b = DocBuilder(cfg, resolver=None)
        self.assertEqual(b._amt({"report_amt": 5, "local_cur_amt": 9}), 5.0)
        self.assertEqual(b._amt({"report_amt": None, "local_cur_amt": 9}), 9.0)
        self.assertEqual(b._amt({"report_amt": "", "local_cur_amt": "", "acc_amt": 3}), 3.0)
        self.assertEqual(b._net({"report_amt": 5, "sign": 1}), 5.0)     # Dr -> positive
        self.assertEqual(b._net({"report_amt": 5, "sign": 2}), -5.0)    # Cr -> negative
        self.assertEqual(b._net({"report_amt": 5, "sign": 1}, flip=-1), -5.0)  # return flip

    def test_tb_reader_callable(self):
        self.assertTrue(callable(read_source_tb_xls))
