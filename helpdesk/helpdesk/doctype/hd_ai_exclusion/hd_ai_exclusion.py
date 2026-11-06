import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime


def last8(value: str) -> str:
    """The number's last 8 digits; Arabic-Indic and Persian digits count as digits."""
    return "".join(str(int(char)) for char in value or "" if char.isdecimal())[-8:]


class HDAIExclusion(Document):
    def validate(self):
        self.value = (self.value or "").strip()
        if self.exclusion_type == "Phone":
            self.value = last8(self.value)
            if len(self.value) < 8:
                frappe.throw(_("A phone exclusion needs a number with at least 8 digits."))
        if not self.active:
            if not (self.removed_reason or "").strip():
                frappe.throw(_("Give a reason for removing this exclusion."))
            self.removed_by = self.removed_by or frappe.session.user
            self.removed_on = self.removed_on or now_datetime()
            return
        # ponytail: app-level check, so two adds in the same instant can both pass; a DB unique key would close that
        duplicate = {"exclusion_type": self.exclusion_type, "value": self.value, "active": 1, "name": ("!=", self.name)}
        if frappe.db.exists("HD AI Exclusion", duplicate):
            frappe.throw(_("This {0} is already excluded.").format(self.exclusion_type.lower()))
