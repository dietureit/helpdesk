import frappe
from frappe.model.document import Document


def _ensure_role(invitation: Document, role_name: str) -> None:
    """Append role to invitation if not already present."""
    if not any(r.role == role_name for r in invitation.roles):
        invitation.append("roles", {"role": role_name})


def before_insert(invitation: Document) -> None:
    """
    Auto-augment roles on invitation:
    - Agent      -> + Messenger User, Raven User, Employee
    - Agent Manager -> + Messenger Manager, Raven User, Employee
    - System Manager/Admin -> + Messenger Admin
    """
    invited_roles = {r.role for r in invitation.roles}

    if "Agent" in invited_roles:
        _ensure_role(invitation, "Messenger User")
        _ensure_role(invitation, "Raven User")
        _ensure_role(invitation, "Employee")

    if "Agent Manager" in invited_roles:
        _ensure_role(invitation, "Messenger Manager")
        _ensure_role(invitation, "Raven User")
        _ensure_role(invitation, "Employee")

    if "System Manager" in invited_roles or "Administrator" in invited_roles:
        _ensure_role(invitation, "Messenger Admin")


def after_accept(invitation: Document, user: Document, user_inserted: bool) -> None:
    if not frappe.db.exists("HD Agent", {"user": user.email}):
        frappe.get_doc(
            doctype="HD Agent",
            user=user.email,
            agent_name=user.first_name,
            is_active=True,
        ).insert(True)
