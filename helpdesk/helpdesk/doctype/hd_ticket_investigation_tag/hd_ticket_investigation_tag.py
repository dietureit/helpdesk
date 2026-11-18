# Copyright (c) 2026, Frappe Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from helpdesk.utils import is_agent


class HDTicketInvestigationTag(Document):
    # Rows may change only through a ticket save, where HDTicket.validate_investigation_tags checks who and what.
    # A ticket save writes its rows directly and never calls these, so they only stop standalone saves and
    # deletes (frappe.client.save, REST), which would skip those checks.
    def validate(self):
        frappe.throw(_("Change investigation tags on the ticket"), frappe.PermissionError)

    on_trash = validate


def permission_query(user):
    # generic list APIs check child tables only against the parent doctype, which customers can read,
    # so without this any portal user could list every ticket's tags
    return None if is_agent(user) else "1=0"
