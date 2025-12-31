import frappe
from frappe.utils import now_datetime, add_to_date


@frappe.whitelist()
def clear(ticket: str | int = None, comment: str = None):
    """
    Mark notifications as read. No arguments will clear all notifications for `user`.

    :param ticket: Ticket to clear notifications for
    :param comment: Comment to clear notifications for
    """
    filters = {"user_to": frappe.session.user, "read": False}
    if ticket:
        filters["reference_ticket"] = ticket
    if comment:
        filters["reference_comment"] = comment
    for notification in frappe.get_all(
        "HD Notification", filters=filters, pluck="name"
    ):
        frappe.db.set_value("HD Notification", notification, "read", 1)


def notify_assignment_from_todo(doc, event=None):
    """
    Create assignment notification from ToDo record.
    Uses cache + database check to prevent duplicate notifications.
    """
    if doc.reference_type != "HD Ticket" or not doc.reference_name:
        return
    if not doc.allocated_to:
        return
    assigned_by = doc.assigned_by or frappe.session.user
    if assigned_by == doc.allocated_to:
        return

    reference_ticket = str(doc.reference_name)
    cache_key = f"hd_assignment_notif_{assigned_by}_{doc.allocated_to}_{reference_ticket}"
    
    # Fast path: Check cache first (handles race conditions within same process)
    try:
        if frappe.cache().get_value(cache_key):
            return
    except Exception:
        # Cache unavailable - continue with DB check (graceful degradation)
        pass
    
    # Check database for existing notification in the last 2 minutes
    # Shorter window is sufficient for race conditions and more performant
    two_minutes_ago = add_to_date(now_datetime(), minutes=-2, as_string=True)
    
    existing_notification = frappe.get_all(
        "HD Notification",
        filters={
            "user_from": assigned_by,
            "user_to": doc.allocated_to,
            "reference_ticket": reference_ticket,
            "notification_type": "Assignment",
            "creation": [">=", two_minutes_ago],
        },
        limit=1,
        pluck="name",
    )

    if existing_notification:
        # Set cache to prevent future duplicates (with error handling)
        try:
            frappe.cache().set_value(cache_key, True, expires_in_sec=120)  # 2 minutes
        except Exception:
            pass  # Cache failure is non-critical
        return

    # Set cache BEFORE insert to prevent race conditions
    # If insert fails, cache will expire naturally (2 min) - acceptable trade-off
    try:
        frappe.cache().set_value(cache_key, True, expires_in_sec=120)  # 2 minutes
    except Exception:
        pass  # Cache failure is non-critical, DB check will handle duplicates
    
    # Create the notification
    try:
        frappe.get_doc(
            frappe._dict(
                doctype="HD Notification",
                user_from=assigned_by,
                user_to=doc.allocated_to,
                reference_ticket=reference_ticket,
                notification_type="Assignment",
            )
        ).insert(ignore_permissions=True)
    except frappe.DuplicateEntryError:
        # Doctype-level duplicate check caught it - this is expected, just clear cache
        try:
            frappe.cache().expire(cache_key, 0)
        except Exception:
            pass
        # Silently ignore - duplicate was prevented at doctype level
        return
    except Exception:
        # Other errors - expire cache and re-raise
        try:
            frappe.cache().expire(cache_key, 0)
        except Exception:
            pass
        raise  # Re-raise to let Frappe handle the error
