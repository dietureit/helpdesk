import json

import frappe
from frappe import _
from frappe.utils import get_timespan_date_range, now_datetime, nowdate
from frappe.utils.xlsxutils import make_xlsx

from helpdesk.utils import agent_only, is_agent, xlsx_rows


def assign_ticket_to_agent(ticket_id, agent_id=None):
    if not ticket_id:
        return

    ticket_doc = frappe.get_doc("HD Ticket", ticket_id)

    if not agent_id:
        # assign to self
        agent_id = frappe.session.user

    if not frappe.db.exists("HD Agent", agent_id):
        frappe.throw(_("Tickets can only be assigned to agents"))

    ticket_doc.assign_agent(agent_id)
    return ticket_doc


@frappe.whitelist()
@agent_only
def bulk_assign_ticket_to_agent(ticket_ids, agent_id=None):
    if ticket_ids:
        ticket_docs = []
        for ticket_id in ticket_ids:
            ticket_doc = assign_ticket_to_agent(ticket_id, agent_id)
            ticket_docs.append(ticket_doc)
        return ticket_docs


FILTER_OPERATORS = {"=", "!=", "<", ">", "<=", ">=", "like", "not like", "in", "not in", "between", "timespan", "is"}
STANDARD_FILTER_FIELDS = {"name", "creation", "modified", "modified_by", "owner", "_assign"}
# The customer portal shares this endpoint; customers may only filter on these.
CUSTOMER_FILTER_FIELDS = {"name", "status", "priority", "ticket_type", "creation", "modified", "resolution_date"}
SEARCH_FIELDS = (
    "name",
    "subject",
    "raised_by",
    "contact",
    "customer",
    "custom_customer_name",
    "custom_customer_phone",
    "custom_phone",
    "custom_messenger_conversation",  # the conversation name contains the customer's name
)


def build_card_filters(raw_filters, agent):
    """Check the card view's {field: value | [operator, operand]} filters and turn them into get_list filters."""
    meta = frappe.get_meta("HD Ticket")
    filters = []
    if agent and raw_filters.get("overdue"):
        # customer SLA: still open and past the resolution due time
        open_statuses = frappe.get_all("HD Ticket Status", filters={"category": "Open"}, pluck="name")
        filters += [["status", "in", open_statuses or ["Open"]], ["resolution_by", "<", now_datetime()]]
    for field, value in raw_filters.items():
        if field not in STANDARD_FILTER_FIELDS and not meta.has_field(field):
            continue
        if not agent and field not in CUSTOMER_FILTER_FIELDS:
            continue
        if isinstance(value, (list, tuple)):
            if len(value) != 2 or str(value[0]).lower() not in FILTER_OPERATORS:
                continue
            operator, operand = str(value[0]).lower(), value[1]
        else:
            operator, operand = "=", value
        if operator == "timespan" and not get_timespan_date_range(operand):
            continue  # get_list would silently fall back to today
        if operator == "between":
            operand = operand.split(",") if isinstance(operand, str) else operand
            if not isinstance(operand, (list, tuple)) or len(operand) != 2:
                continue
        if operator == "is" and operand not in ("set", "not set"):
            continue
        filters.append([field, operator, operand])
    return filters


def build_search_filters(raw_filters):
    """`search` text as or_filters: LIKE on the ticket id, subject and customer fields."""
    search_text = (raw_filters.get("search") or "").strip()
    if not search_text:
        return []
    meta = frappe.get_meta("HD Ticket")
    return [
        [field, "like", f"%{search_text}%"]
        for field in SEARCH_FIELDS
        if field == "name" or meta.has_field(field)
    ]


# (field, column header) for the Excel export; fields missing on a site are skipped
EXPORT_COLUMNS = (
    ("name", "Ticket"),
    ("subject", "Subject"),
    ("status", "Status"),
    ("investigation_status", "Investigation Status"),
    ("priority", "Priority"),
    ("ticket_type", "Ticket Type"),
    ("custom_category", "Category"),
    ("custom_sub_category", "Sub Category"),
    ("custom_complaints_description", "Complaint Description"),
    ("custom_department", "Department"),
    ("agent_group", "Team"),
    ("_assign", "Assigned To"),
    ("owner", "Created By"),
    ("raised_by", "Raised By"),
    ("custom_customer_name", "Customer Name"),
    ("custom_customer_phone", "Customer Phone"),
    ("customer", "Customer"),
    ("contact", "Contact"),
    ("custom_select_channel", "Channel"),
    ("custom_select_source", "Source"),
    ("custom_messenger_conversation", "Messenger Conversation"),
    ("creation", "Created On"),
    ("first_responded_on", "First Responded On"),
    ("resolution_date", "Resolved On"),
    ("custom_solution", "Resolution Provided"),
    ("custom_complaint_status", "Complaint Status"),
    ("custom_follow_up_status", "Follow-up Status"),
    ("agreement_status", "Customer SLA"),
    ("resolution_by", "Resolution Due By"),
    ("internal_sla_tier", "Internal SLA Tier"),
    ("internal_sla_status", "Internal SLA Status"),
    ("internal_sla_due_by", "Internal SLA Due By"),
    ("investigation_resolved_on", "Investigation Resolved On"),
)


@frappe.whitelist()
@agent_only
def export_tickets(filters=None):
    """Excel file of every ticket matching the card view's filters and search (all pages)."""
    filters = frappe.parse_json(filters) if filters else {}
    meta = frappe.get_meta("HD Ticket")
    columns = [
        (field, label)
        for field, label in EXPORT_COLUMNS
        if field in STANDARD_FILTER_FIELDS or meta.has_field(field)
    ]
    tickets = frappe.get_list(
        "HD Ticket",
        filters=build_card_filters(filters, True),
        or_filters=build_search_filters(filters),
        fields=[field for field, _label in columns],
        order_by="name desc",
        limit_page_length=0,
    )
    rows = [[_(label) for _field, label in columns]]
    for ticket in tickets:
        ticket["_assign"] = ", ".join(json.loads(ticket.get("_assign") or "[]"))
        rows.append([ticket.get(field) for field, _label in columns])

    frappe.local.response.filename = f"tickets-{nowdate()}.xlsx"
    frappe.local.response.filecontent = make_xlsx(xlsx_rows(rows), "Tickets").getvalue()
    frappe.local.response.type = "download"


@frappe.whitelist()
def get_tickets_for_card_view(
    filters=None,
    limit=20,
    offset=0,
    order_by="name desc"
):
    """Tickets for the card view. `filters` is {field: value | [operator, operand]}, plus `search` and `overdue`."""
    filters = frappe.parse_json(filters) if filters else {}
    parsed_filters = build_card_filters(filters, is_agent())
    or_filters = build_search_filters(filters)

    # Default to ticket id based ordering so permission queries still apply.
    order_by_value = "name desc"

    tickets = frappe.get_list(
        "HD Ticket",
        filters=parsed_filters,
        or_filters=or_filters,
        fields=[
            "name",
            "subject",
            "status",
            "status_category",
            "priority",
            "creation",
            "modified",
            "raised_by",
            "agent_group",
            "first_responded_on",
            "resolution_date",
            "response_by",
            "resolution_by",
            "agreement_status",
            "contact",
            "_assign",
            "_liked_by",
            "_comments",
        ],
        limit_start=int(offset),
        limit_page_length=int(limit),
        order_by=order_by_value,
        as_list=False,
    )

    # Permission-aware count using get_list to ensure user permissions are applied
    total_count_result = frappe.get_list(
        "HD Ticket",
        filters=parsed_filters,
        or_filters=or_filters,
        fields=["count(name) as total_count"]
    )
    total_count = total_count_result[0].get("total_count", 0) if total_count_result else 0

    return {
        "data": tickets,
        "total_count": total_count,
        "limit": int(limit),
        "offset": int(offset),
    }
