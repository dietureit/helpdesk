from frappe.tests.utils import FrappeTestCase
from frappe.utils import getdate

from helpdesk.api.complaints import _recent_bounds


class TestReports(FrappeTestCase):
    def test_recent_bounds_are_the_3_months_ending_on_to_date(self):
        start, end, weeks = _recent_bounds("2026-11-04")
        self.assertEqual((start, end), (getdate("2026-08-05"), getdate("2026-11-04")))
        self.assertAlmostEqual(weeks, 92 / 7)
        # at a month end the window starts on the 1st, not on a clamped 28th/31st
        start, end, _weeks = _recent_bounds("2026-05-31")
        self.assertEqual((start, end), (getdate("2026-03-01"), getdate("2026-05-31")))
