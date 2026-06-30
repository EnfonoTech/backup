frappe.pages["epromise-migration"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: "ePromise Migration",
		single_column: true,
	});

	$(wrapper).find(".page-content").html(`
		<div class="container" style="max-width:960px;margin-top:20px;">

			<!-- Settings Card -->
			<div class="card mb-4 p-4">
				<h5>Settings</h5>
				<p class="text-muted small mb-2">
					Configure either a <strong>Live SQL Server connection</strong> (recommended — exact amounts &amp; items)
					or a <strong>Backup file path</strong> (.bak file).
				</p>
				<button class="btn btn-default btn-sm" id="btn-open-settings">
					Open ePromise Settings
				</button>
				<button class="btn btn-default btn-sm ml-2" id="btn-test-conn">
					Test Live Connection
				</button>
				<div id="conn-result" class="mt-3"></div>
			</div>

			<!-- Date Range Card -->
			<div class="card mb-4 p-4" style="border-left:4px solid #4299e1;">
				<h5>📅 Import Date Range</h5>
				<p class="text-muted small mb-2">
					All import steps use this date range. Dates are saved to <strong>ePromise Settings</strong>.
					<strong style="color:#e53e3e;">From date must be ≤ To date.</strong>
				</p>
				<div style="display:flex;gap:16px;align-items:flex-end;flex-wrap:wrap;">
					<div>
						<label class="text-muted small" style="display:block;margin-bottom:4px;">From Date</label>
						<input type="date" id="date-from"
							style="padding:6px 10px;border:1px solid #cbd5e0;border-radius:6px;font-size:13px;min-width:140px;">
					</div>
					<div>
						<label class="text-muted small" style="display:block;margin-bottom:4px;">To Date</label>
						<input type="date" id="date-to"
							style="padding:6px 10px;border:1px solid #cbd5e0;border-radius:6px;font-size:13px;min-width:140px;">
					</div>
					<button class="btn btn-primary btn-sm" id="btn-save-dates">
						Apply &amp; Save Dates
					</button>
					<span id="date-save-status" class="text-muted small"></span>
				</div>
				<div id="date-warning" style="display:none;color:#e53e3e;font-size:12px;margin-top:8px;font-weight:600;">
					⚠ From date is after To date — please correct before importing.
				</div>
			</div>

			<!-- Field Mapping Config -->
			<div class="card mb-4 p-4">
				<h5>Field Mapping Configuration</h5>
				<p class="text-muted small">Define which ePromise fields map to ERPNext fields. Pre-seeded with defaults.</p>
				<button class="btn btn-default btn-sm" id="btn-seed-mappings">Seed Default Mappings</button>
				<button class="btn btn-default btn-sm ml-2" id="btn-view-mappings">View / Edit Mappings</button>
				<span id="status-mappings" class="ml-3 text-muted small"></span>
			</div>

			<!-- Customer Import -->
			<div class="card mb-4 p-4">
				<h5>Step 1a — Import Customer Master</h5>
				<p class="text-muted small">
					Source: <code>DICADMAS</code> (sub_head = D). Auto-creates customers not in ERPNext.
					Links existing customers by name if already present.
				</p>
				<button class="btn btn-primary btn-sm" id="btn-import-customers">
					Import Customers
				</button>
				<span id="status-customers" class="ml-3 text-muted small"></span>
			</div>

			<!-- Supplier Import -->
			<div class="card mb-4 p-4">
				<h5>Step 1b — Import Supplier Master</h5>
				<p class="text-muted small">
					Source: <code>DICADMAS</code> (sub_head = C). Auto-creates suppliers not in ERPNext.
					Links existing suppliers by name if already present. Run before Purchase Receipts/Invoices.
				</p>
				<button class="btn btn-primary btn-sm" id="btn-import-suppliers">
					Import Suppliers
				</button>
				<span id="status-suppliers" class="ml-3 text-muted small"></span>
			</div>

			<!-- Item Master Import -->
			<div class="card mb-4 p-4">
				<h5>Step 1c — Import Item Master</h5>
				<p class="text-muted small">
					Reads <strong>Copy of Bahrain Master 16.6.26 (1) (1).xls</strong> (must be in <code>apps/backup/</code>).
					Creates Items using <strong>Unified Code</strong> as <code>item_code</code>.
					Already-existing items are skipped. Run before importing invoices or receipts.
				</p>
				<button class="btn btn-primary btn-sm" id="btn-import-items">
					Import Item Master
				</button>
				<span id="status-items" class="ml-3 text-muted small"></span>
			</div>

			<!-- Invoice Import -->
			<div class="card mb-4 p-4">
				<h5>Step 2 — Import Sales Invoices</h5>
				<div class="row mb-2">
					<div class="col-sm-6">
						<div class="alert alert-success p-2 small mb-0">
							<strong>Live SQL Server mode</strong><br>
							✅ Exact amounts from <code>dichdata.acc_amt</code><br>
							✅ Full items from <code>INVOICE_DETAIL</code> (S01) + <code>sales_data</code> (S06)<br>
							✅ All invoices — no gaps
						</div>
					</div>
					<div class="col-sm-6">
						<div class="alert alert-warning p-2 small mb-0">
							<strong>Backup file mode</strong><br>
							⚠️ Amounts available only for INSERT-statement invoices<br>
							⚠️ Binary-page invoices get amount = 0<br>
							⚠️ Items limited to what's in sales_data
						</div>
					</div>
				</div>
				<p class="text-muted small">
					Date range: set in <em>ePromise Settings → Invoice From/To Date</em>.
					S01 = <strong>Credit Invoice</strong> (series ACC-SINV-CR-),
					S06 = <strong>POS Invoice</strong> (series ACC-SINV-POS-).
				</p>
				<button class="btn btn-primary btn-sm" id="btn-import-invoices">
					Import Sales Invoices
				</button>
				<span id="status-invoices" class="ml-3 text-muted small"></span>
			</div>

			<!-- Sales Returns -->
			<div class="card mb-4 p-4">
				<h5>Step 2b — Import Sales Returns</h5>
				<p class="text-muted small">
					TRC R01 = <strong>Credit Sales Return</strong>, R04 = <strong>Cash(POS) Sales Return</strong>.
					Creates Sales Invoices with <code>is_return=1</code> (Credit Notes). Run after Step 2.
				</p>
				<button class="btn btn-primary btn-sm" id="btn-import-sales-returns">
					Import Sales Returns
				</button>
				<span id="status-sales-returns" class="ml-3 text-muted small"></span>
			</div>

			<!-- Purchase Receipt -->
			<div class="card mb-4 p-4">
				<h5>Step 3 — Import Purchase Receipts (GRN)</h5>
				<p class="text-muted small">
					TRC <strong>GRN</strong> = Goods Receiving Note → Purchase Receipt.<br>
					TRC <strong>GR</strong> = Goods Return → Purchase Receipt (is_return=1) with link to original GRN.<br>
					Items from <code>PURCHASE_DATA</code>. <strong>Run this before Step 4.</strong>
				</p>
				<button class="btn btn-primary btn-sm" id="btn-import-receipts">
					Import Purchase Receipts
				</button>
				<span id="status-receipts" class="ml-3 text-muted small"></span>
			</div>

			<!-- Purchase Invoice Import -->
			<div class="card mb-4 p-4">
				<h5>Step 4 — Import Purchase Invoices</h5>
				<p class="text-muted small">
					TRC <strong>350</strong> = Purchase Invoice Item Wise → Purchase Invoice linked to GRN Receipt (items from <code>PURCHASE_INVOICE_DETAIL</code>).<br>
					TRC <strong>111</strong> = Direct Purchase → standalone Purchase Invoice.<br>
					TRC <strong>IP</strong> = Import Purchase → Purchase Invoice with freight/customs as service items.<br>
					Run after Step 3 so GRN receipts are already in ERPNext.
				</p>
				<button class="btn btn-primary btn-sm" id="btn-import-purchases">
					Import Purchase Invoices
				</button>
				<span id="status-purchases" class="ml-3 text-muted small"></span>
			</div>

			<!-- Purchase Returns -->
			<div class="card mb-4 p-4">
				<h5>Step 4b — Import Purchase Returns</h5>
				<p class="text-muted small">
					TRC <strong>PR</strong> = Purchase Return → Purchase Invoice (is_return=1) with link to original invoice. Run after Step 4.
				</p>
				<button class="btn btn-primary btn-sm" id="btn-import-purchase-returns">
					Import Purchase Returns
				</button>
				<span id="status-purchase-returns" class="ml-3 text-muted small"></span>
			</div>

			<!-- Payment Vouchers -->
			<div class="card mb-4 p-4">
				<h5>Step 5 — Import Payment Vouchers</h5>
				<p class="text-muted small">
					TRC <strong>003</strong> = Cash Payment Voucher → Payment Entry (Pay to Supplier) or Journal Entry (if expense).<br>
					TRC <strong>004</strong> = Cash Receipt Voucher → Payment Entry (Receive from Customer).<br>
					Supplier/customer detected from GL lines in <code>DICADDATA</code>.
					Run after invoices are imported, then use <em>Accounts → Payment Reconciliation</em> to link to invoices.
				</p>
				<button class="btn btn-primary btn-sm" id="btn-import-payments">
					Import Payment Vouchers (003 + 004)
				</button>
				<span id="status-payments" class="ml-3 text-muted small"></span>
			</div>

			<!-- Cash / Journal Vouchers -->
			<div class="card mb-4 p-4">
				<h5>Step 6 — Import Journal &amp; Adjustment Vouchers</h5>
				<p class="text-muted small">
					TRC <strong>020</strong> = Bank/Cash Adjustment, TRC <strong>007</strong> = Journal Voucher → ERPNext Journal Entry.
					GL lines from <code>DICADDATA</code>.
				</p>
				<button class="btn btn-primary btn-sm" id="btn-import-journals">
					Import Journal Vouchers (020 + 007)
				</button>
				<span id="status-journals" class="ml-3 text-muted small"></span>
			</div>

			<!-- Logs -->
			<div class="card p-4">
				<h5>Migration Logs</h5>
				<button class="btn btn-default btn-sm" id="btn-view-logs">View Logs</button>
			</div>
		</div>
	`);

	// ── Navigation ────────────────────────────────────────────────────────────
	wrapper.querySelector("#btn-open-settings").onclick = () =>
		frappe.set_route("Form", "ePromise Settings");
	wrapper.querySelector("#btn-view-logs").onclick = () =>
		frappe.set_route("List", "ePromise Migration Log");
	wrapper.querySelector("#btn-view-mappings").onclick = () =>
		frappe.set_route("List", "ePromise Field Mapping");

	// ── Date Range — load from settings, save back ─────────────────────────────
	function load_date_range() {
		frappe.db.get_value("ePromise Settings", "ePromise Settings",
			["invoice_from_date", "invoice_to_date"], (data) => {
				if (data) {
					if (data.invoice_from_date)
						document.getElementById("date-from").value = data.invoice_from_date;
					if (data.invoice_to_date)
						document.getElementById("date-to").value = data.invoice_to_date;
				}
			}
		);
	}

	function check_date_order() {
		const f = document.getElementById("date-from").value;
		const t = document.getElementById("date-to").value;
		const warn = document.getElementById("date-warning");
		if (f && t && f > t) {
			warn.style.display = "block";
			return false;
		}
		warn.style.display = "none";
		return true;
	}

	document.getElementById("date-from").addEventListener("change", check_date_order);
	document.getElementById("date-to").addEventListener("change", check_date_order);

	document.getElementById("btn-save-dates").onclick = function () {
		if (!check_date_order()) {
			frappe.msgprint({
				title: "Invalid Date Range",
				message: "From date cannot be after To date.",
				indicator: "red",
			});
			return;
		}
		const from_date = document.getElementById("date-from").value;
		const to_date   = document.getElementById("date-to").value;
		const status_el = document.getElementById("date-save-status");
		status_el.textContent = "Saving…";
		frappe.db.set_value("ePromise Settings", "ePromise Settings", {
			invoice_from_date: from_date,
			invoice_to_date:   to_date,
		}).then(() => {
			status_el.innerHTML = '<span style="color:#38a169;">✓ Saved — all imports will use this date range</span>';
			setTimeout(() => status_el.textContent = "", 4000);
		}).catch(() => {
			status_el.innerHTML = '<span style="color:#e53e3e;">Error saving — check permissions</span>';
		});
	};

	load_date_range();

	// ── Live import counts on each step card ──────────────────────────────────
	function load_step_counts() {
		// Each entry: [status_el_id, doctype, filter_field, filter_value(s), label]
		const steps = [
			["status-customers",       "Customer",         "epromise_acc_code",  null,   "Customer"],
			["status-suppliers",       "Supplier",         "epromise_acc_code",  null,   "Supplier"],
			["status-items",           "Item",             "epromise_ite_code",  null,   "Item"],
			["status-invoices",        "Sales Invoice",    "epromise_trc_code",  ["S01","S06"], "Sales Invoice"],
			["status-sales-returns",   "Sales Invoice",    "epromise_trc_code",  ["R01","R04"], "Sales Return"],
			["status-receipts",        "Purchase Receipt", "epromise_trc_code",  ["GRN","GR"],  "Purchase Receipt"],
			["status-purchases",       "Purchase Invoice", "epromise_trc_code",  ["350","111","IP"], "Purchase Invoice"],
			["status-purchase-returns","Purchase Invoice", "epromise_trc_code",  ["PR"], "Purchase Return"],
			["status-payments",        "Payment Entry",    "epromise_trc_code",  ["003","004"], "Payment Entry"],
			["status-journals",        "Journal Entry",    "epromise_trc_code",  ["020","007"], "Journal Entry"],
		];
		steps.forEach(([elId, doctype, field, values, label]) => {
			const el = wrapper.querySelector("#" + elId);
			if (!el) return;
			el.innerHTML = `<span style="color:#a0aec0;font-size:11px;">⏳ checking…</span>`;
			// Build filter
			const filter = values
				? {[field]: ["in", values], docstatus: ["!=", 2]}
				: {[field]: ["!=", ""], docstatus: ["!=", 2]};
			frappe.db.count(doctype, filter).then(n => {
				const color = n > 0 ? "#68d391" : "#a0aec0";
				el.innerHTML = `<span style="background:#1c4532;color:${color};padding:2px 10px;border-radius:12px;font-size:11px;font-weight:700;">
					✓ ${n.toLocaleString()} ${label}${n !== 1 ? "s" : ""} in ERPNext
				</span>`;
			}).catch(() => {
				el.innerHTML = "";
			});
		});
	}

	load_step_counts();

	// Refresh counts button in page header
	page.add_button("↻ Refresh Counts", load_step_counts, { icon: "fa fa-refresh" });

	// Add Mapping Guide button to page header
	page.add_button("Mapping Guide", function () {
		frappe.set_route("page", "epromise-mapping-guide");
	}, { icon: "fa fa-map" });

	page.add_button("📖 Documentation", function () {
		frappe.set_route("page", "epromise-docs");
	}, { icon: "fa fa-book" });

	page.add_button("📥 Excel Import (Production)", function () {
		frappe.set_route("page", "epromise-import");
	}, { icon: "fa fa-upload" });

	// ── Seed Default Mappings ─────────────────────────────────────────────────
	wrapper.querySelector("#btn-seed-mappings").onclick = function () {
		const btn = this;
		const status_el = wrapper.querySelector("#status-mappings");
		btn.disabled = true;
		btn.textContent = "Seeding…";
		status_el.textContent = "";

		frappe.call({
			method: "backup.epromise_migration.utils.mapping_seeder.seed_default_mappings",
			callback(r) {
				btn.disabled = false;
				btn.textContent = "Seed Default Mappings";
				const d = r.message || {};
				status_el.innerHTML =
					`<span class="text-success">${d.message || "Done"}</span>`;
			},
			error() {
				btn.disabled = false;
				btn.textContent = "Seed Default Mappings";
				status_el.innerHTML = '<span class="text-danger">Error — check console</span>';
			},
		});
	};

	// ── Test Connection ───────────────────────────────────────────────────────
	wrapper.querySelector("#btn-test-conn").onclick = function () {
		const btn = this;
		const result_el = wrapper.querySelector("#conn-result");
		btn.disabled = true;
		btn.textContent = "Testing…";
		result_el.innerHTML = "";

		frappe.call({
			method: "backup.epromise_migration.utils.connection_test.test_connection",
			callback(r) {
				btn.disabled = false;
				btn.textContent = "Test Live Connection";
				const d = r.message || {};
				if (d.connected) {
					const c = d.counts || {};
					const dich = c.dichdata || {};
					result_el.innerHTML = `
						<div class="alert alert-success p-2 small">
							<strong>✅ Connected:</strong> ${d.message}<br>
							<strong>dichdata invoices:</strong>
							S01=${dich.s01_count || 0}, S06=${dich.s06_count || 0},
							Submitted=${dich.submitted || 0}, Total=${dich.total || 0}<br>
							<strong>INVOICE_DETAIL rows:</strong> ${c.invoice_detail || 0}<br>
							<strong>sales_data rows:</strong> ${c.sales_data || 0}<br>
							<strong>Customer accounts:</strong> ${c.customers || 0}
						</div>`;
				} else {
					result_el.innerHTML = `
						<div class="alert alert-danger p-2 small">
							<strong>❌ Connection failed:</strong> ${d.message}
						</div>`;
				}
			},
			error() {
				btn.disabled = false;
				btn.textContent = "Test Live Connection";
				result_el.innerHTML = `<div class="alert alert-danger p-2 small">Error calling API — check console.</div>`;
			},
		});
	};

	// ── Generic import runner with stop + live progress ───────────────────────
	let _active_polls = {};

	function run_import(method, btn, status_el) {
		// Block if date range is invalid
		if (!check_date_order()) {
			frappe.msgprint({
				title: "Invalid Date Range",
				message: "From date is after To date. Please fix the date range before importing.",
				indicator: "red",
			});
			return;
		}
		btn.disabled = true;
		const orig = btn.textContent;
		btn.textContent = "Queuing…";
		status_el.textContent = "";

		frappe.call({
			method,
			callback(r) {
				btn.disabled = false;
				btn.textContent = orig;
				if (!r.message) return;
				const { log_name, status } = r.message;
				if (status === "queued") {
					_poll_progress(log_name, status_el);
				} else {
					// Legacy sync response (customers)
					const { total, success, skipped, errors } = r.message;
					const cls = errors ? "text-warning" : "text-success";
					status_el.innerHTML =
						`<span class="${cls}">Done — ${success} created, ` +
						`${skipped} skipped, ${errors} errors (of ${total}). ` +
						`<a href="/app/epromise-migration-log/${log_name}">View Log</a></span>`;
				}
			},
			error() {
				btn.disabled = false;
				btn.textContent = orig;
				status_el.innerHTML = '<span class="text-danger">Error — check console</span>';
			},
		});
	}

	function _poll_progress(log_name, status_el) {
		// Cancel any previous poll on this element
		if (_active_polls[log_name]) clearInterval(_active_polls[log_name]);

		function refresh() {
			frappe.db.get_value("ePromise Migration Log", log_name,
				["status", "success_count", "error_count", "skipped_count", "total_records"],
				(data) => {
					if (!data) return;
					const { status, success_count, error_count, skipped_count, total_records } = data;
					const done_count = (success_count || 0) + (error_count || 0) + (skipped_count || 0);
					const log_link = `<a href="/app/epromise-migration-log/${log_name}" target="_blank">${log_name}</a>`;

					if (["Running", "Queued", "Stop Requested"].includes(status)) {
						const stop_btn = `<button class="btn btn-xs btn-danger ml-2"
							onclick="frappe.call({method:'backup.epromise_migration.utils.invoice_importer.stop_import',
							args:{log_name:'${log_name}'},callback(r){frappe.show_alert(r.message?.message||'Stop requested');}})">
							■ Stop</button>`;
						status_el.innerHTML =
							`<span class="text-info">⏳ ${status} — ✅ ${success_count || 0} created, ` +
							`❌ ${error_count || 0} errors, ⏭ ${skipped_count || 0} skipped ` +
							`(${done_count} processed) — ${log_link}${stop_btn}</span>`;
					} else {
						clearInterval(_active_polls[log_name]);
						delete _active_polls[log_name];
						const cls = (error_count || 0) > 0 ? "text-warning" : "text-success";
						const icon = status === "Completed" ? "✅" : status === "Stopped" ? "⏹" : "❌";
						status_el.innerHTML =
							`<span class="${cls}">${icon} ${status} — ${success_count || 0} created, ` +
							`${error_count || 0} errors, ${skipped_count || 0} skipped. ${log_link}</span>`;
					}
				}
			);
		}

		refresh();
		_active_polls[log_name] = setInterval(refresh, 4000);
	}

	wrapper.querySelector("#btn-import-customers").onclick = function () {
		run_import(
			"backup.epromise_migration.utils.customer_importer.import_customers",
			this,
			wrapper.querySelector("#status-customers")
		);
	};

	wrapper.querySelector("#btn-import-suppliers").onclick = function () {
		run_import(
			"backup.epromise_migration.utils.supplier_importer.import_suppliers",
			this,
			wrapper.querySelector("#status-suppliers")
		);
	};

	wrapper.querySelector("#btn-import-items").onclick = function () {
		run_import(
			"backup.epromise_migration.utils.item_importer.import_item_master",
			this,
			wrapper.querySelector("#status-items")
		);
	};

	wrapper.querySelector("#btn-import-invoices").onclick = function () {
		run_import(
			"backup.epromise_migration.utils.invoice_importer.import_sales_invoices",
			this,
			wrapper.querySelector("#status-invoices")
		);
	};

	wrapper.querySelector("#btn-import-sales-returns").onclick = function () {
		run_import(
			"backup.epromise_migration.utils.invoice_importer.import_sales_returns",
			this, wrapper.querySelector("#status-sales-returns")
		);
	};

	wrapper.querySelector("#btn-import-receipts").onclick = function () {
		run_import(
			"backup.epromise_migration.utils.receipt_importer.import_purchase_receipts",
			this, wrapper.querySelector("#status-receipts")
		);
	};

	wrapper.querySelector("#btn-import-purchases").onclick = function () {
		run_import(
			"backup.epromise_migration.utils.purchase_importer.import_purchase_invoices",
			this, wrapper.querySelector("#status-purchases")
		);
	};

	wrapper.querySelector("#btn-import-purchase-returns").onclick = function () {
		run_import(
			"backup.epromise_migration.utils.purchase_importer.import_purchase_returns",
			this, wrapper.querySelector("#status-purchase-returns")
		);
	};

	wrapper.querySelector("#btn-import-payments").onclick = function () {
		run_import(
			"backup.epromise_migration.utils.payment_importer.import_payment_entries",
			this, wrapper.querySelector("#status-payments")
		);
	};

	wrapper.querySelector("#btn-import-journals").onclick = function () {
		run_import(
			"backup.epromise_migration.utils.payment_importer.import_cash_vouchers",
			this, wrapper.querySelector("#status-journals")
		);
	};

	// ── Checklist completion badges ────────────────────────────────────────────
	function load_checklist_status() {
		frappe.call({
			method: "backup.epromise_migration.page.epromise_mapping_guide.epromise_mapping_guide.get_mapping_stats",
			callback(r) {
				if (!r.message) return;
				const d  = r.message;
				const m  = d.masters || {};
				const s  = d.sales   || {};
				const pr = d.purchase_receipts || {};
				const pi = d.purchase_invoices || {};
				const pe = d.payments || {};
				const je = d.journals || {};

				const badge = (n, label) => n > 0
					? `<span class="badge badge-success ml-2" style="font-size:11px;font-weight:600;">✓ ${n.toLocaleString()} ${label}</span>`
					: `<span class="badge ml-2" style="font-size:11px;background:#edf2f7;color:#718096;">0 ${label}</span>`;

				const steps = [
					["1a — Import Customer",  badge(m.customers_epromise||0, "customers")],
					["1b — Import Supplier",  badge(m.suppliers_epromise||0, "suppliers")],
					["2 — Import Sales Inv",  badge((s.s01||0)+(s.s06||0), "invoices")],
					["2b — Import Sales Ret", badge((s.r01||0)+(s.r04||0), "returns")],
					["3 — Import Purchase Re",badge((pr.grn||0)+(pr.gr||0), "receipts")],
					["4 — Import Purchase In",badge((pi["350"]||0)+(pi["111"]||0)+(pi.ip||0), "invoices")],
					["4b — Import Purchase R",badge(pi.pr||0, "returns")],
					["5 — Import Payment",    badge((pe["003"]||0)+(pe["004"]||0), "entries")],
					["6 — Import Journal",    badge((je["007"]||0)+(je["020"]||0), "entries")],
				];

				wrapper.querySelectorAll(".card h5").forEach(h5 => {
					const txt = h5.textContent.trim();
					steps.forEach(([key, badgeHtml]) => {
						if (txt.includes(key) && !h5.querySelector(".step-status")) {
							const sp = document.createElement("span");
							sp.className = "step-status";
							sp.innerHTML = badgeHtml;
							h5.appendChild(sp);
						}
					});
				});
			}
		});
	}
	load_checklist_status();
};
