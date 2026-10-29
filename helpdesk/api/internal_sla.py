import json

import frappe
from frappe import _
from frappe.utils import get_datetime, now_datetime, nowdate
from frappe.utils.xlsxutils import make_xlsx

from helpdesk.api.dashboard import COUNT_NAME
from helpdesk.helpdesk.doctype.hd_internal_sla_settings.hd_internal_sla_settings import (
    WEEKDAYS,
)
from helpdesk.helpdesk.doctype.hd_internal_sla_settings.hd_internal_sla_settings import (
    get_settings as get_settings_doc,
)
from helpdesk.utils import agent_only, is_dashboard_manager, xlsx_rows

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
    """Category -> sub-categories (crm owns the lists; empty when crm is not installed)."""
    try:
        from crm.api.messenger import get_ticket_categories
    except ImportError:
        return {}
    return get_ticket_categories()


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


# SLA breach report (BRD v12 §9): one row per ticket. (field, column header); fields missing on a site are skipped.
REPORT_COLUMNS = (
    ("name", "Ticket"),
    ("subject", "Subject"),
    ("custom_category", "Category"),
    ("custom_sub_category", "Sub Category"),
    ("agent_group", "Team"),
    ("_assign", "Owner"),
    ("internal_sla_tier", "Tier"),
    ("creation", "Created"),
    ("internal_sla_due_by", "Due"),
    ("investigation_status", "Investigation"),
    ("investigation_resolved_on", "Investigation Resolved On"),
    ("overdue_by", "Overdue By"),
    ("status", "Ticket Status"),
    ("internal_sla_status", "SLA Status"),
)
COMPUTED_COLUMNS = {"name", "_assign", "overdue_by"}
REPORT_PAGE_ROWS = 500


def overdue_text(delta):
    minutes = int(delta.total_seconds() // 60)
    if minutes <= 0:
        return ""
    if minutes < 60:
        return f"{minutes} min"
    if minutes < 24 * 60:
        return f"{minutes // 60} h {minutes % 60} min"
    return f"{minutes // (24 * 60)} d {minutes % (24 * 60) // 60} h"


def breach_report(filters, limit):
    """Breached (and, with include_at_risk, at-risk) tickets matching the ticket list's filter shape, oldest due first."""
    from helpdesk.api.ticket import build_card_filters

    filters = frappe.parse_json(filters) if filters else {}
    statuses = ["Breached", "At Risk"] if filters.get("include_at_risk") else ["Breached"]
    meta = frappe.get_meta("HD Ticket")
    columns = [(f, label) for f, label in REPORT_COLUMNS if f in COMPUTED_COLUMNS or meta.has_field(f)]
    base = build_card_filters(filters, True)
    conditions = [*base, ["internal_sla_status", "in", statuses]]
    # get_list keeps the agent's team restrictions, so the report shows what the ticket list shows
    rows = frappe.get_list(
        "HD Ticket",
        filters=conditions,
        fields=[f for f, _label in columns if f != "overdue_by"],
        order_by="internal_sla_due_by asc, name desc",
        limit_page_length=limit,
    )
    now = now_datetime()
    for row in rows:
        row["_assign"] = ", ".join(json.loads(row.get("_assign") or "[]"))
        end = get_datetime(row.investigation_resolved_on) if row.investigation_resolved_on else now
        row["overdue_by"] = (
            overdue_text(end - get_datetime(row.internal_sla_due_by)) if row.internal_sla_due_by else ""
        )
    return rows, columns, base, conditions


def report_summary(base, conditions):
    def count(filters):
        return frappe.get_list("HD Ticket", fields=[COUNT_NAME], filters=filters)[0].count or 0

    by_status = {
        row.status: row.count
        for row in frappe.get_list(
            "HD Ticket",
            fields=["internal_sla_status as status", COUNT_NAME],
            filters=[*base, ["internal_sla_status", "is", "set"]],
            group_by="internal_sla_status",
        )
    }
    tracked = sum(by_status.values())
    breached = by_status.get("Breached", 0)
    breached_open = count([*base, ["internal_sla_status", "=", "Breached"], ["investigation_status", "=", "Open"]])
    return {
        "tracked": tracked,
        "breached": breached,
        "breached_open": breached_open,
        "breached_resolved": breached - breached_open,
        "at_risk": by_status.get("At Risk", 0),
        "met": by_status.get("Met", 0),
        "on_track": by_status.get("On Track", 0),
        "breach_percent": round(breached / tracked * 100, 1) if tracked else 0,
        "total": count(conditions),  # rows matching the report's own filters
    }


@frappe.whitelist()
@agent_only
def get_breach_report(filters=None):
    rows, columns, base, conditions = breach_report(filters, REPORT_PAGE_ROWS)
    return {
        "rows": rows,
        "columns": [{"key": f, "label": _(label)} for f, label in columns],
        "summary": report_summary(base, conditions),
        "page_rows": REPORT_PAGE_ROWS,
    }


@frappe.whitelist()
@agent_only
def download_breach_report(filters=None):
    """Excel of every row of the breach report (no page limit)."""
    rows, columns, _base, _conditions = breach_report(filters, 0)
    data = [[_(label) for _f, label in columns]]
    data += [[row.get(f) for f, _label in columns] for row in rows]
    frappe.local.response.filename = f"sla-breach-report-{nowdate()}.xlsx"
    frappe.local.response.filecontent = make_xlsx(xlsx_rows(data), "SLA Breaches").getvalue()
    frappe.local.response.type = "download"
