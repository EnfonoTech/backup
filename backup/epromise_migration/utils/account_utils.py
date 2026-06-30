"""
Auto-create Account ledgers for Customer / Supplier and enforce Title Case.

Hooked via doc_events in hooks.py:
  Customer  → validate     → apply_title_case
  Customer  → after_insert → create_customer_account
  Supplier  → validate     → apply_title_case
  Supplier  → after_insert → create_supplier_account

On after_insert the hook:
  1. Creates an Account ledger under the AR / AP group.
  2. Links that account back into the Customer / Supplier's Default Accounts
     child table (Party Account) so the Accounting tab shows the ledger and
     Sales / Purchase Invoices use the correct receivable / payable account.
"""

import frappe

COMPANY   = "Steel Force Trading Bahrain"
ABBR      = "SFTB"
AR_PARENT = "1303 - Accounts Receivables - SFTB"   # Accounts Receivables group
AP_PARENT = "2201 - Accounts Payable - SFTB"        # Accounts Payable group
CURRENCY  = "BHD"


# ── Title Case ────────────────────────────────────────────────────────────────

def apply_title_case(doc, method=None):
    """Enforce Title Case on customer / supplier name on every save."""
    if doc.doctype == "Customer" and doc.customer_name:
        doc.customer_name = doc.customer_name.strip().title()
    elif doc.doctype == "Supplier" and doc.supplier_name:
        doc.supplier_name = doc.supplier_name.strip().title()


# ── Account auto-creation ─────────────────────────────────────────────────────

def create_customer_account(doc, method=None):
    """Create a Receivable ledger and link it to the Customer's Default Accounts."""
    account_name = _create_account(
        party_name=doc.customer_name or doc.name,
        parent_account=AR_PARENT,
        account_type="Receivable",
    )
    if account_name:
        _link_party_account(doc.name, "Customer", account_name)


def create_supplier_account(doc, method=None):
    """Create a Payable ledger and link it to the Supplier's Default Accounts."""
    account_name = _create_account(
        party_name=doc.supplier_name or doc.name,
        parent_account=AP_PARENT,
        account_type="Payable",
    )
    if account_name:
        _link_party_account(doc.name, "Supplier", account_name)


def _create_account(party_name, parent_account, account_type):
    """
    Create an Account ledger under parent_account for this party.
    Returns the account name (whether newly created or already existing).
    Returns None on failure.
    """
    # Return existing account if already created
    existing = frappe.db.get_value(
        "Account",
        {"account_name": party_name, "company": COMPANY},
        "name",
    )
    if existing:
        return existing

    if not frappe.db.exists("Account", parent_account):
        frappe.log_error(
            f"Parent account '{parent_account}' not found — "
            f"cannot create {account_type} account for '{party_name}'.",
            "Account Auto-Creation",
        )
        return None

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
        return acct.name
    except Exception as exc:
        frappe.log_error(
            f"Failed to create {account_type} account for '{party_name}': {exc}",
            "Account Auto-Creation",
        )
        return None


def _link_party_account(party_name, party_doctype, account_name):
    """
    Add account_name to the party's Default Accounts child table (Party Account)
    for COMPANY, if not already present.

    Uses a direct DB insert into tabParty Account to avoid triggering parent
    validation hooks (e.g. VAT checks on Supplier) which would block the save.
    """
    # Check if this company is already mapped in the child table
    existing = frappe.db.get_value(
        "Party Account",
        {"parent": party_name, "parenttype": party_doctype, "company": COMPANY},
        ["name", "account"],
        as_dict=True,
    )
    if existing:
        if existing.account != account_name:
            frappe.db.set_value("Party Account", existing.name, "account", account_name)
            frappe.db.commit()
        return

    try:
        # Determine next idx for child rows
        max_idx = frappe.db.sql(
            "SELECT COALESCE(MAX(idx), 0) FROM `tabParty Account` WHERE parent=%s AND parenttype=%s",
            (party_name, party_doctype),
        )[0][0]
        row_name = frappe.generate_hash(party_name + COMPANY, 10)
        frappe.db.sql(
            """INSERT INTO `tabParty Account`
               (name, creation, modified, modified_by, owner, docstatus,
                parent, parentfield, parenttype, idx, company, account)
               VALUES (%s, NOW(), NOW(), 'Administrator', 'Administrator', 0,
                       %s, 'accounts', %s, %s, %s, %s)""",
            (row_name, party_name, party_doctype, max_idx + 1, COMPANY, account_name),
        )
        frappe.db.commit()
    except Exception as exc:
        frappe.log_error(
            f"Failed to link account '{account_name}' to {party_doctype} '{party_name}': {exc}",
            "Account Auto-Creation",
        )
