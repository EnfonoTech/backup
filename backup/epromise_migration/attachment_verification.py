"""
ePromise Attachment Verification -- human-in-the-loop review before an
ATTACHMENT_DETAIL row (a legacy file blob keyed by TRC_CODE+VR_NO+FY_CODE) is
turned into a Frappe File on its matching ERPNext voucher.

Powers the "ePromise Attachment Verification" desk page. Reuses the same
TRC_CODE -> doctype routing table and epromise_trc_code+epromise_vr_no
compound match key as the bulk migration job -- see
epromise_migration/utils/payment_importer.py (sets epromise_trc_code on both
Payment Entry and Journal Entry, not just Purchase Invoice) and
page/epromise_migration/epromise_migration.js (the authoritative TRC->doctype
map) for why the match key must be the compound pair, not epromise_vr_no
alone: VR_NO is reused as a bare reference number across unrelated documents.
"""

import base64
import os

import frappe
from frappe import _
from frappe.utils.file_manager import save_file

ROUTING = {
	"S01": "Sales Invoice", "S06": "Sales Invoice", "R01": "Sales Invoice", "R04": "Sales Invoice",
	"350": "Purchase Invoice", "111": "Purchase Invoice", "IP": "Purchase Invoice", "PR": "Purchase Invoice",
	"GRN": "Purchase Receipt", "GR": "Purchase Receipt",
	"003": "Payment Entry", "004": "Payment Entry",
	"020": "Journal Entry", "007": "Journal Entry",
}

PREVIEWABLE_EXT = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
	".gif": "image/gif", ".webp": "image/webp", ".pdf": "application/pdf"}

MAX_PREVIEW_BYTES = 8 * 1024 * 1024

# amount field to compare against the ePromise voucher's LOCAL_CUR_AMT when fuzzy-suggesting a
# manual-pick target -- date field is posting_date on every one of these doctypes.
AMOUNT_FIELD = {
	"Sales Invoice": "grand_total", "Purchase Invoice": "grand_total", "Purchase Receipt": "grand_total",
	"Payment Entry": "paid_amount", "Journal Entry": "total_debit",
}


def _check_role():
	if "System Manager" not in frappe.get_roles():
		frappe.throw(_("Not permitted"), frappe.PermissionError)


def _get_connection():
	import pymssql

	settings = frappe.get_single("ePromise Settings")
	host = (settings.mssql_host or "").strip()
	port = int(settings.mssql_port or 1433)
	database = (settings.attachment_mssql_database or settings.mssql_database or "").strip()
	user = (settings.mssql_username or "").strip()
	password = settings.get_password("mssql_password") or ""

	if not host or not database or not user:
		frappe.throw(_(
			"ePromise Settings is missing SQL Server Host, Username, or an Attachment Database "
			"Name / Database Name."
		))

	return pymssql.connect(
		server=host, port=port, database=database, user=user, password=password,
		as_dict=True, login_timeout=15,
	)


def _get_transactional_connection():
	"""Connect to the main dichdata database (Database Name, NOT Attachment Database Name) --
	used only to pull the voucher's own amount/date for fuzzy-matching, since ATTACHMENT_DETAIL
	itself carries no amount."""
	import pymssql

	settings = frappe.get_single("ePromise Settings")
	host = (settings.mssql_host or "").strip()
	port = int(settings.mssql_port or 1433)
	database = (settings.mssql_database or "").strip()
	user = (settings.mssql_username or "").strip()
	password = settings.get_password("mssql_password") or ""

	if not host or not database or not user:
		frappe.throw(_("ePromise Settings is missing SQL Server Host, Username, or Database Name."))

	return pymssql.connect(
		server=host, port=port, database=database, user=user, password=password,
		as_dict=True, login_timeout=15,
	)


def _get_voucher_reference(fy_code, trc_code, vr_no):
	"""Pull the ePromise voucher's own identifying fields from dichdata (the transactional
	database, NOT the attachment one) -- amount + date for fuzzy scoring, plus the descriptive
	fields (particulars/payee/account/bill no) a human reviewer needs to visually confirm a
	manual pick, since ATTACHMENT_DETAIL itself carries none of this."""
	conn = _get_transactional_connection()
	cur = conn.cursor()
	cur.execute(
		"SELECT TOP 1 VR_DATE, LOCAL_CUR_AMT, ACC_AMT, PARTICULARS, PAYEE_NAME, ACC_NAME, "
		"BILL_NO, BILL_DATE, CUR_CODE, CUR_RATE, SOURCE_BR_CODE, TARGET_BR_CODE, "
		"CREATED_USER, CREATED_DATE, REF_TRC_CODE, REF_VR_NO, supplier_name, "
		"vat_amt, total_vat, POSTED_IND, LPO_NO, tax_invoice_no "
		"FROM dichdata "
		"WHERE FY_CODE = %(fy)s AND TRC_CODE = %(trc)s AND CAST(VR_NO AS VARCHAR(50)) = %(vr)s",
		{"fy": fy_code, "trc": trc_code, "vr": str(vr_no)},
	)
	row = cur.fetchone()
	conn.close()
	if not row:
		return None
	return {
		"vr_date": row["VR_DATE"],
		"amount": row["LOCAL_CUR_AMT"] if row["LOCAL_CUR_AMT"] is not None else row["ACC_AMT"],
		"particulars": row["PARTICULARS"], "payee_name": row["PAYEE_NAME"],
		"acc_name": row["ACC_NAME"], "bill_no": row["BILL_NO"], "bill_date": row["BILL_DATE"],
		"currency": row["CUR_CODE"], "currency_rate": row["CUR_RATE"],
		"source_branch": row["SOURCE_BR_CODE"], "target_branch": row["TARGET_BR_CODE"],
		"created_user": row["CREATED_USER"], "created_date": row["CREATED_DATE"],
		"ref_trc_code": row["REF_TRC_CODE"], "ref_vr_no": row["REF_VR_NO"],
		"supplier_name": row["supplier_name"], "vat_amount": row["vat_amt"],
		"total_vat": row["total_vat"], "posted": row["POSTED_IND"],
		"lpo_no": row["LPO_NO"], "tax_invoice_no": row["tax_invoice_no"],
	}


@frappe.whitelist()
def get_voucher_info(fy_code, trc_code, vr_no):
	"""Standalone lookup so any row (even a clean match) can show its ePromise voucher context
	for a sanity check before attaching."""
	_check_role()
	voucher = _get_voucher_reference(fy_code, trc_code, vr_no)
	if not voucher:
		return {"found": False}
	voucher["found"] = True
	return voucher


@frappe.whitelist()
def suggest_candidates(doctype, fy_code, trc_code, vr_no, days_window=15, limit=10):
	"""Fuzzy-match suggestions for the manual-pick dialog: rank same-doctype submitted documents
	near the voucher's own date by how close their amount is to the voucher's LOCAL_CUR_AMT."""
	_check_role()
	if doctype not in AMOUNT_FIELD:
		frappe.throw(_("Unsupported doctype for fuzzy matching: {0}").format(doctype))

	voucher = _get_voucher_reference(fy_code, trc_code, vr_no)
	if not voucher or not voucher.get("vr_date"):
		return {"voucher": voucher, "candidates": []}

	days_window = frappe.utils.cint(days_window) or 15
	vr_date = frappe.utils.getdate(voucher["vr_date"])
	window_start = frappe.utils.add_days(vr_date, -days_window)
	window_end = frappe.utils.add_days(vr_date, days_window)
	amount_field = AMOUNT_FIELD[doctype]

	rows = frappe.get_all(
		doctype,
		filters={"posting_date": ["between", [window_start, window_end]], "docstatus": 1},
		fields=["name", "posting_date", f"{amount_field} as amount"],
		limit=500,
	)

	target_amount = frappe.utils.flt(voucher.get("amount"))
	for r in rows:
		r["amount_diff"] = abs(frappe.utils.flt(r["amount"]) - target_amount)
		r["date_diff"] = abs((frappe.utils.getdate(r["posting_date"]) - vr_date).days)
	rows.sort(key=lambda r: (r["amount_diff"], r["date_diff"]))

	return {"voucher": voucher, "candidates": rows[: frappe.utils.cint(limit) or 10]}


def _classify(trc, vr_no):
	"""Return (doctype_or_None, status, matched_name_or_None, candidates).

	Two migration eras coexist across sites (confirmed live on sft-uat, 2026-09-27): the CURRENT
	importer writes separate epromise_trc_code + epromise_vr_no fields, but an EARLIER era (still
	the only one populated on sft-uat: 24116 Sales Invoice / 1014 Purchase Invoice / 1008 Purchase
	Receipt / 1113 Payment Entry / 3302 Journal Entry rows, split fields either absent or 100%
	empty) wrote a single combined `epromise_vr` field as "{TRC}|{VR_NO}" instead. Try the split
	pair first, then fall back to the legacy combined field before giving up -- never guess which
	era a given site is on."""
	doctype = ROUTING.get(trc)
	if not doctype:
		return None, "out_of_scope", None, []

	meta = frappe.get_meta(doctype)
	has_split = meta.has_field("epromise_trc_code") and meta.has_field("epromise_vr_no")
	has_legacy = meta.has_field("epromise_vr")

	if not has_split and not has_legacy:
		# the migration importer for this doctype has never run on this site at all -- the
		# custom fields only get created when that importer actually runs, not via bench migrate.
		return doctype, "fields_missing", None, []

	matches = []
	if has_split:
		matches = frappe.get_all(
			doctype, filters={"epromise_trc_code": trc, "epromise_vr_no": vr_no}, pluck="name"
		)
	if not matches and has_legacy:
		matches = frappe.get_all(
			doctype, filters={"epromise_vr": f"{trc}|{vr_no}"}, pluck="name"
		)

	if not matches:
		return doctype, "unmatched", None, []
	if len(matches) > 1:
		return doctype, "duplicate", None, matches

	return doctype, "clean", matches[0], []


@frappe.whitelist()
def get_rows(trc_code=None, status=None, search=None, from_date=None, to_date=None,
		limit_start=0, limit_page_length=50):
	_check_role()
	limit_start = frappe.utils.cint(limit_start)
	limit_page_length = frappe.utils.cint(limit_page_length) or 50

	conn = _get_connection()
	cur = conn.cursor()

	# NOTE: only STATIC, hardcoded clause fragments are string-joined below (never user input) --
	# every actual value (trc_code, search, from_date, to_date) goes through a %(name)s placeholder
	# bound by cur.execute. "See all" = no trc_code/status/date filters at all; imageobject IS NOT
	# NULL stays mandatory since a row with no blob has nothing to preview or attach.
	where_clauses = ["imageobject IS NOT NULL"]
	params = {}
	if trc_code:
		where_clauses.append("TRC_CODE = %(trc_code)s")
		params["trc_code"] = trc_code
	if search:
		where_clauses.append("(ATTACHMENT LIKE %(search)s OR CAST(VR_NO AS VARCHAR(50)) LIKE %(search)s)")
		params["search"] = "%" + search + "%"
	if from_date:
		where_clauses.append("CAST(vr_date AS DATE) >= %(from_date)s")
		params["from_date"] = from_date
	if to_date:
		where_clauses.append("CAST(vr_date AS DATE) <= %(to_date)s")
		params["to_date"] = to_date

	where_sql = " AND ".join(where_clauses)
	query = (
		"SELECT FY_CODE, TRC_CODE, VR_NO, ATTACHMENT, vr_date, DATALENGTH(imageobject) AS blob_size "
		"FROM ATTACHMENT_DETAIL WHERE " + where_sql + " ORDER BY vr_date DESC"
	)
	cur.execute(query, params)
	all_rows = cur.fetchall()
	conn.close()

	out = []
	for row in all_rows:
		trc = (row["TRC_CODE"] or "").strip()
		vr = str(row["VR_NO"]).strip()
		doctype, row_status, matched_name, candidates = _classify(trc, vr)

		if row_status == "clean":
			already = frappe.db.exists(
				"File", {"attached_to_doctype": doctype, "attached_to_name": matched_name,
					"file_name": row["ATTACHMENT"]}
			)
			if already:
				row_status = "attached"

		if status and status != "all" and row_status != status:
			continue

		out.append({
			"fy_code": row["FY_CODE"], "trc_code": trc, "vr_no": vr,
			"attachment": row["ATTACHMENT"], "vr_date": row["vr_date"],
			"blob_size": row["blob_size"], "doctype": doctype, "status": row_status,
			"matched_name": matched_name, "candidates": candidates,
		})

	total = len(out)
	page = out[limit_start:limit_start + limit_page_length]
	return {"rows": page, "total": total}


@frappe.whitelist()
def get_preview(fy_code, trc_code, vr_no, attachment):
	_check_role()
	ext = os.path.splitext(attachment or "")[1].lower()
	mime = PREVIEWABLE_EXT.get(ext)
	if not mime:
		return {"previewable": False, "reason": "No inline preview for " + (ext or "this file type")}

	conn = _get_connection()
	cur = conn.cursor()
	cur.execute(
		"SELECT TOP 1 imageobject FROM ATTACHMENT_DETAIL "
		"WHERE FY_CODE = %(fy)s AND TRC_CODE = %(trc)s AND VR_NO = %(vr)s AND ATTACHMENT = %(att)s",
		{"fy": fy_code, "trc": trc_code, "vr": vr_no, "att": attachment},
	)
	row = cur.fetchone()
	conn.close()

	if not row or not row["imageobject"]:
		return {"previewable": False, "reason": "Blob not found"}
	blob = row["imageobject"]
	if len(blob) > MAX_PREVIEW_BYTES:
		return {"previewable": False, "reason": "File too large to preview inline"}

	return {"previewable": True, "mime": mime, "data": base64.b64encode(blob).decode("ascii")}


@frappe.whitelist()
def attach_row(fy_code, trc_code, vr_no, attachment, override_doctype=None, override_name=None):
	_check_role()

	if override_doctype and override_name:
		doctype, docname = override_doctype, override_name
	else:
		doctype, status, docname, candidates = _classify((trc_code or "").strip(), str(vr_no).strip())
		if status != "clean":
			frappe.throw(_(
				"Row is not a clean single match ({0}) -- pick a target document explicitly."
			).format(status))

	if not frappe.db.exists(doctype, docname):
		frappe.throw(_("{0} {1} does not exist").format(doctype, docname))
	if not frappe.has_permission(doctype, "write", doc=docname):
		frappe.throw(_("No write permission on {0} {1}").format(doctype, docname), frappe.PermissionError)

	if frappe.db.exists("File", {"attached_to_doctype": doctype, "attached_to_name": docname,
			"file_name": attachment}):
		frappe.throw(_("This attachment is already on {0} {1}").format(doctype, docname))

	conn = _get_connection()
	cur = conn.cursor()
	cur.execute(
		"SELECT TOP 1 imageobject FROM ATTACHMENT_DETAIL "
		"WHERE FY_CODE = %(fy)s AND TRC_CODE = %(trc)s AND VR_NO = %(vr)s AND ATTACHMENT = %(att)s",
		{"fy": fy_code, "trc": trc_code, "vr": vr_no, "att": attachment},
	)
	row = cur.fetchone()
	conn.close()

	if not row or not row["imageobject"]:
		frappe.throw(_("Blob not found for this row"))

	f = save_file(attachment, row["imageobject"], doctype, docname, is_private=0, decode=False)
	frappe.db.commit()
	return {"file_url": f.file_url, "doctype": doctype, "docname": docname}


@frappe.whitelist()
def search_candidates(doctype, txt):
	_check_role()
	if doctype not in set(ROUTING.values()):
		frappe.throw(_("Invalid doctype"))
	return frappe.get_all(
		doctype,
		filters=[["name", "like", "%" + (txt or "") + "%"]],
		fields=["name"],
		limit=20,
		order_by="modified desc",
		pluck="name",
	)
