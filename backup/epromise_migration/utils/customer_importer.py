"""
Imports Customer Master from ePromise (dicadmas table) into ERPNext.

ePromise account master key fields:
  acc_code        : unique account code  (stored as epromise_acc_code custom field)
  acc_name        : customer name (English)
  ar_acc_name     : customer name (Arabic)
  ah_code = '1'   : Asset / Receivable accounts
  sub_head = 'D'  : Debtor  ← actual customer accounts
  sub_head = 'B'  : Bank accounts  (skipped)
  sub_head = 'N'  : PDC / other    (skipped)
  credit_limit    : credit limit amount
  credit_period   : credit days
  cur_code        : currency
  vat_no          : VAT / Tax registration number
  Contact_person  : contact details
  address         : address text
  posting_ind     : 'Y' = active

Rows are deduplicated by acc_code (last occurrence wins).
"""

import frappe
from frappe.utils import now_datetime

from backup.epromise_migration.utils.bak_parser import extract_table_rows, connect_mssql

CUSTOMER_AH_CODE = "1"
CUSTOMER_SUB_HEAD = "D"

CURRENCY_MAP = {
	"BHD": "BHD", "USD": "USD", "SAR": "SAR", "AED": "AED",
	"KWD": "KWD", "OMR": "OMR", "QAR": "QAR", "EUR": "EUR", "GBP": "GBP",
}


def _get_settings():
	return frappe.get_single("ePromise Settings")


def _get_or_create_currency(code):
	if not code:
		return None
	iso = CURRENCY_MAP.get(code.strip().upper(), code.strip().upper())
	if not frappe.db.exists("Currency", iso):
		frappe.get_doc({"doctype": "Currency", "currency_name": iso, "enabled": 1}).insert(
			ignore_permissions=True
		)
	return iso


def _get_or_create_payment_term(days):
	name = f"Net {days} Days"
	if not frappe.db.exists("Payment Term", name):
		frappe.get_doc({
			"doctype": "Payment Term",
			"payment_term_name": name,
			"due_date_based_on": "Day(s) after invoice date",
			"credit_days": days,
		}).insert(ignore_permissions=True)
	return name


def _ensure_payment_terms_template(days, company):
	pt_name = f"Net {days}"
	if not frappe.db.exists("Payment Terms Template", pt_name):
		frappe.get_doc({
			"doctype": "Payment Terms Template",
			"template_name": pt_name,
			"terms": [{
				"payment_term": _get_or_create_payment_term(days),
				"invoice_portion": 100,
				"credit_days": days,
			}],
		}).insert(ignore_permissions=True)
	return pt_name


def _ensure_custom_fields():
	"""Add epromise_acc_code custom field to Customer if not present."""
	if not frappe.db.exists("Custom Field", {"dt": "Customer", "fieldname": "epromise_acc_code"}):
		frappe.get_doc({
			"doctype": "Custom Field",
			"dt": "Customer",
			"label": "ePromise Account Code",
			"fieldname": "epromise_acc_code",
			"fieldtype": "Data",
			"insert_after": "customer_name",
			"read_only": 1,
			"search_index": 1,
		}).insert(ignore_permissions=True)
		frappe.db.commit()


def _build_customer_doc(row, settings):
	acc_code = (row.get("acc_code") or "").strip()
	acc_name = (row.get("acc_name") or "").strip()
	if not acc_code or not acc_name:
		return None

	currency = _get_or_create_currency(row.get("cur_code"))
	credit_limit = float(row.get("credit_limit") or 0)
	credit_days = int(float(row.get("credit_period") or 0))

	doc = {
		"doctype": "Customer",
		"customer_name": acc_name,
		"customer_type": "Company",
		"customer_group": settings.default_customer_group or "Commercial",
		"territory": settings.default_territory or "All Territories",
		"default_currency": currency,
		"tax_id": (row.get("vat_no") or "").strip() or None,
		"epromise_acc_code": acc_code,
	}

	ar_name = (row.get("ar_acc_name") or "").strip()
	if ar_name and ar_name != acc_name:
		doc["customer_name_in_arabic"] = ar_name

	if credit_limit:
		doc["credit_limits"] = [{
			"company": settings.erpnext_company,
			"credit_limit": credit_limit,
		}]

	if credit_days:
		doc["payment_terms"] = _ensure_payment_terms_template(credit_days, settings.erpnext_company)

	return doc


def _iter_customer_rows(settings):
	"""Yield deduplicated dicadmas rows that represent customer accounts (sub_head=D)."""
	if settings.mssql_host:
		conn = connect_mssql(settings)
		cursor = conn.cursor()
		cursor.execute(
			"SELECT * FROM DICADMAS WHERE AH_CODE='1' AND SUB_HEAD='D'"
		)
		seen = {}
		for row in cursor:
			d = {k.lower(): v for k, v in dict(row).items()}
			seen[d.get("acc_code")] = d
		conn.close()
		yield from seen.values()
	else:
		seen = {}
		for row in extract_table_rows(settings.backup_file_path, "dicadmas"):
			if row.get("ah_code") == CUSTOMER_AH_CODE and row.get("sub_head") == CUSTOMER_SUB_HEAD:
				seen[row.get("acc_code")] = row   # last occurrence wins (most recent data)
		yield from seen.values()


@frappe.whitelist()
def import_customers():
	"""
	Main entry point called from the migration page.
	Returns a summary dict: {log_name, total, success, skipped, errors}
	"""
	settings = _get_settings()
	if not settings.erpnext_company:
		frappe.throw("Please configure ePromise Settings (Company) before importing.")

	_ensure_custom_fields()

	log = frappe.get_doc({
		"doctype": "ePromise Migration Log",
		"migration_type": "Customer Master",
		"status": "Running",
		"started_at": now_datetime(),
	})
	log.insert(ignore_permissions=True)
	frappe.db.commit()

	total = success = skipped = errors = 0
	log_lines = []

	try:
		for row in _iter_customer_rows(settings):
			total += 1
			acc_code = (row.get("acc_code") or "").strip()
			acc_name = (row.get("acc_name") or "").strip()

			if not acc_code or not acc_name:
				skipped += 1
				log_lines.append(f"[SKIP] Empty acc_code or acc_name")
				continue

			if settings.skip_existing and frappe.db.exists(
				"Customer", {"epromise_acc_code": acc_code}
			):
				skipped += 1
				log_lines.append(f"[SKIP] {acc_code} — {acc_name} (already exists)")
				continue

			try:
				doc_dict = _build_customer_doc(row, settings)
				if not doc_dict:
					skipped += 1
					continue
				frappe.get_doc(doc_dict).insert(ignore_permissions=True)
				frappe.db.commit()
				success += 1
				log_lines.append(f"[OK] {acc_code} — {acc_name}")

			except Exception as e:
				errors += 1
				frappe.db.rollback()
				log_lines.append(f"[ERR] {acc_code} — {acc_name}: {e}")

	except Exception as e:
		log.status = "Failed"
		log.log_details = f"Fatal error: {e}\n" + "\n".join(log_lines[-100:])
		log.total_records = total
		log.success_count = success
		log.skipped_count = skipped
		log.error_count = errors
		log.completed_at = now_datetime()
		log.save(ignore_permissions=True)
		frappe.db.commit()
		frappe.throw(str(e))

	log.status = "Completed"
	log.total_records = total
	log.success_count = success
	log.skipped_count = skipped
	log.error_count = errors
	log.completed_at = now_datetime()
	log.log_details = "\n".join(log_lines)
	log.save(ignore_permissions=True)
	frappe.db.commit()

	return {
		"log_name": log.name,
		"total": total,
		"success": success,
		"skipped": skipped,
		"errors": errors,
	}
