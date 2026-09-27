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
import difflib
import os

import frappe
from frappe import _
from frappe.utils.file_manager import save_file

#: trc_code -> ordered list of candidate ERPNext doctypes to search for a match. Almost always
#: one doctype, EXCEPT 003/004 (cash payment / cash receipt vouchers): payment_importer.py's own
#: builders try `_build_payment_entry_from_dicsdata(...) or _build_journal_entry_from_voucher(...)`
#: -- a real fallback chain at IMPORT time, not a fixed target -- so a given 003/004 voucher can
#: land as EITHER a Payment Entry or a Journal Entry, decided per-voucher (multi-party, missing
#: party resolution, etc. push it to JE). A single-doctype ROUTING here silently mis-classified
#: every 003/004 that landed in JE as "no match found" -- confirmed live (2026-09-28, sft prod):
#: of 1141 003/004 rows the old single-doctype lookup called unmatched, 1140 were sitting in
#: Journal Entry all along, findable by the SAME epromise_vr legacy key. _classify/_classify_bulk
#: below search every candidate in order and report whichever one actually has the match.
#: 025 (bank payment vouchers), 011 (customs/import VAT), BA (party settlements), 006 (non-goods
#: expense vouchers -- audit fee, air tickets, vehicle repair -- reimported via the account's own
#: "import_missing" GL-faithful pass) were ALSO always Journal Entry (confirmed both by gl_faithful/
#: config.py's own trc->doctype map and, live on this site 2026-09-28, real submitted JEs matching
#: each one's epromise_vr key) -- just missing from this ROUTING table entirely, so every one of
#: their attachments read as "out_of_scope" (looked never-migrated) when they were in fact migrated
#: fine. Deliberately NOT added: "301"/"300" (inventory-adjustment vouchers, LOCAL_CUR_AMT always
#: 0 -- confirmed live, no GL/financial document was ever meant to exist for these, an accepted
#: migration gap). "EMP"/"RHD" are NOT financial vouchers at all (0 rows in dichdata under either
#: code) so they don't belong in this table -- see SPECIAL_BULK_RESOLVERS below for their own,
#: structurally different resolution.
ROUTING = {
	"S01": ["Sales Invoice"], "S06": ["Sales Invoice"], "R01": ["Sales Invoice"], "R04": ["Sales Invoice"],
	"350": ["Purchase Invoice"], "111": ["Purchase Invoice"], "IP": ["Purchase Invoice"], "PR": ["Purchase Invoice"],
	"GRN": ["Purchase Receipt"], "GR": ["Purchase Receipt"],
	"003": ["Payment Entry", "Journal Entry"], "004": ["Payment Entry", "Journal Entry"],
	"020": ["Journal Entry"], "007": ["Journal Entry"],
	"025": ["Journal Entry"], "011": ["Journal Entry"], "BA": ["Journal Entry"], "006": ["Journal Entry"],
}


def _resolve_emp_bulk(vr_nos):
	"""EMP: vr_no IS the ePromise employee code, which is exactly Employee.employee_number on this
	site -- confirmed live 2026-09-28: employee_number '22024' = 'Reshma Ramesh', matching the EMP
	VR_NO that files her WORK PERMIT/PASSPORT attachments. ePromise's own HR/payroll module
	(PAY_EMPLOYEE_MASTER, PAY_EMPLOYEE_DOCUMENTS, HIRE_EMPLOYEE_DOCUMENTS -- a separate subsystem
	from the financial ledger dichdata reads from) already carries this same code; this migration's
	own, earlier, separate HR import evidently reused it as Employee.employee_number. No
	epromise_trc_code/vr_no/vr custom field involved at all -- a completely different resolution
	path from every trc in ROUTING above. Returns {vr_no: [(doctype, name)]} for the whole batch in
	one query."""
	out = {}
	for r in frappe.get_all("Employee", filters={"employee_number": ["in", list(vr_nos)]}, fields=["name", "employee_number"]):
		out.setdefault(r.employee_number, []).append(("Employee", r.name))
	return out


def _resolve_rhd_bulk(vr_nos):
	"""RHD: vr_no IS an ERPNext ledger Account's own account_number (a customer receivable control
	account) -- confirmed live 2026-09-28, all 6 distinct RHD codes on this site: e.g. '130302A0004'
	= Account '130302A0004 - Ambi Metal Products Co. Bahrain Partnership Co. - SFB'. Resolved back
	to its OWNING Customer via the core Party Account child table (Account -> Party Account.account
	-> Party Account.parent) -- the same link ERPNext itself uses to find a party's default ledger,
	not a name guess (Customer.epromise_acc_code is blank on every one of these, a separate,
	smaller gap this does not attempt to fix). Two batched queries for the whole set, never one per
	vr_no."""
	accounts = frappe.get_all("Account", filters={"account_number": ["in", list(vr_nos)]}, fields=["name", "account_number"])
	account_to_vr = {a.name: a.account_number for a in accounts}
	if not account_to_vr:
		return {}
	out = {}
	for r in frappe.get_all(
		"Party Account",
		filters={"account": ["in", list(account_to_vr.keys())], "parenttype": "Customer"},
		fields=["account", "parent"],
	):
		vr = account_to_vr.get(r.account)
		if vr:
			out.setdefault(vr, []).append(("Customer", r.parent))
	return out


#: trc -> (batched resolver, display doctype for an unmatched/duplicate row). Checked BEFORE
#: ROUTING in both _classify and _classify_bulk -- these are master records, not vouchers, so none
#: of ROUTING's epromise_vr matching, docstatus-cancelled exclusion, or date tie-break applies;
#: each vr_no is expected to resolve to exactly one record via a completely different link.
SPECIAL_BULK_RESOLVERS = {"EMP": _resolve_emp_bulk, "RHD": _resolve_rhd_bulk}
SPECIAL_DISPLAY_DOCTYPE = {"EMP": "Employee", "RHD": "Customer"}


PREVIEWABLE_EXT = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
	".gif": "image/gif", ".webp": "image/webp", ".pdf": "application/pdf"}

MAX_PREVIEW_BYTES = 8 * 1024 * 1024

# amount field to compare against the ePromise voucher's LOCAL_CUR_AMT when fuzzy-suggesting a
# manual-pick target -- date field is posting_date on every one of these doctypes.
AMOUNT_FIELD = {
	"Sales Invoice": "grand_total", "Purchase Invoice": "grand_total", "Purchase Receipt": "grand_total",
	"Payment Entry": "paid_amount", "Journal Entry": "total_debit",
}

# header-level party name field to fuzzy-compare against the voucher's own payee/supplier name.
# Journal Entry has no single header party field (party lives per accounting row) -- skipped.
PARTY_FIELD = {
	"Sales Invoice": "customer_name", "Purchase Invoice": "supplier_name",
	"Purchase Receipt": "supplier_name", "Payment Entry": "party_name",
}


def _party_similarity(a, b):
	"""0-1 fuzzy string similarity (difflib, no extra dependency) between two party names,
	case/space-insensitive. Either side blank -> None (no signal, not a zero score)."""
	a, b = (a or "").strip().lower(), (b or "").strip().lower()
	if not a or not b:
		return None
	return difflib.SequenceMatcher(None, a, b).ratio()


def _confidence_tier(amount_diff, target_amount, date_diff, party_score):
	"""Roll amount/date/party closeness into one at-a-glance tier for the fuzzy suggestion list.
	Amount is the dominant signal (an exact-ish amount match on a legacy cash/petty-cash ledger is
	rarely a coincidence); party name only available for some doctypes (see PARTY_FIELD) so it can
	only raise a tier, never the sole reason for "high"."""
	amount_pct = (amount_diff / target_amount) if target_amount else (1 if amount_diff else 0)
	strong_amount = amount_diff <= 0.01 or amount_pct <= 0.01
	close_amount = amount_diff <= 0.5 or amount_pct <= 0.05
	strong_party = party_score is not None and party_score >= 0.7

	if strong_amount and date_diff <= 3:
		return "high"
	if (strong_amount and date_diff <= 15) or (close_amount and date_diff <= 5) or (close_amount and strong_party):
		return "medium"
	return "low"


def _find_attached_file(doctype, docname, attachment_filename):
	"""Frappe's own save_file() renames on a naming collision to "{name}{6-char-hash-suffix}{ext}"
	(frappe/core/doctype/file/utils.py: get_content_hash() -> md5, get_file_name() splices
	content_hash[-6:] between the name and extension) -- so an EXACT file_name match misses every
	file that collided with an existing name on disk, which is common (many rows share a filename
	like "Scan.pdf"). Match by the same name/extension split instead, allowing anything in between.
	Returns the File docname, or None."""
	partial, extn = os.path.splitext(attachment_filename or "")
	return frappe.db.get_value(
		"File",
		{
			"attached_to_doctype": doctype, "attached_to_name": docname,
			"file_name": ["like", f"{partial}%{extn}"],
		},
		"name",
	)


def _file_already_attached(doctype, docname, attachment_filename):
	return bool(_find_attached_file(doctype, docname, attachment_filename))


def _log_action(action, doctype, docname, trc_code, vr_no, attachment_filename, file_name):
	frappe.get_doc({
		"doctype": "ePromise Attachment Log", "action": action,
		"target_doctype": doctype, "target_name": docname,
		"trc_code": trc_code, "vr_no": vr_no,
		"attachment_filename": attachment_filename, "file": file_name,
	}).insert(ignore_permissions=True)


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
	party_field = PARTY_FIELD.get(doctype)

	fields = ["name", "posting_date", f"{amount_field} as amount"]
	if party_field:
		fields.append(f"{party_field} as party")

	rows = frappe.get_all(
		doctype,
		filters={"posting_date": ["between", [window_start, window_end]], "docstatus": 1},
		fields=fields,
		limit=500,
	)

	target_amount = frappe.utils.flt(voucher.get("amount"))
	voucher_party = voucher.get("payee_name") or voucher.get("supplier_name") or voucher.get("acc_name")
	tier_rank = {"high": 0, "medium": 1, "low": 2}
	for r in rows:
		r["amount_diff"] = abs(frappe.utils.flt(r["amount"]) - target_amount)
		r["date_diff"] = abs((frappe.utils.getdate(r["posting_date"]) - vr_date).days)
		r["party_score"] = _party_similarity(voucher_party, r.get("party")) if party_field else None
		r["confidence"] = _confidence_tier(r["amount_diff"], target_amount, r["date_diff"], r["party_score"])
	rows.sort(key=lambda r: (tier_rank[r["confidence"]], r["amount_diff"], r["date_diff"]))

	return {"voucher": voucher, "candidates": rows[: frappe.utils.cint(limit) or 10]}


def _get_candidate_dates(doctype, names):
	"""posting_date for each of these already-submitted candidate docs, one batched query."""
	if not names:
		return {}
	return {
		r.name: r.posting_date
		for r in frappe.get_all(doctype, filters={"name": ["in", names]}, fields=["name", "posting_date"])
	}


def _resolve_ties_by_date(matches, source_vr_date):
	"""matches: list of (doctype, name), already docstatus!=2 filtered. When more than one remains
	and the ePromise voucher's own date is known, keep only whichever candidate(s) sit closest to
	it (by posting_date) -- a genuine same-key coincidence across two unrelated documents is rare,
	and the far more common cause of a lingering tie after the docstatus filter is a voucher and a
	near-identical OTHER voucher that happen to reuse the same VR_NO, which real dates tell apart.
	Never narrows past an honest tie: if the closest date is shared by more than one candidate (or
	no date is known for any of them), the original list comes back unchanged -- this only ever
	REMOVES candidates it has positive date evidence against, never picks a winner by coin flip."""
	if len(matches) <= 1 or not source_vr_date:
		return matches
	source_date = frappe.utils.getdate(source_vr_date)

	dates = {}
	by_doctype = {}
	for doctype, name in matches:
		by_doctype.setdefault(doctype, []).append(name)
	for doctype, names in by_doctype.items():
		for name, posting_date in _get_candidate_dates(doctype, names).items():
			dates[(doctype, name)] = posting_date

	scored = [
		(abs((frappe.utils.getdate(dates[(d, n)]) - source_date).days), d, n)
		for d, n in matches if dates.get((d, n))
	]
	if not scored:
		return matches

	best_diff = min(s[0] for s in scored)
	tied = [(d, n) for diff, d, n in scored if diff == best_diff]
	return tied if 0 < len(tied) < len(matches) else matches


def _classify(trc, vr_no, vr_date=None):
	"""Single-row classify: return (doctype_or_None, status, matched_name_or_None, candidates).
	Used by the single-row actions (attach_row/detach_row). For scanning many rows at once (the
	table/status-bar), use _classify_bulk() instead -- see its docstring for why.

	Two migration eras coexist across sites (confirmed live on sft-uat, 2026-09-27): the CURRENT
	importer writes separate epromise_trc_code + epromise_vr_no fields, but an EARLIER era (still
	the only one populated on sft-uat: 24116 Sales Invoice / 1014 Purchase Invoice / 1008 Purchase
	Receipt / 1113 Payment Entry / 3302 Journal Entry rows, split fields either absent or 100%
	empty) wrote a single combined `epromise_vr` field as "{TRC}|{VR_NO}" instead. Try the split
	pair first, then fall back to the legacy combined field before giving up -- never guess which
	era a given site is on.

	ROUTING now maps a trc to a LIST of candidate doctypes (003/004 can be either Payment Entry or
	Journal Entry -- see ROUTING's own docstring); every candidate is searched and every match
	collected before deciding clean/unmatched/duplicate, across doctypes.

	2026-09-28, client call: a cancelled document (docstatus=2) must never count as a match -- an
	amended voucher (cancel + resubmit with a "-1" suffix) otherwise pairs its own cancelled
	original against its live replacement under the exact same epromise_vr key, reading as a false
	"duplicate" (confirmed live: 025's own JE ACC-JV-2026-04250 cancelled + ACC-JV-2026-04250-1
	live, same key). vr_date, when given, additionally breaks a genuine remaining tie by date
	proximity -- see _resolve_ties_by_date.

	EMP/RHD are checked FIRST, ahead of ROUTING entirely -- see SPECIAL_BULK_RESOLVERS's own
	docstring for why they need a structurally different lookup (a master record, not a voucher)."""
	if trc in SPECIAL_BULK_RESOLVERS:
		matches = SPECIAL_BULK_RESOLVERS[trc]([vr_no]).get(vr_no, [])
		if not matches:
			return SPECIAL_DISPLAY_DOCTYPE[trc], "unmatched", None, []
		if len(matches) > 1:
			return matches[0][0], "duplicate", None, [{"doctype": d, "name": n} for d, n in matches]
		doctype, name = matches[0]
		return doctype, "clean", name, []

	doctypes = ROUTING.get(trc)
	if not doctypes:
		return None, "out_of_scope", None, []

	all_matches = []
	fields_missing_doctypes = set()
	for doctype in doctypes:
		meta = frappe.get_meta(doctype)
		has_split = meta.has_field("epromise_trc_code") and meta.has_field("epromise_vr_no")
		has_legacy = meta.has_field("epromise_vr")

		if not has_split and not has_legacy:
			# the migration importer for THIS candidate doctype has never run on this site at all
			# -- the custom fields only get created when that importer actually runs, not via
			# bench migrate. Other candidates for this trc are still checked below.
			fields_missing_doctypes.add(doctype)
			continue

		matches = []
		if has_split:
			matches = frappe.get_all(
				doctype,
				filters={"epromise_trc_code": trc, "epromise_vr_no": vr_no, "docstatus": ["!=", 2]},
				pluck="name",
			)
		if not matches and has_legacy:
			matches = frappe.get_all(
				doctype, filters={"epromise_vr": f"{trc}|{vr_no}", "docstatus": ["!=", 2]}, pluck="name"
			)
		all_matches.extend((doctype, name) for name in matches)

	if not all_matches:
		if fields_missing_doctypes == set(doctypes):
			return doctypes[0], "fields_missing", None, []
		return doctypes[0], "unmatched", None, []

	all_matches = _resolve_ties_by_date(all_matches, vr_date)

	if len(all_matches) > 1:
		return all_matches[0][0], "duplicate", None, [{"doctype": d, "name": n} for d, n in all_matches]

	doctype, name = all_matches[0]
	return doctype, "clean", name, []


def _classify_bulk(pairs, vr_dates=None):
	"""Classify many (trc, vr) pairs in a FIXED number of queries (2 per involved doctype: split
	fields + legacy fallback) instead of _classify()'s 1-2 queries PER PAIR. get_rows() scans every
	attachment row on every page load/refresh (often 1000s of rows) -- calling _classify() in that
	loop was the actual cause of the page feeling slow/hung: a few thousand synchronous MySQL round
	trips per refresh. Returns {(trc, vr): (doctype, status, matched_name, candidates)}.

	A trc can route to MULTIPLE candidate doctypes (003/004 -- see ROUTING's own docstring), so
	each candidate doctype is queried across every pair that lists it, and matches from every
	candidate are merged per pair before deciding clean/unmatched/duplicate/fields_missing.

	vr_dates: optional {(trc, vr): vr_date} -- get_rows() already has each row's own ePromise
	voucher date on hand, so it's passed straight through here to break a still-remaining tie by
	date proximity (see _resolve_ties_by_date) rather than this function re-fetching it. Cancelled
	documents (docstatus=2) are excluded from matches outright, not merely tie-broken -- see
	_classify's own docstring for why (an amended voucher's cancelled original vs. its live
	replacement).

	EMP/RHD pairs are split off and resolved via SPECIAL_BULK_RESOLVERS entirely separately, before
	any of the ROUTING/epromise_vr/docstatus/date-tiebreak machinery below ever sees them -- see
	that dict's own docstring for why."""
	vr_dates = vr_dates or {}
	result = {}

	special_vrs_by_trc = {}
	routed_pairs = []
	for trc, vr in pairs:
		if trc in SPECIAL_BULK_RESOLVERS:
			special_vrs_by_trc.setdefault(trc, set()).add(vr)
		else:
			routed_pairs.append((trc, vr))

	for trc, vr_set in special_vrs_by_trc.items():
		matches_by_vr = SPECIAL_BULK_RESOLVERS[trc](vr_set)
		display_doctype = SPECIAL_DISPLAY_DOCTYPE[trc]
		for vr in vr_set:
			matches = matches_by_vr.get(vr, [])
			if not matches:
				result[(trc, vr)] = (display_doctype, "unmatched", None, [])
			elif len(matches) > 1:
				result[(trc, vr)] = (matches[0][0], "duplicate", None, [{"doctype": d, "name": n} for d, n in matches])
			else:
				result[(trc, vr)] = (matches[0][0], "clean", matches[0][1], [])

	candidate_doctypes_by_pair = {}
	pairs_by_doctype = {}
	for trc, vr in routed_pairs:
		doctypes = ROUTING.get(trc)
		if not doctypes:
			result[(trc, vr)] = (None, "out_of_scope", None, [])
			candidate_doctypes_by_pair[(trc, vr)] = None
			continue
		candidate_doctypes_by_pair[(trc, vr)] = doctypes
		for doctype in doctypes:
			pairs_by_doctype.setdefault(doctype, set()).add((trc, vr))

	matches_by_pair = {}
	fields_missing_doctypes_by_pair = {}

	for doctype, trc_vr_set in pairs_by_doctype.items():
		meta = frappe.get_meta(doctype)
		has_split = meta.has_field("epromise_trc_code") and meta.has_field("epromise_vr_no")
		has_legacy = meta.has_field("epromise_vr")

		if not has_split and not has_legacy:
			for pair in trc_vr_set:
				fields_missing_doctypes_by_pair.setdefault(pair, set()).add(doctype)
			continue

		found_by_pair = {}

		if has_split:
			vr_list = sorted({vr for _, vr in trc_vr_set})
			for r in frappe.get_all(
				doctype,
				filters={
					"epromise_vr_no": ["in", vr_list], "epromise_trc_code": ["not in", ["", None]],
					"docstatus": ["!=", 2],
				},
				fields=["name", "epromise_trc_code", "epromise_vr_no"],
			):
				key = (r.epromise_trc_code, r.epromise_vr_no)
				if key in trc_vr_set:
					found_by_pair.setdefault(key, []).append(r.name)

		if has_legacy:
			still_missing = trc_vr_set - found_by_pair.keys()
			if still_missing:
				legacy_to_pair = {f"{trc}|{vr}": (trc, vr) for trc, vr in still_missing}
				for r in frappe.get_all(
					doctype,
					filters={"epromise_vr": ["in", list(legacy_to_pair.keys())], "docstatus": ["!=", 2]},
					fields=["name", "epromise_vr"],
				):
					pair = legacy_to_pair.get(r.epromise_vr)
					if pair:
						found_by_pair.setdefault(pair, []).append(r.name)

		for pair, names in found_by_pair.items():
			matches_by_pair.setdefault(pair, []).extend((doctype, n) for n in names)

	for trc, vr in routed_pairs:
		pair = (trc, vr)
		doctypes = candidate_doctypes_by_pair[pair]
		if doctypes is None:
			continue  # already set to out_of_scope above

		matches = matches_by_pair.get(pair, [])
		if not matches:
			missing = fields_missing_doctypes_by_pair.get(pair, set())
			if missing == set(doctypes):
				result[pair] = (doctypes[0], "fields_missing", None, [])
			else:
				result[pair] = (doctypes[0], "unmatched", None, [])
			continue

		matches = _resolve_ties_by_date(matches, vr_dates.get(pair))

		if len(matches) > 1:
			result[pair] = (matches[0][0], "duplicate", None, [{"doctype": d, "name": n} for d, n in matches])
		else:
			result[pair] = (matches[0][0], "clean", matches[0][1], [])

	return result


def _bulk_already_attached(clean_lookups):
	"""clean_lookups: iterable of (doctype, docname, attachment_filename). Returns the subset
	(as a set of the same tuples) that already have a matching File, using ONE query per doctype
	(IN on docname) instead of one query per row -- see _find_attached_file for why the match is
	by name/extension split, not exact filename."""
	by_doc = {}
	for doctype, docname, fname in clean_lookups:
		by_doc.setdefault((doctype, docname), []).append(fname)
	if not by_doc:
		return set()

	files_by_docname = {}
	for doctype in {d for d, _ in by_doc}:
		docnames = sorted({dn for d, dn in by_doc if d == doctype})
		for f in frappe.get_all(
			"File", filters={"attached_to_doctype": doctype, "attached_to_name": ["in", docnames]},
			fields=["attached_to_name", "file_name"],
		):
			files_by_docname.setdefault((doctype, f.attached_to_name), []).append(f.file_name)

	already = set()
	for (doctype, docname), fnames in by_doc.items():
		existing = files_by_docname.get((doctype, docname), [])
		for fname in fnames:
			partial, extn = os.path.splitext(fname or "")
			if any(ef.startswith(partial) and ef.endswith(extn) for ef in existing):
				already.add((doctype, docname, fname))
	return already


@frappe.whitelist()
def get_rows(trc_code=None, status=None, search=None, from_date=None, to_date=None,
		target_doctype=None, limit_start=0, limit_page_length=50):
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

	pairs = [((row["TRC_CODE"] or "").strip(), str(row["VR_NO"]).strip()) for row in all_rows]
	vr_dates = {pair: row["vr_date"] for row, pair in zip(all_rows, pairs)}
	match_index = _classify_bulk(set(pairs), vr_dates=vr_dates)

	clean_lookups = []
	for row, pair in zip(all_rows, pairs):
		doctype, row_status, matched_name, candidates = match_index[pair]
		if row_status == "clean":
			clean_lookups.append((doctype, matched_name, row["ATTACHMENT"]))
	already_attached = _bulk_already_attached(clean_lookups)

	counts = {"clean": 0, "attached": 0, "unmatched": 0, "duplicate": 0,
		"out_of_scope": 0, "fields_missing": 0}
	out = []
	for row, pair in zip(all_rows, pairs):
		trc, vr = pair
		doctype, row_status, matched_name, candidates = match_index[pair]

		if row_status == "clean" and (doctype, matched_name, row["ATTACHMENT"]) in already_attached:
			row_status = "attached"

		if target_doctype and doctype != target_doctype:
			continue

		# counts reflect every trc_code/search/date/target_doctype filter but are tallied across
		# ALL statuses regardless of the `status` filter, so the summary bar always shows the full
		# breakdown no matter which status tab is currently selected.
		counts[row_status] = counts.get(row_status, 0) + 1

		if status and status != "all" and row_status != status:
			continue

		out.append({
			"fy_code": row["FY_CODE"], "trc_code": trc, "vr_no": vr,
			"attachment": row["ATTACHMENT"], "vr_date": row["vr_date"],
			"blob_size": row["blob_size"], "doctype": doctype, "status": row_status,
			"matched_name": matched_name, "candidates": candidates,
		})

	counts["total"] = sum(counts.values())
	total = len(out)
	page = out[limit_start:limit_start + limit_page_length]
	return {"rows": page, "total": total, "counts": counts}


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


def _attachment_vr_date(fy_code, trc_code, vr_no):
	"""The ePromise voucher's own date for this attachment row, straight from ATTACHMENT_DETAIL --
	used to break a same-key tie by date proximity (see _resolve_ties_by_date). Single-row actions
	(attach_row/detach_row) fetch this on demand rather than carrying it in from the caller, since
	get_rows() already has it in hand for the bulk path and there is no dialog state to thread it
	through here."""
	conn = _get_connection()
	cur = conn.cursor()
	cur.execute(
		"SELECT TOP 1 vr_date FROM ATTACHMENT_DETAIL "
		"WHERE FY_CODE = %(fy)s AND TRC_CODE = %(trc)s AND VR_NO = %(vr)s",
		{"fy": fy_code, "trc": trc_code, "vr": vr_no},
	)
	row = cur.fetchone()
	conn.close()
	return row["vr_date"] if row else None


def _do_attach(doctype, docname, fy_code, trc_code, vr_no, attachment, conn=None):
	"""The actual attach, once doctype/docname are already known. Shared by attach_row (resolves
	its own target via _classify, one attach at a time -- an owned, short-lived MSSQL connection is
	fine there) and bulk_attach, which passes in ONE connection shared across its whole batch
	instead -- see bulk_attach's own docstring for why a connection-per-row was the actual cause of
	a bulk run looking stuck (2026-09-28: measured 1.4s just to OPEN a connection to this MSSQL
	server; at 20 rows/batch that's ~28s of pure connect overhead before a single blob is fetched,
	on a page that gives no in-batch progress feedback -- looked hung, was just badly throttled)."""
	if not frappe.db.exists(doctype, docname):
		frappe.throw(_("{0} {1} does not exist").format(doctype, docname))
	if not frappe.has_permission(doctype, "write", doc=docname):
		frappe.throw(_("No write permission on {0} {1}").format(doctype, docname), frappe.PermissionError)

	if _file_already_attached(doctype, docname, attachment):
		frappe.throw(_("This attachment is already on {0} {1}").format(doctype, docname))

	owns_conn = conn is None
	if owns_conn:
		conn = _get_connection()
	try:
		cur = conn.cursor()
		cur.execute(
			"SELECT TOP 1 imageobject FROM ATTACHMENT_DETAIL "
			"WHERE FY_CODE = %(fy)s AND TRC_CODE = %(trc)s AND VR_NO = %(vr)s AND ATTACHMENT = %(att)s",
			{"fy": fy_code, "trc": trc_code, "vr": vr_no, "att": attachment},
		)
		row = cur.fetchone()
	finally:
		if owns_conn:
			conn.close()

	if not row or not row["imageobject"]:
		frappe.throw(_("Blob not found for this row"))

	f = save_file(attachment, row["imageobject"], doctype, docname, is_private=0, decode=False)
	frappe.db.commit()
	_log_action("Attached", doctype, docname, trc_code, vr_no, attachment, f.name)
	return {"file_url": f.file_url, "doctype": doctype, "docname": docname}


@frappe.whitelist()
def attach_row(fy_code, trc_code, vr_no, attachment, override_doctype=None, override_name=None):
	_check_role()

	if override_doctype and override_name:
		doctype, docname = override_doctype, override_name
	else:
		trc_code, vr_no = (trc_code or "").strip(), str(vr_no).strip()
		vr_date = _attachment_vr_date(fy_code, trc_code, vr_no)
		doctype, status, docname, candidates = _classify(trc_code, vr_no, vr_date=vr_date)
		if status != "clean":
			frappe.throw(_(
				"Row is not a clean single match ({0}) -- pick a target document explicitly."
			).format(status))

	return _do_attach(doctype, docname, fy_code, trc_code, vr_no, attachment)


@frappe.whitelist()
def detach_row(fy_code, trc_code, vr_no, attachment):
	"""Undo: remove the File this row's attachment created, so a wrong auto/manual attach can be
	reversed without going to the target document directly. Logged the same as an attach."""
	_check_role()
	trc_code, vr_no = (trc_code or "").strip(), str(vr_no).strip()
	vr_date = _attachment_vr_date(fy_code, trc_code, vr_no)
	doctype, status, docname, candidates = _classify(trc_code, vr_no, vr_date=vr_date)
	if status not in ("clean", "attached"):
		# even if the split/legacy fields have since changed underneath it, an already-attached
		# row must still resolve to SOME doctype+doc to know what to detach from
		frappe.throw(_("Cannot determine the target document for this row anymore."))

	file_name = _find_attached_file(doctype, docname, attachment)
	if not file_name:
		frappe.throw(_("No attached file found for this row on {0} {1}").format(doctype, docname))

	if not frappe.has_permission(doctype, "write", doc=docname):
		frappe.throw(_("No write permission on {0} {1}").format(doctype, docname), frappe.PermissionError)
	if not frappe.has_permission("File", "delete", doc=file_name):
		frappe.throw(_("No permission to delete this file"), frappe.PermissionError)

	frappe.delete_doc("File", file_name, ignore_permissions=True)
	frappe.db.commit()
	_log_action("Detached", doctype, docname, trc_code, vr_no, attachment, file_name)
	return {"detached": True, "file_name": file_name, "doctype": doctype, "docname": docname}


@frappe.whitelist()
def bulk_attach(trc_code=None, search=None, from_date=None, to_date=None, target_doctype=None, batch_size=20):
	"""Attach one batch of currently-'clean' (unambiguous single-match) rows under the given
	filters, each wrapped in its own try/except so one bad row never aborts the rest. Safe to call
	repeatedly: a row that succeeds flips from 'clean' to 'attached' and drops out of the next
	get_rows(status='clean') scan on its own, so the caller just loops this until processed == 0 --
	no offset/cursor bookkeeping needed. Never touches 'unmatched'/'duplicate' rows -- those still
	need a human to pick a target, which is the entire point of this review page.

	ONE MSSQL connection for the WHOLE batch, reused across every row via _do_attach's conn= param
	-- attach_row (and this function, before 2026-09-28) opened a fresh connection PER ROW, and
	that connect alone measured 1.4s on this box; at the default batch_size=20 that is ~28s of
	pure connection setup before a single blob is even fetched, on a dialog that shows no
	in-batch progress -- a large bulk-attach run (thousands of rows) looked hung, it was just this.
	Also reuses get_rows' own already-computed doctype/matched_name for each row instead of calling
	_classify() a second time -- both calls would resolve identically since this batch's own
	get_rows() call is the one that just produced these exact rows, milliseconds earlier."""
	_check_role()
	batch_size = frappe.utils.cint(batch_size) or 20

	page = get_rows(trc_code=trc_code, status="clean", search=search, from_date=from_date,
		to_date=to_date, target_doctype=target_doctype, limit_start=0, limit_page_length=batch_size)

	attached, failed = [], []
	conn = _get_connection()
	try:
		for row in page["rows"]:
			try:
				r = _do_attach(
					row["doctype"], row["matched_name"], row["fy_code"], row["trc_code"], row["vr_no"],
					row["attachment"], conn=conn,
				)
				attached.append({"trc_code": row["trc_code"], "vr_no": row["vr_no"],
					"attachment": row["attachment"], "doctype": r["doctype"], "docname": r["docname"],
					"file_url": r["file_url"]})
			except Exception as e:
				frappe.db.rollback()
				failed.append({"trc_code": row["trc_code"], "vr_no": row["vr_no"],
					"attachment": row["attachment"], "error": str(e)[:300]})
	finally:
		conn.close()

	return {"processed": len(page["rows"]), "attached": attached, "failed": failed,
		"remaining_clean_total": page["total"] - len(attached)}


@frappe.whitelist()
def get_thumbnails(rows):
	"""Batched small-preview fetch for the table's optional 'Show Thumbnails' mode -- one round
	trip for the whole visible page instead of one per row. `rows` is a JSON list of
	{fy_code, trc_code, vr_no, attachment, blob_size}. Skips non-image extensions and anything
	over the size cap outright (no point paying for a blob transfer the caller will just discard)."""
	_check_role()
	if isinstance(rows, str):
		rows = frappe.parse_json(rows)

	out = {}
	conn = None
	for row in rows:
		ext = os.path.splitext(row.get("attachment") or "")[1].lower()
		mime = PREVIEWABLE_EXT.get(ext)
		if not mime or mime == "application/pdf" or frappe.utils.cint(row.get("blob_size")) > 150 * 1024:
			continue
		if conn is None:
			conn = _get_connection()
		cur = conn.cursor()
		cur.execute(
			"SELECT TOP 1 imageobject FROM ATTACHMENT_DETAIL "
			"WHERE FY_CODE = %(fy)s AND TRC_CODE = %(trc)s AND VR_NO = %(vr)s AND ATTACHMENT = %(att)s",
			{"fy": row["fy_code"], "trc": row["trc_code"], "vr": row["vr_no"], "att": row["attachment"]},
		)
		r = cur.fetchone()
		if r and r["imageobject"]:
			key = "||".join([row["fy_code"], row["trc_code"], str(row["vr_no"]), row["attachment"]])
			out[key] = {"mime": mime, "data": base64.b64encode(r["imageobject"]).decode("ascii")}
	if conn:
		conn.close()
	return out
