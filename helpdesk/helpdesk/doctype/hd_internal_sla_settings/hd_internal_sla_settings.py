import json
from datetime import datetime, time, timedelta

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import escape_html, flt, format_datetime, get_datetime, get_url, now_datetime

from helpdesk.utils import is_agent

WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
# Agents edit investigation_status and internal_sla_tier; the rest is computed here.
TICKET_FIELDS = (
    "investigation_status",
    "investigation_resolved_on",
    "internal_sla_tier",
    "internal_sla_status",
    "internal_sla_warning_by",
    "internal_sla_due_by",
)
# Rule column -> the HD Ticket field it is compared with (category fields come from crm).
RULE_FIELDS = {
    "category": "custom_category",
    "sub_category": "custom_sub_category",
    "ticket_type": "ticket_type",
    "team": "agent_group",
}


class HDInternalSLASettings(Document):
    def validate(self):
        for tier in self.tiers:
            tier.tier = (tier.tier or "").strip()
            if flt(tier.target) <= 0:
                frappe.throw(_("Tier {0} needs a target greater than 0").format(tier.tier))
        names = [tier.tier for tier in self.tiers]
        if len(set(names)) != len(names):
            frappe.throw(_("Tier names must be unique"))
        for rule in self.rules:
            if rule.tier and rule.tier not in names:
                frappe.throw(_("Rule {0} uses unknown tier {1}").format(rule.idx, rule.tier))
        if not 0 < flt(self.warning_percent) < 100:
            frappe.throw(_("Warn at % elapsed must be between 0 and 100"))


def get_settings():
    return frappe.get_cached_doc("HD Internal SLA Settings")


def due_after(start, target, unit, working_weekdays, holidays):
    """When `target` `unit`s have passed since `start`.

    Minutes and hours run around the clock; days count only working weekdays that are not holidays."""
    if unit != "Days":
        return start + timedelta(minutes=flt(target) * (60 if unit == "Hours" else 1))
    remaining = timedelta(days=flt(target))
    current = start
    # ponytail: bounded day walk; ten years without a working day is a broken calendar, not a due date
    for _day in range(3660):
        next_day = datetime.combine(current.date() + timedelta(days=1), time.min)
        if current.weekday() in working_weekdays and current.date() not in holidays:
            if remaining <= next_day - current:
                return current + remaining
            remaining -= next_day - current
        current = next_day
    return current


def match_tier(values, settings):
    """Tier of the first rule whose filled-in columns all equal the ticket's values; None = no internal SLA."""
    for rule in settings.rules:
        if all(not rule.get(col) or rule.get(col) == values.get(field) for col, field in RULE_FIELDS.items()):
            return rule.tier or None
    return None


def get_status(ticket, now=None):
    if not ticket.internal_sla_due_by:
        return ""
    due = get_datetime(ticket.internal_sla_due_by)
    if ticket.investigation_status == "Resolved":
        return "Met" if get_datetime(ticket.investigation_resolved_on) <= due else "Breached"
    now = now or now_datetime()
    if now >= due:
        return "Breached"
    if ticket.internal_sla_warning_by and now >= get_datetime(ticket.internal_sla_warning_by):
        return "At Risk"
    return "On Track"


def apply_internal_sla(doc):
    """HD Ticket before_save: track the department's investigation against the ticket's internal SLA tier."""
    try:
        settings = get_settings()
    except frappe.DoesNotExistError:  # code deployed before migrate synced the doctype
        return
    old = doc.get_doc_before_save()
    if doc.is_new():
        # Split tickets deep-copy their parent and portal input is not trusted, so start clean.
        for field in TICKET_FIELDS:
            doc.set(field, None)
        doc.investigation_status = "Open"
    elif not is_agent():
        for field in TICKET_FIELDS:
            doc.set(field, old.get(field))
        return
    if not doc.investigation_status:  # tickets from before this feature are not tracked
        return
    if doc.has_value_changed("investigation_status"):
        doc.investigation_resolved_on = now_datetime() if doc.investigation_status == "Resolved" else None
    if not settings.enabled:
        return

    if not doc.internal_sla_tier and (doc.is_new() or not old.investigation_status):
        doc.internal_sla_tier = match_tier(doc, settings)
    elif (
        old
        and any(old.get(field) != doc.get(field) for field in RULE_FIELDS.values())
        and doc.internal_sla_tier in (None, "", match_tier(old, settings))
    ):
        # Re-routing moves an auto-picked tier along; a tier an agent picked by hand stays.
        doc.internal_sla_tier = match_tier(doc, settings)

    if doc.has_value_changed("internal_sla_tier"):
        set_due_times(doc, settings)
    if doc.has_value_changed("internal_sla_tier") or doc.has_value_changed("investigation_status"):
        # Only scan_internal_sla moves an open investigation to At Risk / Breached, so each alert goes out once.
        if not doc.internal_sla_due_by:
            doc.internal_sla_status = ""
        else:
            doc.internal_sla_status = get_status(doc) if doc.investigation_status == "Resolved" else "On Track"


def set_due_times(doc, settings):
    tier = next((row for row in settings.tiers if row.tier == doc.internal_sla_tier), None)
    if doc.internal_sla_tier and not tier:
        frappe.throw(_("Unknown internal SLA tier: {0}").format(doc.internal_sla_tier))
    if not tier:
        doc.internal_sla_warning_by = doc.internal_sla_due_by = None
        return
    start = get_datetime(doc.creation or now_datetime())
    working = {i for i, day in enumerate(WEEKDAYS) if settings.get(day)} or set(range(7))
    holidays = set()
    if settings.holiday_list:
        holidays = set(
            frappe.get_all(
                "HD Holiday",
                filters={"parent": settings.holiday_list, "parenttype": "HD Service Holiday List"},
                pluck="holiday_date",
            )
        )
    warning = flt(tier.target) * flt(settings.warning_percent) / 100
    doc.internal_sla_due_by = due_after(start, tier.target, tier.unit, working, holidays)
    doc.internal_sla_warning_by = due_after(start, warning, tier.unit, working, holidays)


def scan_internal_sla():
    """Scheduler (every minute): move open investigations to At Risk / Breached and alert once per step."""
    settings = get_settings()
    if not settings.enabled:
        return
    now = now_datetime()
    tickets = frappe.get_all(
        "HD Ticket",
        filters={
            "internal_sla_status": ["in", ["On Track", "At Risk"]],
            "internal_sla_warning_by": ["<=", now],
        },
        fields=["name", "subject", "owner", "_assign", *TICKET_FIELDS],
    )
    for ticket in tickets:
        status = get_status(ticket, now)
        if status == ticket.internal_sla_status:
            continue
        try:
            frappe.db.set_value("HD Ticket", ticket.name, "internal_sla_status", status, update_modified=False)
            notify(ticket, status, settings)
        except Exception:
            frappe.log_error(f"Internal SLA scan failed for ticket {ticket.name}")


def notify(ticket, status, settings):
    users = set(json.loads(ticket._assign or "[]"))
    # helpdesk.utils.is_agent(user) is always True while the scheduler runs as Administrator
    if not users and frappe.db.exists("HD Agent", {"name": ticket.owner, "is_active": 1}):
        users.add(ticket.owner)
    if status == "Breached":
        users.update(row.user for row in settings.breach_recipients if row.user)
    if not users:
        return

    if status == "Breached":
        message = _("Ticket #{0} breached its internal SLA ({1}, due {2}): {3}")
    else:
        message = _("Ticket #{0} is at risk of breaching its internal SLA ({1}, due {2}): {3}")
    due = format_datetime(ticket.internal_sla_due_by, "d MMM yyyy, h:mm a")
    message = message.format(ticket.name, ticket.internal_sla_tier, due, ticket.subject)
    for user in users:
        frappe.get_doc(
            {
                "doctype": "HD Notification",
                "user_from": "Administrator",
                "user_to": user,
                "notification_type": "SLA Alert",
                "reference_ticket": ticket.name,
                "message": message,
            }
        ).insert(ignore_permissions=True)

    if not settings.send_email:
        return
    recipients = frappe.get_all("User", filters={"name": ["in", list(users)], "enabled": 1}, pluck="email")
    if recipients := [email for email in recipients if email]:
        link = get_url(f"/helpdesk/tickets/{ticket.name}")
        frappe.sendmail(
            recipients=recipients,
            subject=message,
            message=f'{escape_html(message)}<br><br><a href="{link}">{link}</a>',
            reference_doctype="HD Ticket",
            reference_name=ticket.name,
        )
