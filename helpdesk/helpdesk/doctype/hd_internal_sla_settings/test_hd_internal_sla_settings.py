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
            "ticket_types": [
                {"tier": "Fast", "ticket_type": "Quality"},
                {"tier": "Slow", "ticket_type": "Technical"},
                {"tier": "Slow", "ticket_type": "Refund"},
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
        self.assertEqual(match(ticket_type="Quality"), "Fast")
        self.assertEqual(match(ticket_type="Refund"), "Slow")
        # only the type counts: team and category don't route
        self.assertEqual(match(ticket_type="Technical", agent_group="Delivery Issues", custom_category="Enquiry"), "Slow")
        self.assertIsNone(match(ticket_type="Problem"))  # a type on no tier gets no internal SLA
        self.assertIsNone(match())

    def test_tier_ticket_types_are_validated(self):
        self.settings.ticket_types[0].tier = " Fast "
        self.settings.validate()
        self.assertEqual(self.settings.ticket_types[0].tier, "Fast")
        self.settings.append("ticket_types", {"tier": "Fast", "ticket_type": "Refund"})
        self.assertRaisesRegex(frappe.ValidationError, "on both Slow and Fast", self.settings.validate)
        self.settings.ticket_types[-1].update({"tier": "Gone", "ticket_type": "Bug"})
        self.assertRaisesRegex(frappe.ValidationError, "unknown tier Gone", self.settings.validate)

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
        doc = self.ticket(ticket_type="Quality", internal_sla_tier="Slow", internal_sla_status="Met")
        sla.apply_internal_sla(doc)
        self.assertEqual(doc.investigation_status, "Open")
        self.assertEqual(doc.internal_sla_tier, "Fast")
        self.assertEqual(doc.internal_sla_due_by, THU + timedelta(minutes=15))
        self.assertEqual(doc.internal_sla_warning_by, THU + timedelta(minutes=12))
        self.assertEqual(doc.internal_sla_status, "On Track")

        # a type on no tier: the investigation is tracked, with no internal SLA
        doc = self.ticket(ticket_type="Problem")
        sla.apply_internal_sla(doc)
        self.assertEqual((doc.investigation_status, doc.internal_sla_tier, doc.internal_sla_due_by), ("Open", None, None))

    def test_retyping_keeps_a_hand_picked_tier(self):
        tracked = {"investigation_status": "Open", "internal_sla_due_by": THU + timedelta(days=2)}
        old = {**tracked, "ticket_type": "Quality", "internal_sla_tier": "Slow"}
        doc = self.ticket(old, **{**old, "ticket_type": "Problem"})
        sla.apply_internal_sla(doc)
        self.assertEqual(doc.internal_sla_tier, "Slow")
        self.assertEqual(doc.internal_sla_due_by, THU + timedelta(days=2))

        # an auto-picked tier follows the new type
        old = {**tracked, "ticket_type": "Quality", "internal_sla_tier": "Fast"}
        doc = self.ticket(old, **{**old, "ticket_type": "Technical"})
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
        doc = self.ticket({"ticket_type": "Problem"}, ticket_type="Quality")
        sla.apply_internal_sla(doc)
        self.assertIsNone(doc.internal_sla_tier)
        self.assertIsNone(doc.internal_sla_due_by)

    def test_computed_fields_come_from_the_engine(self):
        # a stale Desk form or an API call cannot overwrite the status and due times
        due = THU + timedelta(days=2)
        old = {
            "investigation_status": "Open",
            "internal_sla_tier": "Slow",
            "internal_sla_status": "At Risk",
            "internal_sla_warning_by": THU + timedelta(days=1),
            "internal_sla_due_by": due,
        }
        doc = self.ticket(old, **{**old, "internal_sla_status": "On Track", "internal_sla_due_by": THU})
        sla.apply_internal_sla(doc)
        self.assertEqual((doc.internal_sla_status, doc.internal_sla_due_by), ("At Risk", due))

    def test_hand_picked_no_sla_survives_retyping(self):
        old = {"investigation_status": "Open", "ticket_type": "Quality", "internal_sla_tier": ""}
        doc = self.ticket(old, **{**old, "ticket_type": "Technical"})
        sla.apply_internal_sla(doc)
        self.assertFalse(doc.internal_sla_tier)
        self.assertIsNone(doc.internal_sla_due_by)

    def test_resolving_while_disabled_still_closes_the_sla(self):
        self.settings.enabled = 0
        due = THU + timedelta(minutes=15)
        old = {
            "investigation_status": "Open",
            "internal_sla_tier": "Fast",
            "internal_sla_due_by": due,
            "internal_sla_status": "On Track",
        }
        doc = self.ticket(old, **{**old, "investigation_status": "Resolved"})
        with patch.object(sla, "now_datetime", return_value=due + timedelta(minutes=1)):
            sla.apply_internal_sla(doc)
        self.assertEqual(doc.internal_sla_status, "Breached")

    def test_notify(self):
        ticket = frappe._dict(
            name=1, subject="s", owner="nobody@x.com", _assign=None, internal_sla_tier="Fast", internal_sla_due_by=THU
        )
        self.settings.send_email = 1
        self.settings.append("breach_recipients", {"user": "cx@x.com"})
        inserted, mailed = [], []
        with (
            patch.object(
                sla.frappe,
                "sendmail",
                side_effect=lambda recipients, **kwargs: mailed.append((sorted(recipients), kwargs.get("delayed"))),
            ),
            patch.object(
                sla.frappe,
                "get_doc",
                side_effect=lambda d: frappe._dict(insert=lambda **kwargs: inserted.append(d["user_to"])),
            ),
            patch.object(
                sla.frappe,
                "get_all",
                side_effect=lambda doctype, filters=None, fields=None, **kwargs: [
                    frappe._dict(name=user, email=user) for user in filters["name"][1]
                ],
            ),
            patch.object(sla.frappe.db, "exists", return_value=False),
        ):
            sla.notify(ticket, "Met", self.settings)
            self.assertEqual((inserted, mailed), ([], []))
            sla.notify(ticket, "At Risk", self.settings)  # nobody assigned: the alert people still get it
            self.assertEqual((inserted, mailed), (["cx@x.com"], [(["cx@x.com"], None)]))
            ticket._assign = '["a@x.com"]'
            # the warning reaches the assignee and the alert people, by notification and by email
            sla.notify(ticket, "At Risk", self.settings)
            self.assertEqual(sorted(inserted[1:]), ["a@x.com", "cx@x.com"])
            self.assertEqual(mailed[1:], [(["a@x.com", "cx@x.com"], None)])  # warning stays on the queue
            sla.notify(ticket, "Breached", self.settings)
            self.assertEqual(sorted(inserted[3:]), ["a@x.com", "cx@x.com"])
            self.assertEqual(mailed[2:], [(["a@x.com", "cx@x.com"], False)])  # breach mail leaves now
            self.settings.send_email = 0
            sla.notify(ticket, "At Risk", self.settings)
            self.assertEqual(len(mailed), 3)  # email switched off: notifications only
