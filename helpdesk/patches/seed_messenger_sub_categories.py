"""Fill the Enquiry / Assistance Sub Category lists on HD Settings from the Ticketing BRD v12 §3.1.

A list that already has a value is left alone (an admin owns it from then on). Re-runnable with
`bench execute helpdesk.patches.seed_messenger_sub_categories.execute`.
"""

import frappe


def execute():
    frappe.reload_doc("helpdesk", "doctype", "hd_settings")
    meta = frappe.get_meta("HD Settings")
    for fieldname in ("enquiry_sub_categories", "assistance_sub_categories"):
        if not frappe.db.get_single_value("HD Settings", fieldname):
            frappe.db.set_single_value("HD Settings", fieldname, meta.get_field(fieldname).default)
