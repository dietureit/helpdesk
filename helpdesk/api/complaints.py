# Copyright (c) 2026, Frappe Technologies and contributors
# For license information, please see license.txt

"""Customer Complaints report for Helpdesk agents (Adeeb-style department tables)."""

from __future__ import annotations

import json
import math
import re
from collections import defaultdict
from datetime import date, timedelta
from io import BytesIO

import frappe
from bs4 import BeautifulSoup
from frappe import _
from frappe.utils import add_days, add_months, getdate, nowdate
from openpyxl import Workbook
from openpyxl.chart import BarChart, DoughnutChart, Reference
from openpyxl.chart.label import DataLabelList
from openpyxl.chart.marker import DataPoint
from openpyxl.styles import Alignment, Font, PatternFill

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
    ("investigation_sla", "Investigation SLA"),
)

SUMMARY_COLUMNS = (
    ("ticket_type", "Department"),
    ("raised", "Complaints raised"),
    ("prior_raised", "Same period prior"),
    ("weekly_avg_3m", "Weekly avg (last 3 months)"),
    ("resolved", "Resolved"),
    ("open", "Open"),
    ("investigation_submitted", "Investigation submitted"),
    ("investigation_pending", "Investigation pending"),
)


# Exports mirror the on-screen report (CustomerComplaintsReport.vue): same tiles, colours and charts
TILES = (
    ("Raised", "total", "#318AD8", "prior period {prior_total}"),
    ("Resolved", "resolved", "#48BB78", "status category Resolved"),
    ("Open", "open", "#ED8936", "not yet resolved"),
    (
        "Investigation in",
        "investigation_submitted",
        "#48BB78",
        "department comment present",
    ),
    (
        "Investigation pending",
        "investigation_pending",
        "#F56565",
        "no department comment yet",
    ),
)
DONUT_COLORS = (
    "#318AD8",
    "#48BB78",
    "#ED8936",
    "#F56565",
    "#9F7AEA",
    "#38B2AC",
    "#D69E2E",
    "#718096",
)
BAR_SERIES = (("Resolved", "#48BB78"), ("Open", "#ED8936"))
CELL_COLORS = {
    "Submitted": "#2F855A",
    "Resolved": "#2F855A",
    "Met": "#2F855A",
    "Pending": "#DD6B20",
    "Open": "#DD6B20",
    "At Risk": "#DD6B20",
    "Breached": "#E53E3E",
}
COLORED_COLUMNS = {"investigation", "investigation_status", "investigation_sla"}
NOWRAP_COLUMNS = COLORED_COLUMNS | {"date", "name", "status", "contact_number"}
# wkhtmltopdf has no emoji font: comment text like "📱 Conversation from CRM" would print boxes
EMOJI_RE = re.compile("[\U00010000-\U0010FFFF\uFE0F\u200D]")


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


def _recent_bounds(to_date):
    """The 3 months ending on to_date: inclusive (from, to) dates and the window length in weeks."""
    end = add_days(getdate(to_date), 1)
    start = add_months(end, -3)
    return start, getdate(to_date), (end - start).days / 7


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
        "internal_sla_status",
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


def _counts_by_type(filters: dict, from_date, to_date) -> dict[str, int]:
    """Complaint count per ticket type, same filters, over another inclusive date range."""
    where_sql, values = _ticket_filters_sql({**filters, "from_date": from_date, "to_date": to_date})
    # blank ticket_type counts as Unspecified, like the detail rows (_row_from_ticket)
    rows = frappe.db.sql(
        f"""
        SELECT COALESCE(NULLIF(t.ticket_type, ''), 'Unspecified') AS ticket_type, COUNT(*) AS cnt
        FROM `tabHD Ticket` t
        WHERE {where_sql}
        GROUP BY COALESCE(NULLIF(t.ticket_type, ''), 'Unspecified')
        """,
        values,
        as_dict=True,
    )
    return {r.ticket_type: int(r.cnt) for r in rows}


def _fetch_prior_counts(filters: dict) -> dict[str, int]:
    prior_start, prior_end = _prior_bounds(filters.get("from_date"), filters.get("to_date"))
    if not prior_start:
        return {}
    # to_date inclusive: prior_end is exclusive (= current from_date), so to_date = prior_end - 1 day
    return _counts_by_type(filters, prior_start, add_days(prior_end, -1))


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
        "investigation_sla": ticket.get("internal_sla_status") or "",
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
    recent_from, recent_to, recent_weeks = _recent_bounds(filters["to_date"])
    recent_counts = _counts_by_type(filters, recent_from, recent_to)

    rows = [_row_from_ticket(t, comments, resolved) for t in tickets]
    rows_by_type: dict[str, list] = defaultdict(list)
    for row in rows:
        rows_by_type[row["ticket_type"]].append(row)

    by_type = []
    total = {
        "ticket_type": "Total",
        "raised": 0,
        "prior_raised": 0,
        "weekly_avg_3m": round(sum(recent_counts.values()) / recent_weeks, 1),
        "resolved": 0,
        "open": 0,
        "investigation_submitted": 0,
        "investigation_pending": 0,
    }

    # Types with only prior or last-3-months tickets get a row too, so the Total row adds up
    for ticket_type in set(rows_by_type) | set(prior_counts) | set(recent_counts):
        type_rows = rows_by_type.get(ticket_type, [])
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
            "weekly_avg_3m": round(recent_counts.get(ticket_type, 0) / recent_weeks, 1),
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


def _fmt_date(value) -> str:
    d = getdate(value)
    return f"{d.day} {d:%b %Y}"  # "3 Nov 2026", as on screen


def _filters_line(report: dict) -> str:
    f, prior = report["filters"], report["prior_period"]
    parts = [
        f"{_fmt_date(f['from_date'])} – {_fmt_date(f['to_date'])}",
        f["ticket_type"] or _("All ticket types"),
        f["team"] or _("All teams"),
    ]
    if prior["from_date"]:
        parts.append(
            _("prior period {0} – {1}").format(
                _fmt_date(prior["from_date"]), _fmt_date(prior["to_date"])
            )
        )
    return " · ".join(parts)


def _esc(value) -> str:
    """PDF cell text: escaped, emoji dropped, "—" when empty (as on screen)."""
    text = EMOJI_RE.sub("", "" if value is None else str(value)).strip()
    return frappe.utils.escape_html(text) if text else "—"


def _legend(items) -> str:
    return (
        "<div class='legend'>"
        + "".join(
            f"<span class='item'><span class='key' style='background:{color}'></span>{label}</span>"
            for label, color in items
        )
        + "</div>"
    )


def _donut_svg(slices: list[dict]) -> str:
    total = sum(s["value"] for s in slices)
    r = 60
    circumference = 2 * math.pi * r
    rings, legend, offset = [], [], 0.0
    for i, s in enumerate(slices):
        color = DONUT_COLORS[i % len(DONUT_COLORS)]
        length = circumference * s["value"] / total
        rings.append(
            # each slice is a dash rotated to its start (wkhtmltopdf mis-draws a negative dash offset)
            f'<circle cx="90" cy="90" r="{r}" fill="none" stroke="{color}" stroke-width="34" '
            f'stroke-dasharray="{length:.2f} {circumference:.2f}" '
            f'transform="rotate({offset / circumference * 360 - 90:.2f} 90 90)"/>'
        )
        legend.append(
            (f"{_esc(s['label'])} ({round(s['value'] / total * 100)}%)", color)
        )
        offset += length
    return (
        f'<svg width="180" height="180" viewBox="0 0 180 180">{"".join(rings)}</svg>'
        + _legend(legend)
    )


def _bars_svg(axis: list[dict]) -> str:
    """Grouped Resolved/Open bars per department, with integer y ticks and value labels."""
    width, height, left, top, bottom = 460, 190, 28, 14, 22
    plot_w, plot_h = width - left, height - top - bottom
    peak = max([1] + [a[key] for a in axis for key, _color in BAR_SERIES])
    step = math.ceil(peak / 4)
    y_max = step * math.ceil(peak / step)

    def y(value):
        return top + plot_h * (1 - value / y_max)

    parts = [
        f'<line x1="{left}" x2="{width}" y1="{y(v):.1f}" y2="{y(v):.1f}" stroke="#E5E7EB"/>'
        f'<text x="{left - 6}" y="{y(v) + 3:.1f}" text-anchor="end">{v}</text>'
        for v in range(0, y_max + 1, step)
    ]
    group = plot_w / len(axis)
    bar = min(28, group / 3)
    chars = max(3, int(group / 6))
    for i, a in enumerate(axis):
        mid = left + group * (i + 0.5)
        for j, (key, color) in enumerate(BAR_SERIES):
            x, top_y = mid - bar + j * bar, y(a[key])
            parts.append(
                f'<rect x="{x + 1:.1f}" y="{top_y:.1f}" width="{bar - 2:.1f}" '
                f'height="{y(0) - top_y:.1f}" fill="{color}"/>'
            )
            if a[key]:
                parts.append(
                    f'<text x="{x + bar / 2:.1f}" y="{top_y - 3:.1f}" text-anchor="middle">{a[key]}</text>'
                )
        label = a["type"] if len(a["type"]) <= chars else a["type"][: chars - 1] + "…"
        parts.append(
            f'<text x="{mid:.1f}" y="{height - 6}" text-anchor="middle">{_esc(label)}</text>'
        )
    return (
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" font-size="10" '
        f'font-family="Helvetica, Arial, sans-serif" fill="#6B7280">{"".join(parts)}</svg>'
        + _legend((_esc(_(key)), color) for key, color in BAR_SERIES)
    )


def _html_table(columns, body_rows: list[str]) -> str:
    head = "".join(f"<th>{_esc(_(label))}</th>" for _key, label in columns)
    return f"<table class='data'><thead><tr>{head}</tr></thead><tbody>{''.join(body_rows)}</tbody></table>"


def _cards(cells) -> str:
    """Equal-width bordered cards in a row (a table: wkhtmltopdf's WebKit predates flexbox)."""
    return (
        "<div class='cards'><table><tr>"
        + "".join(f"<td class='card'>{c}</td>" for c in cells)
        + "</tr></table></div>"
    )


def _detail_cell(key: str, row: dict) -> str:
    value = row.get(key)
    if key == "date" and value:
        value = _fmt_date(value)
    elif key == "name":
        value = f"#{value}"
    style = "white-space:nowrap;" if key in NOWRAP_COLUMNS else ""
    if key in COLORED_COLUMNS and value in CELL_COLORS:
        style += f"color:{CELL_COLORS[value]};font-weight:bold;"
    return f"<td style='{style}'>{_esc(value)}</td>"


PDF_CSS = """
body { font-family: Helvetica, Arial, sans-serif; font-size: 10px; color: #374151; }
h1 { font-size: 18px; color: #111827; margin: 0 0 2px; }
h2 { font-size: 13px; color: #111827; margin: 18px 0 6px; }
h3 { font-size: 11px; color: #111827; margin: 0 0 6px; }
.muted, h2 span { color: #6B7280; font-weight: normal; }
.cards { margin: 12px -10px 0; }
.cards table { width: 100%; table-layout: fixed; border-collapse: separate; border-spacing: 10px 0; }
.card { padding: 10px 12px; border: 1px solid #E5E7EB; border-radius: 6px; vertical-align: top; }
.value { font-size: 22px; font-weight: bold; margin: 2px 0; }
.hint { color: #9CA3AF; }
.chart { text-align: center; }
.legend .item { display: inline-block; margin: 4px 8px 0; white-space: nowrap; }
.key { display: inline-block; width: 8px; height: 8px; border-radius: 4px; margin-right: 4px; }
.data { width: 100%; border-collapse: collapse; border: 1px solid #E5E7EB; margin-top: 12px; }
h2 + .data { margin-top: 0; }
.data th { text-align: left; color: #6B7280; background: #F9FAFB; }
.data th, .data td { padding: 5px 6px; border-bottom: 1px solid #F3F4F6; vertical-align: top; }
.data tr.total td { font-weight: bold; color: #111827; background: #F9FAFB; }
thead { display: table-header-group; }
tr, .section { page-break-inside: avoid; }
"""


def _report_to_html(report: dict) -> str:
    s, charts = report["summary"], report["charts"]
    tiles = _cards(
        f"<div class='muted'>{_esc(_(label))}</div>"
        f"<div class='value' style='color:{color}'>{s[key]}</div>"
        f"<div class='hint'>{_esc(_(hint).format(**s))}</div>"
        for label, key, color, hint in TILES
    )
    chart_row = (
        _cards(
            [
                f"<h3>{_esc(_('By department'))}</h3><div class='chart'>{_donut_svg(charts['donut'])}</div>",
                f"<h3>{_esc(_('Resolved vs open'))}</h3><div class='chart'>{_bars_svg(charts['axis'])}</div>",
            ]
        )
        if charts["donut"]
        else ""
    )
    summary = _html_table(
        SUMMARY_COLUMNS,
        [
            f"<tr class='{'total' if row is report['totals'] else ''}'>"
            + "".join(
                f"<td>{_esc(row.get(key))}</td>" for key, _label in SUMMARY_COLUMNS
            )
            + "</tr>"
            for row in [*report["by_type"], report["totals"]]
        ],
    )
    rows_by_type = report["rows_by_type"]
    sections = (
        "".join(
            f"<div class='section'><h2>{_esc(ticket_type)} <span>({len(rows_by_type[ticket_type])})</span></h2>"
            + _html_table(
                DETAIL_COLUMNS,
                [
                    "<tr>"
                    + "".join(_detail_cell(key, row) for key, _label in DETAIL_COLUMNS)
                    + "</tr>"
                    for row in rows_by_type[ticket_type]
                ],
            )
            + "</div>"
            for ticket_type in sorted(rows_by_type)
        )
        or f"<p>{_esc(_('No tickets in this range.'))}</p>"
    )
    # without the doctype WebKit's quirks mode stops tables inheriting the 10px font, and they overflow
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>{PDF_CSS}</style></head><body>
        <h1>{_esc(_("Customer Complaints"))}</h1>
        <div class="muted">{_esc(_filters_line(report))}</div>
        {tiles}
        {chart_row}
        {summary}
        {sections}
    </body></html>"""


def _fit_columns(ws, min_row: int = 1):
    for cells in ws.iter_cols(min_row=min_row):
        longest = max(
            (len(str(c.value)) for c in cells if c.value is not None), default=0
        )
        ws.column_dimensions[cells[0].column_letter].width = min(
            max(longest, 6) + 2, 50
        )


def _xlsx_detail(key: str, row: dict):
    value = row.get(key)
    if key == "date" and value:
        return getdate(value)
    if key == "name" and str(value).isdigit():
        return int(value)
    return value


def _report_to_xlsx(report: dict) -> bytes:
    """Summary sheet (tiles, department table, native Excel charts) + a filterable Tickets sheet."""
    bold, muted, fill = (
        Font(bold=True),
        Font(color="6B7280"),
        PatternFill("solid", fgColor="F3F4F6"),
    )
    s = report["summary"]
    wb = Workbook()
    ws = wb.active
    ws.title = _("Summary")
    ws.append([_("Customer Complaints")])
    ws.append([_filters_line(report)])
    ws.append([])
    ws.append([_(label) for label, *_rest in TILES])
    ws.append([s[key] for _label, key, *_rest in TILES])
    ws.append([_(hint).format(**s) for *_rest, hint in TILES])
    ws.append([])
    ws.append([_(label) for _key, label in SUMMARY_COLUMNS])
    # read after appending: a blank append() adds no cells, so max_row doesn't count it
    header = ws.max_row
    rows = [
        [row.get(key) for key, _label in SUMMARY_COLUMNS]
        for row in [*report["by_type"], report["totals"]]
    ]
    for row in xlsx_rows(rows):
        ws.append(row)

    ws["A1"].font, ws["A2"].font = Font(bold=True, size=14), muted
    for col, (_label, _key, color, _hint) in enumerate(TILES, 1):
        ws.cell(4, col).font = muted
        ws.cell(5, col).font = Font(bold=True, size=16, color=color[1:])
        ws.cell(6, col).font = Font(size=9, color="9CA3AF")
    for cell in (*ws[header], *ws[ws.max_row]):
        cell.font, cell.fill = bold, fill
    _fit_columns(ws, min_row=4)

    # by_type is sorted by raised desc, so the departments the charts show are its first rows
    n = sum(1 for row in report["by_type"] if row["raised"])
    if n:
        col = {key: i for i, (key, _label) in enumerate(SUMMARY_COLUMNS, 1)}
        categories = Reference(
            ws, min_col=col["ticket_type"], min_row=header + 1, max_row=header + n
        )
        anchor = ws.max_row + 3

        donut = DoughnutChart(holeSize=55)
        donut.title, donut.width, donut.height = _("By department"), 11, 8
        donut.add_data(
            Reference(ws, min_col=col["raised"], min_row=header, max_row=header + n),
            titles_from_data=True,
        )
        donut.set_categories(categories)
        for i in range(n):
            point = DataPoint(idx=i)
            color = DONUT_COLORS[i % len(DONUT_COLORS)]
            point.graphicalProperties.solidFill = color[1:]
            donut.series[0].dPt.append(point)
        donut.dataLabels = DataLabelList(
            showPercent=True,
            showVal=False,
            showCatName=False,
            showSerName=False,
            showLegendKey=False,
        )
        ws.add_chart(donut, f"A{anchor}")

        bars = BarChart()
        bars.title, bars.width, bars.height = _("Resolved vs open"), 16, 8
        bars.add_data(
            Reference(
                ws,
                min_col=col["resolved"],
                max_col=col["open"],
                min_row=header,
                max_row=header + n,
            ),
            titles_from_data=True,
        )
        bars.set_categories(categories)
        for series, (_key, color) in zip(bars.series, BAR_SERIES):
            series.graphicalProperties.solidFill = color[1:]
            series.graphicalProperties.line.solidFill = color[1:]
        # openpyxl 3.1 leaves the axes' delete flag unset, and Excel then hides them
        bars.x_axis.delete = bars.y_axis.delete = False
        bars.legend.position = "b"
        ws.add_chart(bars, f"D{anchor}")

    ts = wb.create_sheet(_("Tickets"))
    rows = [
        [_("Department")] + [_(label) for _key, label in DETAIL_COLUMNS] + [_("Team")]
    ]
    for ticket_type in sorted(report["rows_by_type"]):
        rows += [
            [ticket_type]
            + [_xlsx_detail(key, row) for key, _label in DETAIL_COLUMNS]
            + [row.get("agent_group")]
            for row in report["rows_by_type"][ticket_type]
        ]
    for row in xlsx_rows(rows):
        ts.append(row)
    for cell in ts[1]:
        cell.font, cell.fill = bold, fill
    for row in ts.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")
            if isinstance(cell.value, date):
                cell.number_format = "d mmm yyyy"
    ts.freeze_panes = "A2"
    ts.auto_filter.ref = ts.dimensions
    _fit_columns(ts)

    out = BytesIO()
    wb.save(out)
    return out.getvalue()


@frappe.whitelist()
@agent_only
def download_complaints_report(filters=None, file_format: str = "Excel"):
    report = build_complaints_report(filters)
    f = report["filters"]
    stamp = f"{f.get('from_date') or ''}_{f.get('to_date') or ''}".replace(" ", "")
    if (file_format or "Excel").lower() == "pdf":
        from frappe.utils.pdf import get_pdf

        frappe.local.response.filename = f"customer-complaints-{stamp}.pdf"
        # landscape: the 12 ticket columns overflow a portrait page
        frappe.local.response.filecontent = get_pdf(
            _report_to_html(report), {"orientation": "Landscape"}
        )
        frappe.local.response.type = "download"
        return

    frappe.local.response.filename = f"customer-complaints-{stamp}.xlsx"
    frappe.local.response.filecontent = _report_to_xlsx(report)
    frappe.local.response.type = "download"
