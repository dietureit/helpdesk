import json
import uuid
from email.utils import parseaddr
from functools import lru_cache
from typing import List

from click.formatting import measure_table
import frappe
from bs4 import BeautifulSoup
from frappe import _
from frappe.core.page.permission_manager.permission_manager import remove
from frappe.desk.form.assign_to import add as assign
from frappe.desk.form.assign_to import clear as clear_all_assignments
from frappe.desk.form.assign_to import get as get_assignees
from frappe.model.document import Document
from frappe.permissions import add_permission, update_permission_property
from frappe.query_builder import Order
from pypika.functions import Count
from pypika.queries import Query
from pypika.terms import Criterion

from helpdesk.consts import DEFAULT_TICKET_PRIORITY, DEFAULT_TICKET_TYPE
from helpdesk.helpdesk.doctype.hd_settings.helpers import (
    get_default_email_content,
    is_email_content_empty,
)
from helpdesk.helpdesk.doctype.hd_ticket_activity.hd_ticket_activity import (
    log_ticket_activity,
)
from helpdesk.helpdesk.utils.email import (
    default_outgoing_email_account,
    default_ticket_outgoing_email_account,
)
from helpdesk.search import HelpdeskSearch
from helpdesk.utils import (
    capture_event,
    get_agents_team,
    get_customer,
    get_doc_room,
    is_admin,
    is_agent,
    publish_event,
)
from frappe.utils import now_datetime

from ..hd_notification.utils import clear as clear_notifications
from ..hd_service_level_agreement.utils import get_sla


class HDTicket(Document):
    @property
    def default_open_status(self):
        return frappe.db.get_value(
            "HD Service Level Agreement",
            self.sla,
            "default_ticket_status",
        ) or frappe.db.get_single_value("HD Settings", "default_ticket_status")

    @property
    def ticket_reopen_status(self):
        return frappe.db.get_value(
            "HD Service Level Agreement",
            self.sla,
            "ticket_reopen_status",
        ) or frappe.db.get_single_value("HD Settings", "ticket_reopen_status")

    def publish_update(self):
        room = get_doc_room("HD Ticket", self.name)
        publish_event(
            "helpdesk:ticket-update", room=room, data={"ticket_id": self.name}
        )
        capture_event("ticket_updated")

    def autoname(self):
        return self.name

    def before_validate(self):
        self.check_update_perms()
        self.set_ticket_type()
        self.apply_team_mapping_from_ticket_type()
        self.set_raised_by()
        self.set_priority()
        self.set_first_responded_on()
        self.set_feedback_values()
        self.set_default_status()
        self.set_status_category()
        # self.apply_escalation_rule()
        self.set_sla()

        self.set_contact()
        self.set_customer()

    def validate(self):
        self.validate_feedback()

    def before_save(self):
        self.apply_sla()
        if not self.is_new():
            self.handle_ticket_activity_update()

        self.handle_email_feedback()

    def _get_rendered_template(
        self, content: str, default_content: str, args: dict[str, str] | None = None
    ):
        if args is None:
            args = dict()
        template_args = {
            "doc": self.as_dict(),
        }
        for key, value in args.items():
            template_args[key] = value
        return frappe.render_template(
            default_content if is_email_content_empty(content) else content,
            template_args,
        )

    def handle_email_feedback(self):
        if (
            self.is_new()
            or self.via_customer_portal
            or self.feedback_rating
            or not self.has_value_changed("status")
            or not self.key
        ):
            return

        [is_email_feedback_enabled, email_feedback_status] = frappe.get_cached_value(
            "HD Settings",
            "HD Settings",
            ["enable_email_ticket_feedback", "send_email_feedback_on_status"],
        )

        send_feedback_email = int(is_email_feedback_enabled) and (
            email_feedback_status == self.status
            or email_feedback_status == ""
            and self.status == "Closed"
        )

        if not send_feedback_email:
            return

        last_communication = self.get_last_communication()

        url = f"{frappe.utils.get_url()}/ticket-feedback/new?key={self.key}"
        feedback_email_content = frappe.db.get_single_value(
            "HD Settings", "feedback_email_content"
        )
        default_feedback_email_content = get_default_email_content("share_feedback")
        try:
            frappe.sendmail(
                recipients=[self.raised_by],
                subject=f"Re: {self.subject}",
                message=self._get_rendered_template(
                    feedback_email_content,
                    default_feedback_email_content,
                    {"url": url},
                ),
                reference_doctype="HD Ticket",
                reference_name=self.name,
                now=True,
                in_reply_to=last_communication.name if last_communication else None,
                email_headers={"X-Auto-Generated": "hd-email-feedback"},
            )
            frappe.msgprint(_("Feedback email has been sent to the customer"))
        except Exception as e:
            frappe.throw(_("Could not send feedback email,due to: {0}").format(e))

    def before_insert(self):
        self.generate_key()
        self.set_agent_group_from_ticket_type()

    def set_agent_group_from_ticket_type(self):
        """
        Set agent_group based on ticket_type by finding a team whose name contains the ticket_type.
        Only sets if agent_group is not already set.
        """
        if not self.ticket_type or self.agent_group:
            return

        # ticket_type is already set in before_validate() and is a link to HD Ticket Type
        # Use the ticket_type name directly to search for matching teams
        ticket_type_name = self.ticket_type

        # Search for teams whose name contains the ticket_type name (case-insensitive)
        teams = frappe.get_all(
            "HD Team",
            filters={"name": ["like", f"%{ticket_type_name}%"]},
            fields=["name"],
            limit=1,
            order_by="name asc"
        )

        if teams:
            self.agent_group = teams[0].name
            frappe.logger().info(
                f"Auto-assigned team '{self.agent_group}' to ticket based on ticket_type '{self.ticket_type}'"
            )

    def apply_team_mapping_from_ticket_type(self):
        """
        Apply explicit ticket-type -> team mapping from HD Settings.
        Works on new ticket creation and when ticket_type changes.
        """
        if not self.ticket_type:
            return

        settings = frappe.get_cached_doc("HD Settings", "HD Settings")
        mapping_rows = settings.get("ticket_type_team_assignment_rules") or []
        if not mapping_rows:
            return

        matched_team = None
        for row in mapping_rows:
            if not getattr(row, "enabled", 1):
                continue
            if getattr(row, "ticket_type", None) == self.ticket_type and getattr(
                row, "team", None
            ):
                matched_team = row.team
                break

        if matched_team:
            self.agent_group = matched_team
        elif self.is_new() and not self.agent_group:
            # Keep old fallback behavior for backward compatibility.
            self.set_agent_group_from_ticket_type()

    def after_insert(self):
        if self.ticket_split_from:
            log_ticket_activity(
                self.name,
                "split the ticket from #{0}".format(self.ticket_split_from),
            )
            capture_event("ticket_split")
            return

        capture_event("ticket_created")
        publish_event("helpdesk:new-ticket")
        if self.get("description"):
            self.create_communication_via_contact(self.description, new_ticket=True)
            self.handle_inline_media_new_ticket()

        send_ack_email = frappe.db.get_single_value(
            "HD Settings", "send_acknowledgement_email"
        )
        if (
            not self.via_customer_portal
            and not frappe.flags.initial_sync
            and send_ack_email
        ):
            self.send_acknowledgement_email()

        # Send notification to team members when agent_group is assigned
        if self.agent_group and not frappe.flags.initial_sync:
            self.assign_all_team_members_if_enabled()
            # self.send_team_notification_email()
            self.create_team_notifications()

    def on_update(self):
        # flake8: noqa
        if self.status_category == "Open":
            if (
                self.get_doc_before_save()
                and self.get_doc_before_save().status_category != "Open"
            ):
                agents = self.get_assigned_agents()
                if agents:
                    for agent in agents:
                        self.notify_agent(agent.name, "Reaction")

        # Send notification to team members when agent_group is assigned/changed
        if self.agent_group and self.has_value_changed("agent_group"):
            self.assign_all_team_members_if_enabled()
            # self.send_team_notification_email()
            self.create_team_notifications()

        self.remove_assignment_if_not_in_team()
        self.publish_update()
        self.update_search_index()
        self.enqueue_notification_automation_rules()

    def notify_agent(self, agent, notification_type="Assignment"):
        try:
            frappe.get_doc(
                frappe._dict(
                    doctype="HD Notification",
                    user_from=frappe.session.user,
                    reference_ticket=self.name,
                    user_to=agent,
                    notification_type=notification_type,
                )
            ).insert(ignore_permissions=True)
        except frappe.DuplicateEntryError:
            # Duplicate Assignment notifications are intentionally ignored.
            return

    def update_search_index(self):
        search = HelpdeskSearch()
        search.index_doc(self)

    def set_ticket_type(self):
        if self.ticket_type:
            return
        settings = frappe.get_doc("HD Settings")
        ticket_type = settings.default_ticket_type or DEFAULT_TICKET_TYPE
        self.ticket_type = ticket_type

    def set_raised_by(self):
        self.raised_by = self.raised_by or frappe.session.user

    def set_contact(self):
        email_id = parseaddr(self.raised_by)[1]
        # flake8: noqa
        if email_id:
            if not self.contact:
                contact = frappe.db.get_value("Contact", {"email_id": email_id})
                if contact:
                    self.contact = contact

    def set_customer(self):
        """
        Update `Customer` if does not exist already. `Contact` is assumed
        to be set beforehand.
        """
        # Skip if `Customer` is already set
        if self.customer:
            return

        if self.contact:
            customer = get_customer(self.contact)

            # let agent assign the customer when one contact has more than one customer
            if len(customer) == 1:
                self.customer = customer[0]

    def set_priority(self):
        if self.priority:
            return
        self.priority = (
            frappe.get_cached_value("HD Ticket Type", self.ticket_type, "priority")
            or frappe.get_cached_value("HD Settings", "HD Settings", "default_priority")
            or DEFAULT_TICKET_PRIORITY
        )

    def set_first_responded_on(self):
        if self.is_new():
            return
        if self.first_responded_on:
            return

        old_status_category = (
            self.get_doc_before_save().status_category
            if self.get_doc_before_save()
            else None
        )
        is_closed_or_resolved = (
            old_status_category == "Open" and self.status_category == "Resolved"
        )

        if self.status_category == "Paused" or is_closed_or_resolved:
            self.first_responded_on = frappe.utils.now_datetime()

    def set_feedback_values(self):
        if not self.feedback:
            return
        feedback_option = frappe.get_doc("HD Ticket Feedback Option", self.feedback)
        self.feedback_rating = feedback_option.rating

    @property
    def has_agent_replied(self):
        return frappe.db.exists(
            "Communication",
            {
                "reference_doctype": "HD Ticket",
                "reference_name": self.name,
                "sent_or_received": "Sent",
            },
        )

    def validate_feedback(self):
        is_feedback_mandatory = frappe.get_cached_value(
            "HD Settings", "HD Settings", "is_feedback_mandatory"
        )
        if (
            self.feedback_rating
            or self.status_category != "Resolved"
            or is_agent()
            or not self.has_agent_replied
            or not is_feedback_mandatory
        ):
            return

        frappe.throw(
            _("Ticket must be resolved with a feedback"), frappe.ValidationError
        )

    def check_update_perms(self):
        if self.is_new() or is_agent() or not self.via_customer_portal:
            return
        old_doc = self.get_doc_before_save()
        is_closed = old_doc.status == "Closed"
        is_rated = bool(old_doc.feedback)
        if is_closed or is_rated:
            text = _("Closed or rated tickets cannot be updated by non-agents")
            frappe.throw(text, frappe.PermissionError)

    def handle_ticket_activity_update(self):
        """
        Handles the ticket activity update.
        Should be called inside on_update
        """
        field_maps = {
            "status": "status",
            "priority": "priority",
            "agent_group": "team",
            "ticket_type": "type",
            "contact": "contact",
            "customer": "customer",
        }
        for field in [
            "status",
            "priority",
            "agent_group",
            "contact",
            "customer",
            "ticket_type",
        ]:
            if self.has_value_changed(field):
                # Get the display value for customer/contact
                value = self.as_dict()[field]
                if field == "customer" and value:
                    # Get customer name for better display
                    customer_name = frappe.db.get_value("Customer", value, "customer_name") or value
                    log_ticket_activity(
                        self.name, f"set {field_maps[field]} to {customer_name}"
                    )
                elif field == "contact" and value:
                    # Get contact name for better display
                    contact_name = frappe.db.get_value("Contact", value, "full_name") or frappe.db.get_value("Contact", value, "email_id") or value
                    log_ticket_activity(
                        self.name, f"set {field_maps[field]} to {contact_name}"
                    )
                else:
                    log_ticket_activity(
                        self.name, f"set {field_maps[field]} to {value}"
                    )

    def generate_key(self):
        self.key = uuid.uuid4()

    def remove_assignment_if_not_in_team(self):
        """
        Removes the assignment if the agent is not in the team.
        Should be called inside on_update
        """
        if self.is_new():
            return
        if not self.agent_group or (hasattr(self, "_assign") and not self._assign):
            return
        if self.has_value_changed("agent_group") and self.status_category == "Open":
            current_assigned_agent = self.get_assigned_agent()
            if not current_assigned_agent:
                return
            is_agent_in_assigned_team = self.agent_in_assigned_team(
                current_assigned_agent, self.agent_group
            )

            if (
                not is_agent_in_assigned_team
            ) and self.users_present_in_team_assignment_rule():
                clear_all_assignments("HD Ticket", self.name)
                frappe.publish_realtime(
                    "helpdesk:update-ticket-assignee",
                    {"ticket_id": self.name},
                    after_commit=True,
                )

    def agent_in_assigned_team(self, agent, team):
        return frappe.db.exists(
            "HD Team Member",
            {
                "parent": team,
                "user": agent,
            },
        )

    def users_present_in_team_assignment_rule(self):
        if not self.agent_group:
            return False

        assignment_rule = frappe.db.get_value(
            "HD Team", self.agent_group, "assignment_rule"
        )
        if not assignment_rule:
            return False

        is_disabled = frappe.db.get_value(
            "Assignment Rule", assignment_rule, "disabled"
        )
        if is_disabled:
            return False

        users = frappe.get_all(
            "Assignment Rule User", filters={"parent": assignment_rule}
        )
        if not users:
            return False

        return True

    @frappe.whitelist()
    def assign_agent(self, agent):
        assign({"assign_to": [agent], "doctype": "HD Ticket", "name": self.name})

    def get_assigned_agents(self):
        assignees = get_assignees({"doctype": "HD Ticket", "name": self.name})
        if len(assignees) > 0:
            names = [assignee.owner for assignee in assignees]
            return frappe.get_all("HD Agent", filters={"name": ["in", names]})

    def get_assigned_agent(self):
        # TODO: deprecate this
        # for some reason _assign is not set, maybe a framework bug?
        if hasattr(self, "_assign") and self._assign:
            assignees = json.loads(self._assign)
            if len(assignees) > 0:
                # TODO: temporary fix, remove this when only agents can be assigned to ticket
                exists = frappe.db.exists("HD Agent", assignees[0])
                if exists:
                    return assignees[0]

        assignees = get_assignees({"doctype": "HD Ticket", "name": self.name})
        if len(assignees) > 0:
            # TODO: temporary fix, remove this when only agents can be assigned to ticket
            return frappe.db.exists("HD Agent", assignees[0].owner)

        return None

    def on_trash(self):
        activities = frappe.db.get_all("HD Ticket Activity", {"ticket": self.name})
        for activity in activities:
            frappe.db.delete("HD Ticket Activity", activity)

        comments = frappe.db.get_all(
            "HD Ticket Comment", {"reference_ticket": self.name}
        )
        for comment in comments:
            frappe.db.delete("HD Ticket Comment", comment)

    def skip_email_workflow(self):
        skip: str = frappe.get_value("HD Settings", None, "skip_email_workflow") or "0"

        return bool(int(skip))

    def instantly_send_email(self):
        check: str = (
            frappe.get_value("HD Settings", None, "instantly_send_email") or "0"
        )

        return bool(int(check))

    @frappe.whitelist()
    def get_last_communication(self):
        filters = {
            "reference_doctype": "HD Ticket",
            "reference_name": ["=", str(self.name)],
        }

        try:
            communication = frappe.get_last_doc(
                "Communication",
                filters=filters,
            )

            return communication
        except Exception:
            return None

    def last_communication_email(self):
        if not (communication := self.get_last_communication()):
            return

        if not communication.email_account:
            return

        email_account = frappe.get_doc("Email Account", communication.email_account)

        if not email_account.enable_outgoing:
            return

        return email_account

    def sender_email(self):
        """
        Find an email to use as sender. Fall back through multiple choices

        :return: `Email Account`
        """
        if email_account := self.last_communication_email():
            return email_account

        if email_account := default_ticket_outgoing_email_account():
            return email_account

        if email_account := default_outgoing_email_account():
            return email_account

    @property
    def portal_uri(self):
        root_uri = frappe.utils.get_url()
        return f"{root_uri}/helpdesk/my-tickets/{self.name}"

    @frappe.whitelist()
    def new_comment(self, content: str, attachments: List[str] = []):
        if not is_agent():
            frappe.throw(
                _("You are not permitted to add a comment"), frappe.PermissionError
            )
        c = frappe.new_doc("HD Ticket Comment")
        c.commented_by = frappe.session.user
        c.content = content
        c.is_pinned = False
        c.reference_ticket = self.name
        c.save()
        for attachment in attachments:
            self.attach_file_with_doc(
                "HD Ticket Comment", c.name, attachment.get("file_url")
            )

    @frappe.whitelist()
    def reply_via_agent(
        self,
        message: str,
        to: str = None,
        cc: str = None,
        bcc: str = None,
        attachments: List[str] = [],
    ):
        skip_email_workflow = self.skip_email_workflow()
        medium = "" if skip_email_workflow else "Email"
        subject = f"Re: {self.subject}"
        sender = frappe.session.user
        recipients = to or self.raised_by
        sender_email = None if skip_email_workflow else self.sender_email()

        if recipients == "Administrator":
            admin_email = frappe.get_value("User", "Administrator", "email")
            recipients = admin_email

        communication = frappe.get_doc(
            {
                "bcc": bcc,
                "cc": cc,
                "communication_medium": medium,
                "communication_type": "Communication",
                "content": message,
                "doctype": "Communication",
                "email_account": sender_email.name if sender_email else None,
                "email_status": "Open",
                "recipients": recipients,
                "reference_doctype": "HD Ticket",
                "reference_name": self.name,
                "sender": sender,
                "sent_or_received": "Sent",
                "status": "Linked",
                "subject": subject,
            }
        )

        last_communication = self.get_last_communication()
        if last_communication and last_communication.message_id:
            communication.in_reply_to = last_communication.name

        communication.insert(ignore_permissions=True)
        capture_event("agent_replied")

        _attachments = []

        for attachment in attachments:
            file_doc = frappe.get_doc("File", attachment)
            file_doc.attached_to_name = communication.name
            file_doc.attached_to_doctype = "Communication"
            file_doc.save(ignore_permissions=True)
            self.attach_file_with_doc("HD Ticket", self.name, file_doc.file_url)

            _attachments.append({"file_url": file_doc.file_url})

        if skip_email_workflow or not frappe.db.get_single_value(
            "HD Settings", "enable_reply_email_via_agent"
        ):
            return

        if not sender_email:
            frappe.throw(_("Can not send email. No sender email set up!"))

        message = self.parse_content(message)

        reply_to_email = sender_email.email_id
        rendered_template: str | None = None
        if self.via_customer_portal:
            email_content = frappe.db.get_single_value(
                "HD Settings", "reply_via_agent_email_content"
            )
            default_email_content = get_default_email_content("reply_via_agent")
            try:
                rendered_template = self._get_rendered_template(
                    email_content,
                    default_email_content,
                    {"message": message, "ticket_url": self.portal_uri},
                )
            except Exception as e:
                frappe.throw(_("Could not an email due to: {0}").format(e))

        send_delayed = True
        send_now = False

        if self.instantly_send_email():
            send_delayed = False
            send_now = True

        try:
            frappe.sendmail(
                attachments=_attachments,
                bcc=bcc,
                cc=cc,
                communication=communication.name,
                delayed=send_delayed,
                expose_recipients="header",
                message=rendered_template if rendered_template is not None else message,
                as_markdown=True,
                now=send_now,
                recipients=recipients,
                reference_doctype="HD Ticket",
                reference_name=self.name,
                reply_to=reply_to_email,
                sender=reply_to_email,
                subject=subject,
                with_container=False,
                in_reply_to=last_communication.name
                if last_communication.name
                else None,
            )
        except Exception as e:
            frappe.throw(_(e))

    @frappe.whitelist()
    # flake8: noqa
    def create_communication_via_contact(
        self, message, attachments=[], new_ticket=False
    ):
        if not new_ticket and frappe.db.get_single_value(
            "HD Settings", "enable_reply_email_to_agent"
        ):
            # send email to assigned agents
            self.send_reply_email_to_agent()

        # if self.status_category == "Paused" and not new_ticket:
        if not new_ticket:
            self.status = self.ticket_reopen_status
            self.save(ignore_permissions=True)

        c = frappe.new_doc("Communication")
        c.communication_type = "Communication"
        c.communication_medium = "Email"
        c.sent_or_received = "Received"
        c.email_status = "Open"
        c.subject = f"Re: {self.subject}"
        c.sender = frappe.session.user
        c.content = message
        c.status = "Linked"
        c.reference_doctype = "HD Ticket"
        c.reference_name = self.name
        c.ignore_permissions = True
        c.ignore_mandatory = True
        c.save(ignore_permissions=True)

        _attachments = self.get("attachments") or attachments or []
        if not len(_attachments):
            return
        QBFile = frappe.qb.DocType("File")
        condition_name = [QBFile.name == i["name"] for i in _attachments]
        frappe.qb.update(QBFile).set(QBFile.attached_to_name, c.name).set(
            QBFile.attached_to_doctype, "Communication"
        ).where(Criterion.any(condition_name)).run()

        # attach files to ticket
        file_urls = frappe.get_all(
            "File", filters={"attached_to_name": c.name}, pluck="file_url"
        )
        for url in file_urls:
            self.attach_file_with_doc("HD Ticket", self.name, url)

    def handle_inline_media_new_ticket(self):
        soup = BeautifulSoup(self.description, "html.parser")
        files = []  # List of file URLs
        for tag in soup.find_all(["img", "video"]):
            if tag.has_attr("src"):
                src = tag["src"]
                files.append(src)
        for f in files:
            file = frappe.db.exists(
                "File",
                {
                    "file_url": f,
                    "attached_to_doctype": ["is", "Not Set"],
                    "owner": frappe.session.user,
                },
            )
            if file:
                doc = frappe.get_doc("File", file)
                doc.attached_to_doctype = "HD Ticket"
                doc.attached_to_name = self.name
                doc.save()

    def send_reply_email_to_agent(self):
        assigned_agents = self.get_assigned_agents()
        if not assigned_agents:
            return

        recipients = [a.get("name") for a in self.get_assigned_agents()]

        email_content = frappe.db.get_single_value(
            "HD Settings", "reply_email_to_agent_content"
        )
        default_email_content = get_default_email_content("reply_to_agents")
        try:
            frappe.sendmail(
                recipients=recipients,
                subject=f"Re: {self.subject} - #{self.name}",
                message=self._get_rendered_template(
                    email_content,
                    default_email_content,
                    {
                        "ticket_url": frappe.utils.get_url(
                            "/helpdesk/tickets/" + str(self.name)
                        )
                    },
                ),
                reference_doctype="HD Ticket",
                reference_name=self.name,
                now=True,
            )
        except Exception as e:
            frappe.throw(_(e))

    def send_acknowledgement_email(self):
        acknowledgement_email_content = frappe.db.get_single_value(
            "HD Settings", "acknowledgement_email_content"
        )
        default_acknowledgement_email_content = get_default_email_content(
            "acknowledgement"
        )

        try:
            frappe.sendmail(
                recipients=[self.raised_by],
                subject=f"Ticket #{self.name}: We've received your request",
                message=self._get_rendered_template(
                    acknowledgement_email_content,
                    default_acknowledgement_email_content,
                ),
                reference_doctype="HD Ticket",
                reference_name=self.name,
                now=True,
                expose_recipients="header",
                email_headers={"X-Auto-Generated": "hd-acknowledgement"},
            )
        except Exception as e:
            frappe.throw(
                _("Could not send an acknowledgement email due to: {0}").format(e)
            )

    def send_team_notification_email(self):
        """
        Send email notification and create HD Notifications for all team members when a ticket is assigned to their team.
        - For assigned agents: Create "Assignment" notification
        - For non-assigned team members: Create "Team Assignment" notification
        """
        if not self.agent_group:
            return

        # Get all team members
        team_members = frappe.get_all(
            "HD Team Member",
            filters={"parent": self.agent_group},
            fields=["user"],
            pluck="user"
        )

        if not team_members:
            return

        # Get email addresses for team members
        recipients = []
        for user in team_members:
            email = frappe.db.get_value("User", user, "email")
            if email:
                recipients.append(email)

        if not recipients:
            return

        # Get ticket URL
        ticket_url = frappe.utils.get_url(f"/helpdesk/tickets/{self.name}")

        # Create email content
        email_subject = f"New Ticket #{self.name} Assigned to {self.agent_group} Team"
        
        # Nice HTML email template
        email_message = f"""
<div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; background-color: #f5f5f5;">
    <div style="background-color: #ffffff; border-radius: 8px; padding: 30px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
        <div style="text-align: center; margin-bottom: 30px;">
            <h1 style="color: #2c3e50; margin: 0; font-size: 24px;">🎫 New Ticket Assigned</h1>
        </div>
        
        <div style="background-color: #f8f9fa; border-left: 4px solid #007bff; padding: 20px; margin-bottom: 25px; border-radius: 4px;">
            <p style="margin: 0 0 10px 0; color: #495057; font-size: 16px; font-weight: 600;">
                A new ticket has been created and assigned to your team: <strong style="color: #007bff;">{self.agent_group}</strong>
            </p>
        </div>

        <div style="margin-bottom: 25px;">
            <table style="width: 100%; border-collapse: collapse;">
                <tr>
                    <td style="padding: 10px 0; color: #6c757d; font-weight: 600; width: 140px;">Ticket ID:</td>
                    <td style="padding: 10px 0; color: #212529;"><strong>#{self.name}</strong></td>
                </tr>
                <tr>
                    <td style="padding: 10px 0; color: #6c757d; font-weight: 600;">Subject:</td>
                    <td style="padding: 10px 0; color: #212529;">{frappe.utils.escape_html(self.subject or 'No Subject')}</td>
                </tr>
                <tr>
                    <td style="padding: 10px 0; color: #6c757d; font-weight: 600;">Priority:</td>
                    <td style="padding: 10px 0; color: #212529;">
                        <span style="padding: 4px 12px; border-radius: 12px; font-size: 12px; font-weight: 600; 
                            background-color: {'#dc3545' if self.priority == 'High' else '#ffc107' if self.priority == 'Medium' else '#28a745'}; 
                            color: {'#fff' if self.priority == 'High' else '#000' if self.priority == 'Medium' else '#fff'};">
                            {self.priority or 'Low'}
                        </span>
                    </td>
                </tr>
                <tr>
                    <td style="padding: 10px 0; color: #6c757d; font-weight: 600;">Ticket Type:</td>
                    <td style="padding: 10px 0; color: #212529;">{self.ticket_type or 'N/A'}</td>
                </tr>
                <tr>
                    <td style="padding: 10px 0; color: #6c757d; font-weight: 600;">Status:</td>
                    <td style="padding: 10px 0; color: #212529;">{self.status or 'Open'}</td>
                </tr>
            </table>
        </div>

        {f'<div style="background-color: #e9ecef; padding: 15px; border-radius: 4px; margin-bottom: 25px;"><p style="margin: 0; color: #495057; font-size: 14px; line-height: 1.6;">{frappe.utils.escape_html(frappe.utils.strip_html(self.description or ""))[:200]}{"..." if len(self.description or "") > 200 else ""}</p></div>' if self.description else ''}

        <div style="text-align: center; margin-top: 30px;">
            <a href="{ticket_url}" 
               style="display: inline-block; background-color: #007bff; color: #ffffff; padding: 12px 30px; 
                      text-decoration: none; border-radius: 5px; font-weight: 600; font-size: 16px;">
                View Ticket →
            </a>
        </div>

        <div style="margin-top: 30px; padding-top: 20px; border-top: 1px solid #dee2e6; text-align: center;">
            <p style="color: #6c757d; font-size: 12px; margin: 0;">
                This is an automated notification from your Helpdesk system.
            </p>
        </div>
    </div>
</div>
"""

        try:
            frappe.sendmail(
                recipients=recipients,
                subject=email_subject,
                message=email_message,
                reference_doctype="HD Ticket",
                reference_name=self.name,
                now=True,
                expose_recipients="header",
                email_headers={"X-Auto-Generated": "hd-team-notification"},
            )
            frappe.logger().info(
                f"Team notification email sent to {len(recipients)} members of team '{self.agent_group}' for ticket {self.name}"
            )
        except Exception as e:
            frappe.log_error(
                message=f"Could not send team notification email for ticket {self.name}: {str(e)}\n{frappe.get_traceback()}",
                title="Team Notification Email Error"
            )
            # Don't throw - email failure shouldn't break ticket creation

    def create_team_notifications(self):
        """
        Create HD Notifications for all team members when a ticket is assigned to their team.
        - For assigned agents: Create "Assignment" notification (ticket assigned to you)
        - For non-assigned team members: Create "Team Assignment" notification (ticket created for team)
        """
        if not self.agent_group:
            return

        # Get all team members
        team_members = frappe.get_all(
            "HD Team Member",
            filters={"parent": self.agent_group},
            fields=["user"],
            pluck="user"
        )

        if not team_members:
            return

        # Get assigned agents - HD Agent names are User IDs
        assigned_agents = self.get_assigned_agents()
        assigned_user_ids = {agent.get("name") for agent in assigned_agents} if assigned_agents else set()

        # Create HD Notification for each team member
        for user in team_members:
            try:
                # Determine notification type based on assignment
                # Check if this user is assigned to the ticket
                if user in assigned_user_ids:
                    # Assigned agent gets "Assignment" notification (ticket assigned to you)
                    notification_type = "Assignment"
                else:
                    # Non-assigned team member gets "Team Assignment" notification (ticket created for team)
                    notification_type = "Team Assignment"

                # Create HD Notification
                frappe.get_doc(
                    frappe._dict(
                        doctype="HD Notification",
                        user_from=frappe.session.user,
                        reference_ticket=self.name,
                        user_to=user,
                        notification_type=notification_type,
                    )
                ).insert(ignore_permissions=True)
            except frappe.DuplicateEntryError:
                # Duplicate Assignment notifications are intentionally ignored.
                continue
            except Exception as e:
                frappe.log_error(
                    message=f"Could not create HD Notification for user {user} on ticket {self.name}: {str(e)}",
                    title="HD Notification Creation Error"
                )

    def assign_all_team_members_if_enabled(self):
        """
        Optionally assign all members of the selected team to this ticket.
        Controlled by HD Settings.assign_all_team_members_on_team_assignment.
        """
        if not self.agent_group:
            return

        enable_assign_all = frappe.get_cached_value(
            "HD Settings",
            "HD Settings",
            "assign_all_team_members_on_team_assignment",
        )
        if not int(enable_assign_all or 0):
            return

        team_members = frappe.get_all(
            "HD Team Member",
            filters={"parent": self.agent_group},
            pluck="user",
        )
        if not team_members:
            return

        current_assignees = set()
        assignees = get_assignees({"doctype": "HD Ticket", "name": self.name}) or []
        for row in assignees:
            if getattr(row, "owner", None):
                current_assignees.add(row.owner)

        users_to_assign = [u for u in team_members if u and u not in current_assignees]
        if not users_to_assign:
            return

        try:
            assign(
                {
                    "assign_to": users_to_assign,
                    "doctype": "HD Ticket",
                    "name": self.name,
                }
            )
        except Exception:
            frappe.log_error(
                title="HD Ticket Team Members Assignment Error",
                message=frappe.get_traceback(),
            )

    def enqueue_notification_automation_rules(self):
        """Run notification rules in background to keep ticket save responsive."""
        try:
            frappe.enqueue(
                "helpdesk.helpdesk.doctype.hd_ticket.hd_ticket.run_notification_automation_rules_job",
                ticket_name=self.name,
                user=frappe.session.user,
                queue="short",
                now=False,
            )
        except Exception:
            frappe.log_error(
                title="HD Ticket Notification Automation Enqueue Error",
                message=frappe.get_traceback(),
            )

    def run_notification_automation_rules(self):
        """Evaluate HD Settings rules and create HD Notification / optional email."""
        try:
            settings = frappe.get_cached_doc("HD Settings", "HD Settings")
            rules = settings.get("ticket_notification_rules") or []
            if not rules:
                return

            for rule in rules:
                if not getattr(rule, "is_enabled", 1):
                    continue

                condition = (getattr(rule, "condition", None) or "").strip()
                if not condition:
                    condition = self._convert_condition_json_to_expression(
                        getattr(rule, "condition_json", None)
                    )
                if not condition:
                    continue

                try:
                    matched = bool(frappe.safe_eval(condition, None, {"doc": self.as_dict()}))
                except Exception:
                    frappe.log_error(
                        title="HD Ticket Notification Rule Error",
                        message=f"Invalid condition for rule '{getattr(rule, 'description', '')}'\n{frappe.get_traceback()}",
                    )
                    continue

                if not matched:
                    continue

                recipients = self._resolve_notification_rule_recipients(rule)
                if not recipients:
                    continue

                message = (getattr(rule, "notification_message", None) or "").strip()
                notification_type = getattr(rule, "notification_type", None) or "Team Assignment"
                actor = frappe.session.user if frappe.session.user else self.owner

                for user in recipients:
                    try:
                        frappe.get_doc(
                            frappe._dict(
                                doctype="HD Notification",
                                user_from=actor,
                                user_to=user,
                                notification_type=notification_type,
                                reference_ticket=self.name,
                                message=self._render_rule_template(
                                    message,
                                    recipient=user,
                                ),
                            )
                        ).insert(ignore_permissions=True)
                    except frappe.DuplicateEntryError:
                        # Duplicate Assignment notifications are intentionally ignored.
                        continue
                    except Exception:
                        frappe.log_error(
                            title="HD Notification Automation Insert Error",
                            message=frappe.get_traceback(),
                        )

                if getattr(rule, "send_email", 0):
                    subject_template = (getattr(rule, "email_subject", None) or "").strip() or f"Ticket #{self.name} Notification"
                    body_template = (getattr(rule, "email_message", None) or "").strip() or message
                    sender_email = self._get_notification_rule_sender_email()
                    try:
                        for recipient in recipients:
                            rendered_subject = self._render_rule_template(
                                subject_template, recipient=recipient
                            )
                            rendered_body = self._render_rule_template(
                                body_template, recipient=recipient
                            )
                            email_args = {
                                "recipients": [recipient],
                                "subject": rendered_subject,
                                "message": rendered_body,
                                "reference_doctype": "HD Ticket",
                                "reference_name": self.name,
                                "now": True,
                            }
                            if sender_email:
                                email_args["sender"] = sender_email
                                email_args["reply_to"] = sender_email
                            frappe.sendmail(**email_args)
                    except Exception:
                        frappe.log_error(
                            title="HD Notification Automation Email Error",
                            message=frappe.get_traceback(),
                        )
        except Exception:
            frappe.log_error(
                title="HD Ticket Notification Automation Error",
                message=frappe.get_traceback(),
            )

    def _resolve_notification_rule_recipients(self, rule):
        notify_to = getattr(rule, "notify_to", None) or "Assigned Agents"
        recipients = []

        if notify_to == "Assigned Agents":
            recipients = [a.get("name") for a in (self.get_assigned_agents() or []) if a.get("name")]
        elif notify_to == "Team Members":
            if self.agent_group:
                recipients = frappe.get_all(
                    "HD Team Member",
                    filters={"parent": self.agent_group},
                    pluck="user",
                )
        elif notify_to == "Ticket Owner":
            recipients = [self.owner] if self.owner else []
        elif notify_to == "Specific User":
            user = getattr(rule, "notify_user", None)
            recipients = [user] if user else []

        # Keep recipients clean and unique.
        recipients = [r for r in recipients if r]
        return list(dict.fromkeys(recipients))

    def _convert_condition_json_to_expression(self, condition_json):
        """Convert condition JSON into a safe expression string."""
        if not condition_json:
            return ""

        try:
            import json

            conditions = condition_json
            if isinstance(condition_json, str):
                conditions = json.loads(condition_json)
        except Exception:
            return ""

        def _parse(node):
            if isinstance(node, str):
                token = node.strip().lower()
                return token if token in {"and", "or"} else ""

            if isinstance(node, list):
                if len(node) == 3 and isinstance(node[0], str):
                    field, operator, value = node
                    op = (operator or "").strip().lower()
                    field_access = f"doc.{field}"

                    if op == "is":
                        value_str = str(value or "").strip().lower()
                        if value_str == "set":
                            return field_access
                        if value_str == "not set":
                            return f"not {field_access}"

                    if op in {"in", "not in"}:
                        if isinstance(value, list):
                            rhs = repr(value)
                        else:
                            rhs = repr(
                                [v.strip() for v in str(value or "").split(",") if v.strip()]
                            )
                        return f"{field_access} {op} {rhs}"

                    mapped_op = {"=": "==", "equals": "=="}.get(op, operator)
                    return f"{field_access} {mapped_op} {repr(value)}"

                parts = [_parse(x) for x in node]
                parts = [p for p in parts if p]
                return " ".join(parts)

            return ""

        expression = _parse(conditions).strip()
        return expression

    def _render_rule_template(self, template: str, recipient: str | None = None) -> str:
        """
        Render rule template text with dynamic variables.
        Supported variables:
        - {{ ticket_name }}
        - {{ ticket_subject }}
        - {{ ticket_status }}
        - {{ ticket_type }}
        - {{ ticket_priority }}
        - {{ ticket_team }}
        - {{ ticket_owner }}
        - {{ recipient }}
        - {{ recipient_name }}
        """
        template = template or ""
        recipient_name = ""
        if recipient:
            recipient_name = (
                frappe.db.get_value("User", recipient, "full_name") or recipient
            )

        context = {
            "ticket_name": self.name,
            "ticket_subject": self.subject or "",
            "ticket_status": self.status or "",
            "ticket_type": self.ticket_type or "",
            "ticket_priority": self.priority or "",
            "ticket_team": self.agent_group or "",
            "ticket_owner": self.owner or "",
            "recipient": recipient or "",
            "recipient_name": recipient_name,
        }
        try:
            return frappe.render_template(template, context)
        except Exception:
            # keep raw template if rendering fails
            return template

    def _get_notification_rule_sender_email(self) -> str | None:
        """
        Resolve sender email for notification automation emails from HD Settings.
        Falls back to ticket sender resolution if specific setting is missing.
        """
        email_account_name = frappe.get_cached_value(
            "HD Settings",
            "HD Settings",
            "ticket_notification_sender_email_account",
        )
        if email_account_name:
            email_id = frappe.db.get_value("Email Account", email_account_name, "email_id")
            if email_id:
                return email_id

        fallback_account = self.sender_email()
        if fallback_account and getattr(fallback_account, "email_id", None):
            return fallback_account.email_id
        return None

    @frappe.whitelist()
    def mark_seen(self):
        self.add_viewed(
            unique_views=True, force=True
        )  # Document class method, no way to add unique_views via document settings, hence used force and unique_views=True
        clear_notifications(ticket=self.name)

    def get_escalation_rule(self):
        filters = [
            {
                "priority": self.priority,
                "team": self.agent_group,
                "ticket_type": self.ticket_type,
            },
            {
                "priority": self.priority,
                "team": self.agent_group,
            },
            {
                "priority": self.priority,
                "ticket_type": self.ticket_type,
            },
            {
                "team": self.agent_group,
                "ticket_type": self.ticket_type,
            },
            {
                "priority": self.priority,
            },
            {
                "team": self.agent_group,
            },
            {
                "ticket_type": self.ticket_type,
            },
        ]

        for i in range(len(filters)):
            try:
                f = {
                    **filters[i],
                    "is_enabled": True,
                }
                rule = frappe.get_last_doc("HD Escalation Rule", filters=f)
                if rule:
                    return rule
            except Exception:
                pass

    def apply_escalation_rule(self):
        if not self.status_category == "Open" or self.is_new():
            return
        escalation_rule = self.get_escalation_rule()
        if not escalation_rule:
            return
        self.agent_group = escalation_rule.to_team or self.agent_group
        self.priority = escalation_rule.to_priority or self.priority
        self.ticket_type = escalation_rule.to_ticket_type or self.ticket_type

        if escalation_rule.to_agent:
            self.assign_agent(escalation_rule.to_agent)

    def set_sla(self):
        """
        Find an SLA to apply to this ticket.
        """
        if sla := get_sla(self):
            self.sla = sla.name

    def apply_sla(self):
        """
        Apply SLA if set.
        """
        if sla := frappe.get_last_doc("HD Service Level Agreement", {"name": self.sla}):
            sla.apply(self)

    def set_default_status(self):
        if self.is_new():
            self.status = self.default_open_status

    def set_status_category(self):
        self.status_category = self.status_category or frappe.get_value(
            "HD Ticket Status",
            self.status,
            "category",
        )

    # `on_communication_update` is a special method exposed from `Communication` doctype.
    # It is called when a communication is updated. Beware of changes as this effectively
    # is an external dependency. Refer `communication.py` of Frappe framework for more.
    # Since this is called from communication itself, `c` is the communication doc.
    def on_communication_update(self, c):
        # If communication is incoming, then it is a reply from customer, and ticket must
        # be reopened.
        # handle re opening tickets for email
        if c.sent_or_received == "Received":
            # check if agent has replied

            if self.has_agent_replied:
                self.status = self.ticket_reopen_status
            else:
                self.status = self.default_open_status
        # If communication is outgoing, it must be a reply from agent
        if c.sent_or_received == "Sent":
            # Set first response date if not set already
            self.first_responded_on = (
                self.first_responded_on or frappe.utils.now_datetime()
            )

            # TODO: remove this feature once we add automation feature
            if frappe.db.get_single_value("HD Settings", "auto_update_status"):
                self.status = frappe.db.get_single_value(
                    "HD Settings", "update_status_to"
                )

        # Fetch description from communication if not set already. This might not be needed
        # anymore as a communication is created when a ticket is created.
        self.description = self.description or c.content
        # Save the ticket, allowing for hooks to run.
        self.save()

    def attach_file_with_doc(self, doctype, docname, file_url):
        file_doc = frappe.new_doc("File")
        file_doc.attached_to_doctype = doctype
        file_doc.attached_to_name = docname
        file_doc.file_url = file_url
        file_doc.save(ignore_permissions=True)

    @staticmethod
    def default_list_data(show_customer_portal_fields=False):
        columns = [
            {
                "label": "ID",
                "type": "Int",
                "key": "name",
                "width": "5rem",
            },
            {
                "label": "Subject",
                "type": "Data",
                "key": "subject",
                "width": "25rem",
            },
            {
                "label": "Status",
                "type": "Select",
                "key": "status",
                "width": "8rem",
            },
            {
                "label": "First response",
                "type": "Datetime",
                "key": "response_by",
                "width": "8rem",
            },
            {
                "label": "Resolution",
                "type": "Datetime",
                "key": "resolution_by",
                "width": "8rem",
            },
            {
                "label": "Assigned To",
                "type": "MultipleAvatar",
                "key": "_assign",
                "width": "8rem",
            },
            {
                "label": "Customer",
                "type": "Link",
                "key": "customer",
                "options": "HD Customer",
                "width": "8rem",
            },
            {
                "label": "Priority",
                "type": "Link",
                "options": "HD Ticket Priority",
                "key": "priority",
                "width": "10rem",
            },
            {
                "label": "Type",
                "type": "Link",
                "options": "HD Ticket Type",
                "key": "ticket_type",
                "width": "11rem",
            },
            {
                "label": "Team",
                "type": "Link",
                "options": "HD Team",
                "key": "agent_group",
                "width": "10rem",
            },
            {
                "label": "Contact",
                "type": "Link",
                "key": "contact",
                "options": "Contact",
                "width": "8rem",
            },
            {
                "label": "Rating",
                "type": "Rating",
                "key": "feedback_rating",
                "width": "10rem",
            },
            {
                "label": "Created",
                "type": "Datetime",
                "key": "creation",
                "options": "Contact",
                "width": "8rem",
            },
        ]
        customer_portal_columns = [
            {
                "label": "ID",
                "type": "Int",
                "key": "name",
                "width": "5rem",
            },
            {
                "label": "Subject",
                "type": "Data",
                "key": "subject",
                "width": "22rem",
            },
            {
                "label": "Status",
                "type": "Select",
                "key": "status",
                "width": "11rem",
            },
            {
                "label": "Priority",
                "type": "Link",
                "options": "HD Ticket Priority",
                "key": "priority",
                "width": "10rem",
            },
            {
                "label": "First response",
                "type": "Datetime",
                "key": "response_by",
                "width": "8rem",
            },
            {
                "label": "Resolution",
                "type": "Datetime",
                "key": "resolution_by",
                "width": "8rem",
            },
            {
                "label": "Team",
                "type": "Link",
                "options": "HD Team",
                "key": "agent_group",
                "width": "10rem",
            },
            {
                "label": "Created",
                "type": "Datetime",
                "key": "creation",
                "options": "Contact",
                "width": "8rem",
            },
        ]
        rows = [
            "name",
            "subject",
            "status",
            "status_category",
            "priority",
            "ticket_type",
            "agent_group",
            "contact",
            "agreement_status",
            "response_by",
            "resolution_by",
            "customer",
            "first_responded_on",
            "modified",
            "creation",
            "_assign",
            "resolution_date",
        ]
        return {
            "columns": customer_portal_columns
            if show_customer_portal_fields
            else columns,
            "rows": rows,
        }

    def parse_content(self, content):
        """
        Finds 'src' attribute of img/video and replaces it  with 'embed' attribute
        embed tag is important because framework replaces it with <img src="cid:content_id">
        this in turn is displayed as an image in the mail sent to the customer
        """
        if not content:
            return ""

        soup = BeautifulSoup(content, "html.parser")

        for tag in soup.find_all(["img", "video"]):
            if tag.name == "img":
                tag["embed"] = tag.get("src")
                tag["width"] = "80%"
                tag["height"] = "80%"
                del tag["src"]
            elif tag.name == "video":
                tag["embed"] = tag.get("src")
                del tag["src"]

        return str(soup)

    @staticmethod
    def filter_standard_fields(fields):
        for f in fields:
            if f["name"] in customer_not_allowed_fields:
                fields.remove(f)
        return fields


# Check if `user` has access to this specific ticket (`doc`). This implements extra
# permission checks which is not possible with standard permission system. This function
# is being called from hooks. `doc` is the ticket to check against
def has_permission(doc, user=None):
    if not user:
        user = frappe.session.user

    if (
        doc.contact == user
        or doc.raised_by == user
        or doc.owner == user
        or is_admin(user)
        or is_agent(user) 
        or doc.customer in get_customer(user)
    ):
        return True

    if not is_agent(user):
        return False

    # First check if ticket is assigned to user - they should always have access
    # even if ticket belongs to another team
    if doc.get("_assign", None):
        try:
            assignees = json.loads(doc._assign)
            if user in assignees:
                return True
        except:
            pass  # Continue to other checks if assignment parsing fails
    
    # Check if user is mentioned in this ticket - they should have access
    # even if not assigned and ticket belongs to another team
    # Optimized: Use cached query to avoid repeated DB calls per ticket check
    cache_key = f"hd_mentioned_tickets_{user}"
    mentioned_tickets = frappe.cache().get_value(cache_key)
    
    if mentioned_tickets is None:
        # Cache miss: fetch all tickets where user is mentioned (single query)
        mentioned_tickets = set(
            frappe.db.get_all(
                "HD Notification",
                filters={
                    "user_to": user,
                    "notification_type": "Mention",
                },
                pluck="reference_ticket",
                distinct=True,
            )
        )
        # Cache for 1 hour - reduces DB queries from N (per ticket) to 1 (per user per hour)
        frappe.cache().set_value(cache_key, mentioned_tickets)
        frappe.cache().expire(cache_key, 3600)
    
    if doc.name in mentioned_tickets:
        return True

    enable_restrictions = frappe.db.get_single_value(
        "HD Settings", "restrict_tickets_by_agent_group"
    )
    if not enable_restrictions:
        return True
    show_tickets_without_team = frappe.db.get_single_value(
        "HD Settings", "do_not_restrict_tickets_without_an_agent_group"
    )
    if show_tickets_without_team and not doc.get("agent_group"):
        return True

    teams = get_agents_team()
    if any([team.get("ignore_restrictions") for team in teams]):
        return True

    team_names = [t.team_name for t in teams]
    exists = frappe.db.exists(
        "HD Team Member", {"parent": ["in", team_names], "user": frappe.session.user}
    )
    if exists and doc.get("agent_group") in team_names:
        return True

    return False


def is_crm_agent(user):
    from frappe_messenger.util import get_assignable_agents, get_roles_with_full_access
    assignable_agents = get_assignable_agents()
    roles_with_full_access = get_roles_with_full_access()
    user_roles = frappe.get_roles(user)
    is_msg_admin = "Message Admin" in user_roles
    return any(role in roles_with_full_access for role in user_roles) and (user in assignable_agents or is_msg_admin)  



# Custom perms for list query. Only the `WHERE` part
# https://frappeframework.com/docs/user/en/python-api/hooks#modify-list-query
def permission_query(user):
    if not user:
        user = frappe.session.user
    if is_admin(user) or is_crm_agent(user):
        return

    #  To handle the case for normal users i.e. not agents
    customer = get_customer(user)
    query = "(`tabHD Ticket`.owner = {user} OR `tabHD Ticket`.contact = {user} OR `tabHD Ticket`.raised_by = {user})".format(
        user=frappe.db.escape(user)
    )
    for c in customer:
        query += " OR `tabHD Ticket`.customer={customer}".format(
            customer=frappe.db.escape(c)
        )

    if not is_agent(user):
        return query

    teams = get_agents_team(user)
    team_names = [t.get("team_name") for t in teams if t.get("team_name")]

    # Give visibility to tickets assigned to the agent's teams, even if not directly assigned
    if team_names:
        team_names_sql = ", ".join(frappe.db.escape(team) for team in team_names)
        query += f" OR (`tabHD Ticket`.agent_group in ({team_names_sql}))"

        team_users = frappe.get_all(
            "HD Team Member", filters={"parent": ["in", team_names]}, pluck="user"
        )
        team_user_conditions = [
            "(JSON_SEARCH(`tabHD Ticket`._assign, 'all', {user}) IS NOT NULL)".format(
                user=frappe.db.escape(u)
            )
            for u in team_users
        ]
        if team_user_conditions:
            query += f" OR ({' OR '.join(team_user_conditions)})"

    # First, add assignment check - users should always see tickets assigned to them
    # even if the ticket belongs to another team
    query += (
        " OR (JSON_SEARCH(`tabHD Ticket`._assign, 'all', {user}) IS NOT NULL)".format(
            user=frappe.db.escape(user)
        )
    )
    
    # Also check for mentions - users should see tickets where they are mentioned
    # even if not assigned and ticket belongs to another team
    # Optimized: Uses EXISTS with indexed columns (reference_ticket, user_to, notification_type)
    query += (
        " OR EXISTS (SELECT 1 FROM `tabHD Notification` "
        "WHERE `tabHD Notification`.reference_ticket = `tabHD Ticket`.name "
        "AND `tabHD Notification`.user_to = {user} "
        "AND `tabHD Notification`.notification_type = 'Mention' "
        "LIMIT 1)".format(
            user=frappe.db.escape(user)
        )
    )

    enable_restrictions = frappe.db.get_single_value(
        "HD Settings", "restrict_tickets_by_agent_group"
    )
    if not enable_restrictions:
        return query  # If not enabled, return query with assignment check

    show_tickets_without_team = frappe.db.get_single_value(
        "HD Settings", "do_not_restrict_tickets_without_an_agent_group"
    )

    if show_tickets_without_team:
        query += " OR (`tabHD Ticket`.agent_group is null OR `tabHD Ticket`.agent_group = '')"

    # If agent belongs to the team which has ignore_permission set to 1.
    # that means this team can see all the tickets without any restriction,
    # Event the other team's tickets.
    if any(team.get("ignore_restrictions") for team in teams):
        all_teams = frappe.get_all("HD Team", pluck="name")
        if not all_teams:
            return query
        all_teams = ", ".join(f"'{team}'" for team in all_teams)
        query += f" OR (`tabHD Ticket`.agent_group in ({all_teams}))".format(
            all_teams=all_teams
        )
        if not show_tickets_without_team:
            query += " OR (`tabHD Ticket`.agent_group is null)"
        return query

    team_names = [t.get("team_name") for t in teams]

    if not team_names:
        return query

    # Here we will apply the restriction based on the teams the agent belongs to.
    team_names = ", ".join(f"'{team}'" for team in team_names)
    query += f" OR (`tabHD Ticket`.agent_group in ({team_names}))".format(
        team_names=team_names
    )
    return query


def set_guest_ticket_creation_permission():
    doctype = "HD Ticket"
    add_permission(doctype, "Guest", 0)

    role = "Guest"
    permlevel = 0
    ptype = ["read", "write", "create", "if_owner"]

    for p in ptype:
        # update permissions
        update_permission_property(doctype, role, permlevel, p, 1)


def remove_guest_ticket_creation_permission():
    doctype = "HD Ticket"
    role = "Guest"
    permlevel = 0
    remove(doctype, role, permlevel, 1)


customer_not_allowed_fields = ["customer"]


def close_tickets_after_n_days():
    if frappe.db.get_single_value("HD Settings", "auto_close_tickets") == 0:
        return

    status, days_threshold = frappe.db.get_value(
        "HD Settings", "HD Settings", ["auto_close_status", "auto_close_after_days"]
    )

    tickets_to_close = (
        frappe.db.sql(
            """
                SELECT t.name
                FROM `tabHD Ticket` t
                INNER JOIN (
                    SELECT reference_name, MAX(communication_date) as last_communication_date
                    FROM `tabCommunication` 
                    WHERE reference_doctype = 'HD Ticket'
                    GROUP BY reference_name
                ) latest_comm ON t.name = latest_comm.reference_name
                WHERE t.status = %(status)s
                AND latest_comm.last_communication_date < DATE_SUB(NOW(), INTERVAL %(days_threshold)s DAY)
            """,
            {"days_threshold": days_threshold, "status": status},
            pluck="name",
        )
        or []
    )
    tickets_to_close = list(set(tickets_to_close))

    # cant do set_value because SLA will not be applied as setting directly to db and doc is not running.
    for ticket in tickets_to_close:
        doc = frappe.get_doc("HD Ticket", ticket)
        doc.status = "Closed"
        doc.flags.ignore_validate = True
        doc.save(ignore_permissions=True)
        frappe.db.commit()  # nosemgrep


def mark_overdue_tickets():
    try:
        """Mark tickets as Overdue when resolution_date has passed and they are still open."""
        overdue_status = frappe.db.get_value("HD Ticket Status", {"name": "Overdue"}, "name")
        if not overdue_status:
            print("No overdue status found")
            return
        print("overdue_status",overdue_status)
        resolved_statuses = set(
            frappe.get_all(
                "HD Ticket Status", filters={"category": "Resolved", "name": ["!=", "Overdue"]}, pluck="name"
            )
            or []
        )
        # Closed may not be in the resolved category in every setup
        resolved_statuses.update({"Closed", "Resolved"})

        now_ts = now_datetime()
        tickets = frappe.get_all(
            "HD Ticket",
            filters=[
                ["resolution_by", "is", "set"],
                ["resolution_by", "<", now_ts],
                ["status", "not in", list(resolved_statuses)],
                ["status", "!=", overdue_status],
            ],
            pluck="name",
        )
        print("tickets",tickets)

        if not tickets:
            return

        for ticket in tickets:
            frappe.db.set_value(
                "HD Ticket",
                ticket,
                {"status": overdue_status, "status_category": "Paused"},
                update_modified=False,
            )

        frappe.db.commit()  # nosemgrep
    except Exception as e:
        frappe.log_error(title="Error marking overdue tickets", message=frappe.get_traceback())


def _preview_notification_rule_recipients(ticket: HDTicket, rule: dict) -> list[str]:
    notify_to = (rule.get("notify_to") or "Assigned Agents").strip()
    recipients: list[str] = []

    if notify_to == "Assigned Agents":
        recipients = [a.get("name") for a in (ticket.get_assigned_agents() or []) if a.get("name")]
    elif notify_to == "Team Members":
        if ticket.agent_group:
            recipients = frappe.get_all(
                "HD Team Member",
                filters={"parent": ticket.agent_group},
                pluck="user",
            )
    elif notify_to == "Ticket Owner":
        recipients = [ticket.owner] if ticket.owner else []
    elif notify_to == "Specific User":
        user = rule.get("notify_user")
        recipients = [user] if user else []

    recipients = [r for r in recipients if r]
    return list(dict.fromkeys(recipients))


def run_notification_automation_rules_job(ticket_name: str, user: str | None = None):
    """Background worker entrypoint for notification automation rules."""
    if not ticket_name:
        return
    try:
        if user:
            frappe.set_user(user)
        ticket = frappe.get_doc("HD Ticket", ticket_name)
        ticket.run_notification_automation_rules()
    except Exception:
        frappe.log_error(
            title="HD Ticket Notification Automation Background Error",
            message=frappe.get_traceback(),
        )


@frappe.whitelist()
def evaluate_hd_ticket_rule_preview(
    ticket_name: str | int, rule: dict | str, rule_kind: str = "notification"
):
    """
    Preview if a rule matches a given ticket and return evaluation details.
    Used by HD Settings UI "Test Rule" action.
    """
    if not ticket_name:
        frappe.throw(_("Ticket is required"))

    ticket_name = str(ticket_name)
    ticket: HDTicket = frappe.get_doc("HD Ticket", ticket_name)
    if not ticket.has_permission("read"):
        frappe.throw(_("Not permitted"), frappe.PermissionError)

    if isinstance(rule, str):
        try:
            import json

            rule = json.loads(rule)
        except Exception:
            rule = {}
    rule = rule or {}

    condition = (rule.get("condition") or "").strip()
    if not condition:
        condition = ticket._convert_condition_json_to_expression(rule.get("condition_json"))

    matched = True
    if condition:
        try:
            matched = bool(frappe.safe_eval(condition, None, {"doc": ticket.as_dict()}))
        except Exception:
            return {
                "matched": False,
                "condition": condition,
                "error": _("Invalid condition. Please check selected values."),
            }

    if rule_kind == "team_assignment":
        return {
            "matched": matched,
            "condition": condition,
            "team": rule.get("team"),
            "ticket": ticket.name,
        }

    recipients = _preview_notification_rule_recipients(ticket, rule) if matched else []
    recipient_rows = (
        frappe.get_all(
            "User",
            filters={"name": ["in", recipients]},
            fields=["name", "full_name", "email"],
        )
        if recipients
        else []
    )
    return {
        "matched": matched,
        "condition": condition,
        "ticket": ticket.name,
        "recipients": recipient_rows,
    }
