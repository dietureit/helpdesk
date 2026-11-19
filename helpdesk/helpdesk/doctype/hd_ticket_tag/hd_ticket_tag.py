# Copyright (c) 2026, Frappe Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint

# HD Ticket's Table MultiSelect field and its child table
TICKET_FIELD = "investigation_tags"
TAG_TABLE = "HD Ticket Investigation Tag"
# HD Ticket Tag's Table MultiSelect field and its child table: the ticket types a tag is offered on
TYPES_FIELD = "ticket_types"
TYPE_TABLE = "HD Ticket Tag Ticket Type"


class HDTicketTag(Document):
    def validate(self):
        # The Desk picker lists only enabled types, but a type name typed in full skips that filter. A type disabled
        # after it was linked stays linked: its existing tickets can still be investigated.
        old = self.get_doc_before_save()
        linked = {row.ticket_type for row in old.get(TYPES_FIELD) or []} if old else set()
        added = {row.ticket_type for row in self.get(TYPES_FIELD) or []} - linked
        if added and (
            disabled := frappe.get_all(
                "HD Ticket Type", filters={"name": ["in", list(added)], "enabled": 0}, pluck="name"
            )
        ):
            frappe.throw(_("Disabled ticket types can't be linked: {0}").format(frappe.bold(", ".join(disabled))))

    def on_update(self):
        # open agent pages refetch the tag list, which decides where the popup and the Details field show
        frappe.publish_realtime("helpdesk:ticket-tags-updated", after_commit=True)

    after_delete = on_update

    def after_rename(self, old, new, merge=False):
        self.on_update()


def tags_enabled() -> bool:
    """False between a code deploy and the migrate that adds the field."""
    return frappe.get_meta("HD Ticket").has_field(TICKET_FIELD)


def types_enabled() -> bool:
    """False between a code deploy and the migrate that adds HD Ticket Tag's ticket types."""
    return frappe.get_meta("HD Ticket Tag").has_field(TYPES_FIELD)


def tag_options() -> list[dict]:
    """Every tag, disabled ones included: tickets keep them and filters/reports still need them.
    `ticket_types`: the types a tag is offered on. A tag without types is offered on no ticket."""
    if not tags_enabled():
        return []
    tags = frappe.get_all("HD Ticket Tag", fields=["name", "enabled"], order_by="creation asc")
    types: dict = {}
    if types_enabled():
        for row in frappe.get_all(
            TYPE_TABLE,
            filters={"parenttype": "HD Ticket Tag", "parentfield": TYPES_FIELD},
            fields=["parent", "ticket_type"],
            order_by="idx asc",
        ):
            types.setdefault(row.parent, []).append(row.ticket_type)
    for tag in tags:
        tag["ticket_types"] = types.get(tag.name, [])
    return tags


def tagged_types() -> set[str]:
    """Ticket types with at least one enabled tag: only their tickets get the tag popup and the Details field."""
    return {ticket_type for tag in tag_options() if tag.enabled for ticket_type in tag.ticket_types}


def tags_offered_on(ticket_type: str, tags: list[str]) -> set[str]:
    """Which of `tags` are linked to `ticket_type`. All of them before the migrate that adds ticket types, so ticket
    saves keep working in between."""
    if not types_enabled():
        return set(tags)
    return set(
        frappe.get_all(
            TYPE_TABLE,
            filters={
                "parenttype": "HD Ticket Tag",
                "parentfield": TYPES_FIELD,
                "parent": ["in", tags],
                "ticket_type": ticket_type or "",
            },
            pluck="parent",
        )
    )


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


def _type_rows(ticket_types: list[str] | None) -> list[dict]:
    return [{"ticket_type": ticket_type} for ticket_type in dict.fromkeys(ticket_types or [])]


@frappe.whitelist()
def save_tags(tags: list[dict]):
    """Save the Settings > Ticket Tags form: new tags, ticket types and the Enabled switches. It runs in one
    request, and so in one transaction: a refused row saves nothing.
    A new tag is {name, is_new: 1, enabled, ticket_types}. An existing one is {name} plus only the fields the form
    changed (`enabled`, `ticket_types`), so another admin's edit to the other field survives."""
    _check_manager()
    for row in tags:
        if row.get("is_new"):
            # ticket types are mandatory (the field is reqd): no types, no tag
            frappe.get_doc(
                {
                    "doctype": "HD Ticket Tag",
                    "tag": row.get("name"),
                    "enabled": cint(row.get("enabled", 1)),
                    TYPES_FIELD: _type_rows(row.get("ticket_types")),
                }
            ).insert(ignore_permissions=True)
            continue
        doc = frappe.get_doc("HD Ticket Tag", row.get("name"))
        enabled_changed = "enabled" in row and cint(row["enabled"]) != cint(doc.enabled)
        types = _type_rows(row["ticket_types"]) if "ticket_types" in row else None
        types_changed = types is not None and [r.ticket_type for r in doc.get(TYPES_FIELD)] != [
            r["ticket_type"] for r in types
        ]
        if not (enabled_changed or types_changed):
            continue
        if enabled_changed:
            doc.enabled = cint(row["enabled"])
        if types_changed:
            doc.set(TYPES_FIELD, types)
        else:
            # only the switch changed: a tag from before types were mandatory (or the starter tag) can still be
            # switched on and off
            doc.flags.ignore_mandatory = True
        doc.save(ignore_permissions=True)
