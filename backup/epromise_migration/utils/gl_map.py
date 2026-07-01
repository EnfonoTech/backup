"""
GL Mapping: ePromise account codes → ERPNext full account names.
Source: GL Mapping of E Promise to ERP Next.xlsx

load_gl_map()   → {str(epromise_code): erp_account_name}
resolve_account() → ERPNext account name or None
"""

import os
import frappe

_GL_MAP_CACHE = None
_XLSX_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
    "GL Mapping of E Promise to ERP Next.xlsx",
)


def load_gl_map():
    """
    Load the GL mapping from the Excel file.
    Returns {str(epromise_code): erp_account_name}.
    Only includes rows where the ERPNext account column is non-empty.
    """
    global _GL_MAP_CACHE
    if _GL_MAP_CACHE is not None:
        return _GL_MAP_CACHE

    gl_map = {}
    try:
        import openpyxl
        wb = openpyxl.load_workbook(_XLSX_PATH, data_only=True)
        ws = wb.active
        for i, row in enumerate(ws.iter_rows(values_only=True)):
            if i == 0:
                continue  # header
            ep_code, _ep_name, erp_name = (row + (None, None, None))[:3]
            if not ep_code or not erp_name:
                continue
            gl_map[str(int(ep_code) if isinstance(ep_code, float) else ep_code).strip()] = str(erp_name).strip()
    except Exception as e:
        frappe.log_error(str(e), "gl_map: load failed")

    _GL_MAP_CACHE = gl_map
    return gl_map


def resolve_account(ep_code, gl_map=None, fallback=None):
    """
    Resolve an ePromise account code to an ERPNext account name.
    Returns the mapped name, or fallback if not found.
    """
    if not ep_code:
        return fallback
    m = gl_map if gl_map is not None else load_gl_map()
    return m.get(str(ep_code).strip(), fallback)
