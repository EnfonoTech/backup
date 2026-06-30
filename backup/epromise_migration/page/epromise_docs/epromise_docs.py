import frappe
import os


def get_context(context):
    context.no_cache = 1


@frappe.whitelist()
def get_documentation():
    """Read EPROMISE_MIGRATION.md and return as HTML with section metadata."""
    md_path = os.path.join(
        frappe.get_app_path("backup"), "..", "EPROMISE_MIGRATION.md"
    )
    md_path = os.path.normpath(md_path)

    if not os.path.exists(md_path):
        return {"html": "<p>Documentation file not found.</p>", "toc": []}

    with open(md_path, "r", encoding="utf-8") as f:
        md_text = f.read()

    # Convert markdown to HTML using Frappe's built-in converter
    html = frappe.utils.md_to_html(md_text)

    # Build Table of Contents from headings
    toc = []
    for line in md_text.splitlines():
        if line.startswith("## "):
            title = line[3:].strip()
            anchor = title.lower().replace(" ", "-").replace("/", "").replace("&", "").replace("(", "").replace(")", "").replace(".", "").replace(",", "").replace("'", "").replace("`", "")
            toc.append({"level": 2, "title": title, "anchor": anchor})
        elif line.startswith("### "):
            title = line[4:].strip()
            anchor = title.lower().replace(" ", "-").replace("/", "").replace("&", "").replace("(", "").replace(")", "").replace(".", "").replace(",", "").replace("'", "").replace("`", "")
            toc.append({"level": 3, "title": title, "anchor": anchor})

    return {
        "html":        html,
        "toc":         toc,
        "md_path":     md_path,
        "last_updated": frappe.utils.cstr(
            frappe.utils.get_datetime(
                frappe.utils.now_datetime()
            ).strftime("%Y-%m-%d")
        ),
    }
