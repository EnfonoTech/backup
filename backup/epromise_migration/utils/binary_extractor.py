"""
Extracts dichdata invoice rows from the SQL Server .bak binary pages.

SQL Server stores INSERT data split across binary page boundaries.
The strings command gives partial fragments; this module searches the raw
binary for each bill_no pattern and extracts the surrounding text fragment
which contains all key invoice fields (amount, date, customer, posted_ind).
"""

import re
import subprocess
import struct
import datetime
from collections import defaultdict


# ─── patterns ─────────────────────────────────────────────────────────────────

# Matches bill_no IS601xxxxxx or POS601xxxxxx in the fragment
BILL_RE = re.compile(r"(IS|POS)(601\d{6})")

# Matches timestamp values like {ts '2026-01-18 07:07:16.595'}
TS_RE = re.compile(r"\{ts '(\d{4}-\d{2}-\d{2})[^']*'\}")

# Matches N'...' string values
NSTR_RE = re.compile(r"N'([^']*)'")

# Numeric value (standalone integer or decimal)
NUM_RE = re.compile(r"(?<!['\w])(-?\d+\.\d+)(?!['\w])")
INT_RE = re.compile(r"(?<!['\w\.])(\d{6,})(?!['\w\.])")   # 6+ digit ints (vr_no)


def _extract_fragment_data(fragment):
    """
    Parse a text fragment containing a bill_no and return a dict of
    extracted fields. Best-effort: not all fields may be present.
    """
    row = {}

    # bill_no + vr_no
    m = BILL_RE.search(fragment)
    if not m:
        return None
    prefix, num_str = m.groups()
    row["bill_no"] = prefix + num_str
    row["vr_no"] = num_str
    row["trc_code"] = "S01" if prefix == "IS" else "S06"

    # Dates – first timestamp = vr_date
    dates = TS_RE.findall(fragment)
    if dates:
        row["vr_date"] = dates[0]

    # posted_ind – look for N'Y' or N'N' near the end of the fragment
    # The fragment ends with: ...vr_no, N'Y', N'BHD', ...
    # Find the standalone N'Y' that is posted_ind (after the numeric vr_no)
    after_vr = fragment[m.end():]
    nstrs = NSTR_RE.findall(after_vr)
    # posted_ind is typically the first Y/N after bill_no in the tail
    for val in nstrs:
        if val.strip() in ("Y", "N"):
            row["posted_ind"] = val.strip()
            break

    # acc_name – long N'...' string that isn't a code
    all_nstrs = NSTR_RE.findall(fragment)
    for val in all_nstrs:
        v = val.strip()
        if len(v) > 5 and not re.match(r'^[\d]{5,}$', v) and v not in ("BHD","SAR","USD","AED","LOCAL","Retail","Whole Sale","PERCENT","Bill","Y","N",""):
            # Skip codes (all digits/short alpha codes)
            if not re.match(r'^\d+$', v) and not re.match(r'^[A-Z0-9]{3,6}$', v):
                if "acc_name" not in row or len(v) > len(row["acc_name"]):
                    row["acc_name"] = v

    # acc_code – 12-char code like 130302F0001
    acc_re = re.compile(r"\b(1[0-9]{2}[0-9]{3}[A-Z][0-9]{4})\b")
    acc_m = acc_re.search(fragment)
    if acc_m:
        row["acc_code"] = acc_m.group(1)

    # currency
    for cur in ("BHD", "SAR", "USD", "AED", "KWD", "OMR"):
        if f"N'{cur}'" in fragment:
            row["cur_code"] = cur
            break

    # fy_code
    fy_m = re.search(r"N'(10|20|30|60)'", fragment)
    if fy_m:
        row["fy_code"] = fy_m.group(1)

    # acc_amt – look for numeric values near the bill_no
    # In the VALUES string the order is: ...acc_sign, acc_amt, acc_discount,...
    # acc_amt appears as a standalone decimal like 15.664
    decimals = NUM_RE.findall(fragment)
    if decimals:
        # Filter reasonable invoice amounts (0.01 to 999999)
        amounts = [float(d) for d in decimals if 0.001 < float(d) < 999999]
        if amounts:
            # The first significant amount is usually acc_amt
            row["acc_amt"] = amounts[0]
            # vat_amt is usually towards the end
            if len(amounts) >= 2:
                row["vat_amt"] = amounts[-2] if amounts[-2] != amounts[0] else amounts[-1]

    return row


def extract_binary_invoices(bak_file_path):
    """
    Stream the .bak file through `strings`, collect all text fragments,
    then for every fragment containing a bill_no return a parsed row dict.

    Returns:
        dict: {(trc_code, vr_no): row_dict}
    """
    invoices = {}
    processed_bill_nos = set()

    proc = subprocess.Popen(
        ["strings", "-n", "20", bak_file_path],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        bufsize=2 * 1024 * 1024,
    )

    for raw_line in proc.stdout:
        try:
            fragment = raw_line.decode("utf-8", errors="replace").strip()
        except Exception:
            continue

        if not fragment:
            continue

        # Quick filter
        if "IS601" not in fragment and "POS601" not in fragment:
            continue

        row = _extract_fragment_data(fragment)
        if not row:
            continue

        bill_no = row.get("bill_no", "")
        vr_no = row.get("vr_no", "")
        trc = row.get("trc_code", "")

        if not vr_no:
            continue

        key = (trc, vr_no)

        # Keep the most data-rich version (longest fragment)
        if key not in invoices or len(fragment) > invoices[key].get("_frag_len", 0):
            row["_frag_len"] = len(fragment)
            invoices[key] = row

    proc.stdout.close()
    proc.wait()
    return invoices
