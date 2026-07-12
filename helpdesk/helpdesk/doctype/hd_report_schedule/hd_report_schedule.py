# Copyright (c) 2026, Frappe Technologies and contributors
# For license information, please see license.txt

from datetime import date, timedelta

import frappe
from frappe.model.document import Document
from frappe.utils import get_time, getdate, now_datetime, validate_email_address

from helpdesk.api.dashboard import (
    build_group_report_file,
    get_group_report_rows,
    group_report_html,
)


class HDReportSchedule(Document):
    def validate(self):
        for field in ("recipients", "cc"):
            for email in split_emails(self.get(field)):
                validate_email_address(email, throw=True)
        if not split_emails(self.recipients):
            frappe.throw("At least one recipient is required")

    def is_due(self, now) -> bool:
        if self.last_sent_at and getdate(self.last_sent_at) == now.date():
            return False
        if self.frequency == "Weekly" and now.weekday() != 0:
            return False
        if self.frequency == "Monthly" and now.day != 1:
            return False
        # ponytail: hourly scheduler, so delivery lands within the hour
        # after send_time, not on the exact minute
        return now.time() >= get_time(self.send_time)

    def report_period(self, today: date):
        """Previous complete period ending before today."""
        if self.frequency == "Daily":
            return today - timedelta(days=1), today, f"{today - timedelta(days=1)}"
        if self.frequency == "Weekly":
            start = today - timedelta(days=today.weekday() + 7)
            return start, start + timedelta(days=7), f"Week of {start}"
        start = (today.replace(day=1) - timedelta(days=1)).replace(day=1)
        return start, today.replace(day=1), start.strftime("%B %Y")

    def send(self, now):
        from_date, to_date, label = self.report_period(now.date())
        period = "weekly" if self.frequency == "Weekly" else "monthly"
        rows = get_group_report_rows(period, from_date, to_date)
        title = f"Helpdesk Ticket Report — {label}"

        formats = ["PDF", "Excel"] if self.attach_format == "Both" else [self.attach_format]
        attachments = [
            dict(zip(("fname", "fcontent"), build_group_report_file(rows, f, title)))
            for f in formats
        ]

        frappe.sendmail(
            recipients=split_emails(self.recipients),
            cc=split_emails(self.cc),
            subject=title,
            message=group_report_html(rows, title),
            attachments=attachments,
        )
        self.db_set("last_sent_at", now)


def split_emails(value: str | None) -> list[str]:
    return [e.strip() for e in (value or "").split(",") if e.strip()]


def send_scheduled_reports():
    """Hourly scheduler hook."""
    now = now_datetime()
    for name in frappe.get_all("HD Report Schedule", filters={"enabled": 1}, pluck="name"):
        schedule = frappe.get_doc("HD Report Schedule", name)
        if not schedule.is_due(now):
            continue
        try:
            schedule.send(now)
        except Exception:
            frappe.log_error(
                title=f"HD Report Schedule {name} failed",
                message=frappe.get_traceback(),
            )
