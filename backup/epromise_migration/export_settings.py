"""
Export ePromise Settings as bench set-config commands for production.

Usage (run on staging/local):
    bench --site [site] execute backup.epromise_migration.export_settings.print_bench_commands

Copy the output and run it on the production server.
The password is shown once — pipe to a file or use a password manager if needed.

Why site_config.json instead of ePromise Settings on production?
  - site_config.json is NOT included in `bench backup` dumps (safe to restore).
  - Credentials stay in the filesystem, not in the database.
  - No risk of accidentally exporting credentials via ERPNext's Data Export.
"""

import frappe


def print_bench_commands():
    """
    Read ePromise Settings from the current site and print the exact
    `bench set-config` commands to paste on the production server.
    """
    s = frappe.get_single("ePromise Settings")

    host     = (s.mssql_host     or "").strip()
    port     = int(s.mssql_port or 1433)
    database = (s.mssql_database or "").strip()
    user     = (s.mssql_username or "").strip()
    password = s.get_password("mssql_password") or ""

    # If site_config already has overrides, use those (they're more authoritative)
    conf = frappe.conf
    host     = conf.get("epromise_mssql_host")     or host
    port     = int(conf.get("epromise_mssql_port") or port)
    database = conf.get("epromise_mssql_database") or database
    user     = conf.get("epromise_mssql_username") or user
    password = conf.get("epromise_mssql_password") or password

    site = frappe.local.site

    print()
    print("=" * 62)
    print("  ePromise SQL Server — production bench set-config commands")
    print("  Run these on the PRODUCTION server as the bench user")
    print("=" * 62)
    print()
    print(f'bench --site [PROD-SITE] set-config epromise_mssql_host     "{host}"')
    print(f'bench --site [PROD-SITE] set-config epromise_mssql_port     {port}')
    print(f'bench --site [PROD-SITE] set-config epromise_mssql_database "{database}"')
    print(f'bench --site [PROD-SITE] set-config epromise_mssql_username "{user}"')
    print(f'bench --site [PROD-SITE] set-config epromise_mssql_password "{password}"')
    print()
    print("After running the above, verify the connection:")
    print(f'bench --site [PROD-SITE] execute backup.epromise_migration.export_settings.verify_connection')
    print()
    print("The password is stored in site_config.json (filesystem only, NOT in the DB).")
    print("To remove it later:  bench --site [PROD-SITE] set-config epromise_mssql_password ''")
    print("=" * 62)
    print()

    # Also show current source
    src_host = "site_config.json" if conf.get("epromise_mssql_host") else "ePromise Settings (DB)"
    print(f"  (credentials read from: {src_host} on site '{site}')")
    print()


def verify_connection():
    """
    Quick connectivity check — run on production after applying set-config.
    Prints a green OK or a clear error message.
    """
    s = frappe.get_single("ePromise Settings")

    from backup.epromise_migration.utils.bak_parser import _get_mssql_credentials

    host, port, database, user, password = _get_mssql_credentials(s)

    print(f"\nConnecting to {host}:{port}  db={database}  user={user} ...")

    try:
        import pymssql
        conn = pymssql.connect(
            server=host,
            port=port,
            database=database,
            user=user,
            password=password,
            as_dict=True,
            login_timeout=15,
        )
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) AS n FROM DICHDATA WHERE POSTED_IND='Y'")
        row = cur.fetchone()
        conn.close()
        n = row["n"] if row else "?"
        src = "site_config.json" if frappe.conf.get("epromise_mssql_host") else "ePromise Settings"
        print(f"  OK  — {n:,} posted DICHDATA rows found")
        print(f"  Credentials source: {src}")
    except Exception as e:
        print(f"  FAILED — {e}")
        print("  Check: network route to the SQL Server, firewall, port, credentials.")
