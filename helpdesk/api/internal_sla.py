import frappe
from frappe import _

from helpdesk.helpdesk.doctype.hd_internal_sla_settings.hd_internal_sla_settings import (
    WEEKDAYS,
)
from helpdesk.helpdesk.doctype.hd_internal_sla_settings.hd_internal_sla_settings import (
    get_settings as get_settings_doc,
)
from helpdesk.utils import agent_only, is_dashboard_manager

EDITABLE_FIELDS = (
    "enabled",
    "warning_percent",
    *WEEKDAYS,
    "holiday_list",
    "tiers",
    "rules",
    "breach_recipients",
    "send_email",
)


def get_categories():
    """Category -> sub-categories (crm's ticket categories, when crm is installed)."""
    try:
        from crm.api.messenger import TICKET_CATEGORIES
    except ImportError:
        return {}
    return {category: list(sub_categories) for category, sub_categories in TICKET_CATEGORIES.items()}


def check_manager():
    # same audience as the settings tab (auth.isAdmin || auth.isManager)
    if not (is_dashboard_manager() or "System Manager" in frappe.get_roles()):
        frappe.throw(_("Not permitted"), frappe.PermissionError)


@frappe.whitelist()
@agent_only
def get_options():
    settings = get_settings_doc()
    return {
        "enabled": settings.enabled,
        "tiers": [tier.tier for tier in settings.tiers],
        "categories": get_categories(),
    }


@frappe.whitelist()
def get_settings():
    check_manager()
    return {
        "settings": frappe.get_single("HD Internal SLA Settings").as_dict(),
        "categories": get_categories(),
    }


@frappe.whitelist()
def save_settings(settings):
    check_manager()
    values = frappe.parse_json(settings)
    doc = frappe.get_single("HD Internal SLA Settings")
    doc.update({field: values[field] for field in EDITABLE_FIELDS if field in values})
    doc.save(ignore_permissions=True)
    return get_settings()
