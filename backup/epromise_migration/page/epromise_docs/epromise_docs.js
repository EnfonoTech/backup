frappe.pages["epromise-docs"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: "ePromise Migration Documentation",
		single_column: false,
	});

	// ── Nav buttons ────────────────────────────────────────────────────────────
	page.add_button("◀ Migration Dashboard", () => frappe.set_route("page", "epromise-migration"),  { icon: "fa fa-arrow-left" });
	page.add_button("📊 Mapping Guide",       () => frappe.set_route("page", "epromise-mapping-guide"), { icon: "fa fa-map" });
	page.set_primary_action("⬇ Download MD", () => {
		frappe.call({
			method: "backup.epromise_migration.page.epromise_docs.epromise_docs.get_documentation",
			callback(r) {
				if (!r.message) return;
				// Re-fetch raw MD (we only stored HTML in r.message)
				// Download via link to the Python md_path is not directly accessible,
				// so reconstruct the filename
				frappe.msgprint("Use the file at:<br><code>" + r.message.md_path + "</code>", "Documentation Path");
			}
		});
	}, "fa fa-download");

	// ── Inline styles ──────────────────────────────────────────────────────────
	const style = document.createElement("style");
	style.textContent = `
		.ep-doc-layout {
			display: flex;
			gap: 0;
			max-width: 1300px;
			margin: -20px auto 0;
			padding: 20px 16px 80px;
			font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
			background: #0f1117;
			min-height: calc(100vh - 60px);
		}

		/* ── TOC sidebar ── */
		.ep-toc {
			width: 240px;
			flex-shrink: 0;
			position: sticky;
			top: 70px;
			align-self: flex-start;
			max-height: calc(100vh - 90px);
			overflow-y: auto;
			padding: 16px 14px 24px 4px;
			border-right: 1px solid #2d3748;
			margin-right: 32px;
		}
		.ep-toc-title {
			font-size: 10px !important;
			font-weight: 700 !important;
			letter-spacing: 1.5px !important;
			text-transform: uppercase !important;
			color: #4a5568 !important;
			margin-bottom: 12px !important;
		}
		.ep-toc a {
			display: block !important;
			padding: 5px 4px 5px 10px !important;
			font-size: 12px !important;
			color: #a0aec0 !important;
			text-decoration: none !important;
			border-left: 2px solid transparent !important;
			line-height: 1.45 !important;
			transition: color 0.15s, border-color 0.15s !important;
			background: transparent !important;
		}
		.ep-toc a:hover { color: #63b3ed !important; border-left-color: #63b3ed !important; }
		.ep-toc a.active { color: #63b3ed !important; border-left-color: #63b3ed !important; background: #1a2035 !important; border-radius: 0 4px 4px 0 !important; }
		.ep-toc a.level-3 { padding-left: 22px !important; font-size: 11px !important; color: #718096 !important; }
		.ep-toc a.level-3:hover, .ep-toc a.level-3.active { color: #90cdf4 !important; border-left-color: #4299e1 !important; }

		/* ── Main content wrapper ── */
		.ep-doc-body { flex: 1; min-width: 0; }

		/* ── Markdown content ── */
		.ep-content {
			color: #cbd5e0 !important;
			line-height: 1.8 !important;
			font-size: 14px !important;
		}
		.ep-content * { color: inherit; }

		.ep-content h1 {
			font-size: 2rem !important; font-weight: 800 !important;
			color: #f7fafc !important; margin: 0 0 16px !important;
			border-bottom: 3px solid #4299e1 !important; padding-bottom: 12px !important;
		}
		.ep-content h2 {
			font-size: 1.25rem !important; font-weight: 700 !important;
			color: #f7fafc !important; margin: 44px 0 16px !important;
			padding: 12px 18px !important;
			background: #1a2035 !important;
			border-left: 5px solid #4299e1 !important;
			border-radius: 0 8px 8px 0 !important;
		}
		.ep-content h3 {
			font-size: 1.05rem !important; font-weight: 700 !important;
			color: #90cdf4 !important; margin: 32px 0 12px !important;
			padding: 6px 12px !important;
			border-left: 3px solid #4a5568 !important;
		}
		.ep-content h4 {
			font-size: 0.95rem !important; font-weight: 600 !important;
			color: #e2e8f0 !important; margin: 24px 0 10px !important;
		}
		.ep-content p  { margin: 0 0 14px !important; color: #cbd5e0 !important; }
		.ep-content ul, .ep-content ol { margin: 0 0 14px 22px !important; }
		.ep-content li { margin-bottom: 6px !important; color: #cbd5e0 !important; }
		.ep-content strong { color: #f7fafc !important; font-weight: 700 !important; }
		.ep-content em    { color: #a0aec0 !important; font-style: italic !important; }
		.ep-content a     { color: #63b3ed !important; text-decoration: underline !important; }

		.ep-content code {
			background: #2d3748 !important; color: #f6ad55 !important;
			padding: 2px 7px !important; border-radius: 4px !important;
			font-family: "Courier New", Courier, monospace !important;
			font-size: 0.84em !important; font-style: normal !important;
		}
		.ep-content pre {
			background: #0d1117 !important;
			border: 1px solid #2d3748 !important;
			border-radius: 8px !important;
			padding: 18px !important;
			overflow-x: auto !important;
			margin: 0 0 20px !important;
		}
		.ep-content pre code {
			background: none !important; color: #a8ff78 !important;
			padding: 0 !important; font-size: 0.82rem !important;
			line-height: 1.7 !important;
		}

		/* ── Tables — fully override Frappe defaults ── */
		.ep-content table {
			width: 100% !important; border-collapse: collapse !important;
			margin: 0 0 22px !important; font-size: 13px !important;
			background: #111827 !important;
			border: 1px solid #374151 !important;
			border-radius: 8px !important; overflow: hidden !important;
		}
		.ep-content thead { background: #1f2937 !important; }
		.ep-content th {
			background: #1f2937 !important;
			color: #9ca3af !important;
			font-weight: 700 !important;
			padding: 10px 14px !important;
			text-align: left !important;
			border-bottom: 2px solid #374151 !important;
			font-size: 11px !important;
			text-transform: uppercase !important;
			letter-spacing: 0.08em !important;
		}
		.ep-content tbody tr { background: #111827 !important; }
		.ep-content tbody tr:nth-child(even) { background: #161d27 !important; }
		.ep-content td {
			padding: 10px 14px !important;
			border-bottom: 1px solid #1f2937 !important;
			color: #e5e7eb !important;
			vertical-align: top !important;
			line-height: 1.6 !important;
			background: inherit !important;
		}
		.ep-content tbody tr:last-child td { border-bottom: none !important; }
		.ep-content tbody tr:hover td {
			background: #1e3a5f !important;
			color: #f3f4f6 !important;
		}
		.ep-content td code { color: #fbbf24 !important; background: #292524 !important; }

		/* ── Blockquote ── */
		.ep-content blockquote {
			border-left: 4px solid #4299e1 !important;
			margin: 0 0 16px !important;
			padding: 12px 18px !important;
			background: #1a2540 !important;
			border-radius: 0 6px 6px 0 !important;
			color: #a0aec0 !important;
		}
		.ep-content hr {
			border: none !important;
			border-top: 1px solid #2d3748 !important;
			margin: 36px 0 !important;
		}

		/* ── Copy button on pre ── */
		.ep-pre-wrap { position: relative !important; }
		.ep-copy-btn {
			position: absolute !important; top: 10px !important; right: 10px !important;
			background: #374151 !important; color: #d1d5db !important; border: none !important;
			border-radius: 4px; padding: 3px 8px; font-size: 10px;
			cursor: pointer; opacity: 0.7;
		}
		.ep-copy-btn:hover { opacity: 1 !important; background: #63b3ed !important; color: white !important; }
		/* Search highlight */
		.ep-highlight { background: #fbbf24 !important; color: #111 !important; border-radius: 2px !important; padding: 0 2px !important; }
		/* ── Search bar ── */
		.ep-search-wrap {
			margin-bottom: 20px !important;
			display: flex !important; gap: 10px !important; align-items: center !important;
		}
		.ep-search {
			flex: 1 !important; padding: 10px 16px !important; border-radius: 8px !important;
			border: 1px solid #374151 !important; background: #1f2937 !important;
			color: #f3f4f6 !important; font-size: 14px !important; outline: none !important;
		}
		.ep-search::placeholder { color: #6b7280 !important; }
		.ep-search:focus { border-color: #63b3ed !important; box-shadow: 0 0 0 2px rgba(99,179,237,0.2) !important; }
		.ep-search-count { color: #9ca3af !important; font-size: 12px !important; white-space: nowrap !important; }
	`;
	document.head.appendChild(style);

	// ── Shell ──────────────────────────────────────────────────────────────────
	$(wrapper).find(".page-content").html(`
		<div class="ep-doc-layout" id="ep-layout">
			<nav class="ep-toc" id="ep-toc">
				<div class="ep-toc-title">Contents</div>
				<div id="ep-toc-links"><span style="color:#4a5568;font-size:12px;">Loading…</span></div>
			</nav>
			<div class="ep-doc-body">
				<div class="ep-search-wrap">
					<input class="ep-search" id="ep-search" type="text" placeholder="🔍 Search documentation…">
					<span class="ep-search-count" id="ep-search-count"></span>
				</div>
				<div class="ep-content" id="ep-content">
					<div style="text-align:center;padding:60px;color:#718096;">
						<div style="font-size:32px;margin-bottom:16px;">⏳</div>
						Loading documentation…
					</div>
				</div>
			</div>
		</div>
	`);

	// ── Load content ───────────────────────────────────────────────────────────
	frappe.call({
		method: "backup.epromise_migration.page.epromise_docs.epromise_docs.get_documentation",
		callback(r) {
			if (!r.message) return;
			const { html, toc } = r.message;

			// Render content
			const content_el = document.getElementById("ep-content");
			content_el.innerHTML = html;

			// Add IDs to headings for anchor links + copy buttons on code blocks
			content_el.querySelectorAll("h2, h3").forEach(h => {
				const anchor = h.textContent.trim()
					.toLowerCase()
					.replace(/\s+/g, "-")
					.replace(/[\/&().,'`]/g, "");
				h.id = anchor;
				h.style.scrollMarginTop = "80px";
			});
			content_el.querySelectorAll("pre").forEach(pre => {
				const wrap = document.createElement("div");
				wrap.className = "ep-pre-wrap";
				pre.parentNode.insertBefore(wrap, pre);
				wrap.appendChild(pre);
				const btn = document.createElement("button");
				btn.className = "ep-copy-btn";
				btn.textContent = "Copy";
				btn.onclick = () => {
					navigator.clipboard.writeText(pre.innerText || "");
					btn.textContent = "✓ Copied";
					setTimeout(() => btn.textContent = "Copy", 1500);
				};
				wrap.appendChild(btn);
			});

			// Build TOC
			const toc_el = document.getElementById("ep-toc-links");
			toc_el.innerHTML = toc.map(item => `
				<a href="#${item.anchor}" class="level-${item.level}"
					onclick="document.getElementById('${item.anchor}')?.scrollIntoView({behavior:'smooth'});return false;">
					${item.title}
				</a>`).join("");

			// Highlight active TOC item on scroll
			const headings = content_el.querySelectorAll("h2, h3");
			const toc_links = toc_el.querySelectorAll("a");
			const observer = new IntersectionObserver(entries => {
				entries.forEach(entry => {
					if (entry.isIntersecting) {
						toc_links.forEach(a => {
							a.classList.toggle("active", a.getAttribute("href") === "#" + entry.target.id);
						});
					}
				});
			}, { rootMargin: "-10% 0% -80% 0%" });
			headings.forEach(h => observer.observe(h));
		},
		error() {
			document.getElementById("ep-content").innerHTML =
				'<p style="color:#fc8181;">Failed to load documentation. Check that EPROMISE_MIGRATION.md exists in the backup app root.</p>';
		}
	});

	// ── Search ─────────────────────────────────────────────────────────────────
	let _search_marks = [];
	document.getElementById("ep-search").addEventListener("input", function () {
		const term = this.value.trim().toLowerCase();
		const content = document.getElementById("ep-content");
		const count_el = document.getElementById("ep-search-count");

		// Remove previous highlights
		_search_marks.forEach(m => {
			const parent = m.parentNode;
			if (parent) parent.replaceChild(document.createTextNode(m.textContent), m);
		});
		_search_marks = [];
		if (content) content.normalize();

		if (!term || term.length < 2) { count_el.textContent = ""; return; }

		let count = 0;
		const walker = document.createTreeWalker(content, NodeFilter.SHOW_TEXT);
		const nodes = [];
		while (walker.nextNode()) nodes.push(walker.currentNode);

		nodes.forEach(node => {
			const idx = node.textContent.toLowerCase().indexOf(term);
			if (idx === -1) return;
			const mark = document.createElement("mark");
			mark.className = "ep-highlight";
			mark.textContent = node.textContent.substring(idx, idx + term.length);
			const before = document.createTextNode(node.textContent.substring(0, idx));
			const after  = document.createTextNode(node.textContent.substring(idx + term.length));
			const parent = node.parentNode;
			parent.replaceChild(after, node);
			parent.insertBefore(mark, after);
			parent.insertBefore(before, mark);
			_search_marks.push(mark);
			count++;
		});

		count_el.textContent = count > 0 ? `${count} match${count !== 1 ? "es" : ""}` : "No matches";
		if (_search_marks[0]) _search_marks[0].scrollIntoView({ behavior: "smooth", block: "center" });
	});
};
