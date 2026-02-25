import frappe


def execute():
    settings = frappe.get_single("HD Settings")

    target_mappings = [
        ("Payment Issue", "Payment"),
        ("Quality", "Hygine"),
        ("Delivery", "Delivery"),
        ("Refund", "Payment"),
        ("Technical", "Technical"),
        ("Problem", "Food"),
        ("Incident", "Product Experts"),
        ("Packaging", "Packaging"),
        ("Unspecified", "Other Issues"),
    ]

    # Map existing rows by ticket_type for deterministic upsert behavior.
    existing_by_ticket_type = {}
    for row in settings.get("ticket_type_team_assignment_rules") or []:
        if row.ticket_type and row.ticket_type not in existing_by_ticket_type:
            existing_by_ticket_type[row.ticket_type] = row

    changed = False
    for ticket_type, team in target_mappings:
        if not frappe.db.exists("HD Ticket Type", ticket_type):
            frappe.log_error(
                title="Ticket Type Team Mapping Patch",
                message=f"Skipping mapping: missing HD Ticket Type '{ticket_type}'",
            )
            continue

        if not frappe.db.exists("HD Team", team):
            frappe.log_error(
                title="Ticket Type Team Mapping Patch",
                message=f"Skipping mapping: missing HD Team '{team}'",
            )
            continue

        existing = existing_by_ticket_type.get(ticket_type)
        if existing:
            if existing.team != team or not int(existing.enabled or 0):
                existing.team = team
                existing.enabled = 1
                changed = True
        else:
            settings.append(
                "ticket_type_team_assignment_rules",
                {
                    "enabled": 1,
                    "ticket_type": ticket_type,
                    "team": team,
                },
            )
            changed = True

    if changed:
        settings.save(ignore_permissions=True)
