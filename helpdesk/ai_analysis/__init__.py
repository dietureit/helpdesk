"""AI Analysis: recurring issues across tickets, chats and calls (see helpdesk/api/ai_analysis.py)."""

import frappe
from frappe.utils import cint, flt, getdate

DEPARTMENTS = [
    "Kitchen & QA",
    "Operations & Packing",
    "Delivery",
    "Customer Service",
    "Tech",
    "Marketing & Sales",
    "Finance",
]
DECIDER_ROLES = ("System Manager", "Agent Manager", "Messenger Admin", "Messenger Manager")

DEFAULT_COUNCIL = ["openai/gpt-5.4", "google/gemini-2.5-pro"]
DEFAULT_CHAIRMAN = "anthropic/claude-sonnet-5.5"
DEFAULT_RESEARCH = "openai/gpt-4.1"
DEFAULT_BUDGET_USD = 100.0
DEFAULT_RETENTION_MONTHS = 18


def conf() -> frappe._dict:
    from helpdesk.api import ticket_ai

    s = frappe.get_cached_doc("HD Settings")
    council = [m.strip() for m in (s.get("ai_analysis_council_models") or "").splitlines() if m.strip()]
    return frappe._dict(
        enabled=bool(cint(s.get("enable_ai_analysis"))),
        legal_approval=(s.get("ai_analysis_legal_approval") or "").strip(),
        model=(s.get("ai_analysis_model") or "").strip() or ticket_ai.get_config()["model"],
        council_models=council or list(DEFAULT_COUNCIL),
        chairman_model=(s.get("ai_analysis_chairman_model") or "").strip() or DEFAULT_CHAIRMAN,
        web_research=bool(cint(s.get("enable_ai_web_research", 1))),
        research_model=(s.get("ai_analysis_research_model") or "").strip() or DEFAULT_RESEARCH,
        start_date=getdate(s.get("ai_analysis_start_date")) if s.get("ai_analysis_start_date") else None,
        exclude_staff_phones=bool(cint(s.get("ai_analysis_exclude_staff_phones", 1))),
        require_zdr=bool(cint(s.get("ai_analysis_require_zdr"))),
        mask_health=bool(cint(s.get("ai_analysis_mask_health_quotes"))),
        budget_usd=flt(s.get("ai_analysis_monthly_budget_usd")) or DEFAULT_BUDGET_USD,
        retention_months=cint(s.get("ai_analysis_retention_months")) or DEFAULT_RETENTION_MONTHS,
    )


def analysis_enabled() -> bool:
    from helpdesk.api import ticket_ai

    c = conf()
    return bool(c.enabled and c.legal_approval and ticket_ai.get_config()["base_url"] and ticket_ai._api_key())


def ai_provider() -> dict:
    provider = {"data_collection": "deny"}
    if conf().require_zdr:
        provider["zdr"] = True
    return provider


def is_decider(user: str | None = None) -> bool:
    from helpdesk.utils import is_dashboard_manager

    user = user or frappe.session.user
    return is_dashboard_manager(user) or "System Manager" in frappe.get_roles(user)
