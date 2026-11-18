"""Start the ticket tag list (Settings > Ticket Tags) with "Personal Preferences".
New sites get them from after_install, which marks every patch as already run."""

from helpdesk.setup.install import add_default_ticket_tags


def execute():
    add_default_ticket_tags()
