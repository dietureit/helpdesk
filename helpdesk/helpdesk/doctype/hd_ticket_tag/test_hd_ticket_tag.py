# Copyright (c) 2026, Frappe Technologies and Contributors
# See license.txt

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date, now_datetime

from helpdesk.api.complaints import tag_counts
from helpdesk.api.dashboard import get_group_tag_rows
from helpdesk.api.ticket import build_card_filters
from helpdesk.helpdesk.doctype.hd_ticket_tag.hd_ticket_tag import (
    add_tag,
    set_tag_enabled,
    tags_by_ticket,
)
from helpdesk.test_utils import make_ticket

ROW_MODULE = "helpdesk.helpdesk.doctype.hd_ticket_investigation_tag.hd_ticket_investigation_tag"
UNTAGGED = "Resolved without tags"
TAG = "QA Tag Found"
TAG_LONGER = "QA Tag Found Twice"  # contains TAG: an exact filter must not match it
ARABIC = "لا توجد مشكلة"  # "no problem found"
DISABLED = "QA Tag Retired"


def make_tag(tag: str, enabled: int = 1):
    frappe.get_doc({"doctype": "HD Ticket Tag", "tag": tag, "enabled": enabled}).insert(
        ignore_if_duplicate=True
    )


def tags_of(ticket) -> list[str]:
    return [row.tag for row in frappe.get_doc("HD Ticket", ticket.name).investigation_tags]


class TestHDTicketTag(FrappeTestCase):
    def setUp(self):
        # Ticket hooks assign agents, index search, queue jobs and send mail. Keep it all in this
        # transaction (rolled back by FrappeTestCase) so a run on a dev site leaves nothing behind.
        self.enterContext(patch.object(frappe.db, "commit"))
        self.enterContext(patch.object(frappe, "enqueue"))
        self.enterContext(patch.object(frappe, "publish_realtime"))
        self.enterContext(
            patch("helpdesk.helpdesk.doctype.hd_ticket.hd_ticket.HDTicket.update_search_index")
        )
        mute = frappe.flags.mute_emails
        frappe.flags.mute_emails = True
        self.addCleanup(setattr, frappe.flags, "mute_emails", mute)
        for tag in (TAG, TAG_LONGER, ARABIC):
            make_tag(tag)
        make_tag(DISABLED, enabled=0)

    def tag(self, ticket, *tags):
        ticket = frappe.get_doc("HD Ticket", ticket.name)
        ticket.set("investigation_tags", [{"tag": tag} for tag in tags])
        ticket.save(ignore_permissions=True)
        return ticket

    def resolve(self, ticket):
        ticket = frappe.get_doc("HD Ticket", ticket.name)
        ticket.investigation_status = "Resolved"
        ticket.save(ignore_permissions=True)

    def test_new_and_split_tickets_start_untagged(self):
        # split_ticket deep-copies its parent; portal input isn't trusted
        ticket = make_ticket(subject="QA tags new", investigation_tags=[{"tag": TAG}])
        self.assertEqual(tags_of(ticket), [])

    def test_agent_tags_are_deduplicated_and_logged(self):
        ticket = make_ticket(subject="QA tags agent")
        self.tag(ticket, TAG, TAG, ARABIC)
        self.assertEqual(tags_of(ticket), [TAG, ARABIC])
        self.tag(ticket, ARABIC)
        actions = frappe.get_all(
            "HD Ticket Activity", filters={"ticket": ticket.name}, pluck="action", order_by="creation asc"
        )
        self.assertIn(f"added tags {TAG}, {ARABIC}", actions)
        self.assertIn(f"removed tag {TAG}", actions)

    def test_long_tag_names_do_not_break_the_activity_log(self):
        # HD Ticket Activity.action holds 140 characters; a longer line used to fail the whole save
        long_tags = [f"QA long tag {i} " + "x" * 110 for i in range(2)]
        for tag in long_tags:
            make_tag(tag)
        ticket = make_ticket(subject="QA tags long")
        self.tag(ticket, *long_tags)
        self.assertEqual(tags_of(ticket), long_tags)

    def test_disabled_tag_cannot_be_added_but_stays_on_tickets(self):
        ticket = make_ticket(subject="QA tags disabled")
        self.assertRaises(frappe.ValidationError, self.tag, ticket, DISABLED)
        self.tag(ticket, TAG)
        frappe.db.set_value("HD Ticket Tag", TAG, "enabled", 0)
        self.addCleanup(frappe.db.set_value, "HD Ticket Tag", TAG, "enabled", 1)
        self.tag(ticket, TAG, ARABIC)  # TAG was already there: kept
        self.assertEqual(tags_of(ticket), [TAG, ARABIC])

    def test_non_agents_cannot_change_tags(self):
        ticket = make_ticket(subject="QA tags customer")
        self.tag(ticket, TAG)
        with patch("helpdesk.helpdesk.doctype.hd_ticket.hd_ticket.is_agent", return_value=False):
            self.tag(ticket, ARABIC)
        self.assertEqual(tags_of(ticket), [TAG])

    def test_non_agents_cannot_move_another_tickets_row(self):
        victim = self.tag(make_ticket(subject="QA tags victim"), TAG)
        row_name = frappe.get_doc("HD Ticket", victim.name).investigation_tags[0].name
        own = frappe.get_doc("HD Ticket", make_ticket(subject="QA tags own").name)
        own.append("investigation_tags", {"name": row_name, "tag": TAG})
        with patch("helpdesk.helpdesk.doctype.hd_ticket.hd_ticket.is_agent", return_value=False):
            own.save(ignore_permissions=True)
        self.assertEqual(tags_of(victim), [TAG])
        self.assertEqual(tags_of(own), [])

    def test_tag_rows_change_only_through_their_ticket(self):
        # frappe.client.save / REST on a row would skip the ticket's checks and activity log
        ticket = self.tag(make_ticket(subject="QA tags rows"), TAG)
        row_name = frappe.get_doc("HD Ticket", ticket.name).investigation_tags[0].name
        stray = frappe.get_doc(
            {
                "doctype": "HD Ticket Investigation Tag",
                "parenttype": "HD Ticket",
                "parentfield": "investigation_tags",
                "parent": str(ticket.name),
                "tag": ARABIC,
            }
        )
        self.assertRaises(frappe.PermissionError, stray.insert, ignore_permissions=True)
        row = frappe.get_doc("HD Ticket Investigation Tag", row_name)
        row.tag = ARABIC
        self.assertRaises(frappe.PermissionError, row.save, ignore_permissions=True)
        self.assertRaises(
            frappe.PermissionError,
            frappe.delete_doc,
            "HD Ticket Investigation Tag",
            row_name,
            ignore_permissions=True,
        )
        self.assertEqual(tags_of(ticket), [TAG])

    def test_only_agents_can_list_tag_rows(self):
        ticket = self.tag(make_ticket(subject="QA tags list"), TAG)

        def listed():
            return frappe.get_list(
                "HD Ticket Investigation Tag",
                parent_doctype="HD Ticket",
                filters={"parent": str(ticket.name)},
                pluck="tag",
            )

        self.assertEqual(listed(), [TAG])
        with patch(f"{ROW_MODULE}.is_agent", return_value=False):
            self.assertEqual(listed(), [])

    def test_settings_tab_audience_can_manage_tags(self):
        # the tab shows for admins and dashboard managers (e.g. Messenger Manager), who have no rights on the doctype
        manager = patch("helpdesk.api.internal_sla.is_dashboard_manager", return_value=True)
        with manager, patch("frappe.get_roles", return_value=["Messenger Manager"]):
            add_tag("QA Tag Added")
            set_tag_enabled("QA Tag Added", 0)
        self.assertEqual(frappe.db.get_value("HD Ticket Tag", "QA Tag Added", "enabled"), 0)
        agent = patch("helpdesk.api.internal_sla.is_dashboard_manager", return_value=False)
        with agent, patch("frappe.get_roles", return_value=["Agent"]):
            self.assertRaises(frappe.PermissionError, add_tag, "QA Tag Refused")

    def test_duplicate_rows_are_listed_once(self):
        # a Desk rename with "merge" can leave a ticket with the same tag twice until its next save
        ticket = self.tag(make_ticket(subject="QA tags merged"), TAG)
        row = frappe.get_doc("HD Ticket", ticket.name).investigation_tags[0]
        row.name, row.idx = frappe.generate_hash(length=10), 2
        row.db_insert()
        self.assertEqual(tags_by_ticket([ticket.name]), {ticket.name: [TAG]})

    def test_tag_filter_is_an_exact_match(self):
        exact = self.tag(make_ticket(subject="QA tags exact"), TAG)
        longer = self.tag(make_ticket(subject="QA tags longer"), TAG_LONGER)
        arabic = self.tag(make_ticket(subject="QA tags arabic"), ARABIC)

        def matching(value):
            return frappe.get_all(
                "HD Ticket", filters=build_card_filters({"investigation_tags": value}, True), pluck="name"
            )

        self.assertIn(exact.name, matching(["=", TAG]))
        self.assertNotIn(longer.name, matching(["=", TAG]))
        self.assertIn(arabic.name, matching(ARABIC))
        self.assertNotIn(exact.name, matching(ARABIC))
        # an unknown tag or an operator we don't support matches nothing, never everything
        nothing = [["name", "in", [""]]]
        self.assertEqual(build_card_filters({"investigation_tags": "QA no such tag"}, True), nothing)
        self.assertEqual(build_card_filters({"investigation_tags": ["like", "%QA%"]}, True), nothing)
        # customers can't filter on tags
        self.assertEqual(build_card_filters({"investigation_tags": TAG}, False), [])

    def test_reports_count_resolved_investigations_only(self):
        start = add_to_date(now_datetime(), minutes=-1)
        both = self.tag(make_ticket(subject="QA tags both"), TAG, ARABIC)
        self.resolve(both)
        untagged = make_ticket(subject="QA tags untagged")
        self.resolve(untagged)
        # resolved before tags went live: it never had the popup, so it isn't "without tags"
        before_tags = make_ticket(subject="QA tags before")
        self.resolve(before_tags)
        frappe.db.set_value("HD Ticket", before_tags.name, "investigation_resolved_on", "2000-01-01")
        still_open = self.tag(make_ticket(subject="QA tags open"), TAG)

        self.assertEqual(
            tags_by_ticket([both.name, untagged.name, still_open.name]),
            {both.name: [TAG, ARABIC], still_open.name: [TAG]},
        )
        counts = {row["tag"]: row["count"] for row in get_group_tag_rows("monthly", start)}
        self.assertEqual(counts, {TAG: 1, ARABIC: 1, UNTAGGED: 1})

    def test_complaints_tag_counts(self):
        since = now_datetime()
        after, before = add_to_date(since, hours=1), add_to_date(since, hours=-1)
        rows = [
            {"investigation_status": "Resolved", "tag_list": [TAG, ARABIC]},
            {"investigation_status": "Resolved", "tag_list": [TAG]},
            {"investigation_status": "Resolved", "tag_list": [], "investigation_resolved_on": after},
            {"investigation_status": "Resolved", "tag_list": [], "investigation_resolved_on": before},
            {"investigation_status": "Open", "tag_list": [ARABIC]},
        ]
        self.assertEqual(
            tag_counts(rows, since),
            [
                {"tag": TAG, "count": 2},
                {"tag": ARABIC, "count": 1},
                {"tag": UNTAGGED, "count": 1},
            ],
        )
