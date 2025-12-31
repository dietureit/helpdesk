import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime, add_to_date


class HDNotification(Document):
    def before_insert(self):
        """
        Prevent duplicate Assignment notifications at doctype level.
        This is the final safeguard even if hook-level checks are bypassed.
        """
        if self.notification_type == "Assignment" and self.reference_ticket:
            # Check for duplicate assignment notification in the last 2 minutes
            two_minutes_ago = add_to_date(now_datetime(), minutes=-2, as_string=True)
            
            existing = frappe.get_all(
                "HD Notification",
                filters={
                    "user_from": self.user_from,
                    "user_to": self.user_to,
                    "reference_ticket": self.reference_ticket,
                    "notification_type": "Assignment",
                    "creation": [">=", two_minutes_ago],
                    "name": ["!=", self.name],  # Exclude current doc if updating
                },
                limit=1,
                pluck="name",
            )
            
            if existing:
                # Silently prevent duplicate - don't raise error to avoid breaking assignment flow
                frappe.throw(
                    frappe._("Duplicate assignment notification prevented"),
                    frappe.DuplicateEntryError,
                )
    def format_message(self):
        user_from = self.get_from()
        if self.notification_type == "Mention":
            if self.reference_comment:
                return f"{user_from} mentioned you in a comment"
            return f"{user_from} mentioned you"
        return ""

    def get_from(self):
        return frappe.db.get_value(
            "User", {"name": self.user_from}, fieldname="full_name"
        )

    def get_button_label(self):
        if self.reference_comment:
            return "See Comment"
        return "Visit"

    def get_url(self):
        res = "/helpdesk"
        if self.reference_ticket:
            res += "/tickets/" + str(self.reference_ticket)
        if self.reference_comment:
            res += "#" + self.reference_comment
        return frappe.utils.get_url(res)

    def parse_html(self):
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(self.message, "html.parser")
        if soup.find("img"):
            img = soup.find("img")
            img["src"] = ("").join([frappe.utils.get_url(), img["src"]])
            return str(soup)
        return str(soup)

    def get_args(self):
        if self.notification_type == "Mention":
            return {
                "title": self.format_message(),
                "button_label": self.get_button_label(),
                "callback_url": self.get_url(),
                "comment": self.parse_html(),
            }

    def after_insert(self):
        if self.notification_type == "Mention":
            skip_email_workflow = frappe.db.get_single_value(
                "HD Settings", "skip_email_workflow"
            )

            if skip_email_workflow:
                return

            frappe.sendmail(
                recipients=self.user_to,
                subject="New notification",
                message=self.format_message(),
                template="notification",
                args=self.get_args(),
            )
