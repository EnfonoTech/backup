"""
Unified item code map — ePromise ite_code → ERPNext unified_code.

The Excel file "trading inv (2).xlsx" contains the authoritative item master with:
  ite_code     — ePromise internal numeric item key
  unified_code — the code that should be used as item_code in ERPNext
                 (same as ite_code for most items; differs for ~170 barcode/EAN items)
  ite_name     — item description
  ite_unit     — unit of measure

Usage:
    from backup.epromise_migration.utils.unified_code_map import load_unified_map
    unified_map = load_unified_map()                 # {str(ite_code): row_dict}
    row = unified_map.get("110101060024")
    erp_code = row["unified_code"]                   # may differ from ite_code
"""

import os

# Path relative to this file: ../../.. goes from utils/ → epromise_migration/ → backup/ → apps/backup/
_DEFAULT_XLSX = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "trading inv (2).xlsx")
)

_cache = {}   # keyed by resolved path so repeated calls are free


def load_unified_map(xlsx_path=None):
    """
    Load and cache the unified item code map.

    Returns dict  {str(ite_code): {"unified_code": str, "ite_name": str, "ite_unit": str}}

    Falls back to an empty dict (with a logged error) if the file is not found,
    so callers continue to work — they will just use ite_code as-is.
    """
    global _cache
    path = os.path.normpath(xlsx_path or _DEFAULT_XLSX)

    if path in _cache:
        return _cache[path]

    if not os.path.exists(path):
        # Log once; don't crash
        try:
            import frappe
            frappe.log_error(
                f"Unified code map Excel not found at: {path}\n"
                f"item_code will fall back to ite_code for all items.",
                "Unified Code Map",
            )
        except Exception:
            print(f"[unified_code_map] WARNING: file not found — {path}")
        _cache[path] = {}
        return {}

    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    wb.close()

    headers = [str(h).strip() if h is not None else "" for h in rows[0]]
    result = {}

    for row in rows[1:]:
        r = dict(zip(headers, row))
        ite_code_raw    = r.get("ite_code")
        unified_raw     = r.get("unified_code")
        if ite_code_raw is None:
            continue

        try:
            ite_key  = str(int(ite_code_raw))
            uni_code = str(int(unified_raw)) if unified_raw is not None else ite_key
        except (TypeError, ValueError):
            ite_key  = str(ite_code_raw).strip()
            uni_code = str(unified_raw).strip() if unified_raw is not None else ite_key

        result[ite_key] = {
            "unified_code": uni_code,
            "ite_name":     (r.get("ite_name") or "").strip(),
            "ite_unit":     (r.get("ite_unit") or "NOS").strip(),
        }

    _cache[path] = result
    n_differ = sum(1 for k, v in result.items() if v["unified_code"] != k)
    print(f"[unified_code_map] Loaded {len(result):,} items — {n_differ:,} have different unified_code")
    return result


def get_erp_item_code(ite_code, unified_map):
    """
    Convenience: return the ERPNext item_code (unified_code) for a given ite_code.
    Falls back to str(ite_code) if not found in the map.
    """
    if not ite_code:
        return ""
    row = unified_map.get(str(ite_code))
    return row["unified_code"] if row else str(ite_code)
