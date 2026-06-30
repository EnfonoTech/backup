"""
Seed default ePromise → ERPNext field mappings.
Run once from the migration page or via bench execute.
"""

import frappe


_DEFAULT_MAPPINGS = [
    # ── Sales Invoice header fields (from DICHDATA — visible in Credit Sales screen) ──
    {"source_table": "DICHDATA", "source_field": "PARTICULARS",    "target_doctype": "Sales Invoice",    "target_field": "remarks",               "transform": "Direct Copy", "notes": "Invoice narration/description"},
    {"source_table": "DICHDATA", "source_field": "SALES_MAN",      "target_doctype": "Sales Invoice",    "target_field": "sales_team",            "transform": "Direct Copy", "notes": "ePromise salesman code (0002=AKHIL)"},
    {"source_table": "DICHDATA", "source_field": "CONTACT_PERSON", "target_doctype": "Sales Invoice",    "target_field": "contact_person_name",   "transform": "Direct Copy"},
    {"source_table": "DICHDATA", "source_field": "CONTACT_PHONE",  "target_doctype": "Sales Invoice",    "target_field": "contact_phone",         "transform": "Strip Whitespace"},
    {"source_table": "DICHDATA", "source_field": "CONTACT_ADDRESS","target_doctype": "Sales Invoice",    "target_field": "shipping_address_name", "transform": "Direct Copy"},
    {"source_table": "DICHDATA", "source_field": "EMAIL_ID",       "target_doctype": "Sales Invoice",    "target_field": "contact_email",         "transform": "Direct Copy"},
    {"source_table": "DICHDATA", "source_field": "LPO_NO",         "target_doctype": "Sales Invoice",    "target_field": "po_no",                 "transform": "Direct Copy", "notes": "Customer LPO/PO number"},
    {"source_table": "DICHDATA", "source_field": "SOURCE_BR_CODE", "target_doctype": "Sales Invoice",    "target_field": "cost_center",           "transform": "Direct Copy", "notes": "Branch/location code e.g. SFSB"},
    {"source_table": "DICHDATA", "source_field": "CREDIT_PERIOD",  "target_doctype": "Sales Invoice",    "target_field": "payment_terms_template","transform": "Direct Copy", "notes": "Credit days"},
    {"source_table": "DICHDATA", "source_field": "DISC_PERCENT",   "target_doctype": "Sales Invoice",    "target_field": "discount_amount",       "transform": "Direct Copy", "notes": "Header-level discount %"},
    {"source_table": "DICHDATA", "source_field": "NARRATION",      "target_doctype": "Sales Invoice",    "target_field": "remarks",               "transform": "Direct Copy", "notes": "Narration field (same as PARTICULARS)"},
    {"source_table": "DICHDATA", "source_field": "COUNTRY_NAME",   "target_doctype": "Sales Invoice",    "target_field": "customer_address",      "transform": "Direct Copy", "notes": "Customer country"},
    # ── Sales Invoice item fields (from SALES_DATA) ────────────────────────────
    {"source_table": "SALES_DATA", "source_field": "DISC_PERCENT", "target_doctype": "Sales Invoice Item","target_field": "discount_percentage",  "transform": "Direct Copy"},
    {"source_table": "SALES_DATA", "source_field": "VAT_RATE",     "target_doctype": "Sales Invoice Item","target_field": "tax_rate",             "transform": "Direct Copy"},
    # ── Purchase Invoice header (from DICHDATA — Purchase screens) ────────────
    {"source_table": "DICHDATA", "source_field": "PARTICULARS",    "target_doctype": "Purchase Invoice",  "target_field": "remarks",              "transform": "Direct Copy"},
    {"source_table": "DICHDATA", "source_field": "LPO_NO",         "target_doctype": "Purchase Invoice",  "target_field": "bill_no",              "transform": "Direct Copy", "notes": "Supplier bill/invoice number"},
    {"source_table": "DICHDATA", "source_field": "LC_NO",          "target_doctype": "Purchase Invoice",  "target_field": "letter_of_credit",     "transform": "Direct Copy", "notes": "LC number for import purchases"},
    {"source_table": "DICHDATA", "source_field": "CREDIT_PERIOD",  "target_doctype": "Purchase Invoice",  "target_field": "payment_terms_template","transform": "Direct Copy"},
    {"source_table": "DICHDATA", "source_field": "CONTACT_PERSON", "target_doctype": "Purchase Invoice",  "target_field": "contact_person",       "transform": "Direct Copy"},
    {"source_table": "DICHDATA", "source_field": "SOURCE_BR_CODE", "target_doctype": "Purchase Invoice",  "target_field": "cost_center",          "transform": "Direct Copy"},
    # ── Purchase Invoice item fields (from PURCHASE_DATA) ─────────────────────
    {"source_table": "PURCHASE_DATA", "source_field": "DISC_PERCENT","target_doctype": "Purchase Invoice Item","target_field": "discount_percentage","transform": "Direct Copy"},
    # ── Customer master (from DICADMAS) ───────────────────────────────────────
    {"source_table": "DICADMAS", "source_field": "ADDRESS",        "target_doctype": "Customer", "target_field": "customer_details",   "transform": "Direct Copy"},
    {"source_table": "DICADMAS", "source_field": "ACC_PHONE",      "target_doctype": "Customer", "target_field": "mobile_no",          "transform": "Strip Whitespace"},
    {"source_table": "DICADMAS", "source_field": "EMAIL_ADDRESS",  "target_doctype": "Customer", "target_field": "email_id",           "transform": "Direct Copy"},
    {"source_table": "DICADMAS", "source_field": "VAT_NO",         "target_doctype": "Customer", "target_field": "tax_id",             "transform": "Direct Copy", "notes": "VAT Registration Number"},
    {"source_table": "DICADMAS", "source_field": "CONTACT_PERSON", "target_doctype": "Customer", "target_field": "customer_details",   "transform": "Direct Copy", "notes": "Primary contact person name"},
    {"source_table": "DICADMAS", "source_field": "COUNTRY_CODE",   "target_doctype": "Customer", "target_field": "country",            "transform": "Direct Copy"},
    {"source_table": "DICADMAS", "source_field": "CREDIT_LIMIT",   "target_doctype": "Customer", "target_field": "credit_limit_amount","transform": "Direct Copy"},
    {"source_table": "DICADMAS", "source_field": "CREDIT_PERIOD",  "target_doctype": "Customer", "target_field": "payment_terms",      "transform": "Direct Copy"},
    # ── Supplier master (from DICADMAS sub_head=C) ────────────────────────────
    {"source_table": "DICADMAS", "source_field": "ADDRESS",        "target_doctype": "Supplier", "target_field": "supplier_details",   "transform": "Direct Copy"},
    {"source_table": "DICADMAS", "source_field": "ACC_PHONE",      "target_doctype": "Supplier", "target_field": "mobile_no",          "transform": "Strip Whitespace"},
    {"source_table": "DICADMAS", "source_field": "EMAIL_ADDRESS",  "target_doctype": "Supplier", "target_field": "email_id",           "transform": "Direct Copy"},
    {"source_table": "DICADMAS", "source_field": "VAT_NO",         "target_doctype": "Supplier", "target_field": "tax_id",             "transform": "Direct Copy"},
    {"source_table": "DICADMAS", "source_field": "COUNTRY_CODE",   "target_doctype": "Supplier", "target_field": "country",            "transform": "Direct Copy"},
    # ── Item master (from DICIHMAS) ────────────────────────────────────────────
    {"source_table": "DICIHMAS", "source_field": "GROUP_CODE",     "target_doctype": "Item", "target_field": "item_group_code",        "transform": "Direct Copy"},
    {"source_table": "DICIHMAS", "source_field": "FAMILY_CODE",    "target_doctype": "Item", "target_field": "item_collection",        "transform": "Direct Copy"},
    {"source_table": "DICIHMAS", "source_field": "BRAND_CODE",     "target_doctype": "Item", "target_field": "brand",                  "transform": "Direct Copy"},
    {"source_table": "DICIHMAS", "source_field": "SAL1_RATE",      "target_doctype": "Item", "target_field": "standard_rate",          "transform": "Direct Copy", "notes": "Wholesale rate from ePromise"},
    {"source_table": "DICIHMAS", "source_field": "VAT_RATE",       "target_doctype": "Item", "target_field": "tax_code",               "transform": "Direct Copy"},
    {"source_table": "DICIHMAS", "source_field": "REMARKS",        "target_doctype": "Item", "target_field": "description",            "transform": "Direct Copy"},
    # ── Payment Entry / Journal (from DICHDATA — Transaction screens) ─────────
    {"source_table": "DICHDATA", "source_field": "PARTICULARS",    "target_doctype": "Payment Entry",  "target_field": "remarks",         "transform": "Direct Copy", "notes": "Payment narration"},
    {"source_table": "DICHDATA", "source_field": "PAYEE_NAME",     "target_doctype": "Payment Entry",  "target_field": "party_name",      "transform": "Direct Copy", "notes": "Paid To / From"},
    {"source_table": "DICHDATA", "source_field": "PARTICULARS",    "target_doctype": "Journal Entry",  "target_field": "user_remark",     "transform": "Direct Copy"},
]


@frappe.whitelist()
def seed_default_mappings():
    """
    Create default ePromise Field Mapping records if they do not already exist.
    Returns a summary dict with counts of created and skipped records.
    """
    created = 0
    skipped = 0

    for m in _DEFAULT_MAPPINGS:
        name = f"{m['source_table']}-{m['source_field']}-{m['target_doctype']}"
        if frappe.db.exists("ePromise Field Mapping", name):
            skipped += 1
            continue

        doc = frappe.get_doc({
            "doctype": "ePromise Field Mapping",
            "source_table": m["source_table"],
            "source_field": m["source_field"],
            "target_doctype": m["target_doctype"],
            "target_field": m["target_field"],
            "transform": m.get("transform", "Direct Copy"),
            "enabled": 1,
            "notes": m.get("notes", ""),
        })
        doc.insert(ignore_permissions=True)
        created += 1

    frappe.db.commit()
    return {
        "created": created,
        "skipped": skipped,
        "message": f"Done — {created} mappings created, {skipped} already existed.",
    }
