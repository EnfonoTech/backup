"""
Whitelisted API for testing live ePromise SQL Server connection
from the migration page.
"""

import frappe


@frappe.whitelist()
def test_connection():
	"""
	Test the live SQL Server connection using credentials from ePromise Settings.
	Returns a result dict with connected status, message, and table row counts.
	"""
	settings = frappe.get_single("ePromise Settings")

	host     = (settings.mssql_host or "").strip()
	port     = int(settings.mssql_port or 1433)
	database = (settings.mssql_database or "").strip()
	user     = (settings.mssql_username or "").strip()
	password = settings.get_password("mssql_password") or ""

	if not host:
		return {"connected": False, "message": "SQL Server Host is not configured in ePromise Settings."}

	from backup.epromise_migration.utils.bak_parser import test_mssql_connection

	result = test_mssql_connection(host, port, database, user, password)
	return result
