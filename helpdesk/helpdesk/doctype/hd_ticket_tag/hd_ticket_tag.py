# Copyright (c) 2026, Frappe Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import cint

# HD Ticket's Table MultiSelect field and its child table
TICKET_FIELD = "investigation_tags"
TAG_TABLE = "HD Ticket Investigation Tag"


class HDTicketTag(Document):
    pass


def tags_enabled() -> bool:
    """False between a code deploy and the migrate that adds the field."""
    return frappe.get_meta("HD Ticket").has_field(TICKET_FIELD)


def tag_options() -> list[dict]:
    """Every tag, disabled ones included: tickets keep them and filters/reports still need them."""
    if not tags_enabled():
        return []
    return frappe.get_all("HD Ticket Tag", fields=["name", "enabled"], order_by="creation asc")


def tags_since():
    """When tags went live (the seed patch adds the first ones at deploy), or None before any exist.
    Investigations resolved earlier never had the popup, so reports don't count them as resolved without tags."""
    return frappe.db.sql("SELECT MIN(creation) FROM `tabHD Ticket Tag`")[0][0]


def tags_by_ticket(names) -> dict:
    """Ticket name -> its tags in picked order, for list rows and reports. Keys are the names passed in:
    HD Ticket names are ints, but the child table's `parent` column is text."""
    if not names or not tags_enabled():
        return {}
    by_text = {str(name): name for name in names}
    out: dict = {}
    for row in frappe.get_all(
        TAG_TABLE,
        filters={"parenttype": "HD Ticket", "parentfield": TICKET_FIELD, "parent": ["in", list(by_text)]},
        fields=["parent", "tag"],
        order_by="parent asc, idx asc",
    ):
        tags = out.setdefault(by_text.get(row.parent, row.parent), [])
        # a rename with "merge" in Desk can leave a ticket with the same tag twice until its next save
        if row.tag not in tags:
            tags.append(row.tag)
    return out


def tickets_with_tag(tag: str) -> list[str]:
    if not tags_enabled():
        return []
    return frappe.get_all(
        TAG_TABLE,
        filters={"parenttype": "HD Ticket", "parentfield": TICKET_FIELD, "tag": tag},
        pluck="parent",
        distinct=True,
    )


# Settings > Ticket Tags saves through these, so its whole audience (admins and dashboard managers, the
# same as the Internal SLA tab) can manage tags without write permission on the doctype.
def _check_manager():
    from helpdesk.api.internal_sla import check_manager  # that module imports this one

    check_manager()


@frappe.whitelist()
def get_tags():
    _check_manager()
    return tag_options()


@frappe.whitelist()
def add_tag(tag: str):
    _check_manager()
    frappe.get_doc({"doctype": "HD Ticket Tag", "tag": tag}).insert(ignore_permissions=True)


@frappe.whitelist()
def set_tag_enabled(tag: str, enabled: int):
    _check_manager()
    doc = frappe.get_doc("HD Ticket Tag", tag)
    doc.enabled = cint(enabled)
    doc.save(ignore_permissions=True)
