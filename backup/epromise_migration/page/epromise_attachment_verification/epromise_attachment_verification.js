frappe.pages['epromise-attachment-verification'].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: 'ePromise Attachment Verification',
		single_column: true,
	});

	new AttachmentVerification(page);
};

const DOCTYPE_OPTIONS = ['Sales Invoice', 'Purchase Invoice', 'Purchase Receipt', 'Payment Entry', 'Journal Entry'];

const CONFIDENCE_META = {
	high: { label: 'High', color: 'green' },
	medium: { label: 'Medium', color: 'orange' },
	low: { label: 'Low', color: 'grey' },
};

function render_voucher_info_html(v) {
	if (!v || !v.found) {
		return '<div class="text-muted">No matching voucher found in the transactional ePromise database for this row.</div>';
	}
	// { raw: true } rows already come out of a Frappe formatter (frappe.format / str_to_user) and
	// are safe, self-contained HTML -- escaping them a second time turns their own markup into
	// visible text. Everything else is untrusted plain text straight out of dichdata and MUST be
	// escaped.
	const branch = v.source_branch && v.target_branch && v.source_branch !== v.target_branch
		? `${v.source_branch} -> ${v.target_branch}` : (v.source_branch || v.target_branch || '-');
	const ref = v.ref_trc_code && v.ref_vr_no ? `${v.ref_trc_code}/${v.ref_vr_no}` : '-';

	const rows = [
		{ label: 'Voucher Date', value: frappe.datetime.str_to_user(v.vr_date), raw: true },
		{ label: 'Amount', value: v.amount != null ? frappe.format(v.amount, { fieldtype: 'Currency', options: v.currency }) : '-', raw: true },
		{ label: 'Currency', value: v.currency ? `${v.currency}${v.currency_rate ? ' @ ' + v.currency_rate : ''}` : '-' },
		{ label: 'VAT Amount', value: v.vat_amount != null ? frappe.format(v.vat_amount, { fieldtype: 'Currency', options: v.currency }) : '-', raw: true },
		{ label: 'Total VAT', value: v.total_vat != null ? frappe.format(v.total_vat, { fieldtype: 'Currency', options: v.currency }) : '-', raw: true },
		{ label: 'Particulars', value: v.particulars || '-' },
		{ label: 'Payee Name', value: v.payee_name || '-' },
		{ label: 'Supplier Name', value: v.supplier_name || '-' },
		{ label: 'Account', value: v.acc_name || '-' },
		{ label: 'Bill No', value: v.bill_no || '-' },
		{ label: 'Bill Date', value: v.bill_date ? frappe.datetime.str_to_user(v.bill_date) : '-', raw: true },
		{ label: 'Tax Invoice No', value: v.tax_invoice_no || '-' },
		{ label: 'LPO No', value: v.lpo_no || '-' },
		{ label: 'Branch', value: branch },
		{ label: 'References Voucher', value: ref },
		{ label: 'Posted (ePromise)', value: v.posted === 'Y' ? 'Yes' : (v.posted === 'N' ? 'No' : '-') },
		{ label: 'Created By', value: v.created_user || '-' },
		{ label: 'Created On', value: v.created_date ? frappe.datetime.str_to_user(v.created_date) : '-', raw: true },
	];
	return '<table class="table table-bordered">' + rows.map(function (r) {
		const value = r.raw ? String(r.value) : frappe.utils.escape_html(String(r.value));
		return '<tr><th style="width:150px;">' + r.label + '</th><td>' + value + '</td></tr>';
	}).join('') + '</table>';
}

const STATUS_META = {
	clean: { label: 'Ready to attach', color: 'blue' },
	attached: { label: 'Already attached', color: 'green' },
	unmatched: { label: 'No match found', color: 'orange' },
	duplicate: { label: 'Multiple matches', color: 'red' },
	fields_missing: { label: 'Not migrated on this site', color: 'grey' },
	out_of_scope: { label: 'Not migrated (TRC not mapped)', color: 'grey' },
};

class AttachmentVerification {
	constructor(page) {
		this.page = page;
		this.limit_start = 0;
		this.page_length = 50;
		this.show_thumbnails = false;
		this.setup_filters();
		this.setup_table();
		this.refresh();
	}

	setup_filters() {
		const me = this;

		this.trc_field = this.page.add_field({
			label: 'TRC Code', fieldtype: 'Select', fieldname: 'trc_code',
			options: '\nS01\nS06\nR01\nR04\n350\n111\nIP\nPR\nGRN\nGR\n003\n004\n020\n007',
			change() { me.limit_start = 0; me.refresh(); },
		});

		this.doctype_field = this.page.add_field({
			label: 'Target Doctype (ERPNext)', fieldtype: 'Select', fieldname: 'target_doctype',
			options: [''].concat(DOCTYPE_OPTIONS).join('\n'),
			change() { me.limit_start = 0; me.refresh(); },
		});

		this.status_field = this.page.add_field({
			label: 'Status', fieldtype: 'Select', fieldname: 'status',
			options: [
				{ label: 'All', value: 'all' },
				{ label: 'Ready to attach', value: 'clean' },
				{ label: 'Already attached', value: 'attached' },
				{ label: 'No match found', value: 'unmatched' },
				{ label: 'Multiple matches', value: 'duplicate' },
				{ label: 'Not migrated', value: 'out_of_scope' },
				{ label: 'Not migrated on this site', value: 'fields_missing' },
			].map((o) => o.value).join('\n'),
			default: 'clean',
			change() { me.limit_start = 0; me.refresh(); },
		});
		this.status_field.set_value('clean');

		this.search_field = this.page.add_field({
			label: 'Search (filename / VR No)', fieldtype: 'Data', fieldname: 'search',
			change: frappe.utils.debounce(() => { me.limit_start = 0; me.refresh(); }, 400),
		});

		this.from_date_field = this.page.add_field({
			label: 'From Date', fieldtype: 'Date', fieldname: 'from_date',
			change() { me.limit_start = 0; me.refresh(); },
		});

		this.to_date_field = this.page.add_field({
			label: 'To Date', fieldtype: 'Date', fieldname: 'to_date',
			change() { me.limit_start = 0; me.refresh(); },
		});

		this.thumbnail_field = this.page.add_field({
			label: 'Show Thumbnails', fieldtype: 'Check', fieldname: 'show_thumbnails',
			change() { me.show_thumbnails = !!me.thumbnail_field.get_value(); me.refresh(); },
		});

		this.page.set_primary_action('Refresh', () => this.refresh(), 'refresh');
		this.page.add_action_item('Bulk Attach (clean matches, current filters)', () => this.bulk_attach());
	}

	get_filter_args() {
		return {
			trc_code: this.trc_field.get_value() || null,
			target_doctype: this.doctype_field.get_value() || null,
			search: this.search_field.get_value() || null,
			from_date: this.from_date_field.get_value() || null,
			to_date: this.to_date_field.get_value() || null,
		};
	}

	setup_table() {
		this.$wrapper = $(`
			<div class="epv-wrapper" style="margin-top: 15px;">
				<div class="epv-status-bar" style="margin-bottom: 12px;"></div>
				<div class="epv-summary text-muted small" style="margin-bottom: 8px;"></div>
				<table class="table table-bordered epv-table">
					<thead>
						<tr>
							<th style="width: 70px;">TRC</th>
							<th style="width: 110px;">VR No</th>
							<th style="width: 100px;">Date</th>
							<th>Attachment</th>
							<th style="width: 130px;">Target Doctype</th>
							<th style="width: 160px;">Matched Doc</th>
							<th style="width: 150px;">Status</th>
							<th style="width: 220px;">Actions</th>
						</tr>
					</thead>
					<tbody></tbody>
				</table>
				<div class="epv-pagination" style="display:flex; justify-content: space-between; align-items:center;"></div>
			</div>
		`).appendTo(this.page.main);

		this.$tbody = this.$wrapper.find('tbody');
		this.$summary = this.$wrapper.find('.epv-summary');
		this.$pagination = this.$wrapper.find('.epv-pagination');
		this.$status_bar = this.$wrapper.find('.epv-status-bar');
	}

	refresh() {
		const me = this;
		this.$tbody.html('<tr><td colspan="8" class="text-muted">Loading...</td></tr>');
		this.$status_bar.html('<span class="text-muted">Loading...</span>');

		frappe.call({
			method: 'backup.epromise_migration.attachment_verification.get_rows',
			args: Object.assign({}, this.get_filter_args(), {
				status: this.status_field.get_value() || 'all',
				limit_start: this.limit_start,
				limit_page_length: this.page_length,
			}),
			callback(r) {
				// one call now returns both the page of rows AND the full-filter status counts
				// (see attachment_verification.py get_rows docstring) -- this used to be two
				// separate full-dataset scans per refresh, which is what made the page feel slow.
				me.render_status_bar(r.message.counts);
				me.render(r.message);
			},
		});
	}

	render_status_bar(counts) {
		const me = this;
		const badges = [
			['clean', 'Ready to attach', 'blue'],
			['attached', 'Already attached', 'green'],
			['unmatched', 'No match found', 'orange'],
			['duplicate', 'Multiple matches', 'red'],
			['out_of_scope', 'Not migrated', 'grey'],
			['fields_missing', 'Not migrated on site', 'grey'],
		];
		let html = '<div style="display:flex; align-items:center; gap:10px; flex-wrap:wrap;">';
		badges.forEach(function ([key, label, color]) {
			html += `<span class="indicator ${color}" style="cursor:pointer;" data-status="${key}">${label}: <b>${counts[key] || 0}</b></span>`;
		});
		if (counts.clean) {
			html += `<button class="btn btn-sm btn-primary epv-bulk-attach-glance">⚡ Bulk Attach all ${counts.clean} Ready-to-attach</button>`;
		}
		html += '</div>';
		this.$status_bar.html(html);

		this.$status_bar.find('[data-status]').on('click', function () {
			me.status_field.set_value($(this).data('status'));
		});
		this.$status_bar.find('.epv-bulk-attach-glance').on('click', function () {
			me.bulk_attach();
		});
	}

	render(data) {
		const { rows, total } = data;
		this.total = total;

		if (!rows.length) {
			this.$tbody.html('<tr><td colspan="8" class="text-muted">No rows match these filters.</td></tr>');
		} else {
			this.$tbody.html(rows.map((row) => this.render_row(row)).join(''));
		}

		this.$summary.text(
			`${total} row(s) matching filters. Showing ${this.limit_start + 1}-${Math.min(this.limit_start + rows.length, total)}.`
		);
		this.render_pagination();
		this.bind_row_actions(rows);
		if (this.show_thumbnails) this.load_thumbnails(rows);
	}

	render_row(row) {
		const meta = STATUS_META[row.status] || { label: row.status, color: 'grey' };
		const key = [row.fy_code, row.trc_code, row.vr_no, row.attachment].join('||');
		const matched_html = row.matched_name
			? `<a href="/app/${frappe.router.slug(row.doctype)}/${encodeURIComponent(row.matched_name)}" target="_blank">${frappe.utils.escape_html(row.matched_name)}</a>`
			: (row.candidates && row.candidates.length ? `${row.candidates.length} candidates` : '-');

		let actions = `<button class="btn btn-xs btn-default epv-preview" data-key="${key}">Preview</button> `;
		actions += `<button class="btn btn-xs btn-default epv-info" data-key="${key}">Info</button> `;
		if (row.status === 'clean') {
			actions += `<button class="btn btn-xs btn-primary epv-attach" data-key="${key}">Attach</button>`;
		} else if (row.status === 'unmatched' || row.status === 'duplicate') {
			actions += `<button class="btn btn-xs btn-warning epv-manual" data-key="${key}">Pick target</button>`;
		} else if (row.status === 'attached') {
			actions += `<button class="btn btn-xs btn-danger epv-detach" data-key="${key}">Detach</button>`;
		}

		const attachment_cell = `<span class="epv-thumb-slot" data-key="${key}">${frappe.utils.escape_html(row.attachment)}</span>`;

		return `
			<tr data-key="${key}">
				<td>${frappe.utils.escape_html(row.trc_code)}</td>
				<td>${frappe.utils.escape_html(row.vr_no)}</td>
				<td>${frappe.datetime.str_to_user(row.vr_date) || ''}</td>
				<td title="${frappe.utils.escape_html(row.attachment)}">${attachment_cell}</td>
				<td>${row.doctype || '-'}</td>
				<td>${matched_html}</td>
				<td><span class="indicator ${meta.color}">${meta.label}</span></td>
				<td>${actions}</td>
			</tr>
		`;
	}

	load_thumbnails(rows) {
		const eligible = rows.filter(function (row) {
			const ext = (row.attachment.match(/\.[^.]+$/) || [''])[0].toLowerCase();
			return ['.jpg', '.jpeg', '.png', '.gif', '.webp'].includes(ext) && (row.blob_size || 0) <= 150 * 1024;
		});
		if (!eligible.length) return;

		frappe.call({
			method: 'backup.epromise_migration.attachment_verification.get_thumbnails',
			args: { rows: eligible.map((row) => ({
				fy_code: row.fy_code, trc_code: row.trc_code, vr_no: row.vr_no,
				attachment: row.attachment, blob_size: row.blob_size,
			})) },
			callback: (r) => {
				const thumbs = r.message || {};
				Object.keys(thumbs).forEach((key) => {
					const t = thumbs[key];
					this.$tbody.find(`.epv-thumb-slot[data-key="${CSS.escape(key)}"]`)
						.prepend(`<img src="data:${t.mime};base64,${t.data}" style="max-height:40px; max-width:60px; margin-right:6px; vertical-align:middle;" />`);
				});
			},
		});
	}

	render_pagination() {
		this.$pagination.empty();

		const $left = $('<div></div>').appendTo(this.$pagination);
		if (this.limit_start > 0) {
			$('<button class="btn btn-xs btn-default">Previous</button>')
				.on('click', () => { this.limit_start = Math.max(0, this.limit_start - this.page_length); this.refresh(); })
				.appendTo($left);
		}

		// Standard list-view-style page-size picker -- same idea as the desk list view's own
		// 20/100/500/2500 row, sized to this page's own default (50) instead.
		const $right = $('<div class="btn-group"></div>').appendTo(this.$pagination);
		[50, 100, 500].forEach((size) => {
			$(`<button class="btn btn-xs ${size === this.page_length ? 'btn-primary' : 'btn-default'}">${size}</button>`)
				.on('click', () => {
					if (size === this.page_length) return;
					this.page_length = size;
					this.limit_start = 0;
					this.refresh();
				})
				.appendTo($right);
		});
		if (this.limit_start + this.page_length < this.total) {
			$('<button class="btn btn-xs btn-default" style="margin-left:8px;">Next</button>')
				.on('click', () => { this.limit_start += this.page_length; this.refresh(); })
				.appendTo($right);
		}
	}

	bind_row_actions(rows) {
		const me = this;
		const by_key = {};
		rows.forEach((row) => {
			by_key[[row.fy_code, row.trc_code, row.vr_no, row.attachment].join('||')] = row;
		});

		this.$tbody.find('.epv-preview').on('click', function () {
			me.show_preview(by_key[$(this).data('key')]);
		});
		this.$tbody.find('.epv-info').on('click', function () {
			me.show_voucher_info(by_key[$(this).data('key')]);
		});
		this.$tbody.find('.epv-attach').on('click', function () {
			me.confirm_attach(by_key[$(this).data('key')]);
		});
		this.$tbody.find('.epv-manual').on('click', function () {
			me.manual_pick(by_key[$(this).data('key')]);
		});
		this.$tbody.find('.epv-detach').on('click', function () {
			me.confirm_detach(by_key[$(this).data('key')]);
		});
	}

	show_preview(row) {
		frappe.call({
			method: 'backup.epromise_migration.attachment_verification.get_preview',
			args: { fy_code: row.fy_code, trc_code: row.trc_code, vr_no: row.vr_no, attachment: row.attachment },
			callback(r) {
				const d = new frappe.ui.Dialog({ title: row.attachment, size: 'large' });
				if (r.message.previewable) {
					if (r.message.mime === 'application/pdf') {
						d.$body.html(`<embed src="data:${r.message.mime};base64,${r.message.data}" style="width:100%; height:70vh;" />`);
					} else {
						d.$body.html(`<img src="data:${r.message.mime};base64,${r.message.data}" style="max-width:100%;" />`);
					}
				} else {
					d.$body.html(`<div class="text-muted">${frappe.utils.escape_html(r.message.reason)}</div>`);
				}
				d.show();
			},
		});
	}

	show_voucher_info(row) {
		frappe.call({
			method: 'backup.epromise_migration.attachment_verification.get_voucher_info',
			args: { fy_code: row.fy_code, trc_code: row.trc_code, vr_no: row.vr_no },
			callback(r) {
				const d = new frappe.ui.Dialog({ title: `ePromise voucher ${row.trc_code}/${row.vr_no}` });
				d.$body.html(render_voucher_info_html(r.message));
				d.show();
			},
		});
	}

	confirm_attach(row) {
		const me = this;
		frappe.confirm(
			`Attach <b>${frappe.utils.escape_html(row.attachment)}</b> to ${row.doctype} <b>${frappe.utils.escape_html(row.matched_name)}</b> as a public file?`,
			() => {
				frappe.call({
					method: 'backup.epromise_migration.attachment_verification.attach_row',
					args: { fy_code: row.fy_code, trc_code: row.trc_code, vr_no: row.vr_no, attachment: row.attachment },
					freeze: true,
					callback(r) {
						frappe.show_alert({ message: `Attached: ${r.message.file_url}`, indicator: 'green' });
						me.refresh();
					},
				});
			}
		);
	}

	confirm_detach(row) {
		const me = this;
		frappe.confirm(
			`Remove <b>${frappe.utils.escape_html(row.attachment)}</b> from ${row.doctype} <b>${frappe.utils.escape_html(row.matched_name)}</b>? This deletes the File record.`,
			() => {
				frappe.call({
					method: 'backup.epromise_migration.attachment_verification.detach_row',
					args: { fy_code: row.fy_code, trc_code: row.trc_code, vr_no: row.vr_no, attachment: row.attachment },
					freeze: true,
					callback() {
						frappe.show_alert({ message: 'Detached.', indicator: 'orange' });
						me.refresh();
					},
				});
			}
		);
	}

	manual_pick(row) {
		const me = this;
		const d = new frappe.ui.Dialog({
			title: `Manually attach: ${row.attachment}`,
			size: 'large',
			fields: [
				{ label: 'ePromise Voucher', fieldname: 'voucher_html', fieldtype: 'HTML' },
				{ fieldname: 'col_break_1', fieldtype: 'Column Break' },
				{ label: 'Doctype', fieldname: 'doctype', fieldtype: 'Select',
					options: DOCTYPE_OPTIONS.join('\n'),
					default: row.doctype || undefined, reqd: 1,
					change() { me.refresh_suggestions(d, row); } },
				{ label: 'Document Name', fieldname: 'docname', fieldtype: 'Dynamic Link',
					options: 'doctype', reqd: 1,
					description: row.candidates && row.candidates.length
						? `Candidates from auto-match: ${row.candidates.map((c) => `${c.doctype} ${c.name}`).join(', ')}`
						: undefined },
				{ fieldname: 'sec_break_1', fieldtype: 'Section Break', label: 'Fuzzy match suggestions (amount + date + party)' },
				{ fieldname: 'suggestions_html', fieldtype: 'HTML' },
			],
			primary_action_label: 'Attach',
			primary_action(values) {
				frappe.call({
					method: 'backup.epromise_migration.attachment_verification.attach_row',
					args: {
						fy_code: row.fy_code, trc_code: row.trc_code, vr_no: row.vr_no, attachment: row.attachment,
						override_doctype: values.doctype, override_name: values.docname,
					},
					freeze: true,
					callback(r) {
						frappe.show_alert({ message: `Attached: ${r.message.file_url}`, indicator: 'green' });
						d.hide();
						me.refresh();
					},
				});
			},
		});
		d.show();

		frappe.call({
			method: 'backup.epromise_migration.attachment_verification.get_voucher_info',
			args: { fy_code: row.fy_code, trc_code: row.trc_code, vr_no: row.vr_no },
			callback(r) {
				d.fields_dict.voucher_html.$wrapper.html(render_voucher_info_html(r.message));
			},
		});

		this.refresh_suggestions(d, row);
	}

	refresh_suggestions(d, row) {
		const doctype = d.get_value('doctype');
		if (!doctype) return;
		d.fields_dict.suggestions_html.$wrapper.html('<div class="text-muted">Loading suggestions...</div>');

		frappe.call({
			method: 'backup.epromise_migration.attachment_verification.suggest_candidates',
			args: { doctype, fy_code: row.fy_code, trc_code: row.trc_code, vr_no: row.vr_no },
			callback(r) {
				const candidates = (r.message && r.message.candidates) || [];
				if (!candidates.length) {
					d.fields_dict.suggestions_html.$wrapper.html('<div class="text-muted">No same-doctype documents found near this voucher\'s date.</div>');
					return;
				}
				const html = '<table class="table table-bordered">' +
					'<thead><tr><th>Confidence</th><th>Document</th><th>Date</th><th>Amount</th><th>Amount diff</th><th>Days diff</th><th>Party match</th><th></th></tr></thead><tbody>' +
					candidates.map(function (c) {
						const conf = CONFIDENCE_META[c.confidence] || CONFIDENCE_META.low;
						const party_pct = c.party_score != null ? Math.round(c.party_score * 100) + '%' : '-';
						return '<tr>' +
							'<td><span class="indicator ' + conf.color + '">' + conf.label + '</span></td>' +
							'<td>' + frappe.utils.escape_html(c.name) + '</td>' +
							'<td>' + frappe.datetime.str_to_user(c.posting_date) + '</td>' +
							'<td>' + frappe.format(c.amount, { fieldtype: 'Currency' }) + '</td>' +
							'<td>' + frappe.format(c.amount_diff, { fieldtype: 'Currency' }) + '</td>' +
							'<td>' + c.date_diff + '</td>' +
							'<td>' + party_pct + '</td>' +
							'<td><button class="btn btn-xs btn-default epv-pick-suggestion" data-name="' + frappe.utils.escape_html(c.name) + '">Use this</button></td>' +
							'</tr>';
					}).join('') + '</tbody></table>';
				d.fields_dict.suggestions_html.$wrapper.html(html);
				d.fields_dict.suggestions_html.$wrapper.find('.epv-pick-suggestion').on('click', function () {
					d.set_value('docname', $(this).data('name'));
				});
			},
		});
	}

	bulk_attach() {
		const me = this;
		const filter_args = this.get_filter_args();

		frappe.call({
			method: 'backup.epromise_migration.attachment_verification.get_rows',
			args: Object.assign({}, filter_args, { status: 'clean', limit_start: 0, limit_page_length: 1 }),
			callback(r) {
				const total = r.message.total;
				if (!total) {
					frappe.msgprint('No "Ready to attach" rows under the current filters.');
					return;
				}
				frappe.confirm(
					`Bulk-attach all <b>${total}</b> currently "Ready to attach" row(s) under these filters? Rows that are unmatched or ambiguous are never touched -- only clean single-matches.`,
					() => me.run_bulk_attach(filter_args, total)
				);
			},
		});
	}

	run_bulk_attach(filter_args, total_estimate) {
		const me = this;
		const d = new frappe.ui.Dialog({ title: 'Bulk Attach', fields: [{ fieldname: 'log_html', fieldtype: 'HTML' }] });
		d.show();
		d.get_close_btn().hide();

		let attached_count = 0;
		const failed = [];

		function render() {
			d.fields_dict.log_html.$wrapper.html(
				'<div>Attached: <b>' + attached_count + '</b> / ~' + total_estimate + '</div>' +
				(failed.length ? '<div class="text-danger" style="margin-top:8px;">Failed (' + failed.length + '):</div>' +
					'<table class="table table-bordered"><tbody>' +
					failed.map(function (f) {
						return '<tr><td>' + frappe.utils.escape_html(f.trc_code) + '/' + frappe.utils.escape_html(f.vr_no) +
							'</td><td>' + frappe.utils.escape_html(f.attachment) + '</td><td class="text-danger">' +
							frappe.utils.escape_html(f.error) + '</td></tr>';
					}).join('') + '</tbody></table>' : '')
			);
		}
		render();

		function step() {
			frappe.call({
				method: 'backup.epromise_migration.attachment_verification.bulk_attach',
				args: Object.assign({}, filter_args, { batch_size: 20 }),
				callback(r) {
					const msg = r.message;
					attached_count += msg.attached.length;
					failed.push(...msg.failed);
					render();

					if (msg.processed === 0) {
						d.get_close_btn().show();
						d.set_title('Bulk Attach -- done');
						frappe.show_alert({ message: `Bulk attach done: ${attached_count} attached, ${failed.length} failed.`, indicator: failed.length ? 'orange' : 'green' });
						me.refresh();
						return;
					}
					step();
				},
			});
		}
		step();
	}
}
