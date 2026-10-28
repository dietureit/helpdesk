// Copyright (c) 2017, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

// Routing and workflow fields never belong in the per-type form.
const BLOCKED_FIELDS = ["status", "agreement_status", "ticket_type", "sub_type", "agent_group"];
// fieldname -> label, so the grid shows "Delivery Date" rather than custom_delivery_date (as Web Form Fields does).
const ticketFieldLabels = {};

frappe.ui.form.on("HD Ticket Type", {
  setup(frm) {
    const df = frappe.meta.docfield_map["HD Ticket Type Field"]?.fieldname;
    if (df) df.formatter = (value) => ticketFieldLabels[value] || frappe.unscrub(value || "");
  },

  refresh(frm) {
    // First contact fields are picked from HD Ticket's fields in a select, like Web Form Fields.
    frappe.model.with_doctype("HD Ticket", () => {
      const fields = frappe
        .get_meta("HD Ticket")
        .fields.filter(
          (df) => frappe.model.is_value_type(df.fieldtype) && !BLOCKED_FIELDS.includes(df.fieldname)
        );
      frm.ticket_field_meta = Object.fromEntries(fields.map((df) => [df.fieldname, df]));
      fields.forEach((df) => (ticketFieldLabels[df.fieldname] = __(df.label) || df.fieldname));
      frm.fields_dict.first_contact_fields.grid.update_docfield_property(
        "fieldname",
        "options",
        [""].concat(fields.map((df) => ({ label: __(df.label) || df.fieldname, value: df.fieldname })))
      );
      frm.refresh_field("first_contact_fields");
    });
  },
});

frappe.ui.form.on("HD Ticket Type Field", {
  fieldname(frm, cdt, cdn) {
    const df = frm.ticket_field_meta?.[locals[cdt][cdn].fieldname];
    frappe.model.set_value(cdt, cdn, {
      label: df ? df.label : "",
      fieldtype: df ? df.fieldtype : "",
      options: df ? df.options || "" : "",
    });
  },
});
