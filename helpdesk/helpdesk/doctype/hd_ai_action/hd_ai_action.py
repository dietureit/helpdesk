from frappe.model.document import Document
from frappe.utils import today


class HDAIAction(Document):
    def validate(self):
        if self.status == "Done" and not self.done_on:
            self.done_on = today()
