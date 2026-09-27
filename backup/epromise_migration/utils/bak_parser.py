"""
Parses ePromise SQL Server .bak backup files to extract INSERT statement data.

ePromise embeds SQL INSERT scripts inside the SQL Server backup. The GNU `strings`
utility is used to extract readable text from the binary, then INSERT statements
are parsed into Python dicts — no SQL Server installation required.
"""

import os
import re
import subprocess


# Matches N'...' string literals, numeric values, timestamps, and NULL
_VALUE_TOKEN_RE = re.compile(
	r"N'((?:[^']|'')*)'|'((?:[^']|'')*)'|\{ts\s*'([^']+)'\}|(NULL)|(-?\d+(?:\.\d+)?)",
	re.IGNORECASE,
)


def _parse_values(values_str):
	"""Tokenise a SQL VALUES(...) string into a Python list."""
	result = []
	for m in _VALUE_TOKEN_RE.finditer(values_str):
		nstr, str_, ts, null, num = m.groups()
		if null is not None:
			result.append(None)
		elif nstr is not None:
			result.append(nstr.replace("''", "'"))
		elif str_ is not None:
			result.append(str_.replace("''", "'"))
		elif ts is not None:
			result.append(ts)
		elif num is not None:
			result.append(num)
	return result


def extract_table_rows(bak_file_path, table_name):
	"""
	Pipe the .bak file through `strings`, then yield dicts for every complete
	INSERT row belonging to *table_name* (case-insensitive).

	Yields:
		dict: column_name -> value for each row found
	"""
	if not os.path.exists(bak_file_path):
		raise FileNotFoundError(f"Backup file not found: {bak_file_path}")

	target = table_name.lower()

	# INSERT INTO <table> (<columns>) VALUES (<values>)
	# Column list: no parens allowed; VALUES: anything up to the trailing ' )'
	insert_re = re.compile(
		r"INSERT\s+INTO\s+(\w+)\s*\(([^)]+)\)\s*VALUES\s*\((.+)\)\s*$",
		re.IGNORECASE,
	)

	proc = subprocess.Popen(
		["strings", bak_file_path],
		stdout=subprocess.PIPE,
		stderr=subprocess.DEVNULL,
		bufsize=1 * 1024 * 1024,
	)

	try:
		for raw_line in proc.stdout:
			try:
				line = raw_line.decode("utf-8", errors="replace").rstrip("\n").rstrip("\r")
			except Exception:
				continue

			if not line:
				continue
			if "INSERT" not in line.upper() or target not in line.lower():
				continue

			m = insert_re.match(line)
			if not m:
				continue

			tbl, cols_str, vals_str = m.groups()
			if tbl.lower() != target:
				continue

			columns = [c.strip() for c in cols_str.split(",")]
			values = _parse_values(vals_str)
			if len(columns) != len(values):
				continue

			yield dict(zip(columns, values))
	finally:
		proc.stdout.close()
		proc.wait()


def _get_mssql_credentials(settings):
	"""
	Return (host, port, database, user, password) for the SQL Server connection.

	Priority:
	  1. site_config.json keys (epromise_mssql_*) — set via `bench set-config`
	     These never appear in database dumps and survive site restores.
	  2. ePromise Settings DocType values (stored encrypted in the DB).

	Set on production with:
	  bench --site [site] set-config epromise_mssql_host    "37.224.24.154"
	  bench --site [site] set-config epromise_mssql_port    14335
	  bench --site [site] set-config epromise_mssql_database "SteelForce_Bahrain_2026"
	  bench --site [site] set-config epromise_mssql_username "sa"
	  bench --site [site] set-config epromise_mssql_password "your-password"
	"""
	import frappe

	conf = frappe.conf  # loaded from site_config.json

	host     = conf.get("epromise_mssql_host")     or (settings.mssql_host or "").strip()
	port     = int(conf.get("epromise_mssql_port") or settings.mssql_port or 1433)
	database = conf.get("epromise_mssql_database") or (settings.mssql_database or "").strip()
	user     = conf.get("epromise_mssql_username") or (settings.mssql_username or "").strip()
	password = conf.get("epromise_mssql_password") or settings.get_password("mssql_password") or ""

	return host, port, database, user, password


def connect_mssql(settings):
	"""
	Return a pymssql connection.

	Credentials are resolved via _get_mssql_credentials():
	  site_config.json (epromise_mssql_*) overrides ePromise Settings DB values.
	"""
	import pymssql

	host, port, database, user, password = _get_mssql_credentials(settings)

	if not host:
		raise ValueError("ePromise Settings: SQL Server Host is required for live connection.")
	if not database:
		raise ValueError("ePromise Settings: Database Name is required for live connection.")
	if not user:
		raise ValueError("ePromise Settings: Username is required for live connection.")

	last_err = None
	for attempt in range(1, 4):   # up to 3 attempts
		try:
			conn = pymssql.connect(
				server=host,
				port=port,
				database=database,
				user=user,
				password=password,
				as_dict=True,
				login_timeout=30,
				timeout=600,
				charset="UTF-8",
			)
			return conn
		except pymssql.OperationalError as e:
			last_err = e
			import time
			time.sleep(5 * attempt)   # 5s, 10s, 15s back-off
	raise ConnectionError(
		f"Cannot connect to SQL Server at {host}:{port} database={database} "
		f"after 3 attempts. Check credentials and ensure port {port} is reachable. "
		f"Error: {last_err}"
	) from last_err


def _probe_transactional_schema(cur, result):
	"""dichdata-family checks -- the main ePromise transactional database."""
	cur.execute("""
		SELECT
			SUM(CASE WHEN trc_code = 'S01' THEN 1 ELSE 0 END) AS s01_count,
			SUM(CASE WHEN trc_code = 'S06' THEN 1 ELSE 0 END) AS s06_count,
			SUM(CASE WHEN trc_code IN ('S01','S06') AND posted_ind = 'Y' THEN 1 ELSE 0 END) AS submitted,
			COUNT(*) AS total
		FROM dichdata
		WHERE trc_code IN ('S01', 'S06')
	""")
	row = cur.fetchone()
	result["counts"]["dichdata"] = dict(row) if row else {}

	cur.execute("SELECT COUNT(*) AS cnt FROM INVOICE_DETAIL")
	r = cur.fetchone()
	result["counts"]["invoice_detail"] = r["cnt"] if r else 0

	cur.execute("SELECT COUNT(*) AS cnt FROM sales_data WHERE trc_code IN ('S01','S06')")
	r = cur.fetchone()
	result["counts"]["sales_data"] = r["cnt"] if r else 0

	cur.execute("SELECT COUNT(*) AS cnt FROM dicadmas WHERE ah_code = '1' AND sub_head = 'D'")
	r = cur.fetchone()
	result["counts"]["customers"] = r["cnt"] if r else 0


def _probe_attachment_schema(cur, result):
	"""ATTACHMENT_DETAIL -- the separate per-year Attachment_<Company> database (file blobs
	for cash payments/purchase bills/etc, keyed by FY_CODE+TRC_CODE+VR_NO -- same voucher key
	as dichdata, just a different database on the same SQL Server instance)."""
	cur.execute("SELECT COUNT(*) AS cnt FROM ATTACHMENT_DETAIL")
	r = cur.fetchone()
	result["counts"]["attachment_detail"] = r["cnt"] if r else 0

	cur.execute("SELECT COUNT(*) AS cnt FROM ATTACHMENT_DETAIL WHERE imageobject IS NOT NULL")
	r = cur.fetchone()
	result["counts"]["attachment_detail_with_file"] = r["cnt"] if r else 0

	cur.execute("SELECT COUNT(*) AS cnt FROM ATTACHMENT_DETAIL WHERE TRC_CODE = 'EMP'")
	r = cur.fetchone()
	result["counts"]["attachment_detail_employee_docs"] = r["cnt"] if r else 0


def test_mssql_connection(host, port, database, user, password):
	"""
	Standalone connection test — returns (success, message, sample_counts).
	Used from the migration page Test Connection button.

	Schema-aware: an ePromise SQL Server instance hosts BOTH the transactional database
	(dichdata) and a separate per-company Attachment_* database (ATTACHMENT_DETAIL) for file
	blobs. Which one is "correct" depends on what this Settings record is being used for right
	now -- this used to hard-fail with a raw "Invalid object name 'dichdata'" the moment someone
	pointed Database Name at an Attachment_* database to pull files, even though that connection
	is completely valid for THAT purpose. Detect which schema is actually present and report the
	matching counts instead of assuming transactional.
	"""
	import pymssql

	result = {"connected": False, "message": "", "counts": {}, "schema": None}
	try:
		conn = pymssql.connect(
			server=host,
			port=int(port or 1433),
			database=database,
			user=user,
			password=password,
			as_dict=True,
			login_timeout=10,
		)
		cur = conn.cursor()

		cur.execute("""
			SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES
			WHERE TABLE_NAME IN ('dichdata', 'ATTACHMENT_DETAIL')
		""")
		available = {r["TABLE_NAME"].lower() for r in cur.fetchall()}

		if "dichdata" in available:
			result["schema"] = "transactional"
			_probe_transactional_schema(cur, result)
		elif "attachment_detail" in available:
			result["schema"] = "attachment"
			_probe_attachment_schema(cur, result)
		else:
			conn.close()
			result["message"] = (
				f"Connected to {database} on {host}:{port}, but it has neither dichdata "
				"(the ePromise transactional database) nor ATTACHMENT_DETAIL (an Attachment_* "
				"database) -- check the Database Name."
			)
			return result

		conn.close()
		result["connected"] = True
		result["message"] = f"Connected to {database} on {host}:{port}"
	except Exception as e:
		result["message"] = str(e)

	return result
