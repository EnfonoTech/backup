frappe.pages["epromise-mapping-guide"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: "ePromise Mapping Guide",
		single_column: true,
	});

	// ── Add action buttons in the page header ──────────────────────────────────
	page.add_button("Migration Dashboard", function () {
		frappe.set_route("page", "epromise-migration");
	}, { icon: "fa fa-arrow-left" });

	page.add_button("📖 Documentation", function () {
		frappe.set_route("page", "epromise-docs");
	}, { icon: "fa fa-book" });

	page.set_primary_action("Generate CSV Report", function () {
		frappe.call({
			method: "backup.epromise_migration.page.epromise_mapping_guide.epromise_mapping_guide.download_mapping_report",
			callback: function (r) {
				// download_mapping_report sets frappe.response directly for file download
				// Use a direct URL approach instead
				const url = "/api/method/backup.epromise_migration.page.epromise_mapping_guide.epromise_mapping_guide.download_mapping_report";
				const a = document.createElement("a");
				a.href = url;
				a.download = "epromise_mapping_report.csv";
				document.body.appendChild(a);
				a.click();
				document.body.removeChild(a);
			}
		});
	}, "fa fa-download");

	// ── Inline styles ──────────────────────────────────────────────────────────
	const style = document.createElement("style");
	style.textContent = `
		.em-guide-wrap {
			max-width: 1100px;
			margin: 0 auto;
			padding: 20px 0 60px;
			font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
		}
		.em-summary-grid {
			display: grid;
			grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
			gap: 14px;
			margin-bottom: 30px;
		}
		.em-stat-card {
			background: #1a1f2e;
			color: #e2e8f0;
			border-radius: 10px;
			padding: 16px;
			text-align: center;
			border: 1px solid #2d3748;
		}
		.em-stat-card .em-stat-num {
			font-size: 2rem;
			font-weight: 700;
			line-height: 1;
			color: #63b3ed;
		}
		.em-stat-card .em-stat-label {
			font-size: 0.72rem;
			color: #a0aec0;
			margin-top: 6px;
			text-transform: uppercase;
			letter-spacing: 0.05em;
		}
		.em-section {
			margin-bottom: 28px;
			border-radius: 10px;
			overflow: hidden;
			border: 1px solid #2d3748;
			background: #1a1f2e;
		}
		.em-section-header {
			padding: 12px 18px;
			display: flex;
			align-items: center;
			justify-content: space-between;
			cursor: pointer;
			user-select: none;
		}
		.em-section-header h5 {
			margin: 0;
			font-size: 0.95rem;
			font-weight: 600;
			color: #e2e8f0;
			display: flex;
			align-items: center;
			gap: 8px;
		}
		.em-section-header .em-toggle-icon {
			color: #a0aec0;
			font-size: 0.8rem;
			transition: transform 0.2s;
		}
		.em-section-header.collapsed .em-toggle-icon {
			transform: rotate(-90deg);
		}
		.em-section-body {
			padding: 0 18px 16px;
		}
		.em-table {
			width: 100%;
			border-collapse: collapse;
			font-size: 0.82rem;
			color: #cbd5e0;
		}
		.em-table thead tr {
			background: #0d1117;
		}
		.em-table th {
			padding: 8px 10px;
			text-align: left;
			color: #718096;
			font-weight: 600;
			text-transform: uppercase;
			font-size: 0.7rem;
			letter-spacing: 0.06em;
			border-bottom: 1px solid #2d3748;
			white-space: nowrap;
		}
		.em-table td {
			padding: 8px 10px;
			border-bottom: 1px solid #1e2533;
			vertical-align: top;
		}
		.em-table tr:last-child td {
			border-bottom: none;
		}
		.em-table tr:hover td {
			background: #202636;
		}
		.badge-mapped {
			background: #1c4532;
			color: #68d391;
			border: 1px solid #2f6846;
			padding: 2px 8px;
			border-radius: 20px;
			font-size: 0.7rem;
			font-weight: 600;
			white-space: nowrap;
		}
		.badge-partial {
			background: #744210;
			color: #f6ad55;
			border: 1px solid #975a16;
			padding: 2px 8px;
			border-radius: 20px;
			font-size: 0.7rem;
			font-weight: 600;
			white-space: nowrap;
		}
		.badge-notmapped {
			background: #742a2a;
			color: #fc8181;
			border: 1px solid #9b2c2c;
			padding: 2px 8px;
			border-radius: 20px;
			font-size: 0.7rem;
			font-weight: 600;
			white-space: nowrap;
		}
		.em-trc-code {
			font-family: "Courier New", monospace;
			background: #2d3748;
			color: #90cdf4;
			padding: 1px 6px;
			border-radius: 4px;
			font-size: 0.8rem;
			font-weight: 600;
		}
		.em-series {
			font-family: "Courier New", monospace;
			color: #b794f4;
			font-size: 0.75rem;
		}
		.em-source {
			font-family: "Courier New", monospace;
			color: #68d391;
			font-size: 0.75rem;
		}
		.em-field-col {
			font-family: "Courier New", monospace;
			color: #f6ad55;
			font-size: 0.78rem;
		}
		.em-count-chip {
			background: #2a4365;
			color: #90cdf4;
			padding: 2px 7px;
			border-radius: 12px;
			font-size: 0.72rem;
			font-weight: 600;
			margin-left: 6px;
		}
		.em-section-sales .em-section-header { background: #1a2f1a; border-left: 4px solid #48bb78; }
		.em-section-purchase .em-section-header { background: #1a2240; border-left: 4px solid #63b3ed; }
		.em-section-payment .em-section-header { background: #2a1f10; border-left: 4px solid #f6ad55; }
		.em-section-journal .em-section-header { background: #241a30; border-left: 4px solid #b794f4; }
		.em-section-master .em-section-header { background: #1a2828; border-left: 4px solid #4fd1c5; }
		.em-section-fields .em-section-header { background: #1f1f10; border-left: 4px solid #ecc94b; }
		.em-section-items .em-section-header { background: #1f1020; border-left: 4px solid #f687b3; }
		.em-section-suggestions .em-section-header { background: #201818; border-left: 4px solid #fc8181; }
		.em-loading-bar {
			text-align: center;
			padding: 40px;
			color: #718096;
		}
		.em-spinner {
			display: inline-block;
			width: 20px;
			height: 20px;
			border: 3px solid #2d3748;
			border-top-color: #63b3ed;
			border-radius: 50%;
			animation: spin 0.8s linear infinite;
			vertical-align: middle;
			margin-right: 8px;
		}
		@keyframes spin { to { transform: rotate(360deg); } }
		.em-refresh-btn {
			font-size: 0.75rem;
			color: #718096;
			background: none;
			border: 1px solid #2d3748;
			border-radius: 6px;
			padding: 3px 10px;
			cursor: pointer;
			margin-left: 12px;
		}
		.em-refresh-btn:hover { color: #63b3ed; border-color: #63b3ed; }
	`;
	document.head.appendChild(style);

	// ── Build shell HTML ───────────────────────────────────────────────────────
	$(wrapper).find(".page-content").html(`
		<div class="em-guide-wrap">

			<div style="display:flex;align-items:center;margin-bottom:18px;">
				<div>
					<p style="color:#a0aec0;margin:0;font-size:0.85rem;">
						Live counts from ERPNext · Field and TRC code mapping reference for the ePromise → ERPNext migration
					</p>
				</div>
				<button class="em-refresh-btn" id="em-btn-refresh">
					&#8635; Refresh Counts
				</button>
			</div>

			<div id="em-summary-grid" class="em-summary-grid">
				<div class="em-loading-bar"><span class="em-spinner"></span> Loading stats…</div>
			</div>

			<!-- SALES SECTION -->
			<div class="em-section em-section-sales">
				<div class="em-section-header" data-target="em-sales-body">
					<h5>&#9632; Sales Transactions</h5>
					<span class="em-toggle-icon">&#9660;</span>
				</div>
				<div class="em-section-body" id="em-sales-body">
					<table class="em-table">
						<thead><tr>
							<th>TRC Code</th>
							<th>ePromise Name</th>
							<th>ERPNext DocType</th>
							<th>Series</th>
							<th>Item Source</th>
							<th>Status</th>
							<th>Imported</th>
						</tr></thead>
						<tbody>
							<tr>
								<td><span class="em-trc-code">S01</span></td>
								<td>Credit Sales</td>
								<td>Sales Invoice</td>
								<td><span class="em-series">ACC-SINV-CR-.YYYY.-</span></td>
								<td><span class="em-source">SALES_DATA</span></td>
								<td><span class="badge-mapped">&#10003; Mapped</span></td>
								<td><span class="em-count-chip" id="em-cnt-s01">—</span></td>
							</tr>
							<tr>
								<td><span class="em-trc-code">S06</span></td>
								<td>Point of Sale</td>
								<td>Sales Invoice</td>
								<td><span class="em-series">ACC-SINV-POS-.YYYY.-</span></td>
								<td><span class="em-source">SALES_DATA</span></td>
								<td><span class="badge-mapped">&#10003; Mapped</span></td>
								<td><span class="em-count-chip" id="em-cnt-s06">—</span></td>
							</tr>
							<tr>
								<td><span class="em-trc-code">R01</span></td>
								<td>Credit Sales Return</td>
								<td>Sales Invoice <em>(is_return=1)</em></td>
								<td><span class="em-series">ACC-SINV-CR-RET-.YYYY.-</span></td>
								<td><span class="em-source">DICZDATA</span></td>
								<td><span class="badge-mapped">&#10003; Mapped</span></td>
								<td><span class="em-count-chip" id="em-cnt-r01">—</span></td>
							</tr>
							<tr>
								<td><span class="em-trc-code">R04</span></td>
								<td>POS Sales Return</td>
								<td>Sales Invoice <em>(is_return=1)</em></td>
								<td><span class="em-series">ACC-SINV-POS-RET-.YYYY.-</span></td>
								<td><span class="em-source">DICZDATA</span></td>
								<td><span class="badge-mapped">&#10003; Mapped</span></td>
								<td><span class="em-count-chip" id="em-cnt-r04">—</span></td>
							</tr>
						</tbody>
					</table>
				</div>
			</div>

			<!-- PURCHASE RECEIPTS SECTION -->
			<div class="em-section em-section-purchase">
				<div class="em-section-header" data-target="em-receipt-body">
					<h5>&#9632; Purchase Receipts</h5>
					<span class="em-toggle-icon">&#9660;</span>
				</div>
				<div class="em-section-body" id="em-receipt-body">
					<table class="em-table">
						<thead><tr>
							<th>TRC Code</th>
							<th>ePromise Name</th>
							<th>ERPNext DocType</th>
							<th>Series</th>
							<th>Item Source</th>
							<th>Status</th>
							<th>Imported</th>
						</tr></thead>
						<tbody>
							<tr>
								<td><span class="em-trc-code">GRN</span></td>
								<td>Goods Receiving Note</td>
								<td>Purchase Receipt</td>
								<td><span class="em-series">MAT-PRE-.YYYY.-</span></td>
								<td><span class="em-source">PURCHASE_DATA</span></td>
								<td><span class="badge-mapped">&#10003; Mapped</span></td>
								<td><span class="em-count-chip" id="em-cnt-grn">—</span></td>
							</tr>
							<tr>
								<td><span class="em-trc-code">GR</span></td>
								<td>Goods Return</td>
								<td>Purchase Receipt <em>(is_return=1)</em></td>
								<td><span class="em-series">MAT-PRE-.YYYY.-</span></td>
								<td><span class="em-source">PURCHASE_DATA</span></td>
								<td><span class="badge-mapped">&#10003; Mapped</span></td>
								<td><span class="em-count-chip" id="em-cnt-gr">—</span></td>
							</tr>
						</tbody>
					</table>
				</div>
			</div>

			<!-- PURCHASE INVOICES SECTION -->
			<div class="em-section em-section-purchase">
				<div class="em-section-header" data-target="em-pinv-body">
					<h5>&#9632; Purchase Invoices</h5>
					<span class="em-toggle-icon">&#9660;</span>
				</div>
				<div class="em-section-body" id="em-pinv-body">
					<table class="em-table">
						<thead><tr>
							<th>TRC Code</th>
							<th>ePromise Name</th>
							<th>ERPNext DocType</th>
							<th>Series</th>
							<th>Item Source</th>
							<th>Status</th>
							<th>Imported</th>
						</tr></thead>
						<tbody>
							<tr>
								<td><span class="em-trc-code">350</span></td>
								<td>Purchase Invoice Item Wise</td>
								<td>Purchase Invoice</td>
								<td><span class="em-series">ACC-PINV-PI-.YYYY.-</span></td>
								<td><span class="em-source">PURCHASE_INVOICE_DETAIL</span></td>
								<td><span class="badge-mapped">&#10003; Mapped</span></td>
								<td><span class="em-count-chip" id="em-cnt-350">—</span></td>
							</tr>
							<tr>
								<td><span class="em-trc-code">111</span></td>
								<td>Direct Purchase</td>
								<td>Purchase Invoice</td>
								<td><span class="em-series">ACC-PINV-DIR-.YYYY.-</span></td>
								<td><span class="em-source">PURCHASE_DATA</span></td>
								<td><span class="badge-mapped">&#10003; Mapped</span></td>
								<td><span class="em-count-chip" id="em-cnt-111">—</span></td>
							</tr>
							<tr>
								<td><span class="em-trc-code">IP</span></td>
								<td>Import Purchase</td>
								<td>Purchase Invoice</td>
								<td><span class="em-series">ACC-PINV-IMP-.YYYY.-</span></td>
								<td><span class="em-source">PURCHASE_DATA + DICADDATA (5xx)</span></td>
								<td><span class="badge-mapped">&#10003; Mapped</span></td>
								<td><span class="em-count-chip" id="em-cnt-ip">—</span></td>
							</tr>
							<tr>
								<td><span class="em-trc-code">PR</span></td>
								<td>Purchase Return</td>
								<td>Purchase Invoice <em>(is_return=1)</em></td>
								<td><span class="em-series">ACC-PINV-RET-.YYYY.-</span></td>
								<td><span class="em-source">PURCHASE_DATA</span></td>
								<td><span class="badge-mapped">&#10003; Mapped</span></td>
								<td><span class="em-count-chip" id="em-cnt-pr">—</span></td>
							</tr>
						</tbody>
					</table>
				</div>
			</div>

			<!-- PAYMENTS SECTION -->
			<div class="em-section em-section-payment">
				<div class="em-section-header" data-target="em-pay-body">
					<h5>&#9632; Payment Vouchers</h5>
					<span class="em-toggle-icon">&#9660;</span>
				</div>
				<div class="em-section-body" id="em-pay-body">
					<table class="em-table">
						<thead><tr>
							<th>TRC Code</th>
							<th>ePromise Name</th>
							<th>ERPNext DocType</th>
							<th>Payment Type</th>
							<th>Party Detection</th>
							<th>Status</th>
							<th>Imported</th>
						</tr></thead>
						<tbody>
							<tr>
								<td><span class="em-trc-code">003</span></td>
								<td>Cash Payment Voucher</td>
								<td>Payment Entry</td>
								<td>Pay (to Supplier)</td>
								<td><span class="em-source">DICADDATA GL lines</span></td>
								<td><span class="badge-mapped">&#10003; Mapped</span></td>
								<td><span class="em-count-chip" id="em-cnt-003">—</span></td>
							</tr>
							<tr>
								<td><span class="em-trc-code">004</span></td>
								<td>Cash Receipt Voucher</td>
								<td>Payment Entry</td>
								<td>Receive (from Customer)</td>
								<td><span class="em-source">1303 GL line</span></td>
								<td><span class="badge-mapped">&#10003; Mapped</span></td>
								<td><span class="em-count-chip" id="em-cnt-004">—</span></td>
							</tr>
						</tbody>
					</table>
				</div>
			</div>

			<!-- JOURNALS SECTION -->
			<div class="em-section em-section-journal">
				<div class="em-section-header" data-target="em-jv-body">
					<h5>&#9632; Journal &amp; Adjustment Vouchers</h5>
					<span class="em-toggle-icon">&#9660;</span>
				</div>
				<div class="em-section-body" id="em-jv-body">
					<table class="em-table">
						<thead><tr>
							<th>TRC Code</th>
							<th>ePromise Name</th>
							<th>ERPNext DocType</th>
							<th>GL Source</th>
							<th>Status</th>
							<th>Imported</th>
						</tr></thead>
						<tbody>
							<tr>
								<td><span class="em-trc-code">007</span></td>
								<td>Journal Voucher</td>
								<td>Journal Entry</td>
								<td><span class="em-source">DICADDATA</span></td>
								<td><span class="badge-mapped">&#10003; Mapped</span></td>
								<td><span class="em-count-chip" id="em-cnt-007">—</span></td>
							</tr>
							<tr>
								<td><span class="em-trc-code">020</span></td>
								<td>Bank/Cash Adjustment</td>
								<td>Journal Entry</td>
								<td><span class="em-source">DICADDATA</span></td>
								<td><span class="badge-mapped">&#10003; Mapped</span></td>
								<td><span class="em-count-chip" id="em-cnt-020">—</span></td>
							</tr>
						</tbody>
					</table>
				</div>
			</div>

			<!-- MASTER DATA SECTION -->
			<div class="em-section em-section-master">
				<div class="em-section-header" data-target="em-master-body">
					<h5>&#9632; Master Data</h5>
					<span class="em-toggle-icon">&#9660;</span>
				</div>
				<div class="em-section-body" id="em-master-body">
					<table class="em-table">
						<thead><tr>
							<th>ePromise Source</th>
							<th>Filter</th>
							<th>ERPNext DocType</th>
							<th>Key Field Stored</th>
							<th>Status</th>
							<th>Imported</th>
						</tr></thead>
						<tbody>
							<tr>
								<td><span class="em-source">DICADMAS</span></td>
								<td>sub_head = D</td>
								<td>Customer</td>
								<td><span class="em-field-col">epromise_acc_code</span></td>
								<td><span class="badge-mapped">&#10003; Mapped</span></td>
								<td><span class="em-count-chip" id="em-cnt-cust">—</span></td>
							</tr>
							<tr>
								<td><span class="em-source">DICADMAS</span></td>
								<td>sub_head = C</td>
								<td>Supplier</td>
								<td><span class="em-field-col">epromise_acc_code</span></td>
								<td><span class="badge-mapped">&#10003; Mapped</span></td>
								<td><span class="em-count-chip" id="em-cnt-supp">—</span></td>
							</tr>
							<tr>
								<td><span class="em-source">DICIHMAS</span></td>
								<td>—</td>
								<td>Item</td>
								<td><span class="em-field-col">is_stock_item=0</span></td>
								<td><span class="badge-mapped">&#10003; Mapped</span></td>
								<td><span class="em-count-chip" id="em-cnt-item">—</span></td>
							</tr>
						</tbody>
					</table>
				</div>
			</div>

			<!-- FIELD MAPPINGS SECTION (DICHDATA → Sales Invoice) -->
			<div class="em-section em-section-fields">
				<div class="em-section-header" data-target="em-fields-body">
					<h5>&#9632; Field Mappings — DICHDATA &#8594; Sales Invoice</h5>
					<span class="em-toggle-icon">&#9660;</span>
				</div>
				<div class="em-section-body" id="em-fields-body">
					<table class="em-table">
						<thead><tr>
							<th>ePromise Column (DICHDATA)</th>
							<th>ERPNext Field</th>
							<th>Notes</th>
						</tr></thead>
						<tbody>
							<tr><td class="em-field-col">ACC_CODE</td><td class="em-field-col">customer</td><td>via epromise_acc_code lookup</td></tr>
							<tr><td class="em-field-col">VR_NO</td><td class="em-field-col">epromise_vr_no</td><td>Custom field — source voucher number</td></tr>
							<tr><td class="em-field-col">TRC_CODE</td><td class="em-field-col">epromise_trc_code</td><td>Custom field — transaction type code</td></tr>
							<tr><td class="em-field-col">BILL_NO</td><td class="em-field-col">epromise_bill_no, po_no</td><td>Bill/PO reference</td></tr>
							<tr><td class="em-field-col">VR_DATE</td><td class="em-field-col">posting_date, due_date</td><td>Voucher date</td></tr>
							<tr><td class="em-field-col">CUR_CODE</td><td class="em-field-col">currency</td><td>Transaction currency (BHD, SAR, USD …)</td></tr>
							<tr><td class="em-field-col">CUR_RATE</td><td class="em-field-col">conversion_rate</td><td>Exchange rate to base currency</td></tr>
							<tr><td class="em-field-col">ACC_AMT</td><td class="em-field-col">grand_total</td><td>Calculated total including tax</td></tr>
							<tr><td class="em-field-col">VAT_AMT</td><td class="em-field-col">taxes[0].tax_amount</td><td>VAT / tax line amount</td></tr>
							<tr><td class="em-field-col">LPO_NO</td><td class="em-field-col">po_no</td><td>Local Purchase Order reference</td></tr>
							<tr><td class="em-field-col">CONTACT_PERSON</td><td class="em-field-col">contact_person_name</td><td>Contact on invoice</td></tr>
							<tr><td class="em-field-col">CREDIT_PERIOD</td><td class="em-field-col">payment_terms_template</td><td>Days to payment</td></tr>
							<tr><td class="em-field-col">DISC_PERCENT</td><td class="em-field-col">discount_amount</td><td>Invoice-level discount</td></tr>
							<tr><td class="em-field-col">SOURCE_BR_CODE</td><td class="em-field-col">cost_center</td><td>Branch code → Cost Center name mapping needed</td></tr>
							<tr><td class="em-field-col">REF_VR_NO</td><td class="em-field-col">return_against</td><td>For return vouchers only</td></tr>
						</tbody>
					</table>
				</div>
			</div>

			<!-- ITEM-LEVEL MAPPINGS SECTION -->
			<div class="em-section em-section-items">
				<div class="em-section-header" data-target="em-items-body">
					<h5>&#9632; Item-Level Mappings — SALES_DATA &#8594; Sales Invoice Item</h5>
					<span class="em-toggle-icon">&#9660;</span>
				</div>
				<div class="em-section-body" id="em-items-body">
					<table class="em-table">
						<thead><tr>
							<th>ePromise Column (SALES_DATA)</th>
							<th>ERPNext Field</th>
							<th>Notes</th>
						</tr></thead>
						<tbody>
							<tr><td class="em-field-col">ITE_CODE</td><td class="em-field-col">item_code</td><td>via DICIHMAS lookup</td></tr>
							<tr><td class="em-field-col">ITE_QTY</td><td class="em-field-col">qty</td><td>Negative for returns</td></tr>
							<tr><td class="em-field-col">ITE_RATE</td><td class="em-field-col">rate</td><td>Unit selling price</td></tr>
							<tr><td class="em-field-col">X_UNIT / ITE_UNIT</td><td class="em-field-col">uom</td><td>Unit of measure</td></tr>
							<tr><td class="em-field-col">VAT_RATE</td><td class="em-field-col">item tax template</td><td>Per-item tax rate</td></tr>
							<tr><td class="em-field-col">ITE_NAME</td><td class="em-field-col">item_name, description</td><td>Item display name</td></tr>
						</tbody>
					</table>
				</div>
			</div>

			<!-- SUGGESTIONS / NOT YET MAPPED SECTION -->
			<div class="em-section em-section-suggestions">
				<div class="em-section-header" data-target="em-suggest-body">
					<h5>&#9888; Gaps &amp; Improvement Suggestions</h5>
					<span class="em-toggle-icon">&#9660;</span>
				</div>
				<div class="em-section-body" id="em-suggest-body">
					<table class="em-table">
						<thead><tr>
							<th>#</th>
							<th>ePromise Source</th>
							<th>ERPNext Target</th>
							<th>Status</th>
							<th>Notes</th>
						</tr></thead>
						<tbody>
							<tr>
								<td>1</td>
								<td class="em-field-col">DICADMAS.ADDRESS, ACC_PHONE</td>
								<td>Customer Address DocType</td>
								<td><span class="badge-notmapped">&#10007; Not Mapped</span></td>
								<td>Import to Address and link to Customer</td>
							</tr>
							<tr>
								<td>2</td>
								<td class="em-field-col">DICADMAS.CREDIT_PERIOD</td>
								<td>Supplier payment_terms</td>
								<td><span class="badge-notmapped">&#10007; Not Mapped</span></td>
								<td>Set payment terms on Supplier record</td>
							</tr>
							<tr>
								<td>3</td>
								<td class="em-field-col">DICIHMAS custom fields</td>
								<td>Item custom fields (length, width, weight)</td>
								<td><span class="badge-notmapped">&#10007; Not Mapped</span></td>
								<td>Create Item custom fields and populate during import</td>
							</tr>
							<tr>
								<td>4</td>
								<td class="em-field-col">DICADDATA.REF_VR_NO, B_R_INT</td>
								<td>Payment Entry → Invoice reconciliation</td>
								<td><span class="badge-partial">&#9888; Partial</span></td>
								<td>Needs further exploration; use Payment Reconciliation tool</td>
							</tr>
							<tr>
								<td>5</td>
								<td class="em-field-col">DICHDATA.SO_NO</td>
								<td>Sales Invoice.po_no</td>
								<td><span class="badge-partial">&#9888; Partial</span></td>
								<td>Currently BILL_NO used for po_no; SO_NO excluded</td>
							</tr>
							<tr>
								<td>6</td>
								<td class="em-field-col">DICHDATA.SOURCE_BR_CODE</td>
								<td>Cost Center</td>
								<td><span class="badge-partial">&#9888; Partial</span></td>
								<td>Branch codes need explicit mapping to ERPNext Cost Center names</td>
							</tr>
							<tr>
								<td>7</td>
								<td class="em-field-col">DICADMAS.VAT_NO</td>
								<td>Customer.tax_id</td>
								<td><span class="badge-mapped">&#10003; Mapped</span></td>
								<td>Mapped during customer import step</td>
							</tr>
							<tr>
								<td>8</td>
								<td>Invoice currency</td>
								<td>Debtors account (BHD-K / SAR-K)</td>
								<td><span class="badge-mapped">&#10003; Mapped</span></td>
								<td>BHD invoices → Debtors BHD-K; SAR invoices → Debtors SAR-K</td>
							</tr>
							<tr>
								<td>9</td>
								<td class="em-field-col">DICIHMAS.is_stock_item</td>
								<td>Item.is_stock_item</td>
								<td><span class="badge-notmapped">&#10007; Not Mapped</span></td>
								<td>All items imported as non-stock; re-import needed once warehouses configured</td>
							</tr>
							<tr>
								<td>10</td>
								<td class="em-field-col">DICHDATA.SALES_MAN</td>
								<td>Sales Team (child table)</td>
								<td><span class="badge-notmapped">&#10007; Not Mapped</span></td>
								<td>Child table limitation — currently excluded from import</td>
							</tr>
						</tbody>
					</table>
				</div>
			</div>

		</div>
	`);

	// ── Collapsible sections ───────────────────────────────────────────────────
	$(wrapper).find(".em-section-header").on("click", function () {
		const targetId = $(this).data("target");
		const $body = $("#" + targetId);
		$body.slideToggle(200);
		$(this).toggleClass("collapsed");
	});

	// ── Load stats from server ─────────────────────────────────────────────────
	function load_stats() {
		$("#em-summary-grid").html('<div class="em-loading-bar"><span class="em-spinner"></span> Loading stats…</div>');

		frappe.call({
			method: "backup.epromise_migration.page.epromise_mapping_guide.epromise_mapping_guide.get_mapping_stats",
			callback: function (r) {
				if (!r.message) return;
				const d = r.message;
				const s = d.sales || {};
				const pr_data = d.purchase_receipts || {};
				const pi = d.purchase_invoices || {};
				const pay = d.payments || {};
				const jv = d.journals || {};
				const m = d.masters || {};
				const logs = d.logs || {};

				// Populate summary cards
				const cards = [
					{ label: "Sales Invoices", num: s.total || 0, color: "#48bb78" },
					{ label: "Purchase Receipts", num: pr_data.total || 0, color: "#63b3ed" },
					{ label: "Purchase Invoices", num: pi.total || 0, color: "#76e4f7" },
					{ label: "Payment Entries", num: pay.total || 0, color: "#f6ad55" },
					{ label: "Journal Entries", num: jv.total || 0, color: "#b794f4" },
					{ label: "Customers", num: m.customers_epromise || 0, color: "#4fd1c5" },
					{ label: "Suppliers", num: m.suppliers_epromise || 0, color: "#4fd1c5" },
					{ label: "Items", num: m.items_total || 0, color: "#f687b3" },
					{ label: "Migration Logs", num: logs.total || 0, color: "#718096" },
				];

				let cardHtml = "";
				cards.forEach(c => {
					cardHtml += `
						<div class="em-stat-card">
							<div class="em-stat-num" style="color:${c.color}">${(c.num).toLocaleString()}</div>
							<div class="em-stat-label">${c.label}</div>
						</div>`;
				});
				$("#em-summary-grid").html(cardHtml);

				// Populate per-TRC counts
				const countMap = {
					"em-cnt-s01": s.s01,
					"em-cnt-s06": s.s06,
					"em-cnt-r01": s.r01,
					"em-cnt-r04": s.r04,
					"em-cnt-grn": pr_data.grn,
					"em-cnt-gr": pr_data.gr,
					"em-cnt-350": pi["350"],
					"em-cnt-111": pi["111"],
					"em-cnt-ip": pi.ip,
					"em-cnt-pr": pi.pr,
					"em-cnt-003": pay["003"],
					"em-cnt-004": pay["004"],
					"em-cnt-007": jv["007"],
					"em-cnt-020": jv["020"],
					"em-cnt-cust": m.customers_epromise,
					"em-cnt-supp": m.suppliers_epromise,
					"em-cnt-item": m.items_total,
				};

				Object.entries(countMap).forEach(([id, val]) => {
					const el = document.getElementById(id);
					if (el) el.textContent = (val != null ? Number(val).toLocaleString() : "0");
				});
			},
			error: function () {
				$("#em-summary-grid").html(
					'<div style="color:#fc8181;padding:20px;">Failed to load stats. Check console for errors.</div>'
				);
			}
		});
	}

	// ── Refresh button ─────────────────────────────────────────────────────────
	document.getElementById("em-btn-refresh").onclick = load_stats;

	// ── Initial load ───────────────────────────────────────────────────────────
	load_stats();

	// ─────────────────────────────────────────────────────────────────────────
	// EPROMISE REPORT SECTION — date range counts & amounts from live DB
	// ─────────────────────────────────────────────────────────────────────────
	const report_section = document.createElement("div");
	report_section.innerHTML = `
		<div style="margin-top:32px;padding:24px;background:#1a202c;border-radius:12px;border:1px solid #2d3748;">
			<h3 style="color:#f7fafc;font-size:18px;font-weight:700;margin:0 0 8px;">
				📊 ePromise → ERPNext Import Report
			</h3>
			<p style="color:#a0aec0;font-size:13px;margin:0 0 20px;">
				Query the live ePromise database for a date range to see record counts and amounts pending import.
			</p>

			<!-- Date inputs -->
			<div style="display:flex;gap:16px;align-items:flex-end;flex-wrap:wrap;margin-bottom:20px;">
				<div>
					<label style="display:block;color:#e2e8f0;font-size:12px;font-weight:600;margin-bottom:6px;">From Date</label>
					<div style="position:relative;display:inline-block;">
						<input type="date" id="rpt-from-date"
							style="padding:10px 44px 10px 14px;border-radius:8px;border:2px solid #4a5568;background:#2d3748;color:#f7fafc;font-size:14px;min-width:170px;cursor:pointer;appearance:none;-webkit-appearance:none;"
							onclick="this.showPicker&&this.showPicker()">
						<span onclick="document.getElementById('rpt-from-date').showPicker&&document.getElementById('rpt-from-date').showPicker()"
							style="position:absolute;right:10px;top:50%;transform:translateY(-50%);font-size:18px;cursor:pointer;pointer-events:auto;">📅</span>
					</div>
				</div>
				<div>
					<label style="display:block;color:#e2e8f0;font-size:12px;font-weight:600;margin-bottom:6px;">To Date</label>
					<div style="position:relative;display:inline-block;">
						<input type="date" id="rpt-to-date"
							style="padding:10px 44px 10px 14px;border-radius:8px;border:2px solid #4a5568;background:#2d3748;color:#f7fafc;font-size:14px;min-width:170px;cursor:pointer;appearance:none;-webkit-appearance:none;"
							onclick="this.showPicker&&this.showPicker()">
						<span onclick="document.getElementById('rpt-to-date').showPicker&&document.getElementById('rpt-to-date').showPicker()"
							style="position:absolute;right:10px;top:50%;transform:translateY(-50%);font-size:18px;cursor:pointer;pointer-events:auto;">📅</span>
					</div>
				</div>
				<div>
					<label style="display:block;color:#718096;font-size:12px;font-weight:600;margin-bottom:6px;">Branch</label>
					<select id="rpt-branch"
						style="padding:10px 14px;border-radius:8px;border:2px solid #4a5568;background:#2d3748;color:#f7fafc;font-size:13px;min-width:150px;cursor:pointer;">
						<option value="">All Branches</option>
					</select>
				</div>
				<button id="rpt-btn-run"
					style="padding:10px 22px;background:#4299e1;color:white;border:none;border-radius:8px;font-size:13px;font-weight:600;cursor:pointer;white-space:nowrap;">
					🔍 Run Report
				</button>
				<button id="rpt-btn-csv"
					style="padding:10px 22px;background:#38a169;color:white;border:none;border-radius:8px;font-size:13px;font-weight:600;cursor:pointer;display:none;white-space:nowrap;">
					⬇ Download CSV
				</button>
			</div>

			<!-- Results area -->
			<div id="rpt-results"></div>
			<div id="rpt-detail-panel" style="margin-top:16px;display:none;"></div>
		</div>
	`;
	(wrapper.querySelector(".em-guide-wrap") || wrapper.querySelector(".page-content")).appendChild(report_section);

	// Set default dates from ePromise Settings or sensible defaults
	// ── Load default dates from ePromise Settings ─────────────────────────────
	frappe.db.get_value("ePromise Settings", "ePromise Settings",
		["invoice_from_date", "invoice_to_date"], (data) => {
			const today = new Date();
			const firstOfMonth = new Date(today.getFullYear(), today.getMonth(), 1);
			document.getElementById("rpt-from-date").value =
				(data && data.invoice_from_date) || firstOfMonth.toISOString().slice(0, 10);
			document.getElementById("rpt-to-date").value =
				(data && data.invoice_to_date) || today.toISOString().slice(0, 10);
		}
	);

	// ── Auto-refresh on date change (500ms debounce) ───────────────────────────
	let _refresh_timer = null;
	function _debounced_refresh() {
		const f = document.getElementById("rpt-from-date").value;
		const t = document.getElementById("rpt-to-date").value;
		if (!f || !t) return;
		if (f > t) {
			document.getElementById("rpt-results").innerHTML =
				'<div style="color:#fc8181;padding:12px;">⚠ From date is after To date — please correct.</div>';
			return;
		}
		clearTimeout(_refresh_timer);
		_refresh_timer = setTimeout(() => {
			document.getElementById("rpt-btn-run").click();
		}, 600);
	}
	document.getElementById("rpt-from-date").addEventListener("change", _debounced_refresh);
	document.getElementById("rpt-to-date").addEventListener("change",   _debounced_refresh);

	let _last_report_data = null;

	function fmt_num(n) {
		return (n || 0).toLocaleString();
	}
	function fmt_amt(n) {
		return parseFloat(n || 0).toLocaleString(undefined, {minimumFractionDigits: 3, maximumFractionDigits: 3});
	}
	function pct(done, total) {
		if (!total) return "—";
		const p = Math.round((done / total) * 100);
		const color = p >= 100 ? "#68d391" : p > 50 ? "#f6e05e" : "#fc8181";
		return `<span style="color:${color};font-weight:700;">${p}%</span>`;
	}
	function badge(n, color) {
		return `<span style="background:${color}22;color:${color};padding:2px 8px;border-radius:100px;font-size:11px;font-weight:700;">${n}</span>`;
	}

	function render_report(data) {
		_last_report_data = data;
		const el = document.getElementById("rpt-results");
		const rows = data.rows || [];
		const masters = data.masters || {};

		const catColors = {
			"Sales":"#68d391","Returns":"#fc8181","Purchase":"#63b3ed",
			"Payment":"#f6ad55","Journal":"#b794f4",
		};
		const catLabels = {
			"Sales":"─── SALES ────────────────────────────",
			"Returns":"─── SALES RETURNS ────────────────────",
			"Purchase":"─── PURCHASES ────────────────────────",
			"Payment":"─── CASH MOVEMENT ───────────────────",
			"Journal":"─── JOURNALS ─────────────────────────",
		};

		const petty_note = data.petty_cash_acc
			? `· Petty cash account: <strong style="color:#63b3ed;">${data.petty_cash_acc}</strong> (used to filter 003/004/020/007)`
			: `· 🌐 <em>003/004/020/007: all branches</em> (no branch filter — set a branch to filter by petty cash account)`;
		let html = `
			<p style="color:#718096;font-size:12px;margin-bottom:16px;">
				Period: <strong style="color:#e2e8f0;">${data.from_date||"All"}</strong> to
				<strong style="color:#e2e8f0;">${data.to_date||"All"}</strong>
				· Branch: <strong style="color:#63b3ed;">${data.branch||"All"}</strong>
				${petty_note}
			</p>
			<div style="overflow-x:auto;">
			<table style="width:100%;border-collapse:collapse;font-size:13px;">
				<thead>
					<tr style="border-bottom:2px solid #4a5568;background:#2d3748;">
						<th style="text-align:left;padding:10px 14px;color:#a0aec0;font-weight:700;">Module / TRC</th>
						<th style="text-align:left;padding:10px 10px;color:#a0aec0;font-weight:700;">ERPNext DocType</th>
						<th style="text-align:right;padding:10px 10px;color:#a0aec0;font-weight:700;">eP Count</th>
						<th style="text-align:right;padding:10px 10px;color:#f6e05e;font-weight:700;">eP Amount</th>
						<th style="text-align:right;padding:10px 10px;color:#68d391;font-weight:700;">Imported</th>
						<th style="text-align:right;padding:10px 10px;color:#63b3ed;font-weight:700;">ERPNext Amt</th>
						<th style="text-align:right;padding:10px 10px;color:#fc8181;font-weight:700;">Pending</th>
						<th style="text-align:left;padding:10px 10px;color:#a0aec0;font-weight:700;min-width:120px;">Progress</th>
					</tr>
				</thead>
				<tbody>`;

		let prev_cat = "";
		rows.forEach(r => {
			const c = catColors[r.category] || "#e2e8f0";
			if (r.category !== prev_cat) {
				prev_cat = r.category;
				html += `<tr style="background:#171923;">
					<td colspan="8" style="padding:8px 14px;color:#4a5568;font-size:11px;letter-spacing:1px;">
						${catLabels[r.category] || r.category}</td></tr>`;
			}
			const pend_c = r.pending > 0 ? "#fc8181" : "#68d391";
			const pct_v  = r.pct_done || 0;
			const bar_c  = pct_v >= 100 ? "#68d391" : pct_v > 50 ? "#f6e05e" : "#fc8181";
			const amtCell = r.has_amount
				? `<td style="padding:8px 10px;text-align:right;color:#f6e05e;font-family:monospace;">${fmt_amt(r.ep_total)}</td>
				   <td style="padding:8px 10px;text-align:right;color:#68d391;font-family:monospace;">${fmt_num(r.erp_count)}</td>
				   <td style="padding:8px 10px;text-align:right;color:#63b3ed;font-family:monospace;">${fmt_amt(r.erp_total)}</td>`
				: `<td style="padding:8px 10px;text-align:right;color:#4a5568;">—</td>
				   <td style="padding:8px 10px;text-align:right;color:#68d391;font-family:monospace;">${fmt_num(r.erp_count)}</td>
				   <td style="padding:8px 10px;text-align:right;color:#4a5568;">—</td>`;
			const nobrTag = r.no_branch ? `<span style="color:#4a5568;font-size:10px;margin-left:6px;">🌐 all branches</span>` : "";
			const drillIcon = `<span style="opacity:0.4;font-size:10px;margin-left:6px;">▶</span>`;
			html += `
				<tr style="border-bottom:1px solid #1a202c;cursor:pointer;"
					data-trc="${r.trc_code}" data-label="${r.ep_name}"
					onmouseover="this.style.background='#2d3748'" onmouseout="this.style.background=''">
					<td style="padding:8px 14px;">
						<span style="background:${c}22;color:${c};padding:1px 7px;border-radius:4px;font-size:11px;font-weight:700;margin-right:8px;">${r.trc_code}</span>
						<span style="color:#e2e8f0;">${r.ep_name}</span>${nobrTag}${drillIcon}
					</td>
					<td style="padding:8px 10px;color:#718096;font-size:11px;">${r.erp_doctype}</td>
					<td style="padding:8px 10px;text-align:right;color:#f7fafc;font-weight:600;font-family:monospace;">${fmt_num(r.ep_count)}</td>
					${amtCell}
					<td style="padding:8px 10px;text-align:right;color:${pend_c};font-weight:700;font-family:monospace;">${fmt_num(r.pending)}</td>
					<td style="padding:8px 10px;min-width:120px;">
						<div style="background:#2d3748;border-radius:4px;height:8px;overflow:hidden;">
							<div style="background:${bar_c};width:${Math.min(pct_v,100)}%;height:100%;border-radius:4px;"></div>
						</div>
						<div style="color:${bar_c};font-size:10px;margin-top:2px;font-weight:700;">${pct_v}%</div>
					</td>
				</tr>`;
		});

		// Summary totals row
		const tot_ep  = rows.reduce((s,r)=>s+r.ep_count,0);
		const tot_amt = rows.filter(r=>r.has_amount).reduce((s,r)=>s+r.ep_total,0);
		const tot_erp = rows.reduce((s,r)=>s+r.erp_count,0);
		const tot_pend= rows.reduce((s,r)=>s+r.pending,0);
		const tot_pct = tot_ep ? Math.round((tot_erp/tot_ep)*100) : 100;
		html += `
				<tr style="border-top:2px solid #4a5568;background:#2d3748;font-weight:700;">
					<td style="padding:12px 14px;color:#e2e8f0;">TOTAL TRANSACTIONS</td>
					<td></td>
					<td style="padding:12px 10px;text-align:right;color:#f7fafc;font-family:monospace;">${fmt_num(tot_ep)}</td>
					<td style="padding:12px 10px;text-align:right;color:#f6e05e;font-family:monospace;">${fmt_amt(tot_amt)}</td>
					<td style="padding:12px 10px;text-align:right;color:#68d391;font-family:monospace;">${fmt_num(tot_erp)}</td>
					<td></td>
					<td style="padding:12px 10px;text-align:right;color:#fc8181;font-family:monospace;">${fmt_num(tot_pend)}</td>
					<td style="padding:12px 10px;color:#f6e05e;font-weight:700;">${tot_pct}% Done</td>
				</tr>
			</tbody></table></div>`;

		// Masters summary
		const m = masters;
		html += `
			<div style="margin-top:20px;display:grid;grid-template-columns:repeat(3,1fr);gap:12px;">`;
		[
			{label:"Customers", ep: m.customers?.ep, erp: m.customers?.erp, color:"#68d391"},
			{label:"Suppliers", ep: m.suppliers?.ep, erp: m.suppliers?.erp, color:"#63b3ed"},
			{label:"Items",     ep: m.items?.ep,     erp: m.items?.erp,     color:"#f6ad55"},
		].forEach(master => {
			const pend = Math.max(0, (master.ep||0) - (master.erp||0));
			html += `
				<div style="background:#2d3748;border-radius:8px;padding:14px;border:1px solid #4a5568;">
					<div style="color:${master.color};font-weight:700;font-size:13px;margin-bottom:8px;">${master.label}</div>
					<div style="display:flex;justify-content:space-between;font-size:12px;color:#a0aec0;margin-bottom:4px;">
						<span>In ePromise</span><span style="color:#f7fafc;font-weight:600;">${fmt_num(master.ep)}</span>
					</div>
					<div style="display:flex;justify-content:space-between;font-size:12px;color:#a0aec0;margin-bottom:4px;">
						<span>In ERPNext</span><span style="color:#68d391;font-weight:600;">${fmt_num(master.erp)}</span>
					</div>
					<div style="display:flex;justify-content:space-between;font-size:12px;color:#a0aec0;">
						<span>Pending</span><span style="color:${pend>0?'#fc8181':'#68d391'};font-weight:700;">${fmt_num(pend)}</span>
					</div>
				</div>`;
		});
		html += `</div>`;

		el.innerHTML = html;
		document.getElementById("rpt-btn-csv").style.display = "inline-block";

		// Attach drill-down click handlers (same as DCR)
		el.querySelectorAll("tr[data-trc]").forEach(tr => {
			tr.addEventListener("click", function () {
				const trc       = this.dataset.trc;
				const label     = this.dataset.label;
				const from_date = document.getElementById("rpt-from-date").value;
				const to_date   = document.getElementById("rpt-to-date").value;
				const branch    = document.getElementById("rpt-branch").value;
				const panel     = document.getElementById("rpt-detail-panel");

				if (panel.dataset.active === trc) {
					panel.style.display = "none"; panel.dataset.active = ""; return;
				}
				panel.dataset.active = trc;
				panel.style.display = "block";
				panel.innerHTML = `<div style="color:#a0aec0;padding:16px;text-align:center;">⏳ Loading ${label}…</div>`;

				// Use same get_voucher_detail API as DCR
				// For 003/004/020/007: pass petty_cash_acc from report data for branch-specific drill-down
				const no_branch_trcs = ["003","004","020","007"];
				const drill_branch   = no_branch_trcs.includes(trc) ? null : (branch || null);
				const drill_petty    = no_branch_trcs.includes(trc)
					? ((_last_report_data || {}).petty_cash_acc || "")
					: "";

				frappe.call({
					method: "backup.epromise_migration.page.epromise_mapping_guide.epromise_mapping_guide.get_voucher_detail",
					args: { from_date, to_date, drilldown: trc, branch_code: drill_branch, petty_cash_acc: drill_petty },
					callback(r) {
						const rows = r.message || [];
						if (!rows.length) {
							panel.innerHTML = `<div style="color:#718096;padding:16px;">No vouchers found for ${label}.</div>`;
							return;
						}
						let h = `
							<div style="background:#2d3748;border-radius:8px;padding:16px;margin-bottom:8px;">
								<div style="color:#e2e8f0;font-weight:700;font-size:13px;margin-bottom:12px;">
									<span style="background:#4299e133;color:#63b3ed;padding:2px 8px;border-radius:4px;font-size:11px;margin-right:8px;">${trc}</span>
									${label} — ${rows.length} voucher(s)
									<button onclick="document.getElementById('rpt-detail-panel').style.display='none';document.getElementById('rpt-detail-panel').dataset.active='';"
										style="float:right;padding:3px 12px;background:#4a5568;color:white;border:none;border-radius:5px;font-size:11px;cursor:pointer;">✕</button>
								</div>
								<div style="overflow-x:auto;">
								<table style="width:100%;border-collapse:collapse;font-size:12px;">
									<thead><tr style="border-bottom:1px solid #4a5568;">
										<th style="padding:6px 10px;color:#a0aec0;text-align:left;">Date</th>
										<th style="padding:6px 10px;color:#a0aec0;text-align:left;">Voucher No</th>
										<th style="padding:6px 10px;color:#a0aec0;text-align:left;">Bill No</th>
										<th style="padding:6px 10px;color:#a0aec0;text-align:left;">Party</th>
										<th style="padding:6px 10px;color:#f6e05e;text-align:right;">Gross</th>
										<th style="padding:6px 10px;color:#a0aec0;text-align:right;">VAT</th>
										<th style="padding:6px 10px;color:#68d391;text-align:right;font-weight:700;">Net</th>
										<th style="padding:6px 10px;color:#a0aec0;text-align:left;">Remarks</th>
									</tr></thead><tbody>`;
						let totNet = 0, totGross = 0;
						rows.forEach(v => {
							totNet += v.net; totGross += v.gross;
							h += `<tr style="border-bottom:1px solid #1a202c;" onmouseover="this.style.background='#4a5568'" onmouseout="this.style.background=''">
								<td style="padding:5px 10px;color:#a0aec0;">${v.date}</td>
								<td style="padding:5px 10px;color:#63b3ed;font-family:monospace;">${v.vr_no}</td>
								<td style="padding:5px 10px;color:#718096;">${v.bill_no||"—"}</td>
								<td style="padding:5px 10px;color:#e2e8f0;max-width:180px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${v.party}">${v.party||"—"}</td>
								<td style="padding:5px 10px;text-align:right;color:#f6e05e;font-family:monospace;">${v.gross.toFixed(3)}</td>
								<td style="padding:5px 10px;text-align:right;color:#718096;font-family:monospace;">${v.vat.toFixed(3)}</td>
								<td style="padding:5px 10px;text-align:right;color:#68d391;font-family:monospace;font-weight:700;">${v.net.toFixed(3)}</td>
								<td style="padding:5px 10px;color:#718096;font-size:11px;max-width:150px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${v.remarks}">${v.remarks||""}</td>
							</tr>`;
						});
						h += `<tr style="border-top:2px solid #4a5568;font-weight:700;background:#2d3748;">
								<td colspan="4" style="padding:7px 10px;color:#e2e8f0;">TOTAL (${rows.length})</td>
								<td style="padding:7px 10px;text-align:right;color:#f6e05e;font-family:monospace;">${totGross.toFixed(3)}</td>
								<td></td>
								<td style="padding:7px 10px;text-align:right;color:#68d391;font-family:monospace;">${totNet.toFixed(3)}</td>
								<td></td>
							</tr></tbody></table></div></div>`;
						panel.innerHTML = h;
					},
					error() { panel.innerHTML = `<div style="color:#fc8181;padding:16px;">Error loading voucher detail.</div>`; }
				});
			});
		});
	}

	// Load branch list for import report
	frappe.call({
		method: "backup.epromise_migration.page.epromise_mapping_guide.epromise_mapping_guide.get_branch_list",
		callback(r) {
			const sel = document.getElementById("rpt-branch");
			if (!sel) return;
			(r.message || []).forEach(b => {
				const opt = document.createElement("option");
				opt.value = b.code; opt.text = b.code;
				sel.appendChild(opt);
			});
		}
	});

	document.getElementById("rpt-branch").addEventListener("change", () => {
		document.getElementById("rpt-detail-panel").style.display = "none";
		document.getElementById("rpt-detail-panel").dataset.active = "";
		if (_last_report_data) document.getElementById("rpt-btn-run").click();
	});

	document.getElementById("rpt-btn-run").onclick = function () {
		const from_date   = document.getElementById("rpt-from-date").value;
		const to_date     = document.getElementById("rpt-to-date").value;
		const branch_code = document.getElementById("rpt-branch").value;
		const btn = this;
		btn.disabled = true;
		btn.textContent = "Running…";
		document.getElementById("rpt-results").innerHTML =
			'<div style="color:#a0aec0;padding:20px;text-align:center;">⏳ Querying ePromise database…</div>';
		document.getElementById("rpt-detail-panel").style.display = "none";

		frappe.call({
			method: "backup.epromise_migration.page.epromise_mapping_guide.epromise_mapping_guide.get_epromise_report",
			args: { from_date, to_date, branch_code: branch_code || null },
			callback(r) {
				btn.disabled = false;
				btn.textContent = "🔍 Run Report";
				if (r.message) render_report(r.message);
			},
			error() {
				btn.disabled = false;
				btn.textContent = "🔍 Run Report";
				document.getElementById("rpt-results").innerHTML =
					'<div style="color:#fc8181;padding:20px;">Error querying ePromise — check SQL Server connection in ePromise Settings.</div>';
			},
		});
	};

	document.getElementById("rpt-btn-csv").onclick = function () {
		if (!_last_report_data) return;
		const rows = _last_report_data.rows || [];
		const header = ["Category","TRC Code","ePromise Module","ERPNext DocType",
			"ePromise Count","ePromise Amount","ERPNext Count","ERPNext Amount","Pending","% Done"];
		const lines = [header.join(",")];
		rows.forEach(r => {
			const done = r.ep_count ? Math.round((r.erp_count/r.ep_count)*100)+"%" : "—";
			lines.push([r.category,r.trc_code,r.ep_name,r.erp_doctype,
				r.ep_count,r.ep_total.toFixed(3),r.erp_count,r.erp_total.toFixed(3),r.pending,done].join(","));
		});
		const m = _last_report_data.masters || {};
		lines.push(""); lines.push("Masters");
		lines.push(["Customers",_last_report_data.from_date||"All",_last_report_data.to_date||"All",
			"",m.customers?.ep||0,"",m.customers?.erp||0,"",
			Math.max(0,(m.customers?.ep||0)-(m.customers?.erp||0))].join(","));
		lines.push(["Suppliers","","","",m.suppliers?.ep||0,"",m.suppliers?.erp||0,"",
			Math.max(0,(m.suppliers?.ep||0)-(m.suppliers?.erp||0))].join(","));
		lines.push(["Items","","","",m.items?.ep||0,"",m.items?.erp||0,"",
			Math.max(0,(m.items?.ep||0)-(m.items?.erp||0))].join(","));

		const blob = new Blob([lines.join("\n")], {type:"text/csv"});
		const a = document.createElement("a");
		a.href = URL.createObjectURL(blob);
		a.download = `epromise_report_${_last_report_data.from_date||"all"}_${_last_report_data.to_date||"all"}.csv`;
		a.click();
	};

	// ─────────────────────────────────────────────────────────────────────────
	// DAILY COLLECTION REPORT — matches ePromise's Daily Transaction-wise format
	// ─────────────────────────────────────────────────────────────────────────
	const daily_section = document.createElement("div");
	daily_section.innerHTML = `
		<div style="margin-top:32px;padding:24px;background:#1a202c;border-radius:12px;border:1px solid #2d3748;">
			<h3 style="color:#f7fafc;font-size:18px;font-weight:700;margin:0 0 6px;">
				📋 Daily Collection Report
			</h3>
			<p style="color:#718096;font-size:12px;margin:0 0 20px;">
				Matches ePromise's <em>Daily Transaction-wise Report</em> — Sales, Returns, Purchases and Cash Movement for the selected period.
			</p>

			<!-- Date + Branch inputs -->
			<div style="display:flex;gap:16px;align-items:flex-end;flex-wrap:wrap;margin-bottom:20px;">
				<div>
					<label style="display:block;color:#e2e8f0;font-size:12px;font-weight:600;margin-bottom:6px;">From Date</label>
					<div style="position:relative;display:inline-block;">
						<input type="date" id="dcr-from-date"
							style="padding:10px 44px 10px 14px;border-radius:8px;border:2px solid #553c9a;background:#2d3748;color:#f7fafc;font-size:14px;min-width:170px;cursor:pointer;appearance:none;-webkit-appearance:none;"
							onclick="this.showPicker&&this.showPicker()">
						<span onclick="document.getElementById('dcr-from-date').showPicker&&document.getElementById('dcr-from-date').showPicker()"
							style="position:absolute;right:10px;top:50%;transform:translateY(-50%);font-size:18px;cursor:pointer;">📅</span>
					</div>
				</div>
				<div>
					<label style="display:block;color:#e2e8f0;font-size:12px;font-weight:600;margin-bottom:6px;">To Date</label>
					<div style="position:relative;display:inline-block;">
						<input type="date" id="dcr-to-date"
							style="padding:10px 44px 10px 14px;border-radius:8px;border:2px solid #553c9a;background:#2d3748;color:#f7fafc;font-size:14px;min-width:170px;cursor:pointer;appearance:none;-webkit-appearance:none;"
							onclick="this.showPicker&&this.showPicker()">
						<span onclick="document.getElementById('dcr-to-date').showPicker&&document.getElementById('dcr-to-date').showPicker()"
							style="position:absolute;right:10px;top:50%;transform:translateY(-50%);font-size:18px;cursor:pointer;">📅</span>
					</div>
				</div>
				<div>
					<label style="display:block;color:#e2e8f0;font-size:12px;font-weight:600;margin-bottom:6px;">Branch</label>
					<select id="dcr-branch"
						style="padding:8px 12px;border-radius:8px;border:1px solid #4a5568;background:#2d3748;color:#f7fafc;font-size:13px;min-width:140px;">
						<option value="">All Branches</option>
					</select>
				</div>
				<button id="dcr-btn-run"
					style="padding:9px 22px;background:#805ad5;color:white;border:none;border-radius:8px;font-size:13px;font-weight:600;cursor:pointer;">
					📋 Generate Report
				</button>
				<button id="dcr-btn-csv"
					style="padding:9px 22px;background:#38a169;color:white;border:none;border-radius:8px;font-size:13px;font-weight:600;cursor:pointer;display:none;">
					⬇ Download CSV
				</button>
			</div>
			<div id="dcr-results"></div>
		</div>
	`;
	(wrapper.querySelector(".em-guide-wrap") || wrapper.querySelector(".page-content")).appendChild(daily_section);

	// Load branch list from ePromise
	frappe.call({
		method: "backup.epromise_migration.page.epromise_mapping_guide.epromise_mapping_guide.get_branch_list",
		callback(r) {
			const sel = document.getElementById("dcr-branch");
			(r.message || []).forEach(b => {
				const opt = document.createElement("option");
				opt.value = b.code; opt.text = b.code;
				sel.appendChild(opt);
			});
		}
	});

	// Sync dates with the Run Report inputs
	const syncDates = () => {
		const f = document.getElementById("rpt-from-date")?.value;
		const t = document.getElementById("rpt-to-date")?.value;
		if (f) document.getElementById("dcr-from-date").value = f;
		if (t) document.getElementById("dcr-to-date").value = t;
	};
	syncDates();
	document.getElementById("rpt-from-date")?.addEventListener("change", syncDates);
	document.getElementById("rpt-to-date")?.addEventListener("change", syncDates);

	let _last_dcr_data = null;

	function fmt_dcr(n) {
		if (!n || n === 0) return ".00";
		const abs = Math.abs(n).toFixed(3);
		return n < 0 ? `(${parseFloat(abs).toLocaleString(undefined,{minimumFractionDigits:2})})` :
		               parseFloat(abs).toLocaleString(undefined,{minimumFractionDigits:2});
	}

	function render_daily_report(data) {
		_last_dcr_data = data;
		const rows = data.rows || [];
		const s    = data.summary || {};
		const el   = document.getElementById("dcr-results");

		const catColors = {
			"sales":"#68d391","returns":"#fc8181","purchase":"#63b3ed",
			"cash":"#f6ad55","balance":"#f6e05e","":'#e2e8f0',
		};

		let html = `
			<p style="color:#718096;font-size:12px;margin:0 0 12px;">
				<strong style="color:#e2e8f0;">STEEL FORCE TRADING COMPANY W.L.L</strong>&nbsp;·&nbsp;
				Branch: <strong style="color:#63b3ed;">${data.branch||"All Branches"}</strong>&nbsp;·&nbsp;
				Period: <strong style="color:#e2e8f0;">${data.from_date||"All"}</strong> to
				<strong style="color:#e2e8f0;">${data.to_date||"All"}</strong>
			</p>
			<div style="overflow-x:auto;">
			<table style="width:100%;border-collapse:collapse;font-size:13px;">
				<thead>
					<tr style="border-bottom:2px solid #4a5568;background:#2d3748;">
						<th style="text-align:left;padding:10px 16px;color:#a0aec0;font-weight:700;width:55%;">Particulars</th>
						<th style="text-align:right;padding:10px 16px;color:#68d391;font-weight:700;width:22%;">Income</th>
						<th style="text-align:right;padding:10px 16px;color:#fc8181;font-weight:700;width:23%;">Expense</th>
					</tr>
				</thead>
				<tbody>`;

		rows.forEach(r => {
			if (r.separator) {
				html += `<tr><td colspan="3" style="padding:10px 16px;color:#4a5568;font-size:11px;
					letter-spacing:1px;border-top:1px solid #2d3748;border-bottom:1px solid #2d3748;
					background:#171923;">${r.label}</td></tr>`;
				return;
			}
			const c = catColors[r.category] || "#e2e8f0";
			const incomeVal  = r.income  ? fmt_dcr(r.income)  : ".00";
			const expenseVal = r.expense ? fmt_dcr(r.expense) : ".00";
			const incomeColor  = r.income  < 0 ? "#fc8181" : (r.income  > 0 ? "#68d391" : "#4a5568");
			const expenseColor = r.expense < 0 ? "#68d391" : (r.expense > 0 ? "#fc8181" : "#4a5568");
			const fw = r.bold ? "700" : "400";
			const isIndent = r.label.startsWith("  ");
			const hasDrill = !isIndent && r.drilldown;
			const bg = r.bold ? "background:#2d3748;" : isIndent ? "background:#171923;" : "";
			const labelColor = isIndent ? "#718096" : c;
			const labelStyle = isIndent ? "padding:5px 16px 5px 32px;font-size:12px;" : "padding:8px 16px;";
			const drillIcon = hasDrill ? ` <span style="font-size:10px;opacity:0.5;margin-left:6px;">▶</span>` : "";
			const cursor = hasDrill ? "cursor:pointer;" : "";
			const drillAttr = hasDrill ? `data-drilldown="${r.drilldown}" data-label="${r.label.trim()}"` : "";
			html += `
				<tr style="${bg}border-bottom:1px solid #1a202c;${cursor}"
					${drillAttr}
					onmouseover="this.style.background='#2d3748'" onmouseout="this.style.background='${r.bold?'#2d3748':isIndent?'#171923':''}'"  >
					<td style="${labelStyle}color:${labelColor};font-weight:${fw};">${r.label.trim()}${drillIcon}</td>
					<td style="padding:8px 16px;text-align:right;font-weight:${fw};color:${incomeColor};font-family:monospace;">
						${incomeVal}</td>
					<td style="padding:8px 16px;text-align:right;font-weight:${fw};color:${expenseColor};font-family:monospace;">
						${expenseVal}</td>
				</tr>`;
		});

		html += `</tbody></table></div>`;

		// Summary cards
		html += `
			<div style="margin-top:20px;display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;">`;
		[
			{label:"Net Cash Sales",      v:s.net_cash_sales,   c:"#68d391"},
			{label:"Net Credit Sales",    v:s.net_credit_sales, c:"#68d391"},
			{label:"Total Payments",      v:s.petty_payments,   c:"#fc8181"},
			{label:"Total Receipts",      v:s.petty_receipts,   c:"#63b3ed"},
			{label:"Cash Balance",        v:s.cash_balance,     c:s.cash_balance>=0?"#68d391":"#fc8181"},
		].forEach(item => {
			html += `
				<div style="background:#2d3748;border-radius:8px;padding:12px 14px;border-top:3px solid ${item.c};">
					<div style="color:#718096;font-size:11px;margin-bottom:4px;">${item.label}</div>
					<div style="color:${item.c};font-size:16px;font-weight:700;font-family:monospace;">
						${fmt_dcr(item.v)}</div>
				</div>`;
		});
		html += `</div>`;
		// Add detail panel after table
		html += `<div id="dcr-detail-panel" style="margin-top:16px;display:none;"></div>`;
		el.innerHTML = html;
		document.getElementById("dcr-btn-csv").style.display = "inline-block";

		// Attach click handlers for drilldown rows
		el.querySelectorAll("tr[data-drilldown]").forEach(tr => {
			tr.addEventListener("click", function() {
				const drilldown = this.dataset.drilldown;
				const label     = this.dataset.label;
				const from_date = document.getElementById("dcr-from-date").value;
				const to_date   = document.getElementById("dcr-to-date").value;
				const branch_code = document.getElementById("dcr-branch").value;
				const petty_cash_acc = (_last_dcr_data || {}).petty_cash_acc || "";

				// Toggle: if same row clicked, collapse
				const panel = document.getElementById("dcr-detail-panel");
				if (panel.dataset.active === drilldown) {
					panel.style.display = "none";
					panel.dataset.active = "";
					return;
				}
				panel.dataset.active = drilldown;
				panel.style.display = "block";
				panel.innerHTML = `<div style="color:#a0aec0;padding:16px;text-align:center;">⏳ Loading ${label}…</div>`;

				frappe.call({
					method: "backup.epromise_migration.page.epromise_mapping_guide.epromise_mapping_guide.get_voucher_detail",
					args: { from_date, to_date, drilldown, branch_code: branch_code || null, petty_cash_acc },
					callback(r) {
						const rows = r.message || [];
						if (!rows.length) {
							panel.innerHTML = `<div style="color:#718096;padding:16px;">No vouchers found for ${label}.</div>`;
							return;
						}
						let html = `
							<div style="background:#2d3748;border-radius:8px;padding:16px;">
								<div style="color:#e2e8f0;font-weight:700;font-size:13px;margin-bottom:12px;">
									${label} — ${rows.length} voucher(s)
								</div>
								<div style="overflow-x:auto;">
								<table style="width:100%;border-collapse:collapse;font-size:12px;">
									<thead><tr style="border-bottom:1px solid #4a5568;">
										<th style="text-align:left;padding:6px 10px;color:#a0aec0;">Date</th>
										<th style="text-align:left;padding:6px 10px;color:#a0aec0;">Voucher No</th>
										<th style="text-align:left;padding:6px 10px;color:#a0aec0;">Bill No</th>
										<th style="text-align:left;padding:6px 10px;color:#a0aec0;">Party</th>
										<th style="text-align:right;padding:6px 10px;color:#a0aec0;">Gross</th>
										<th style="text-align:right;padding:6px 10px;color:#a0aec0;">VAT</th>
										<th style="text-align:right;padding:6px 10px;color:#a0aec0;font-weight:700;">Net</th>
										<th style="text-align:left;padding:6px 10px;color:#a0aec0;">Remarks</th>
									</tr></thead><tbody>`;
						let totalNet = 0, totalGross = 0;
						rows.forEach(v => {
							totalNet += v.net; totalGross += v.gross;
							html += `<tr style="border-bottom:1px solid #1a202c;"
								onmouseover="this.style.background='#4a5568'" onmouseout="this.style.background=''">
								<td style="padding:5px 10px;color:#a0aec0;">${v.date}</td>
								<td style="padding:5px 10px;color:#63b3ed;font-family:monospace;">${v.vr_no}</td>
								<td style="padding:5px 10px;color:#718096;">${v.bill_no||"—"}</td>
								<td style="padding:5px 10px;color:#e2e8f0;max-width:180px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${v.party}">${v.party||"—"}</td>
								<td style="padding:5px 10px;text-align:right;color:#718096;font-family:monospace;">${v.gross.toFixed(3)}</td>
								<td style="padding:5px 10px;text-align:right;color:#718096;font-family:monospace;">${v.vat.toFixed(3)}</td>
								<td style="padding:5px 10px;text-align:right;color:#68d391;font-family:monospace;font-weight:700;">${v.net.toFixed(3)}</td>
								<td style="padding:5px 10px;color:#718096;font-size:11px;max-width:150px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${v.remarks}">${v.remarks||""}</td>
							</tr>`;
						});
						html += `
							<tr style="border-top:2px solid #4a5568;font-weight:700;">
								<td colspan="4" style="padding:7px 10px;color:#e2e8f0;">TOTAL (${rows.length} records)</td>
								<td style="padding:7px 10px;text-align:right;color:#e2e8f0;font-family:monospace;">${totalGross.toFixed(3)}</td>
								<td></td>
								<td style="padding:7px 10px;text-align:right;color:#68d391;font-family:monospace;">${totalNet.toFixed(3)}</td>
								<td></td>
							</tr>
							</tbody></table></div>
							<button onclick="document.getElementById('dcr-detail-panel').style.display='none';document.getElementById('dcr-detail-panel').dataset.active='';"
								style="margin-top:10px;padding:5px 14px;background:#4a5568;color:white;border:none;border-radius:6px;font-size:12px;cursor:pointer;">
								✕ Close
							</button></div>`;
						panel.innerHTML = html;
					},
					error() {
						panel.innerHTML = `<div style="color:#fc8181;padding:16px;">Error loading voucher detail.</div>`;
					}
				});
			});
		});
	}

	document.getElementById("dcr-btn-run").onclick = function () {
		const from_date   = document.getElementById("dcr-from-date").value;
		const to_date     = document.getElementById("dcr-to-date").value;
		const branch_code = document.getElementById("dcr-branch").value;
		const btn = this;
		btn.disabled = true;
		btn.textContent = "Running…";
		document.getElementById("dcr-results").innerHTML =
			'<div style="color:#a0aec0;padding:20px;text-align:center;">⏳ Querying ePromise database…</div>';

		frappe.call({
			method: "backup.epromise_migration.page.epromise_mapping_guide.epromise_mapping_guide.get_daily_collection_report",
			args: { from_date, to_date, branch_code: branch_code || null },
			callback(r) {
				btn.disabled = false;
				btn.textContent = "📋 Generate Report";
				if (r.message) render_daily_report(r.message);
			},
			error() {
				btn.disabled = false;
				btn.textContent = "📋 Generate Report";
				document.getElementById("dcr-results").innerHTML =
					'<div style="color:#fc8181;padding:20px;">Error — check SQL Server connection.</div>';
			},
		});
	};

	document.getElementById("dcr-btn-csv").onclick = function () {
		if (!_last_dcr_data) return;
		const rows = _last_dcr_data.rows || [];
		const s = _last_dcr_data.summary || {};
		const lines = [
			`STEEL FORCE TRADING COMPANY W.L.L`,
			`DAILY COLLECTION REPORT - ${_last_dcr_data.from_date||"All"} TO ${_last_dcr_data.to_date||"All"}`,
			"",
			"Particulars,Income,Expense",
		];
		rows.forEach(r => {
			if (r.separator) { lines.push(`${r.label},,`); return; }
			lines.push(`"${r.label}",${r.income||""},${r.expense||""}`);
		});
		lines.push("","SUMMARY");
		lines.push(`Net Cash Sales,,${s.net_cash_sales}`);
		lines.push(`Net Credit Sales,,${s.net_credit_sales}`);
		lines.push(`Total Payments,,${s.petty_payments}`);
		lines.push(`Total Receipts,${s.petty_receipts},`);
		lines.push(`Cash Balance,${s.cash_balance >= 0 ? s.cash_balance : ""},${s.cash_balance < 0 ? Math.abs(s.cash_balance) : ""}`);
		const blob = new Blob([lines.join("\n")], {type:"text/csv"});
		const a = document.createElement("a");
		a.href = URL.createObjectURL(blob);
		a.download = `daily_collection_${_last_dcr_data.from_date||"all"}.csv`;
		a.click();
	};
};
