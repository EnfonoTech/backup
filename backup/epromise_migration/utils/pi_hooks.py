import frappe


def route_stock_expense(doc, method=None):
    """PI goods stay on SRBNB (ERPNext default for stock items when update_stock=0).
    We only backfill a cost center where missing; no expense-account override, so all
    goods land in Stock Received But Not Billed."""
    if doc.doctype != "Purchase Invoice":
        return
    if getattr(doc, "update_stock", 0):
        return
    cc = frappe.db.get_value("Company", doc.company, "cost_center")
    if not cc:
        return
    for it in doc.items:
        if not it.cost_center:
            it.cost_center = cc
