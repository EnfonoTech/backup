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


def connect_mssql(settings):
	"""
	Return a pymssql connection using live SQL Server credentials from settings.
	Raises a clear error if credentials are missing or connection fails.
	"""
	import pymssql  # already installed: pymssql 2.3.13

	host = (settings.mssql_host or "").strip()
	port = int(settings.mssql_port or 1433)
	database = (settings.mssql_database or "").strip()
	user = (settings.mssql_username or "").strip()
	password = settings.get_password("mssql_password") or ""

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


def test_mssql_connection(host, port, database, user, password):
	"""
	Standalone connection test — returns (success, message, sample_counts).
	Used from the migration page Test Connection button.
	"""
	import pymssql

	result = {"connected": False, "message": "", "counts": {}}
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

		# Verify dichdata exists and count records
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

		# Check INVOICE_DETAIL
		cur.execute("SELECT COUNT(*) AS cnt FROM INVOICE_DETAIL")
		r = cur.fetchone()
		result["counts"]["invoice_detail"] = r["cnt"] if r else 0

		# Check sales_data
		cur.execute("SELECT COUNT(*) AS cnt FROM sales_data WHERE trc_code IN ('S01','S06')")
		r = cur.fetchone()
		result["counts"]["sales_data"] = r["cnt"] if r else 0

		# Check dicadmas (customer master)
		cur.execute("SELECT COUNT(*) AS cnt FROM dicadmas WHERE ah_code = '1' AND sub_head = 'D'")
		r = cur.fetchone()
		result["counts"]["customers"] = r["cnt"] if r else 0

		conn.close()
		result["connected"] = True
		result["message"] = f"Connected to {database} on {host}:{port}"
	except Exception as e:
		result["message"] = str(e)

	return result
