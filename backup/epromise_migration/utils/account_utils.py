"""
Auto-create Account ledgers for Customer / Supplier and enforce Title Case.

Hooked via doc_events in hooks.py:
  Customer  → validate → apply_title_case
  Customer  → after_insert → create_customer_account
  Supplier  → validate → apply_title_case
  Supplier  → after_insert → create_supplier_account
"""

import frappe

COMPANY     = "Steel Force Trading Bahrain"
ABBR        = "SFTB"
AR_PARENT   = "1303 - Accounts Receivables - SFTB"   # Accounts Receivables group
AP_PARENT   = "2201 - Accounts Payable - SFTB"        # Accounts Payable group
CURRENCY    = "BHD"


# ── Title Case ────────────────────────────────────────────────────────────────

def apply_title_case(doc, method=None):
    """Enforce Title Case on customer / supplier name on every save."""
    if doc.doctype == "Customer" and doc.customer_name:
        doc.customer_name = doc.customer_name.strip().title()
    elif doc.doctype == "Supplier" and doc.supplier_name:
        doc.supplier_name = doc.supplier_name.strip().title()


# ── Account auto-creation ─────────────────────────────────────────────────────

def create_customer_account(doc, method=None):
    """Create a Receivable ledger under AR group when a new Customer is saved."""
    _create_account(
        party_name=doc.customer_name or doc.name,
        parent_account=AR_PARENT,
        account_type="Receivable",
    )


def create_supplier_account(doc, method=None):
    """Create a Payable ledger under AP group when a new Supplier is saved."""
    _create_account(
        party_name=doc.supplier_name or doc.name,
        parent_account=AP_PARENT,
        account_type="Payable",
    )


def _create_account(party_name, parent_account, account_type):
    # Skip if an account with this name already exists for the company
    if frappe.db.exists("Account", {"account_name": party_name, "company": COMPANY}):
        return

    if not frappe.db.exists("Account", parent_account):
        frappe.log_error(
            f"Parent account '{parent_account}' not found — "
            f"cannot create {account_type} account for '{party_name}'.",
            "Account Auto-Creation",
        )
        return

    try:
        acct = frappe.get_doc({
            "doctype": "Account",
            "account_name": party_name,
            "parent_account": parent_account,
            "account_type": account_type,
            "account_currency": CURRENCY,
            "company": COMPANY,
            "is_group": 0,
        })
        acct.flags.ignore_permissions = True
        acct.insert()
        frappe.db.commit()
    except Exception as exc:
        frappe.log_error(
            f"Failed to create {account_type} account for '{party_name}': {exc}",
            "Account Auto-Creation",
        )
