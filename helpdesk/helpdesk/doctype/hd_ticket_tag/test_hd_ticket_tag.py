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
    save_tags,
    tag_options,
    tagged_types,
    tags_by_ticket,
)
from helpdesk.test_utils import make_ticket as _make_ticket

ROW_MODULE = "helpdesk.helpdesk.doctype.hd_ticket_investigation_tag.hd_ticket_investigation_tag"
UNTAGGED = "Resolved without tags"
TAG = "QA Tag Found"
TAG_LONGER = "QA Tag Found Twice"  # contains TAG: an exact filter must not match it
ARABIC = "لا توجد مشكلة"  # "no problem found"
DISABLED = "QA Tag Retired"
# throwaway ticket types, so results don't depend on how the site links its tags
QA_TYPE = "QA Tag Type"  # the test tags are linked to it
OTHER_TYPE = "QA Tag Other Type"  # no tags


def make_ticket(**args):
    return _make_ticket(**{"ticket_type": QA_TYPE, **args})


def make_tag(tag: str, enabled: int = 1, types=(QA_TYPE,)):
    # the tests share one transaction (FrappeTestCase rolls back after the class): don't add its type rows twice
    if frappe.db.exists("HD Ticket Tag", tag):
        return
    frappe.get_doc(
        {
            "doctype": "HD Ticket Tag",
            "tag": tag,
            "enabled": enabled,
            "ticket_types": [{"ticket_type": ticket_type} for ticket_type in types],
        }
    ).insert(ignore_mandatory=not types)  # no types: a tag from before they were mandatory


def types_of(tag: str) -> list[str]:
    return [row.ticket_type for row in frappe.get_doc("HD Ticket Tag", tag).ticket_types]


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
        for ticket_type in (QA_TYPE, OTHER_TYPE):
            frappe.get_doc({"doctype": "HD Ticket Type", "name": ticket_type}).insert(ignore_if_duplicate=True)
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

    def test_tags_are_offered_only_on_their_ticket_types(self):
        self.assertRaises(
            frappe.ValidationError, self.tag, make_ticket(subject="QA tags other", ticket_type=OTHER_TYPE), TAG
        )
        # a tag the ticket already has stays when its type changes, but none can be added for the new type
        ticket = self.tag(make_ticket(subject="QA tags type change"), TAG)
        ticket.ticket_type = OTHER_TYPE
        ticket.save(ignore_permissions=True)
        self.assertRaises(frappe.ValidationError, self.tag, ticket, TAG, ARABIC)
        self.tag(ticket, TAG)
        self.assertEqual(tags_of(ticket), [TAG])

    def test_tag_options_list_ticket_types(self):
        make_tag("QA Tag Off", enabled=0, types=(OTHER_TYPE,))
        make_tag("QA Tag Untyped", types=())
        types = {tag.name: tag.ticket_types for tag in tag_options()}
        self.assertEqual(types[TAG], [QA_TYPE])
        self.assertEqual(types["QA Tag Off"], [OTHER_TYPE])
        self.assertEqual(types["QA Tag Untyped"], [])
        # a type whose only tag is disabled gets no popup, like a type without tags
        self.assertIn(QA_TYPE, tagged_types())
        self.assertNotIn(OTHER_TYPE, tagged_types())

    def test_only_enabled_ticket_types_can_be_linked(self):
        for ticket_type in (QA_TYPE, OTHER_TYPE):
            frappe.db.set_value("HD Ticket Type", ticket_type, "enabled", 0)
            self.addCleanup(frappe.db.set_value, "HD Ticket Type", ticket_type, "enabled", 1)
        self.assertRaises(frappe.ValidationError, make_tag, "QA Tag Disabled Type", types=(OTHER_TYPE,))
        self.assertRaises(
            frappe.ValidationError, save_tags, [{"name": TAG, "ticket_types": [QA_TYPE, OTHER_TYPE]}]
        )
        # QA_TYPE was linked before it was disabled: it stays linked, and the tag can still be saved
        save_tags([{"name": TAG, "enabled": 0, "ticket_types": [QA_TYPE]}])
        self.addCleanup(frappe.db.set_value, "HD Ticket Tag", TAG, "enabled", 1)
        self.assertEqual(
            frappe.get_all(
                "HD Ticket Tag Ticket Type", filters={"parent": TAG}, pluck="ticket_type"
            ),
            [QA_TYPE],
        )

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
            save_tags([{"name": "QA Tag Added", "is_new": 1, "enabled": 1, "ticket_types": [QA_TYPE]}])
            save_tags([{"name": "QA Tag Added", "enabled": 0, "ticket_types": [OTHER_TYPE]}])
        self.assertEqual(frappe.db.get_value("HD Ticket Tag", "QA Tag Added", "enabled"), 0)
        self.assertEqual(types_of("QA Tag Added"), [OTHER_TYPE])
        agent = patch("helpdesk.api.internal_sla.is_dashboard_manager", return_value=False)
        with agent, patch("frappe.get_roles", return_value=["Agent"]):
            self.assertRaises(
                frappe.PermissionError,
                save_tags,
                [{"name": "QA Tag Refused", "is_new": 1, "enabled": 1, "ticket_types": [QA_TYPE]}],
            )

    def test_ticket_types_are_mandatory(self):
        new = {"name": "QA Tag No Types", "is_new": 1, "enabled": 1}
        self.assertRaises(frappe.MandatoryError, save_tags, [new])
        self.assertRaises(frappe.MandatoryError, save_tags, [{**new, "ticket_types": []}])
        save_tags([{**new, "name": "QA Tag Typed", "ticket_types": [QA_TYPE, QA_TYPE]}])
        self.assertEqual(types_of("QA Tag Typed"), [QA_TYPE])  # listed once
        typed = {"name": "QA Tag Typed", "enabled": 1}
        self.assertRaises(frappe.MandatoryError, save_tags, [{**typed, "ticket_types": []}])
        self.assertEqual(types_of("QA Tag Typed"), [QA_TYPE])
        # a tag from before types were mandatory (or the starter tag) can still be switched off and on
        make_tag("QA Tag Legacy", types=())
        save_tags([{"name": "QA Tag Legacy", "enabled": 0, "ticket_types": []}])
        self.assertEqual(frappe.db.get_value("HD Ticket Tag", "QA Tag Legacy", "enabled"), 0)
        # only the fields sent change: another admin's edit to the other one survives
        save_tags([{"name": "QA Tag Typed", "enabled": 0}])
        self.assertEqual(types_of("QA Tag Typed"), [QA_TYPE])
        save_tags([{"name": "QA Tag Typed", "ticket_types": [OTHER_TYPE]}])
        self.assertEqual(frappe.db.get_value("HD Ticket Tag", "QA Tag Typed", "enabled"), 0)
        self.assertEqual(types_of("QA Tag Typed"), [OTHER_TYPE])
        save_tags([{"name": "QA Tag Typed", "enabled": 1, "ticket_types": [QA_TYPE]}])
        # rows that didn't change aren't saved again
        modified = frappe.db.get_value("HD Ticket Tag", "QA Tag Typed", "modified")
        save_tags([{**typed, "ticket_types": [QA_TYPE]}])
        self.assertEqual(frappe.db.get_value("HD Ticket Tag", "QA Tag Typed", "modified"), modified)

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
        # its type has no tags, so it never had the popup either
        self.resolve(make_ticket(subject="QA tags no popup", ticket_type=OTHER_TYPE))
        still_open = self.tag(make_ticket(subject="QA tags open"), TAG)

        self.assertEqual(
            tags_by_ticket([both.name, untagged.name, still_open.name]),
            {both.name: [TAG, ARABIC], still_open.name: [TAG]},
        )
        counts = {row["tag"]: row["count"] for row in get_group_tag_rows("monthly", start)}
        self.assertEqual(counts, {TAG: 1, ARABIC: 1, UNTAGGED: 1})
        with patch("helpdesk.api.dashboard.tagged_types", return_value=set()):
            counts = {row["tag"]: row["count"] for row in get_group_tag_rows("monthly", start)}
        self.assertEqual(counts, {TAG: 1, ARABIC: 1})

    def test_complaints_tag_counts(self):
        since = now_datetime()
        after, before = add_to_date(since, hours=1), add_to_date(since, hours=-1)
        resolved = {"investigation_status": "Resolved", "ticket_type": QA_TYPE}
        rows = [
            {**resolved, "tag_list": [TAG, ARABIC]},
            {**resolved, "tag_list": [TAG]},
            {**resolved, "tag_list": [], "investigation_resolved_on": after},
            {**resolved, "tag_list": [], "investigation_resolved_on": before},
            {**resolved, "tag_list": [], "investigation_resolved_on": after, "ticket_type": OTHER_TYPE},
            {"investigation_status": "Open", "ticket_type": QA_TYPE, "tag_list": [ARABIC]},
        ]
        self.assertEqual(
            tag_counts(rows, since, {QA_TYPE}),
            [
                {"tag": TAG, "count": 2},
                {"tag": ARABIC, "count": 1},
                {"tag": UNTAGGED, "count": 1},
            ],
        )
