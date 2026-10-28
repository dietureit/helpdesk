# Copyright (c) 2026, Frappe Technologies and contributors
# For license information, please see license.txt

"""Expose Dieture complaint custom_* fields on HD Ticket Template → Default."""

from __future__ import annotations

import frappe

from helpdesk.consts import DEFAULT_TICKET_TEMPLATE

# Ordered to match Dieture Update Complaint sections (Overview → Customer → Classification → Tracking).
COMPLAINT_TEMPLATE_FIELDS = (
    # Complaints Overview
    "custom_select_source",
    "custom_select_channel",
    "custom_select_type",
    "custom_ticket_number",
    # Customer Information
    "custom_customer_type",
    "custom_customer_phone",
    "custom_customer_name",
    "custom_customer_email",
    "custom_account_status",
    "custom_age",
    "custom_gender",
    # Complaints Classification
    "custom_proof",
    "custom_complaints_description",
    "custom_department",
    "custom_dish",
    "custom_dish_complaint",
    "custom_ingredients",
    "custom_date_of_dish",
    # Complaints Tracking
    "custom_customer_request",
    "custom_assigned_agent",
    "custom_assigned_manager",
    "custom_complaint_status",
    "custom_solution",
)


def _field_exists_on_ticket(fieldname: str) -> bool:
    return bool(
        frappe.db.exists("DocField", {"parent": "HD Ticket", "fieldname": fieldname})
        or frappe.db.exists("Custom Field", {"dt": "HD Ticket", "fieldname": fieldname})
    )


def execute():
    if not frappe.db.exists("HD Ticket Template", DEFAULT_TICKET_TEMPLATE):
        return

    doc = frappe.get_doc("HD Ticket Template", DEFAULT_TICKET_TEMPLATE)
    existing = {row.fieldname for row in doc.fields if row.fieldname}
    added = False

    for fieldname in COMPLAINT_TEMPLATE_FIELDS:
        if fieldname in existing:
            continue
        if not _field_exists_on_ticket(fieldname):
            continue
        doc.append(
            "fields",
            {
                "fieldname": fieldname,
                "required": 0,
                # Agent Details only — keep off customer portal.
                "hide_from_customer": 1,
            },
        )
        existing.add(fieldname)
        added = True

    if added:
        doc.save(ignore_permissions=True)
