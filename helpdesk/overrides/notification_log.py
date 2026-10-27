import frappe


def before_insert(doc, event=None):
    """Point HD Ticket notifications (assignment, mention, ...) at the helpdesk agent UI
    instead of the desk form. Notification Log prefers `link` over `/app/<doctype>/<name>`
    in both the bell dropdown and the notification email."""
    if doc.document_type == "HD Ticket" and doc.document_name and not doc.link:
        doc.link = frappe.utils.get_url(f"/helpdesk/tickets/{doc.document_name}")
