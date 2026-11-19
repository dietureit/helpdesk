// Copyright (c) 2026, Frappe Technologies and contributors
// For license information, please see license.txt

frappe.ui.form.on("HD Ticket Tag", {
  setup(frm) {
    // only enabled ticket types (HDTicketTag.validate also refuses a disabled one typed in full)
    frm.set_query("ticket_types", () => ({ filters: { enabled: 1 } }));
  },
});
