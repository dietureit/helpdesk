import zipfile
from io import BytesIO

from frappe.tests.utils import FrappeTestCase
from frappe.utils import getdate

from helpdesk.api.complaints import _recent_bounds, _report_to_html, _report_to_xlsx


def _type_row(ticket_type, raised, resolved):
    return {
        "ticket_type": ticket_type,
        "raised": raised,
        "prior_raised": 1,
        "weekly_avg_3m": 0.5,
        "resolved": resolved,
        "open": raised - resolved,
        "investigation_submitted": raised,
        "investigation_pending": 0,
    }


def _fake_report():
    ticket = {
        "name": "7",
        "date": "2026-11-03",
        "status": "Open",
        "complaint": "=1+1",
        "department_reason": "📱 Conversation from CRM",
        "investigation": "Submitted",
    }
    by_type = [_type_row("Packaging", 2, 1), _type_row("Delivery", 1, 0), _type_row("Old", 0, 0)]
    return {
        "filters": {"from_date": "2026-10-06", "to_date": "2026-11-04", "ticket_type": "", "team": ""},
        "prior_period": {"from_date": "2026-09-06", "to_date": "2026-10-05"},
        "summary": {
            "total": 3,
            "resolved": 1,
            "open": 2,
            "investigation_submitted": 3,
            "investigation_pending": 0,
            "prior_total": 3,
        },
        "by_type": by_type,
        "totals": {**_type_row("Total", 3, 1), "prior_raised": 3},
        "rows_by_type": {"Packaging": [ticket]},
        "charts": {
            "donut": [{"label": "Packaging", "value": 2}, {"label": "Delivery", "value": 1}],
            "axis": [
                {"type": "Packaging", "Resolved": 1, "Open": 1},
                {"type": "Delivery", "Resolved": 0, "Open": 1},
            ],
        },
    }


class TestReports(FrappeTestCase):
    def test_complaint_exports_have_charts_and_safe_text(self):
        report = _fake_report()
        html = _report_to_html(report)
        self.assertEqual(html.count("<svg"), 2)  # donut + bars
        self.assertNotIn("📱", html)  # wkhtmltopdf would print a box

        with zipfile.ZipFile(BytesIO(_report_to_xlsx(report))) as xlsx:
            donut = xlsx.read("xl/charts/chart1.xml").decode()
            bars = xlsx.read("xl/charts/chart2.xml").decode()
            tickets = xlsx.read("xl/worksheets/sheet2.xml").decode()
        # header on row 8: charts plot rows 9-10, the departments with complaints (not "Old" or Total)
        self.assertIn("'Summary'!$A$9:$A$10<", donut)
        self.assertIn("'Summary'!$B$9:$B$10<", donut)
        self.assertIn("'Summary'!$F$9:$F$10<", bars)
        self.assertNotIn("<f>", tickets)  # "=1+1" stays text, not a formula

    def test_recent_bounds_are_the_3_months_ending_on_to_date(self):
        start, end, weeks = _recent_bounds("2026-11-04")
        self.assertEqual((start, end), (getdate("2026-08-05"), getdate("2026-11-04")))
        self.assertAlmostEqual(weeks, 92 / 7)
        # at a month end the window starts on the 1st, not on a clamped 28th/31st
        start, end, _weeks = _recent_bounds("2026-05-31")
        self.assertEqual((start, end), (getdate("2026-03-01"), getdate("2026-05-31")))
