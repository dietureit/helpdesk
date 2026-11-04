# Copyright (c) 2017, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from helpdesk.helpdesk.doctype.hd_ticket_type.hd_ticket_type import (
    FORM_FIELD_BLOCKLIST,
    get_form_field_options,
)


class TestHDTicketType(FrappeTestCase):
    def test_field_picker_offers_only_fields_validation_accepts(self):
        fieldnames = {option["value"] for option in get_form_field_options()}
        meta = frappe.get_meta("HD Ticket")

        self.assertIn("subject", fieldnames)
        self.assertFalse(fieldnames & FORM_FIELD_BLOCKLIST)
        self.assertFalse(
            {f for f in fieldnames if meta.get_field(f).fieldtype in frappe.model.no_value_fields}
        )
