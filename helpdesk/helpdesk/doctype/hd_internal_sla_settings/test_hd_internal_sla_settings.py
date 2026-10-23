from datetime import date, datetime, timedelta
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from helpdesk.helpdesk.doctype.hd_internal_sla_settings import hd_internal_sla_settings as sla

THU = datetime(2026, 10, 22, 10, 0)  # a Thursday
EVERY_DAY = set(range(7))
SUN_TO_THU = {6, 0, 1, 2, 3}


def make_settings():
    return frappe.get_doc(
        {
            "doctype": "HD Internal SLA Settings",
            "enabled": 1,
            "warning_percent": 80,
            **{day: 1 for day in sla.WEEKDAYS},
            "tiers": [
                {"tier": "Fast", "target": 15, "unit": "Minutes"},
                {"tier": "Slow", "target": 2, "unit": "Days"},
            ],
            "rules": [
                {"category": "Enquiry"},
                {"team": "Delivery Issues", "tier": "Fast"},
                {"ticket_type": "Technical", "tier": "Slow"},
            ],
        }
    )


class TestHDInternalSLASettings(FrappeTestCase):
    def setUp(self):
        self.settings = make_settings()
        self.enterContext(patch.object(sla, "get_settings", return_value=self.settings))
        self.enterContext(patch.object(sla, "is_agent", return_value=True))

    def ticket(self, old=None, **values):
        """Unsaved HD Ticket; with `old` it behaves like an update of a saved ticket."""
        doc = frappe.new_doc("HD Ticket")
        doc.update({"creation": THU, **values})
        if old is not None:
            doc.set("__islocal", None)
            doc._doc_before_save = frappe._dict({"creation": THU, **old})
        return doc

    def test_due_after(self):
        self.assertEqual(sla.due_after(THU, 15, "Minutes", EVERY_DAY, set()), THU + timedelta(minutes=15))
        self.assertEqual(sla.due_after(THU, 2, "Hours", EVERY_DAY, set()), THU + timedelta(hours=2))
        self.assertEqual(sla.due_after(THU, 1, "Days", EVERY_DAY, set()), datetime(2026, 10, 23, 10, 0))
        # Friday and Saturday are off: 14h on Thursday + 10h on Sunday
        self.assertEqual(sla.due_after(THU, 1, "Days", SUN_TO_THU, set()), datetime(2026, 10, 25, 10, 0))
        # raised on a day off: the clock starts on the next working day
        friday = datetime(2026, 10, 23, 15, 0)
        self.assertEqual(sla.due_after(friday, 1, "Days", SUN_TO_THU, set()), datetime(2026, 10, 26, 0, 0))
        self.assertEqual(sla.due_after(THU, 1, "Days", EVERY_DAY, {date(2026, 10, 23)}), datetime(2026, 10, 24, 10, 0))
        self.assertEqual(sla.due_after(THU, 0.8, "Days", EVERY_DAY, set()), datetime(2026, 10, 23, 5, 12))

    def test_match_tier(self):
        match = lambda **values: sla.match_tier(frappe._dict(values), self.settings)  # noqa: E731
        self.assertIsNone(match(custom_category="Enquiry", agent_group="Delivery Issues"))
        self.assertEqual(match(custom_category="Complaint", agent_group="Delivery Issues"), "Fast")
        self.assertEqual(match(ticket_type="Technical", agent_group="Other Issues"), "Slow")
        self.assertIsNone(match())

    def test_get_status(self):
        due, warning = THU + timedelta(minutes=15), THU + timedelta(minutes=12)
        open_ticket = frappe._dict(
            investigation_status="Open", internal_sla_due_by=due, internal_sla_warning_by=warning
        )
        self.assertEqual(sla.get_status(open_ticket, THU), "On Track")
        self.assertEqual(sla.get_status(open_ticket, warning), "At Risk")
        self.assertEqual(sla.get_status(open_ticket, due), "Breached")
        resolved = frappe._dict(open_ticket, investigation_status="Resolved", investigation_resolved_on=due)
        self.assertEqual(sla.get_status(resolved), "Met")
        resolved.investigation_resolved_on = due + timedelta(seconds=1)
        self.assertEqual(sla.get_status(resolved), "Breached")
        self.assertEqual(sla.get_status(frappe._dict(investigation_status="Open")), "")

    def test_new_ticket(self):
        # split tickets arrive with the parent's values
        doc = self.ticket(agent_group="Delivery Issues", internal_sla_tier="Slow", internal_sla_status="Met")
        sla.apply_internal_sla(doc)
        self.assertEqual(doc.investigation_status, "Open")
        self.assertEqual(doc.internal_sla_tier, "Fast")
        self.assertEqual(doc.internal_sla_due_by, THU + timedelta(minutes=15))
        self.assertEqual(doc.internal_sla_warning_by, THU + timedelta(minutes=12))
        self.assertEqual(doc.internal_sla_status, "On Track")

    def test_rerouting_keeps_a_hand_picked_tier(self):
        tracked = {"investigation_status": "Open", "internal_sla_due_by": THU + timedelta(days=2)}
        old = {**tracked, "agent_group": "Delivery Issues", "internal_sla_tier": "Slow"}
        doc = self.ticket(old, **{**old, "agent_group": "Technical Issues"})
        sla.apply_internal_sla(doc)
        self.assertEqual(doc.internal_sla_tier, "Slow")
        self.assertEqual(doc.internal_sla_due_by, THU + timedelta(days=2))

        # an auto-picked tier follows the new route
        old = {**tracked, "agent_group": "Delivery Issues", "internal_sla_tier": "Fast"}
        doc = self.ticket(old, **{**old, "agent_group": "Technical Issues", "ticket_type": "Technical"})
        sla.apply_internal_sla(doc)
        self.assertEqual(doc.internal_sla_tier, "Slow")
        self.assertEqual(doc.internal_sla_due_by, THU + timedelta(days=2))
        self.assertEqual(doc.internal_sla_status, "On Track")

    def test_resolving_the_investigation(self):
        due = THU + timedelta(minutes=15)
        old = {"investigation_status": "Open", "internal_sla_tier": "Fast", "internal_sla_due_by": due}
        for resolved_on, status in ((due, "Met"), (due + timedelta(minutes=1), "Breached")):
            doc = self.ticket(old, **{**old, "investigation_status": "Resolved"})
            with patch.object(sla, "now_datetime", return_value=resolved_on):
                sla.apply_internal_sla(doc)
            self.assertEqual(doc.investigation_resolved_on, resolved_on)
            self.assertEqual(doc.internal_sla_status, status)

    def test_non_agents_cannot_change_it(self):
        old = {"investigation_status": "Open", "internal_sla_tier": "Fast"}
        doc = self.ticket(old, investigation_status="Resolved", internal_sla_tier="Slow")
        with patch.object(sla, "is_agent", return_value=False):
            sla.apply_internal_sla(doc)
        self.assertEqual((doc.investigation_status, doc.internal_sla_tier), ("Open", "Fast"))

    def test_old_tickets_are_not_tracked(self):
        doc = self.ticket({"agent_group": "Other Issues"}, agent_group="Delivery Issues")
        sla.apply_internal_sla(doc)
        self.assertIsNone(doc.internal_sla_tier)
        self.assertIsNone(doc.internal_sla_due_by)
