from frappe.tests.utils import FrappeTestCase

from helpdesk.api.ticket import build_card_filters, build_search_filters
from helpdesk.utils import xlsx_rows


class TestTicketFilters(FrappeTestCase):
    def test_build_card_filters(self):
        raw = {
            "overdue": 1,
            "search": "abc",
            "status": ["=", "Open"],
            "creation": ["timespan", "last 7 days"],
            "resolution_date": ["between", "2026-01-01,2026-01-31"],
            "_assign": ["not like", '%"%'],
            "priority": ["is", "maybe"],  # bad operand
            "subject": ["regexp", "x"],  # bad operator
            "modified": ["timespan", "sometime"],  # unknown timespan: get_list would fall back to today
            "nonsense": "1",  # unknown field
        }
        filters = build_card_filters(raw, agent=True)
        self.assertEqual(filters[0][:2], ["status", "in"])  # overdue: open statuses ...
        self.assertEqual(filters[1][:2], ["resolution_by", "<"])  # ... past their due time
        self.assertEqual(
            filters[2:],
            [
                ["status", "=", "Open"],
                ["creation", "timespan", "last 7 days"],
                ["resolution_date", "between", ["2026-01-01", "2026-01-31"]],
                ["_assign", "not like", '%"%'],
            ],
        )

    def test_customers_only_filter_their_own_fields(self):
        raw = {"status": "Open", "agent_group": "Food", "_assign": ["like", "%x%"], "overdue": 1}
        self.assertEqual(build_card_filters(raw, agent=False), [["status", "=", "Open"]])

    def test_search(self):
        self.assertEqual(build_search_filters({"search": "  "}), [])
        filters = build_search_filters({"search": " 12 "})
        self.assertIn(["name", "like", "%12%"], filters)
        self.assertIn(["subject", "like", "%12%"], filters)

    def test_xlsx_rows_neutralise_formulas(self):
        self.assertEqual(xlsx_rows([["=1+1", "a", 1, None]]), [[" =1+1", "a", 1, None]])
