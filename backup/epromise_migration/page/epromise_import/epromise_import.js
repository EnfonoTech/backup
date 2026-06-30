frappe.pages["epromise-import"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: "ePromise Excel Import",
		single_column: true,
	});

	// ── State ────────────────────────────────────────────────────────────────
	let file_url = null;
	let _active_polls = {};

	const SHEETS = [
		{ key: "Customers",         label: "Customers",          doctype: "Customer" },
		{ key: "Suppliers",         label: "Suppliers",          doctype: "Supplier" },
		{ key: "Sales_Invoices",    label: "Sales Invoices",     doctype: "Sales Invoice" },
		{ key: "Purchase_Invoices", label: "Purchase Invoices",  doctype: "Purchase Invoice" },
		{ key: "Payment_Entries",   label: "Payment Entries",    doctype: "Payment Entry" },
		{ key: "Journal_Entries",   label: "Journal Entries",    doctype: "Journal Entry" },
	];

	// ── Layout ───────────────────────────────────────────────────────────────
	$(wrapper).find(".page-content").html(`
		<div class="container" style="max-width:900px;margin-top:20px;">

			<!-- Upload Card -->
			<div class="card mb-4 p-4" style="border-left:4px solid #4299e1;">
				<h5>Step 1 — Upload Excel File</h5>
				<p class="text-muted small mb-3">
					Upload the <code>epromise_export_SFTB_*.xlsx</code> file exported from the staging ERPNext.
					Only <strong>.xlsx</strong> files are accepted.
				</p>
				<div id="upload-area"
					style="border:2px dashed #cbd5e0;border-radius:8px;padding:32px;text-align:center;cursor:pointer;background:#f7fafc;transition:background .2s;">
					<div style="font-size:32px;margin-bottom:8px;">📂</div>
					<div style="font-size:14px;color:#4a5568;">Click to choose file or drag &amp; drop here</div>
					<div style="font-size:11px;color:#a0aec0;margin-top:4px;">Accepts: .xlsx</div>
					<input type="file" id="file-input" accept=".xlsx"
						style="position:absolute;opacity:0;width:0;height:0;">
				</div>
				<div id="file-status" class="mt-3" style="display:none;">
					<span id="file-icon" style="font-size:20px;">📄</span>
					<strong id="file-name" style="margin-left:8px;"></strong>
					<span id="sheet-count" class="text-muted small ml-2"></span>
					<button class="btn btn-xs btn-default ml-3" id="btn-clear-file">✕ Change file</button>
				</div>
			</div>

			<!-- Import Card -->
			<div class="card mb-4 p-4" id="import-card" style="display:none;">
				<h5>Step 2 — Import Sheets (run in order)</h5>
				<p class="text-muted small mb-3">
					Import each sheet in sequence. Each sheet is deduplicated by
					<code>ePromise Acc Code</code> (masters) or <code>ePromise VR No</code> (transactions)
					— already-imported records are skipped automatically.
				</p>
				<div id="sheet-list"></div>

				<div class="mt-4 pt-3" style="border-top:1px solid #e2e8f0;">
					<button class="btn btn-primary" id="btn-import-all">
						⚡ Import All Sheets in Sequence
					</button>
					<span id="status-all" class="ml-3 text-muted small"></span>
				</div>
			</div>

			<!-- Logs Card -->
			<div class="card p-4">
				<h5>Import Logs</h5>
				<p class="text-muted small">View all Excel import logs to monitor progress and review errors.</p>
				<button class="btn btn-default btn-sm" id="btn-view-logs">View Import Logs</button>
			</div>
		</div>
	`);

	// ── Upload Area ───────────────────────────────────────────────────────────
	const upload_area = wrapper.querySelector("#upload-area");
	const file_input  = wrapper.querySelector("#file-input");

	upload_area.addEventListener("click", () => file_input.click());
	upload_area.addEventListener("dragover", e => {
		e.preventDefault();
		upload_area.style.background = "#ebf8ff";
	});
	upload_area.addEventListener("dragleave", () => {
		upload_area.style.background = "#f7fafc";
	});
	upload_area.addEventListener("drop", e => {
		e.preventDefault();
		upload_area.style.background = "#f7fafc";
		const file = e.dataTransfer.files[0];
		if (file) handle_file(file);
	});
	file_input.addEventListener("change", e => {
		const file = e.target.files[0];
		if (file) handle_file(file);
	});

	wrapper.querySelector("#btn-clear-file").onclick = () => {
		file_url = null;
		file_input.value = "";
		wrapper.querySelector("#file-status").style.display = "none";
		wrapper.querySelector("#import-card").style.display = "none";
	};

	function handle_file(file) {
		if (!file.name.endsWith(".xlsx")) {
			frappe.msgprint({ title: "Wrong file type", message: "Please upload an .xlsx file.", indicator: "red" });
			return;
		}
		upload_area.style.background = "#f0fff4";
		upload_area.querySelector("div:nth-child(2)").textContent = "Uploading…";

		frappe.upload_file({
			file_obj: file,
			method: "upload_file",
			type: "private",
			args: {},
			callback(r) {
				upload_area.style.background = "#f7fafc";
				upload_area.querySelector("div:nth-child(2)").textContent = "Click to choose file or drag & drop here";

				if (!r.message || !r.message.file_url) {
					frappe.msgprint({ title: "Upload failed", message: "Could not upload file.", indicator: "red" });
					return;
				}
				file_url = r.message.file_url;
				show_file_info(file.name, file_url);
			},
			error() {
				upload_area.style.background = "#f7fafc";
				upload_area.querySelector("div:nth-child(2)").textContent = "Click to choose file or drag & drop here";
				frappe.msgprint({ title: "Upload error", message: "File upload failed — check console.", indicator: "red" });
			},
		});
	}

	function show_file_info(filename, furl) {
		wrapper.querySelector("#file-name").textContent = filename;
		wrapper.querySelector("#file-status").style.display = "block";
		wrapper.querySelector("#sheet-count").textContent = "Loading sheets…";

		frappe.call({
			method: "backup.epromise_migration.api.get_excel_sheets",
			args: { file_url: furl },
			callback(r) {
				const available = (r.message && r.message.sheets) || [];
				wrapper.querySelector("#sheet-count").textContent =
					`— ${available.length} sheet${available.length !== 1 ? "s" : ""} found`;
				build_sheet_list(available);
				wrapper.querySelector("#import-card").style.display = "block";
			},
		});
	}

	// ── Sheet List ────────────────────────────────────────────────────────────
	function build_sheet_list(available_sheets) {
		const container = wrapper.querySelector("#sheet-list");
		container.innerHTML = "";

		SHEETS.forEach((sheet, idx) => {
			const present = available_sheets.includes(sheet.key);
			const row = document.createElement("div");
			row.id = `sheet-row-${sheet.key}`;
			row.style.cssText = "display:flex;align-items:center;gap:12px;padding:10px 0;border-bottom:1px solid #edf2f7;";
			row.innerHTML = `
				<span style="width:22px;text-align:center;color:#a0aec0;font-size:13px;font-weight:700;">
					${idx + 1}
				</span>
				<span style="flex:1;font-size:13px;font-weight:500;color:${present ? "#2d3748" : "#a0aec0"};">
					${sheet.label}
					${present ? "" : '<span class="text-muted small"> — not in file</span>'}
				</span>
				<span id="status-${sheet.key}" class="text-muted small" style="min-width:260px;text-align:right;"></span>
				<button id="btn-${sheet.key}" class="btn btn-sm btn-primary" ${present ? "" : "disabled"}>
					Import
				</button>
			`;
			container.appendChild(row);

			if (present) {
				row.querySelector(`#btn-${sheet.key}`).onclick = () => {
					run_sheet_import(sheet.key);
				};
			}
		});
	}

	// ── Import Logic ──────────────────────────────────────────────────────────
	function run_sheet_import(sheet_key, on_done) {
		if (!file_url) {
			frappe.msgprint({ title: "No file", message: "Please upload a file first.", indicator: "red" });
			return;
		}

		const btn = wrapper.querySelector(`#btn-${sheet_key}`);
		const status_el = wrapper.querySelector(`#status-${sheet_key}`);
		const orig_text = btn ? btn.textContent : "";

		if (btn) { btn.disabled = true; btn.textContent = "Queuing…"; }
		if (status_el) status_el.innerHTML = '<span style="color:#a0aec0;">⏳ Queuing…</span>';

		frappe.call({
			method: "backup.epromise_migration.api.import_excel_sheet",
			args: { file_url, sheet_name: sheet_key },
			callback(r) {
				if (btn) { btn.disabled = false; btn.textContent = orig_text; }
				if (!r.message) return;

				const { log_name, status } = r.message;
				if (status === "queued") {
					_poll_progress(log_name, status_el, () => {
						if (on_done) on_done();
					});
				}
			},
			error() {
				if (btn) { btn.disabled = false; btn.textContent = orig_text; }
				if (status_el) status_el.innerHTML = '<span style="color:#e53e3e;">Error — check console</span>';
				if (on_done) on_done(true);
			},
		});
	}

	function _poll_progress(log_name, status_el, on_done) {
		if (_active_polls[log_name]) clearInterval(_active_polls[log_name]);

		function refresh() {
			frappe.db.get_value(
				"ePromise Migration Log",
				log_name,
				["status", "success_count", "error_count", "skipped_count", "total_records"],
				data => {
					if (!data) return;
					const { status, success_count, error_count, skipped_count } = data;
					const log_link = `<a href="/app/epromise-migration-log/${log_name}" target="_blank">${log_name}</a>`;

					if (["Running", "Queued"].includes(status)) {
						const done = (success_count || 0) + (error_count || 0) + (skipped_count || 0);
						status_el.innerHTML =
							`<span style="color:#3182ce;">⏳ ${status} — ✅ ${success_count || 0}, ` +
							`❌ ${error_count || 0}, ⏭ ${skipped_count || 0} (${done} done) — ${log_link}</span>`;
					} else {
						clearInterval(_active_polls[log_name]);
						delete _active_polls[log_name];
						const ok = status === "Completed" && (error_count || 0) === 0;
						const icon = status === "Completed" ? (ok ? "✅" : "⚠️") : "❌";
						const color = ok ? "#38a169" : ((error_count || 0) > 0 ? "#d69e2e" : "#e53e3e");
						status_el.innerHTML =
							`<span style="color:${color};">${icon} ${status} — ` +
							`${success_count || 0} created, ${skipped_count || 0} skipped, ` +
							`${error_count || 0} errors — ${log_link}</span>`;
						if (on_done) on_done((error_count || 0) > 0);
					}
				}
			);
		}

		refresh();
		_active_polls[log_name] = setInterval(refresh, 3000);
	}

	// ── Import All ────────────────────────────────────────────────────────────
	wrapper.querySelector("#btn-import-all").onclick = function () {
		const btn = this;
		const status_el = wrapper.querySelector("#status-all");
		btn.disabled = true;

		const available = SHEETS.filter(s =>
			wrapper.querySelector(`#btn-${s.key}`) &&
			!wrapper.querySelector(`#btn-${s.key}`).disabled
		);

		if (!available.length) {
			frappe.msgprint({ title: "Nothing to import", message: "No sheets are available in the uploaded file.", indicator: "orange" });
			btn.disabled = false;
			return;
		}

		status_el.innerHTML = `<span style="color:#4299e1;">Importing ${available.length} sheets in sequence…</span>`;

		let idx = 0;
		function run_next(had_error) {
			if (idx >= available.length) {
				btn.disabled = false;
				const msg = had_error
					? '<span style="color:#d69e2e;">⚠️ All sheets processed — some errors occurred. Check individual logs.</span>'
					: '<span style="color:#38a169;">✅ All sheets imported successfully.</span>';
				status_el.innerHTML = msg;
				frappe.show_alert({ message: "Import sequence complete", indicator: had_error ? "orange" : "green" });
				return;
			}

			const sheet = available[idx++];
			status_el.innerHTML =
				`<span style="color:#4299e1;">Importing ${sheet.label} (${idx}/${available.length})…</span>`;

			run_sheet_import(sheet.key, err => run_next(had_error || err));
		}

		run_next(false);
	};

	// ── Navigation ────────────────────────────────────────────────────────────
	wrapper.querySelector("#btn-view-logs").onclick = () => {
		frappe.set_route("List", "ePromise Migration Log", {
			"migration_type": ["in", [
				"Excel: Customers", "Excel: Suppliers", "Excel: Sales Invoices",
				"Excel: Purchase Invoices", "Excel: Payment Entries", "Excel: Journal Entries",
			]],
		});
	};

	page.add_button("← Back to Migration", () => {
		frappe.set_route("page", "epromise-migration");
	});
};
