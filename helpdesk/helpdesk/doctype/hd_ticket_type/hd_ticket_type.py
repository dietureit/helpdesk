import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint

# Routing and workflow fields are never part of the per-type ticket form.
FORM_FIELD_BLOCKLIST = {"status", "agreement_status", "ticket_type", "sub_type", "agent_group"}


class HDTicketType(Document):
    def validate(self):
        self.validate_sub_types()
        self.validate_first_contact_fields()

    def on_trash(self):
        self.prevent_system_delete()

    def prevent_system_delete(self):
        if self.is_system:
            frappe.throw(_("System types can not be deleted"))

    def validate_sub_types(self):
        seen = set()
        for row in self.sub_types:
            row.sub_type = (row.sub_type or "").strip()
            if row.sub_type.lower() in seen:
                frappe.throw(_("Sub Type {0} is repeated").format(frappe.bold(row.sub_type)))
            seen.add(row.sub_type.lower())

    def validate_first_contact_fields(self):
        meta = frappe.get_meta("HD Ticket")
        seen = set()
        for row in self.first_contact_fields:
            df = meta.get_field(row.fieldname)
            if not df or df.fieldtype in frappe.model.no_value_fields:
                frappe.throw(_("Row {0}: {1} is not a field of HD Ticket").format(row.idx, frappe.bold(row.fieldname)))
            if row.fieldname in FORM_FIELD_BLOCKLIST:
                frappe.throw(_("Row {0}: {1} cannot be a first contact field").format(row.idx, frappe.bold(row.fieldname)))
            if row.fieldname in seen:
                frappe.throw(_("Row {0}: {1} is repeated").format(row.idx, frappe.bold(row.fieldname)))
            seen.add(row.fieldname)
            # The grid shows what the field is; HD Ticket's metadata stays the source of truth.
            row.label, row.fieldtype, row.options = df.label, df.fieldtype, df.options or ""


def get_first_contact_fields(ticket_type: str) -> dict[str, dict]:
    """{fieldname: {"required": bool}} for the fields the ticket type's form exposes, in form order.
    Only live HD Ticket fields (a row whose custom field was deleted is skipped); anything else a client sends is dropped."""
    meta = frappe.get_meta("HD Ticket")
    rows = frappe.get_all(
        "HD Ticket Type Field",
        filters={"parent": ticket_type, "parenttype": "HD Ticket Type"},
        fields=["fieldname", "required"],
        order_by="idx",
    )
    return {row.fieldname: {"required": bool(cint(row.required))} for row in rows if meta.get_field(row.fieldname)}


def get_first_contact_fieldnames(ticket_type: str) -> set[str]:
    return set(get_first_contact_fields(ticket_type))


@frappe.whitelist()
def get_ticket_type_forms():
    """{ticket type: {"sub_types": [...], "fields": [...]}} for every type: drives the per-type ticket form."""
    frappe.has_permission("HD Ticket Type", throw=True)
    meta = frappe.get_meta("HD Ticket")
    forms = {name: {"sub_types": [], "fields": []} for name in frappe.get_all("HD Ticket Type", pluck="name")}
    for row in frappe.get_all(
        "HD Ticket Sub Type",
        filters={"parenttype": "HD Ticket Type"},
        fields=["parent", "sub_type"],
        order_by="parent, idx",
    ):
        if row.parent in forms:
            forms[row.parent]["sub_types"].append(row.sub_type)
    for row in frappe.get_all(
        "HD Ticket Type Field",
        fields=["parent", "fieldname", "required", "placeholder"],
        order_by="parent, idx",
    ):
        df = meta.get_field(row.fieldname)
        if not df or row.parent not in forms:
            continue
        forms[row.parent]["fields"].append(
            {
                "fieldname": df.fieldname,
                "label": df.label,
                "fieldtype": df.fieldtype,
                "options": df.options or "",
                "required": cint(row.required),
                "placeholder": row.placeholder or "",
            }
        )
    return forms
