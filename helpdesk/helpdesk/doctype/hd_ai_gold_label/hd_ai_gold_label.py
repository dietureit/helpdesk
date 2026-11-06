import frappe
from frappe import _
from frappe.model.document import Document


class HDAIGoldLabel(Document):
    def validate(self):
        # ponytail: app-level unique check; gold rows are created by one job, so inserts don't race
        duplicate = {"contact": self.contact, "labeller": self.labeller, "name": ("!=", self.name)}
        if frappe.db.exists("HD AI Gold Label", duplicate):
            frappe.throw(_("{0} already has a gold label for this contact.").format(self.labeller))

        lines = [line.strip() for line in (self.codes or "").splitlines() if line.strip()]
        # exists() returns the stored name, so a code typed in another case is saved as the real one
        codes = {line: frappe.db.exists("HD AI Issue Code", line) for line in lines}
        unknown = [line for line, code in codes.items() if not code]
        if unknown:
            frappe.throw(_("Not an issue code: {0}").format(", ".join(unknown)))
        self.codes = "\n".join(dict.fromkeys(codes.values()))
        if self.primary_code and self.primary_code not in codes.values():
            frappe.throw(_("The primary code must be one of the codes."))
