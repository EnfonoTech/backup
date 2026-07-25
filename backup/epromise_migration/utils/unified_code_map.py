"""
Unified item code map — ePromise Resource Code → ERPNext Unified Code.

Source file: "Copy of Bahrain Master 16.6.26 (1) (1).xls"
  Resource Code  — ePromise internal numeric item key
  Unified Code   — the code used as item_code in ERPNext
                   (same as Resource Code for most items; differs where items are consolidated)
  ERP NEXT Item Name — cleaned item name for production
  Unit           — unit of measure

Usage:
    from backup.epromise_migration.utils.unified_code_map import load_unified_map
    unified_map = load_unified_map()                 # {str(resource_code): row_dict}
    row = unified_map.get("110101060024")
    erp_code = row["unified_code"]                   # may differ from resource_code
"""

import os

# Authoritative master file — relative to this file:
# utils/ → epromise_migration/ → backup/ → apps/backup/
_DEFAULT_XLS = os.path.normpath(
    os.path.join(
        os.path.dirname(__file__),
        "..", "..", "..",
        "BH Enable items.xlsx",
    )
)

_cache = {}   # keyed by resolved path so repeated calls are free


def _load_xls(path):
    """Load rows from a .xls file using xlrd. Returns (headers, data_rows)."""
    import xlrd
    wb  = xlrd.open_workbook(path)
    ws  = wb.sheet_by_index(0)
    headers = [str(ws.cell_value(0, c)).strip() for c in range(ws.ncols)]
    rows = []
    for r in range(1, ws.nrows):
        rows.append([ws.cell_value(r, c) for c in range(ws.ncols)])
    return headers, rows


def _load_xlsx(path):
    """Load rows from a .xlsx file using openpyxl. Returns (headers, data_rows)."""
    import openpyxl
    wb  = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws  = wb.active
    all_rows = list(ws.iter_rows(values_only=True))
    wb.close()
    headers  = [str(h).strip() if h is not None else "" for h in all_rows[0]]
    return headers, [list(r) for r in all_rows[1:]]


def _to_str_code(raw):
    """Convert a numeric or string cell value to a clean integer string."""
    if raw is None:
        return None
    try:
        return str(int(float(raw)))
    except (TypeError, ValueError):
        s = str(raw).strip()
        return s if s else None


def load_unified_map(xlsx_path=None):
    """
    Load and cache the unified item code map.

    Returns dict  {str(resource_code): {"unified_code": str, "ite_name": str, "ite_unit": str}}

    Falls back to an empty dict (with a logged error) if the file is not found,
    so callers continue to work — they will just use resource_code as-is.
    """
    global _cache
    path = os.path.normpath(xlsx_path or _DEFAULT_XLS)

    if path in _cache:
        return _cache[path]

    if not os.path.exists(path):
        try:
            import frappe
            frappe.log_error(
                f"Unified code map file not found at: {path}\n"
                f"item_code will fall back to resource_code for all items.",
                "Unified Code Map",
            )
        except Exception:
            print(f"[unified_code_map] WARNING: file not found — {path}")
        _cache[path] = {}
        return {}

    ext = os.path.splitext(path)[1].lower()
    try:
        if ext == ".xls":
            headers, data_rows = _load_xls(path)
        else:
            headers, data_rows = _load_xlsx(path)
    except Exception as e:
        print(f"[unified_code_map] ERROR loading {path}: {e}")
        _cache[path] = {}
        return {}

    # Column name aliases — handles both old (trading inv) and new (Bahrain Master) formats
    _aliases = {
        # new Bahrain Master names → canonical key
        "Resource Code":       "resource_code",
        "old E promise Resource Code": "resource_code",
        "Unified Code":        "unified_code",
        "Unifide Code":        "unified_code",
        "ERP NEXT Item Name":  "ite_name",
        "Item Name":           "ite_name",
        "Item Group":          "item_group",
        "Currenrt Item Name ": "ite_name_alt",  # typo in source file
        "Resource Name":       "resource_name",
        "Unit":                "ite_unit",
        # legacy trading inv names
        "ite_code":            "resource_code",
        "unified_code":        "unified_code",
        "ite_name":            "ite_name",
        "ite_unit":            "ite_unit",
    }
    col_map = {}  # index → canonical name
    for i, h in enumerate(headers):
        canon = _aliases.get(h.strip())
        if canon:
            col_map[i] = canon

    result = {}
    for row in data_rows:
        r = {canon: row[i] for i, canon in col_map.items() if i < len(row)}

        resource_raw = r.get("resource_code")
        unified_raw  = r.get("unified_code")
        if resource_raw is None:
            continue

        res_key  = _to_str_code(resource_raw)
        uni_code = _to_str_code(unified_raw) if unified_raw is not None else res_key
        if not res_key:
            continue

        # Prefer "ERP NEXT Item Name" over "Resource Name" for cleaner names
        ite_name = (
            (r.get("ite_name") or r.get("ite_name_alt") or r.get("resource_name") or res_key)
        )
        if isinstance(ite_name, str):
            ite_name = ite_name.strip().replace("\n", " ").replace("\xa0", " ")
        else:
            ite_name = str(ite_name).strip()

        ite_unit = str(r.get("ite_unit") or "NOS").strip().upper()

        result[res_key] = {
            "unified_code": uni_code,
            "ite_name":     ite_name,
            "ite_unit":     ite_unit,
            "item_group":   (str(r.get("item_group")).strip() if r.get("item_group") else None),
        }

    _cache[path] = result
    n_differ = sum(1 for k, v in result.items() if v["unified_code"] != k)
    print(f"[unified_code_map] Loaded {len(result):,} items — {n_differ:,} have different unified_code")
    return result


def get_erp_item_code(ite_code, unified_map):
    """
    Return the ERPNext item_code (unified_code) for a given resource_code.
    Falls back to str(ite_code) if not found in the map.
    """
    if not ite_code:
        return ""
    row = unified_map.get(str(ite_code))
    return row["unified_code"] if row else str(ite_code)
