"""
Imports Supplier Master from ePromise (DICADMAS table) into ERPNext.

ePromise account master key fields:
  acc_code     : unique account code (stored as epromise_acc_code)
  acc_name     : supplier name (English)
  ar_acc_name  : supplier name (Arabic)
  sub_head='C' : Creditor → supplier accounts
  credit_limit : credit limit
  credit_period: credit days
  cur_code     : currency
  vat_no       : VAT / Tax registration number
  address      : address text
"""

import frappe
from frappe.utils import now_datetime

from backup.epromise_migration.utils.bak_parser import connect_mssql


def _get_settings():
	return frappe.get_single("ePromise Settings")


def _ensure_custom_field():
	if not frappe.db.exists("Custom Field", {"dt": "Supplier", "fieldname": "epromise_acc_code"}):
		frappe.get_doc({
			"doctype": "Custom Field",
			"dt": "Supplier",
			"label": "ePromise Account Code",
			"fieldname": "epromise_acc_code",
			"fieldtype": "Data",
			"insert_after": "supplier_name",
			"read_only": 1,
			"search_index": 1,
		}).insert(ignore_permissions=True)
		frappe.db.commit()


def _build_supplier_doc(row, settings):
	acc_code = (row.get("acc_code") or "").strip()
	acc_name = (row.get("acc_name") or "").strip()
	if not acc_code or not acc_name:
		return None

	doc = {
		"doctype": "Supplier",
		"supplier_name": acc_name,
		"supplier_type": "Company",
		"supplier_group": settings.default_supplier_group or "All Supplier Groups",
		"epromise_acc_code": acc_code,
	}

	if (row.get("vat_no") or "").strip():
		doc["tax_id"] = row["vat_no"].strip()

	credit_days = int(float(row.get("credit_period") or 0))
	if credit_days:
		pt_name = f"Net {credit_days} Days"
		if not frappe.db.exists("Payment Terms Template", pt_name):
			try:
				frappe.get_doc({
					"doctype": "Payment Terms Template",
					"template_name": pt_name,
					"terms": [{
						"payment_term": _ensure_payment_term(credit_days),
						"invoice_portion": 100,
						"credit_days": credit_days,
					}],
				}).insert(ignore_permissions=True)
			except Exception:
				frappe.db.rollback()
				pt_name = None
		if pt_name:
			doc["payment_terms"] = pt_name

	return doc


def _ensure_payment_term(days):
	name = f"Net {days} Days"
	if not frappe.db.exists("Payment Term", name):
		frappe.get_doc({
			"doctype": "Payment Term",
			"payment_term_name": name,
			"due_date_based_on": "Day(s) after invoice date",
			"credit_days": days,
		}).insert(ignore_permissions=True)
	return name


def _iter_supplier_rows(settings):
	"""Yield deduplicated DICADMAS rows for sub_head='C' (creditors/suppliers)."""
	if settings.mssql_host:
		conn = connect_mssql(settings)
		cur = conn.cursor()
		cur.execute("SELECT * FROM DICADMAS WHERE SUB_HEAD='C' AND ACC_NAME IS NOT NULL")
		seen = {}
		for row in cur:
			d = {k.lower(): v for k, v in dict(row).items()}
			seen[d.get("acc_code")] = d
		conn.close()
		yield from seen.values()
	else:
		from backup.epromise_migration.utils.bak_parser import extract_table_rows
		seen = {}
		for row in extract_table_rows(settings.backup_file_path, "dicadmas"):
			if row.get("sub_head") == "C":
				seen[row.get("acc_code")] = row
		yield from seen.values()


@frappe.whitelist()
def import_suppliers():
	"""
	Main entry point — imports all suppliers from DICADMAS (sub_head=C).
	Returns {log_name, total, success, skipped, errors}
	"""
	settings = _get_settings()
	if not settings.erpnext_company:
		frappe.throw("Please configure ePromise Settings (Company) before importing.")

	_ensure_custom_field()

	log = frappe.get_doc({
		"doctype": "ePromise Migration Log",
		"migration_type": "Supplier Master",
		"status": "Running",
		"started_at": now_datetime(),
	})
	log.insert(ignore_permissions=True)
	frappe.db.commit()

	total = success = skipped = errors = 0
	log_lines = []

	try:
		for row in _iter_supplier_rows(settings):
			total += 1
			acc_code = (row.get("acc_code") or "").strip()
			acc_name = (row.get("acc_name") or "").strip()

			if not acc_code or not acc_name:
				skipped += 1
				continue

			if settings.skip_existing and frappe.db.exists(
				"Supplier", {"epromise_acc_code": acc_code}
			):
				skipped += 1
				log_lines.append(f"[SKIP] {acc_code} — {acc_name} (exists)")
				continue

			try:
				# If supplier already exists by name, just link the acc_code
				existing = frappe.db.get_value("Supplier", acc_name, "name")
				if existing:
					frappe.db.set_value("Supplier", existing, "epromise_acc_code", acc_code)
					frappe.db.commit()
					success += 1
					log_lines.append(f"[LINK] {acc_code} — {acc_name} (linked to existing)")
					continue

				doc_dict = _build_supplier_doc(row, settings)
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
