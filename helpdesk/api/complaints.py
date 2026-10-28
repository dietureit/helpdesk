# Copyright (c) 2026, Frappe Technologies and contributors
# For license information, please see license.txt

"""Customer Complaints report for Helpdesk agents (Adeeb-style department tables)."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import timedelta

import frappe
from bs4 import BeautifulSoup
from frappe import _
from frappe.utils import add_days, getdate, nowdate
from frappe.utils.xlsxutils import make_xlsx

from helpdesk.utils import agent_only, is_dashboard_manager, xlsx_rows

DETAIL_COLUMNS = (
    ("date", "Date"),
    ("name", "Ticket"),
    ("status", "Status"),
    ("investigation_status", "Investigation Status"),
    ("contact_number", "Contact number"),
    ("customer_name", "Customer name"),
    ("complaint", "Complaint"),
    ("item_affected", "Item affected"),
    ("resolution_by_cs", "Resolution by CS"),
    ("department_reason", "Reason given by department"),
    ("investigation", "Investigation"),
)

SUMMARY_COLUMNS = (
    ("ticket_type", "Department"),
    ("raised", "Complaints raised"),
    ("prior_raised", "Same period prior"),
    ("resolved", "Resolved"),
    ("open", "Open"),
    ("investigation_submitted", "Investigation submitted"),
    ("investigation_pending", "Investigation pending"),
)


def _parse_filters(filters) -> dict:
    if isinstance(filters, str):
        filters = json.loads(filters) if filters else {}
    return filters or {}


def _check_report_access(filters: dict):
    """Non-managers may only see their own assigned tickets (same idea as dashboard)."""
    user = frappe.session.user
    if is_dashboard_manager(user) or "System Manager" in frappe.get_roles(user):
        return
    # Force agent scope for non-managers
    filters["agent"] = user


def _resolved_statuses() -> list[str]:
    statuses = frappe.get_all(
        "HD Ticket Status", filters={"category": "Resolved"}, pluck="name"
    )
    return statuses or ["Resolved", "Closed"]


def _has_field(fieldname: str) -> bool:
    return frappe.get_meta("HD Ticket").has_field(fieldname)


def _strip_html(html: str | None) -> str:
    if not html:
        return ""
    text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
    return " ".join(text.split())


def _date_bounds(from_date, to_date):
    """Inclusive calendar dates → creation half-open window [start, end)."""
    if not from_date or not to_date:
        return None, None
    start = getdate(from_date)
    end = add_days(getdate(to_date), 1)
    return start, end


def _prior_bounds(from_date, to_date):
    """Same-length window immediately before from_date."""
    start, end = _date_bounds(from_date, to_date)
    if not start:
        return None, None
    length_days = (getdate(to_date) - getdate(from_date)).days + 1
    prior_end = start  # exclusive end = current start
    prior_start = start - timedelta(days=length_days)
    return prior_start, prior_end


def _complaint_scope_sql(alias: str = "t") -> tuple[str, dict]:
    """
    Complaint tickets: custom_category = Complaint, or blank category with a ticket_type.
    Falls back to ticket_type IS NOT NULL when custom_category is missing on the site.
    """
    if _has_field("custom_category"):
        return (
            f"""(
                IFNULL({alias}.custom_category, '') = 'Complaint'
                OR (
                    IFNULL({alias}.custom_category, '') = ''
                    AND IFNULL({alias}.ticket_type, '') != ''
                )
            )""",
            {},
        )
    return f"IFNULL({alias}.ticket_type, '') != ''", {}


def _ticket_filters_sql(filters: dict, alias: str = "t") -> tuple[str, dict]:
    clauses = []
    values: dict = {}

    scope_sql, scope_vals = _complaint_scope_sql(alias)
    clauses.append(scope_sql)
    values.update(scope_vals)

    start, end = _date_bounds(filters.get("from_date"), filters.get("to_date"))
    if start and end:
        clauses.append(f"{alias}.creation >= %(from_dt)s AND {alias}.creation < %(to_dt)s")
        values["from_dt"] = start
        values["to_dt"] = end

    if filters.get("ticket_type"):
        clauses.append(f"{alias}.ticket_type = %(ticket_type)s")
        values["ticket_type"] = filters["ticket_type"]

    if filters.get("team") or filters.get("agent_group"):
        clauses.append(f"{alias}.agent_group = %(agent_group)s")
        values["agent_group"] = filters.get("team") or filters.get("agent_group")

    if filters.get("agent"):
        # JSON _assign contains the user id
        clauses.append(f"JSON_SEARCH({alias}._assign, 'one', %(agent)s) IS NOT NULL")
        values["agent"] = filters["agent"]

    return " AND ".join(clauses), values


def _select_fields(alias: str = "t") -> str:
    fields = [
        f"{alias}.name",
        f"{alias}.creation",
        f"{alias}.subject",
        f"{alias}.status",
        f"{alias}.ticket_type",
        f"{alias}.agent_group",
    ]
    for field in (
        "custom_customer_phone",
        "custom_customer_name",
        "custom_complaints_description",
        "custom_dish",
        "custom_dish_complaint",
        "custom_solution",
        "custom_category",
        "investigation_status",
    ):
        if _has_field(field):
            fields.append(f"{alias}.{field}")
    return ", ".join(fields)


def _fetch_tickets(filters: dict) -> list[dict]:
    where_sql, values = _ticket_filters_sql(filters)
    return frappe.db.sql(
        f"""
        SELECT {_select_fields("t")}
        FROM `tabHD Ticket` t
        WHERE {where_sql}
        ORDER BY IFNULL(t.ticket_type, ''), t.creation ASC, t.name ASC
        """,
        values,
        as_dict=True,
    )


def _fetch_prior_counts(filters: dict) -> dict[str, int]:
    prior_start, prior_end = _prior_bounds(filters.get("from_date"), filters.get("to_date"))
    if not prior_start:
        return {}

    prior_filters = {
        k: v
        for k, v in filters.items()
        if k not in ("from_date", "to_date")
    }
    prior_filters["from_date"] = prior_start.isoformat()
    # to_date inclusive: prior_end is exclusive (= current from_date), so to_date = prior_end - 1 day
    prior_filters["to_date"] = add_days(prior_end, -1).isoformat()

    where_sql, values = _ticket_filters_sql(prior_filters)
    rows = frappe.db.sql(
        f"""
        SELECT IFNULL(t.ticket_type, 'Unspecified') AS ticket_type, COUNT(*) AS cnt
        FROM `tabHD Ticket` t
        WHERE {where_sql}
        GROUP BY IFNULL(t.ticket_type, 'Unspecified')
        """,
        values,
        as_dict=True,
    )
    return {r.ticket_type: int(r.cnt) for r in rows}


def _latest_comments(ticket_names: list[str]) -> dict[str, str]:
    if not ticket_names:
        return {}
    rows = frappe.db.sql(
        """
        SELECT c.reference_ticket, c.content
        FROM `tabHD Ticket Comment` c
        INNER JOIN (
            SELECT reference_ticket, MAX(creation) AS max_creation
            FROM `tabHD Ticket Comment`
            WHERE reference_ticket IN %(names)s
            GROUP BY reference_ticket
        ) latest
            ON latest.reference_ticket = c.reference_ticket
            AND latest.max_creation = c.creation
        """,
        {"names": tuple(ticket_names)},
        as_dict=True,
    )
    out = {}
    for row in rows:
        out[str(row.reference_ticket)] = _strip_html(row.content)
    return out


def _is_resolved(status: str, resolved: set[str]) -> bool:
    return (status or "") in resolved


def _row_from_ticket(ticket: dict, comments: dict[str, str], resolved: set[str]) -> dict:
    name = str(ticket.name)
    reason = comments.get(name, "")
    investigation = "Submitted" if reason else "Pending"
    # Prefer explicit investigation_status when present and Resolved
    inv_status = ticket.get("investigation_status")
    if inv_status and str(inv_status).lower() in ("resolved", "closed"):
        investigation = "Submitted"

    complaint = (ticket.get("subject") or "").strip()
    if not complaint:
        complaint = (ticket.get("custom_complaints_description") or "").strip()
        complaint = _strip_html(complaint)

    item = (ticket.get("custom_dish") or "").strip()
    if not item:
        item = (ticket.get("custom_dish_complaint") or "").strip()

    return {
        "name": name,
        "date": getdate(ticket.creation).isoformat() if ticket.creation else "",
        "creation": ticket.creation,
        "contact_number": ticket.get("custom_customer_phone") or "",
        "customer_name": ticket.get("custom_customer_name") or "",
        "complaint": complaint,
        "item_affected": item,
        "resolution_by_cs": _strip_html(ticket.get("custom_solution")),
        "department_reason": reason,
        "investigation": investigation,
        "ticket_type": ticket.get("ticket_type") or "Unspecified",
        "agent_group": ticket.get("agent_group") or "",
        "status": ticket.get("status") or "",
        "investigation_status": inv_status or "",
        "is_resolved": 1 if _is_resolved(ticket.get("status"), resolved) else 0,
    }


def build_complaints_report(filters: dict | None = None) -> dict:
    filters = _parse_filters(filters)
    _check_report_access(filters)

    if not filters.get("from_date") or not filters.get("to_date"):
        # Default: last 30 days
        filters["to_date"] = nowdate()
        filters["from_date"] = add_days(filters["to_date"], -29)

    resolved = set(_resolved_statuses())
    tickets = _fetch_tickets(filters)
    comments = _latest_comments([str(t.name) for t in tickets])
    prior_counts = _fetch_prior_counts(filters)

    rows = [_row_from_ticket(t, comments, resolved) for t in tickets]
    rows_by_type: dict[str, list] = defaultdict(list)
    for row in rows:
        rows_by_type[row["ticket_type"]].append(row)

    by_type = []
    total = {
        "ticket_type": "Total",
        "raised": 0,
        "prior_raised": 0,
        "resolved": 0,
        "open": 0,
        "investigation_submitted": 0,
        "investigation_pending": 0,
    }

    for ticket_type in sorted(rows_by_type.keys(), key=lambda x: (x == "Unspecified", x)):
        type_rows = rows_by_type[ticket_type]
        raised = len(type_rows)
        resolved_n = sum(1 for r in type_rows if r["is_resolved"])
        open_n = raised - resolved_n
        submitted = sum(1 for r in type_rows if r["investigation"] == "Submitted")
        pending = raised - submitted
        prior = int(prior_counts.get(ticket_type, 0))
        entry = {
            "ticket_type": ticket_type,
            "raised": raised,
            "prior_raised": prior,
            "resolved": resolved_n,
            "open": open_n,
            "investigation_submitted": submitted,
            "investigation_pending": pending,
        }
        by_type.append(entry)
        for key in (
            "raised",
            "prior_raised",
            "resolved",
            "open",
            "investigation_submitted",
            "investigation_pending",
        ):
            total[key] += entry[key]

    # Include prior-only types so comparison column is complete
    for ticket_type, prior in prior_counts.items():
        if ticket_type not in rows_by_type:
            by_type.append(
                {
                    "ticket_type": ticket_type,
                    "raised": 0,
                    "prior_raised": prior,
                    "resolved": 0,
                    "open": 0,
                    "investigation_submitted": 0,
                    "investigation_pending": 0,
                }
            )
            total["prior_raised"] += prior
    by_type.sort(key=lambda r: (-r["raised"], r["ticket_type"]))

    donut = [
        {"label": e["ticket_type"], "value": e["raised"]}
        for e in by_type
        if e["raised"]
    ]
    axis = [
        {
            "type": e["ticket_type"],
            "Resolved": e["resolved"],
            "Open": e["open"],
        }
        for e in by_type
        if e["raised"]
    ]

    prior_start, prior_end = _prior_bounds(filters.get("from_date"), filters.get("to_date"))
    return {
        "filters": {
            "from_date": filters.get("from_date"),
            "to_date": filters.get("to_date"),
            "ticket_type": filters.get("ticket_type") or "",
            "team": filters.get("team") or filters.get("agent_group") or "",
        },
        "prior_period": {
            "from_date": prior_start.isoformat() if prior_start else None,
            "to_date": add_days(prior_end, -1).isoformat() if prior_end else None,
        },
        "summary": {
            "total": total["raised"],
            "resolved": total["resolved"],
            "open": total["open"],
            "investigation_submitted": total["investigation_submitted"],
            "investigation_pending": total["investigation_pending"],
            "prior_total": total["prior_raised"],
        },
        "by_type": by_type,
        "totals": total,
        "rows_by_type": dict(rows_by_type),
        "charts": {"donut": donut, "axis": axis},
        "columns": {
            "detail": [{"key": k, "label": _(v)} for k, v in DETAIL_COLUMNS],
            "summary": [{"key": k, "label": _(v)} for k, v in SUMMARY_COLUMNS],
        },
    }


@frappe.whitelist()
@agent_only
def get_complaints_report(filters=None):
    return build_complaints_report(filters)


def _report_to_excel_rows(report: dict) -> list[list]:
    data = [[_(label) for _k, label in SUMMARY_COLUMNS]]
    for row in report["by_type"]:
        data.append([row.get(k) for k, _ in SUMMARY_COLUMNS])
    data.append([report["totals"].get(k) for k, _ in SUMMARY_COLUMNS])
    data.append([])
    data.append([_(label) for _k, label in DETAIL_COLUMNS] + [_("Department"), _("Team")])
    for ticket_type, rows in report["rows_by_type"].items():
        for row in rows:
            data.append(
                [row.get(k) for k, _ in DETAIL_COLUMNS]
                + [ticket_type, row.get("agent_group") or ""]
            )
    return data


def _report_to_html(report: dict) -> str:
    f = report["filters"]
    title = _("Customer Complaints Report — {0} to {1}").format(
        f.get("from_date") or "", f.get("to_date") or ""
    )
    s = report["summary"]
    summary_intro = _(
        "{0} complaint tickets; {1} resolved, {2} open; "
        "{3} investigations submitted, {4} pending. "
        "Prior period: {5} tickets."
    ).format(
        s["total"],
        s["resolved"],
        s["open"],
        s["investigation_submitted"],
        s["investigation_pending"],
        s["prior_total"],
    )

    head = "".join(
        f"<th style='text-align:left;padding:4px 8px'>{frappe.utils.escape_html(_(label))}</th>"
        for _k, label in SUMMARY_COLUMNS
    )
    body_rows = []
    for row in report["by_type"]:
        cells = "".join(
            f"<td style='padding:4px 8px'>{frappe.utils.escape_html(str(row.get(k) if row.get(k) is not None else ''))}</td>"
            for k, _ in SUMMARY_COLUMNS
        )
        body_rows.append(f"<tr>{cells}</tr>")
    totals = report["totals"]
    body_rows.append(
        "<tr>"
        + "".join(
            f"<td style='padding:4px 8px'><b>{frappe.utils.escape_html(str(totals.get(k) if totals.get(k) is not None else ''))}</b></td>"
            for k, _ in SUMMARY_COLUMNS
        )
        + "</tr>"
    )
    summary_table = f"""
        <table border="1" style="border-collapse:collapse;font-size:12px;margin-bottom:16px">
            <thead><tr>{head}</tr></thead>
            <tbody>{''.join(body_rows)}</tbody>
        </table>
    """

    detail_parts = []
    dhead = "".join(
        f"<th style='text-align:left;padding:4px 8px'>{frappe.utils.escape_html(_(label))}</th>"
        for _k, label in DETAIL_COLUMNS
    )
    for ticket_type, rows in report["rows_by_type"].items():
        if not rows:
            continue
        body = []
        for row in rows:
            cells = "".join(
                f"<td style='padding:4px 8px;vertical-align:top'>{frappe.utils.escape_html(str(row.get(k) or ''))}</td>"
                for k, _ in DETAIL_COLUMNS
            )
            body.append(f"<tr>{cells}</tr>")
        detail_parts.append(
            f"<h4 style='margin:16px 0 8px'>{frappe.utils.escape_html(ticket_type)} "
            f"({len(rows)})</h4>"
            f"<table border='1' style='border-collapse:collapse;font-size:11px;width:100%'>"
            f"<thead><tr>{dhead}</tr></thead><tbody>{''.join(body)}</tbody></table>"
        )

    return f"""
        <h2>{frappe.utils.escape_html(title)}</h2>
        <p style="font-size:13px">{frappe.utils.escape_html(summary_intro)}</p>
        {summary_table}
        {''.join(detail_parts) or '<p>No tickets in this range.</p>'}
    """


@frappe.whitelist()
@agent_only
def download_complaints_report(filters=None, file_format: str = "Excel"):
    report = build_complaints_report(filters)
    f = report["filters"]
    stamp = f"{f.get('from_date') or ''}_{f.get('to_date') or ''}".replace(" ", "")
    if (file_format or "Excel").lower() == "pdf":
        from frappe.utils.pdf import get_pdf

        frappe.local.response.filename = f"customer-complaints-{stamp}.pdf"
        frappe.local.response.filecontent = get_pdf(_report_to_html(report))
        frappe.local.response.type = "download"
        return

    frappe.local.response.filename = f"customer-complaints-{stamp}.xlsx"
    frappe.local.response.filecontent = make_xlsx(
        xlsx_rows(_report_to_excel_rows(report)), "Complaints"
    ).getvalue()
    frappe.local.response.type = "download"
