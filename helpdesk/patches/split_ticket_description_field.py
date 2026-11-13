"""Keep the ticket body and the type-form Description on different columns.

HD Ticket.description is the Details box (and the opening Activity comment). Types that
listed that same field as a first-contact "Description" now point at custom_description.
Existing tickets of those types keep their current sidebar text.
"""

from __future__ import annotations

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

CUSTOM_FIELDS = {
    "HD Ticket": [
        {
            "fieldname": "custom_description",
            "label": "Description",
            "fieldtype": "Small Text",
            "insert_after": "description",
        }
    ]
}


def execute():
    create_custom_fields(CUSTOM_FIELDS, ignore_validate=True)
    frappe.clear_cache(doctype="HD Ticket")

    rows = frappe.get_all(
        "HD Ticket Type Field",
        filters={"parenttype": "HD Ticket Type", "fieldname": "description"},
        fields=["name", "parent"],
    )
    if not rows:
        return

    parents = list(dict.fromkeys(row.parent for row in rows))
    frappe.db.sql(
        """
        UPDATE `tabHD Ticket`
        SET custom_description = description
        WHERE ticket_type IN %(types)s
          AND IFNULL(custom_description, '') = ''
          AND IFNULL(description, '') != ''
        """,
        {"types": parents},
    )

    for row in rows:
        already = frappe.db.exists(
            "HD Ticket Type Field",
            {"parent": row.parent, "parenttype": "HD Ticket Type", "fieldname": "custom_description"},
        )
        if already:
            frappe.db.delete("HD Ticket Type Field", {"name": row.name})
            continue
        frappe.db.set_value(
            "HD Ticket Type Field",
            row.name,
            {
                "fieldname": "custom_description",
                "label": "Description",
                "fieldtype": "Small Text",
                "options": "",
            },
            update_modified=False,
        )
