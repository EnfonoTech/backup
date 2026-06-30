"""
ePromise Live SQL Server Connection — Example Script
=====================================================

Run this script BEFORE using the migration page to verify your SQL Server
credentials and see what data will be imported.

Usage:
    /home/gym/new-bench/env/bin/python epromise_live_connection_example.py

Fill in your SQL Server connection details below.
"""

import pymssql
from decimal import Decimal

# ─── FILL IN YOUR DETAILS HERE ────────────────────────────────────────────────
HOST     = "192.168.1.100"      # IP or hostname of the SQL Server machine
PORT     = 1433                  # default SQL Server port
DATABASE = "SteelForce_Bahrain"  # ePromise database name
USER     = "sa"                  # SQL Server login (usually 'sa' or 'epromise')
PASSWORD = "YourPassword123"     # SQL Server password
# ──────────────────────────────────────────────────────────────────────────────


def run():
    print(f"\nConnecting to {HOST}:{PORT} → {DATABASE} as {USER}...")

    try:
        conn = pymssql.connect(
            server=HOST, port=PORT, database=DATABASE,
            user=USER, password=PASSWORD,
            as_dict=True, login_timeout=15,
        )
        print("✅  Connected successfully!\n")
    except Exception as e:
        print(f"❌  Connection failed: {e}")
        return

    cur = conn.cursor()

    # ── 1. Invoice header counts ───────────────────────────────────────────────
    print("=" * 60)
    print("INVOICE SUMMARY (dichdata)")
    print("=" * 60)
    cur.execute("""
        SELECT
            trc_code,
            posted_ind,
            COUNT(*)           AS total,
            MIN(vr_date)       AS earliest,
            MAX(vr_date)       AS latest,
            SUM(acc_amt)       AS total_amount,
            SUM(vat_amt)       AS total_vat
        FROM dichdata
        WHERE trc_code IN ('S01', 'S06')
        GROUP BY trc_code, posted_ind
        ORDER BY trc_code, posted_ind
    """)
    for row in cur:
        label = "Credit Invoice" if row["trc_code"] == "S01" else "POS Invoice"
        status = "Submitted" if row["posted_ind"] == "Y" else "Draft"
        print(
            f"  {label} ({row['trc_code']}) | {status} | "
            f"Count={row['total']} | "
            f"Date: {str(row['earliest'])[:10]} → {str(row['latest'])[:10]} | "
            f"Total={row['total_amount']:.3f} | VAT={row['total_vat']:.3f}"
        )

    # ── 2. Sample S01 invoice with INVOICE_DETAIL items ───────────────────────
    print("\n" + "=" * 60)
    print("SAMPLE S01 INVOICE WITH INVOICE_DETAIL ITEMS")
    print("=" * 60)
    cur.execute("""
        SELECT TOP 1 *
        FROM dichdata
        WHERE trc_code = 'S01' AND posted_ind = 'Y'
        ORDER BY vr_no DESC
    """)
    hdr = cur.fetchone()
    if hdr:
        print(f"  Invoice : {hdr['bill_no']}  (vr_no={hdr['vr_no']})")
        print(f"  Customer: {hdr['acc_name']}  ({hdr['acc_code']})")
        print(f"  Date    : {str(hdr['vr_date'])[:10]}")
        print(f"  Amount  : {hdr['acc_amt']:.3f} {hdr['cur_code']}  "
              f"(VAT={hdr['vat_amt']:.3f})")
        print(f"  Posted  : {hdr['posted_ind']}")

        # Fetch items from INVOICE_DETAIL
        cur.execute("""
            SELECT id.*, im.ite_name, im.base_uom
            FROM INVOICE_DETAIL id
            LEFT JOIN dicihmas im ON im.ite_code = id.ite_code
            WHERE id.trc_code = 'S01' AND id.vr_no = %s
            ORDER BY id.sr_no
        """, (hdr["vr_no"],))
        items = cur.fetchall()
        if items:
            print(f"  Items ({len(items)}):")
            for it in items:
                name = it.get("ite_name") or it["ite_code"]
                print(
                    f"    [{it['sr_no']}] {it['ite_code']} | {name} | "
                    f"Qty={it['ite_qty']} | Rate={it['ite_rate']:.3f} | "
                    f"VAT={it['vat_rate']}%"
                )
        else:
            print("  Items: none found in INVOICE_DETAIL for this vr_no")

    # ── 3. Sample S06 POS invoice with sales_data items ───────────────────────
    print("\n" + "=" * 60)
    print("SAMPLE S06 POS INVOICE WITH SALES_DATA ITEMS")
    print("=" * 60)
    cur.execute("""
        SELECT TOP 1 *
        FROM dichdata
        WHERE trc_code = 'S06' AND posted_ind = 'Y'
        ORDER BY vr_no DESC
    """)
    hdr6 = cur.fetchone()
    if hdr6:
        print(f"  Invoice : {hdr6['bill_no']}  (vr_no={hdr6['vr_no']})")
        print(f"  Customer: {hdr6['acc_name']}  ({hdr6['acc_code']})")
        print(f"  Date    : {str(hdr6['vr_date'])[:10]}")
        print(f"  Amount  : {hdr6['acc_amt']:.3f} {hdr6['cur_code']}  "
              f"(VAT={hdr6['vat_amt']:.3f})")
        cur.execute("""
            SELECT sd.*, im.ite_name
            FROM sales_data sd
            LEFT JOIN dicihmas im ON im.ite_code = sd.ite_code
            WHERE sd.trc_code = 'S06' AND sd.vr_no = %s
            ORDER BY sd.sr_no
        """, (hdr6["vr_no"],))
        items6 = cur.fetchall()
        if items6:
            print(f"  Items ({len(items6)}):")
            for it in items6:
                name = it.get("ite_name") or it["ite_code"]
                print(
                    f"    [{it['sr_no']}] {it['ite_code']} | {name} | "
                    f"Qty={it['ite_qty']} | Rate={it['ite_rate']:.3f}"
                )

    # ── 4. INVOICE_DETAIL coverage ────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("ITEM DETAIL COVERAGE")
    print("=" * 60)
    cur.execute("SELECT COUNT(DISTINCT vr_no) AS inv, COUNT(*) AS rows FROM INVOICE_DETAIL WHERE trc_code='S01'")
    r = cur.fetchone()
    print(f"  INVOICE_DETAIL: {r['rows']} rows across {r['inv']} S01 invoices")

    cur.execute("SELECT COUNT(DISTINCT vr_no) AS inv, COUNT(*) AS rows FROM sales_data WHERE trc_code='S06'")
    r = cur.fetchone()
    print(f"  sales_data    : {r['rows']} rows across {r['inv']} S06 invoices")

    cur.execute("SELECT COUNT(*) AS cnt FROM dicihmas")
    r = cur.fetchone()
    print(f"  dicihmas      : {r['cnt']} item master records")

    conn.close()
    print("\n✅  Done. Use these credentials in ePromise Settings → SQL Server fields.")
    print("    Then click 'Import Sales Invoices' on the migration page.\n")


if __name__ == "__main__":
    run()
