frappe.pages['epromise-attachment-verification'].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: 'ePromise Attachment Verification',
		single_column: true,
	});

	new AttachmentVerification(page);
};

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

		this.page.set_primary_action('Refresh', () => this.refresh(), 'refresh');
	}

	setup_table() {
		this.$wrapper = $(`
			<div class="epv-wrapper" style="margin-top: 15px;">
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
							<th style="width: 160px;">Actions</th>
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
	}

	refresh() {
		const me = this;
		this.$tbody.html('<tr><td colspan="8" class="text-muted">Loading...</td></tr>');

		frappe.call({
			method: 'backup.epromise_migration.attachment_verification.get_rows',
			args: {
				trc_code: this.trc_field.get_value() || null,
				status: this.status_field.get_value() || 'all',
				search: this.search_field.get_value() || null,
				limit_start: this.limit_start,
				limit_page_length: this.page_length,
			},
			callback(r) {
				me.render(r.message);
			},
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
	}

	render_row(row) {
		const meta = STATUS_META[row.status] || { label: row.status, color: 'grey' };
		const key = [row.fy_code, row.trc_code, row.vr_no, row.attachment].join('||');
		const matched_html = row.matched_name
			? `<a href="/app/${frappe.router.slug(row.doctype)}/${encodeURIComponent(row.matched_name)}" target="_blank">${frappe.utils.escape_html(row.matched_name)}</a>`
			: (row.candidates && row.candidates.length ? `${row.candidates.length} candidates` : '-');

		let actions = `<button class="btn btn-xs btn-default epv-preview" data-key="${key}">Preview</button> `;
		if (row.status === 'clean') {
			actions += `<button class="btn btn-xs btn-primary epv-attach" data-key="${key}">Attach</button>`;
		} else if (row.status === 'unmatched' || row.status === 'duplicate') {
			actions += `<button class="btn btn-xs btn-warning epv-manual" data-key="${key}">Pick target</button>`;
		}

		return `
			<tr data-key="${key}">
				<td>${frappe.utils.escape_html(row.trc_code)}</td>
				<td>${frappe.utils.escape_html(row.vr_no)}</td>
				<td>${frappe.datetime.str_to_user(row.vr_date) || ''}</td>
				<td title="${frappe.utils.escape_html(row.attachment)}">${frappe.utils.escape_html(row.attachment)}</td>
				<td>${row.doctype || '-'}</td>
				<td>${matched_html}</td>
				<td><span class="indicator ${meta.color}">${meta.label}</span></td>
				<td>${actions}</td>
			</tr>
		`;
	}

	render_pagination() {
		this.$pagination.empty();
		if (this.limit_start > 0) {
			$('<button class="btn btn-xs btn-default">Previous</button>')
				.on('click', () => { this.limit_start = Math.max(0, this.limit_start - this.page_length); this.refresh(); })
				.appendTo(this.$pagination);
		} else {
			$('<span></span>').appendTo(this.$pagination);
		}
		if (this.limit_start + this.page_length < this.total) {
			$('<button class="btn btn-xs btn-default">Next</button>')
				.on('click', () => { this.limit_start += this.page_length; this.refresh(); })
				.appendTo(this.$pagination);
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
		this.$tbody.find('.epv-attach').on('click', function () {
			me.confirm_attach(by_key[$(this).data('key')]);
		});
		this.$tbody.find('.epv-manual').on('click', function () {
			me.manual_pick(by_key[$(this).data('key')]);
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

	manual_pick(row) {
		const me = this;
		const d = new frappe.ui.Dialog({
			title: `Manually attach: ${row.attachment}`,
			fields: [
				{ label: 'Doctype', fieldname: 'doctype', fieldtype: 'Select',
					options: ['Sales Invoice', 'Purchase Invoice', 'Purchase Receipt', 'Payment Entry', 'Journal Entry'].join('\n'),
					default: row.doctype || undefined, reqd: 1 },
				{ label: 'Document Name', fieldname: 'docname', fieldtype: 'Dynamic Link',
					options: 'doctype', reqd: 1,
					description: row.candidates && row.candidates.length
						? `Candidates from auto-match: ${row.candidates.join(', ')}` : undefined },
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
	}
}
