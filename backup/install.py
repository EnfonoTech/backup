"""
Frappe lifecycle hooks — called by bench install-app / uninstall-app.

after_install  → installs Python packages, creates custom fields and naming series
before_uninstall → no-op (DocTypes and custom fields are removed by bench automatically)
"""

import sys
import subprocess
import frappe

# Packages required by this app
_REQUIRED_PACKAGES = [
    ("openpyxl", "openpyxl>=3.0.0"),
    ("xlrd",     "xlrd>=2.0.0"),
    ("pymssql",  "pymssql>=2.2.0"),
]


def _pip_install(import_name, pip_spec):
    """Try to import; install via pip if the import fails."""
    try:
        __import__(import_name)
        print(f"  OK       {pip_spec} (already installed)")
        return True
    except ImportError:
        print(f"  INSTALL  {pip_spec} ...")
        try:
            subprocess.check_call(
                [sys.executable, "-m", "pip", "install", "--quiet", pip_spec],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
            __import__(import_name)
            print(f"  DONE     {pip_spec}")
            return True
        except subprocess.CalledProcessError as e:
            stderr = e.stderr.decode("utf-8", errors="replace") if e.stderr else ""
            print(f"  FAILED   {pip_spec}")
            if "pymssql" in pip_spec:
                print(
                    "  HINT     pymssql requires system packages on Ubuntu/Debian:\n"
                    "             apt-get install -y freetds-dev freetds-bin\n"
                    "           Then re-run: pip install pymssql"
                )
            elif stderr:
                print(f"           {stderr[:300]}")
            frappe.log_error(
                f"Failed to install {pip_spec}:\n{stderr}",
                "backup app: package install",
            )
            return False
        except ImportError:
            print(f"  FAILED   {pip_spec} installed but still cannot import {import_name}")
            return False


def _ensure_custom_fields():
    """Create all ePromise custom fields needed across the site."""
    try:
        from backup.epromise_migration.utils.invoice_importer import (
            _ensure_custom_fields as _si_fields,
            _ensure_naming_series,
        )
        _si_fields()
        _ensure_naming_series()
        print("  OK       Sales Invoice custom fields + naming series")
    except Exception as e:
        print(f"  WARN     Sales Invoice custom fields: {e}")

    try:
        from backup.epromise_migration.utils.purchase_importer import (
            _ensure_custom_fields as _pi_fields,
            _ensure_naming_series as _pi_series,
            _ensure_supplier_custom_field,
        )
        _pi_fields()
        _pi_series()
        _ensure_supplier_custom_field()
        print("  OK       Purchase Invoice custom fields + naming series")
    except Exception as e:
        print(f"  WARN     Purchase Invoice custom fields: {e}")

    # epromise_acc_code on Customer
    try:
        if not frappe.db.exists("Custom Field", {"dt": "Customer", "fieldname": "epromise_acc_code"}):
            frappe.get_doc({
                "doctype": "Custom Field",
                "dt": "Customer",
                "fieldname": "epromise_acc_code",
                "label": "ePromise Acc Code",
                "fieldtype": "Data",
                "insert_after": "customer_name",
                "read_only": 1,
                "search_index": 1,
            }).insert(ignore_permissions=True)
            frappe.db.commit()
            print("  OK       Customer.epromise_acc_code — created")
        else:
            print("  OK       Customer.epromise_acc_code — exists")
    except Exception as e:
        print(f"  WARN     Customer.epromise_acc_code: {e}")

    # epromise_vr_no on Payment Entry and Journal Entry
    for dt in ("Payment Entry", "Journal Entry"):
        fn = "epromise_vr_no"
        try:
            if not frappe.db.exists("Custom Field", {"dt": dt, "fieldname": fn}):
                frappe.get_doc({
                    "doctype": "Custom Field",
                    "dt": dt,
                    "fieldname": fn,
                    "label": "ePromise Voucher No",
                    "fieldtype": "Data",
                    "insert_after": "naming_series",
                    "read_only": 1,
                    "search_index": 1,
                }).insert(ignore_permissions=True)
                frappe.db.commit()
                print(f"  OK       {dt}.epromise_vr_no — created")
            else:
                print(f"  OK       {dt}.epromise_vr_no — exists")
        except Exception as e:
            print(f"  WARN     {dt}.epromise_vr_no: {e}")


def after_install():
    """
    Called automatically by bench after `bench install-app backup`.

    1. Installs required Python packages (openpyxl, xlrd, pymssql) into the
       bench virtual environment.
    2. Creates all ePromise custom fields and naming series on the site.

    After this completes, run the company-specific setup:
        bench --site [site] execute backup.epromise_migration.setup_production.run_setup
    """
    print("\n" + "=" * 58)
    print("backup app — post-install setup")
    print("=" * 58)

    # Step 1: Python packages
    print("\n[1] Installing Python packages")
    failed = []
    for import_name, pip_spec in _REQUIRED_PACKAGES:
        ok = _pip_install(import_name, pip_spec)
        if not ok:
            failed.append(pip_spec)

    if failed:
        print(f"\n  WARNING: {len(failed)} package(s) failed to install: {', '.join(failed)}")
        print("  Install them manually, then re-run bench migrate.")
    else:
        print("\n  All packages installed successfully.")

    # Step 2: Custom fields
    print("\n[2] Creating ePromise custom fields")
    _ensure_custom_fields()

    print("\n" + "=" * 58)
    print("Post-install complete.")
    print("Next: bench --site [site] execute")
    print("      backup.epromise_migration.setup_production.run_setup")
    print("=" * 58 + "\n")
