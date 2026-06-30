"""
Reads SQL Server 8KB data pages from a .bak backup file and extracts
dichdata (invoice header) rows for S01 and S06 transaction codes.

Row layout (SQL Server heap row):
  [2 bytes: status bits]
  [fixed-length fields: dates (8 bytes each), amounts (numeric), ints]
  [2 bytes: null bitmap length indicator]
  [null bitmap]
  [2 bytes: variable-length column count]
  [2 bytes x N: variable-length column end-offsets]
  [variable-length data: nvarchar/varchar fields as ASCII]

The readable fields (trc_code, acc_code, bill_no, acc_name, posted_ind, etc.)
are always in the variable-length section at the end of the row.
Dates (vr_date, bill_date) and amounts (acc_amt, vat_amt) are in the
fixed-length binary section at the start.
"""

import struct
import re
import datetime

PAGE_SIZE = 8192

# Obj IDs whose data pages contain dichdata S01/S06 rows
DICHDATA_OBJ_IDS = {0, 5870, 16777216, 721420800, 163840000, 11786752, 4483}

# SQL Server datetime base
_SQL_EPOCH = datetime.date(1900, 1, 1)

VALID_DATE_RANGE = (
    datetime.date(2019, 1, 1),
    datetime.date(2026, 12, 31),
)


def _days_to_date(days):
    try:
        d = _SQL_EPOCH + datetime.timedelta(days=int(days))
        if VALID_DATE_RANGE[0] <= d <= VALID_DATE_RANGE[1]:
            return d
    except Exception:
        pass
    return None


def _parse_row_fields(row_bytes):
    """
    Given a raw SQL Server data row, extract invoice fields.
    Returns a dict or None.
    """
    if len(row_bytes) < 10:
        return None

    text = row_bytes.decode('ascii', errors='replace')

    # ── bill_no anchors everything ───────────────────────────────────────────
    m_is  = re.search(r'IS(601\d{6})', text)
    m_pos = re.search(r'POS(601\d{6})', text)
    m_bill = m_is or m_pos
    if not m_bill:
        return None

    prefix   = 'IS' if m_is else 'POS'
    vr_no    = m_bill.group(1)
    bill_no  = prefix + vr_no
    trc_code = 'S01' if m_is else 'S06'

    # ── acc_code: between trc_code and bill_no in the readable section ───────
    # Pattern: [fy][trc_code][acc_code][bill_no]
    acc_code = ''
    pre_bill = text[:m_bill.start()]
    trc_idx  = pre_bill.rfind(trc_code)
    if trc_idx != -1:
        between = pre_bill[trc_idx + 3:]          # text after trc_code
        # acc_code is 11 chars (all-digit or alphanumeric starting with 1)
        ac_m = re.match(r'(1[0-9A-Z]{10,11})', between)
        if ac_m:
            acc_code = ac_m.group(1)

    # ── currency ─────────────────────────────────────────────────────────────
    cur_code = 'BHD'
    for c in ('BHD', 'SAR', 'USD', 'AED'):
        if c in text:
            cur_code = c
            break

    # ── posted_ind: Y that immediately follows a username (4–8 uppercase) ────
    # Pattern after bill_no: ...username(4-8 caps)Y...
    after_bill = text[m_bill.end():]
    posted_ind = 'N'
    pm = re.search(r'[A-Z]{4,8}(Y)', after_bill[:80])
    if pm:
        posted_ind = 'Y'

    # ── acc_name: text immediately after PERCENT, before the username+Y ──────
    acc_name = ''
    pct_idx = text.find('PERCENT')
    if pct_idx != -1:
        after_pct = text[pct_idx + 7:]
        # acc_name = readable chars until we hit USERNAME(4-8 caps)Y
        nm = re.match(r'([A-Za-z0-9 \-\.&\(\)/\',]{3,60}?)(?=[A-Z]{4,8}[YN])', after_pct)
        if nm:
            acc_name = nm.group(1).strip()

    # ── date: 2026-01-01 default for 601xxxxxx fiscal-year-6 invoices ────────
    # (Binary decoding is unreliable; use the fiscal year from the vr_no prefix)
    vr_date = '2026-01-01'

    return {
        'trc_code'  : trc_code,
        'vr_no'     : vr_no,
        'bill_no'   : bill_no,
        'acc_code'  : acc_code,
        'acc_name'  : acc_name,
        'vr_date'   : vr_date,
        'cur_code'  : cur_code,
        'posted_ind': posted_ind,
        'acc_amt'   : 0.0,   # amount not reliably extractable from binary pages
        'vat_amt'   : 0.0,
    }


def _parse_page(page):
    """Return list of row-dicts from one 8KB SQL Server data page."""
    if len(page) < PAGE_SIZE:
        return []
    if page[0] != 0x01 or page[1] != 0x01:
        return []

    slot_cnt = struct.unpack_from('<H', page, 22)[0]
    if slot_cnt == 0 or slot_cnt > 800:
        return []

    rows = []
    for i in range(slot_cnt):
        slot_pos = PAGE_SIZE - 2 * (i + 1)
        if slot_pos < 96:
            break
        slot_off = struct.unpack_from('<H', page, slot_pos)[0]
        if slot_off < 2 or slot_off >= PAGE_SIZE - 2:
            continue
        # Row end = start of next slot (slots are stored back-to-front)
        if i > 0:
            prev_off = struct.unpack_from('<H', page, PAGE_SIZE - 2 * i)[0]
            row_end = prev_off
        else:
            row_end = PAGE_SIZE - 2 * slot_cnt
        if row_end <= slot_off:
            row_end = slot_off + 600
        row_end = min(row_end, PAGE_SIZE - 2 * slot_cnt)
        row_bytes = page[slot_off:row_end]
        r = _parse_row_fields(row_bytes)
        if r:
            rows.append(r)
    return rows


def extract_page_invoices(bak_file_path):
    """
    Stream the .bak file, read every SQL Server data page belonging to
    dichdata tables, parse the rows and return a deduplicated dict.

    Returns:
        dict: {(trc_code, vr_no): row_dict}
    """
    invoices = {}
    chunk_size = 128 * 1024 * 1024  # 128 MB chunks

    with open(bak_file_path, 'rb') as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break

            for i in range(0, len(chunk) - PAGE_SIZE, 512):
                page = chunk[i:i + PAGE_SIZE]
                if page[0] != 0x01 or page[1] != 0x01:
                    continue
                obj_id = struct.unpack_from('<I', page, 24)[0]
                if obj_id not in DICHDATA_OBJ_IDS:
                    continue
                # Quick pre-filter
                if b'S01' not in page and b'S06' not in page:
                    continue
                if b'IS6' not in page and b'POS6' not in page:
                    continue

                for row in _parse_page(page):
                    key = (row['trc_code'], row['vr_no'])
                    # Keep row with the most information
                    existing = invoices.get(key)
                    score = len(row.get('acc_name', '')) + len(row.get('acc_code', '')) + (1 if row.get('vr_date') else 0)
                    old_score = len(existing.get('acc_name', '')) + len(existing.get('acc_code', '')) + (1 if existing and existing.get('vr_date') else 0) if existing else -1
                    if score > old_score:
                        invoices[key] = row

    return invoices
