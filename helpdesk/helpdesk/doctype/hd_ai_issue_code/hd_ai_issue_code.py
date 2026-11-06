import frappe
from frappe import _
from frappe.model.document import Document


class HDAIIssueCode(Document):
    def validate(self):
        if not self.merged_into:
            return
        self.status = "Retired"
        seen = set()
        code = self.merged_into
        while code and code not in seen:
            if code == self.name:
                frappe.throw(_("Merging {0} into {1} would make a loop.").format(self.name, self.merged_into))
            seen.add(code)
            code = frappe.db.get_value("HD AI Issue Code", code, "merged_into")
