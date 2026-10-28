"""Seed per-type sub types and first contact fields from the Ticketing BRD v12 §3.3.

Only ticket types that exist on the site are touched, and a table that already has rows is left
alone (an admin owns it from then on). Safe to re-run with
`bench execute helpdesk.patches.seed_ticket_type_forms.execute` after creating a missing type.
"""

from __future__ import annotations

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

# First contact details the BRD asks CS to capture that HD Ticket had no field for yet.
CUSTOM_FIELDS = {
    "HD Ticket": [
        {"fieldname": "custom_sample_available", "label": "Sample Still Available", "fieldtype": "Select", "options": "\nYes\nNo", "insert_after": "custom_ingredients"},
        {"fieldname": "custom_time_consumed", "label": "Time Consumed", "fieldtype": "Datetime", "insert_after": "custom_sample_available"},
        {"fieldname": "custom_symptoms", "label": "Symptoms Reported", "fieldtype": "Small Text", "insert_after": "custom_time_consumed"},
        {"fieldname": "custom_delivery_date", "label": "Delivery Date", "fieldtype": "Date", "insert_after": "custom_symptoms"},
        {"fieldname": "custom_delivery_window", "label": "Delivery Window", "fieldtype": "Select", "options": "\nMorning\nEvening", "insert_after": "custom_delivery_date"},
        {"fieldname": "custom_delivery_area", "label": "Delivery Area", "fieldtype": "Data", "insert_after": "custom_delivery_window"},
        {"fieldname": "custom_delay_duration", "label": "Delay Duration", "fieldtype": "Data", "insert_after": "custom_delivery_area"},
        {"fieldname": "custom_refund_amount", "label": "Refund Amount", "fieldtype": "Currency", "insert_after": "custom_delay_duration"},
        {"fieldname": "custom_payment_method", "label": "Payment Method", "fieldtype": "Select", "options": "\nCard\nCash\nBank Transfer\nWallet / App Credit\nOther", "insert_after": "custom_refund_amount"},
        {"fieldname": "custom_platform", "label": "Platform", "fieldtype": "Select", "options": "\nApp\nWeb", "insert_after": "custom_payment_method"},
        {"fieldname": "custom_device_version", "label": "Device & App Version", "fieldtype": "Data", "insert_after": "custom_platform"},
        {"fieldname": "custom_screen_affected", "label": "Screen / Feature Affected", "fieldtype": "Data", "insert_after": "custom_device_version"},
    ]
}

# BRD "Responsible Department" -> the site's ticket type (HD Settings maps each type to its team).
TICKET_TYPE_FORMS = {
    "Problem": {  # Kitchen / Pastry
        "sub_types": ["Taste", "Undercooked", "Burnt", "Portion Size", "Seasoning"],
        "fields": ["custom_dish", "custom_date_of_dish", "custom_proof"],
    },
    "Packaging": {  # Packing
        "sub_types": ["Missing Item", "Incorrect Item", "Damaged Seal or Tray", "Leakage", "Cold-Pack Condition"],
        "fields": ["custom_dish", "custom_proof"],
    },
    "Quality": {  # Food Safety & Hygiene
        "sub_types": ["Foreign Object", "Spoilage", "Temperature Control", "Cross-Contamination", "Illness"],
        "fields": ["custom_dish", "custom_proof", "custom_sample_available", "custom_time_consumed", "custom_symptoms"],
    },
    "Delivery": {
        "sub_types": ["Late", "Missing", "Wrong Address"],
        "fields": ["custom_delivery_date", "custom_delivery_window", "custom_delivery_area", "custom_delay_duration"],
    },
    "Refund": {  # Refund / Finance; reasons are the BRD §3.2 cancellation reasons
        "sub_types": [
            "Price", "Food Quality or Taste", "Portion or Variety", "Delivery Experience", "Service Experience",
            "Goal Achieved", "Travel or Relocation", "Health Reasons", "Switched to a Competitor", "Other",
        ],
        "fields": ["custom_refund_amount", "custom_payment_method"],
    },
    "Technical": {  # Tech / System; issue types from the existing Application options
        "sub_types": ["App Crash", "Login", "Payment", "Notification", "Order Flow", "Other"],
        "fields": ["custom_platform", "custom_device_version", "custom_screen_affected", "custom_proof"],
    },
    "Customer Service": {  # not on every site: seeded once the type exists
        "sub_types": ["Communication", "Process", "Follow-up"],
        "fields": ["custom_agent_name"],
    },
    "Ingredient": {  # not on every site: seeded once the type exists
        "sub_types": [],
        "fields": ["custom_ingredients", "custom_proof"],
    },
    "Unspecified": {  # Other / Uncategorized
        "sub_types": [],
        "fields": ["custom_proof"],
    },
}


def execute():
    create_custom_fields(CUSTOM_FIELDS, ignore_validate=True)
    frappe.clear_cache(doctype="HD Ticket")
    meta = frappe.get_meta("HD Ticket")

    for ticket_type, form in TICKET_TYPE_FORMS.items():
        if not frappe.db.exists("HD Ticket Type", ticket_type):
            continue
        doc = frappe.get_doc("HD Ticket Type", ticket_type)
        changed = False
        if not doc.sub_types:
            for sub_type in form["sub_types"]:
                doc.append("sub_types", {"sub_type": sub_type})
                changed = True
        if not doc.first_contact_fields:
            for fieldname in form["fields"]:
                if meta.has_field(fieldname):
                    doc.append("first_contact_fields", {"fieldname": fieldname})
                    changed = True
        if changed:
            doc.save(ignore_permissions=True)
