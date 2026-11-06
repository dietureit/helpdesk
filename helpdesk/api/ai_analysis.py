"""AI Analysis page endpoints. Thin: validate, check the role, call helpdesk.ai_analysis.

Every endpoint is @frappe.whitelist() + @agent_only + _reader(): any agent reads the company-wide view,
except one whose HD Agent row is deactivated. Decision endpoints add _decider(). Responses never carry a
conversation name, phone, customer name or customer_key; contact refs are opaque hash names.
"""

import json
import re
from datetime import date, timedelta
from urllib.parse import quote

import frappe
from frappe import _
from frappe.utils import add_days, cint, get_fullname, getdate, now_datetime

from helpdesk.ai_analysis import DEPARTMENTS, analysis_enabled, conf, is_decider
from helpdesk.utils import agent_only, is_agent

CONTACT = "HD AI Contact"
ISSUE = "HD AI Contact Issue"
INSIGHT = "HD AI Insight"
ACTION = "HD AI Action"
CHANNELS = ("Ticket", "WhatsApp", "Instagram DM", "Instagram comment", "Facebook comment", "Messenger")
KINDS = ("problems", "demand", "feedback", "all")
REVIEWS = ("Confirmed", "Rejected", "")
EXCLUSION_TYPES = ("Ticket", "Conversation", "Phone", "Contact")
CARDS = ("quick_win", "structural_fix", "combined_plan")
REJECT_REASONS = ("Not feasible", "Already tried", "Wrong cause", "Too costly", "Other")
ACTION_STATUSES = ("Open", "In progress", "Done", "Dropped")
ACTION_FILTERS = ("open", "overdue", "verifying", "all")
RESEARCH_DAYS = 30  # a code's web research is reused this long, unless regenerated
MAX_DAYS = 731  # a window of at most two years
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
CODE = re.compile(r"[A-Z][A-Z0-9_]{1,63}")
PLACEHOLDER = re.compile(r"\{\{\s*([\w.]+)\s*\}\}")
# Defence in depth: these never leave the server, whatever an engine function returns.
PRIVATE_KEYS = frozenset(
    {
        "conversation",
        "customer_key",
        "source_key",
        "identity",
        "phone",
        "sender_id",
        "sender_name",
        "customer_name",
        "alias_map",
        "input_json",
    }
)


def _reader():
    """Any agent reads, except one whose HD Agent row is deactivated (role-only agents have no row)."""
    active = frappe.db.get_value("HD Agent", {"user": frappe.session.user}, "is_active")
    if active is not None and not cint(active):
        frappe.throw(_("Your agent account is deactivated."), frappe.PermissionError)


def _decider():
    if not is_decider():
        frappe.throw(_("Only managers can do this."), frappe.PermissionError)


def _public(value):
    if isinstance(value, dict):
        return {k: _public(v) for k, v in value.items() if k not in PRIVATE_KEYS}
    if isinstance(value, list | tuple):
        return [_public(v) for v in value]
    return value


# --- input checks (this is the trust boundary) ------------------------------------------------------


def _date(value, label: str) -> date:
    value = value.strip() if isinstance(value, str) else ""
    if DATE.fullmatch(value):
        try:
            return date.fromisoformat(value)
        except ValueError:
            pass
    frappe.throw(_("{0} must be a date like 2026-06-30.").format(label))


def _window(from_date, to_date) -> tuple[date, date]:
    if not from_date and not to_date:
        from helpdesk.ai_analysis import metrics

        window = metrics.default_window()
        return getdate(window["from_date"]), getdate(window["to_date"])
    start, end = _date(from_date, _("From date")), _date(to_date, _("To date"))
    if start > end:
        frappe.throw(_("From date must be on or before To date."))
    if (end - start).days > MAX_DAYS:
        frappe.throw(_("Pick a period of at most two years."))
    return start, end


def _choice(value, options, label: str, required: bool = False):
    """A value from `options`, or None when blank. The value is never echoed back (no HTML in errors)."""
    value = value.strip() if isinstance(value, str) else value
    if value in (None, "") and not required:
        return None
    if value not in options:
        frappe.throw(_("Unknown {0}.").format(label))
    return value


def _text(value, label: str, max_length: int) -> str:
    value = value.strip() if isinstance(value, str) else ""
    if not value or len(value) > max_length:
        frappe.throw(_("{0} is required, at most {1} characters.").format(label, max_length))
    return value


def _list(value, label: str, max_items: int) -> list:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            value = None
    if not isinstance(value, list) or not 1 <= len(value) <= max_items:
        frappe.throw(_("{0} must be a list of 1 to {1} items.").format(label, max_items))
    return value


def _names(value, label: str, max_items: int) -> list[str]:
    return list(dict.fromkeys(_text(v, label, 140) for v in _list(value, label, max_items)))


def _code(code) -> str:
    code = code.strip() if isinstance(code, str) else ""
    if not (CODE.fullmatch(code) and frappe.db.exists("HD AI Issue Code", code)):
        frappe.throw(_("Unknown issue code."))
    return code


def _ref(ref) -> str:
    ref = ref.strip() if isinstance(ref, str) else ""
    if not (0 < len(ref) <= 140 and frappe.db.exists(CONTACT, ref)):
        frappe.throw(_("This case no longer exists. Refresh the page."), frappe.DoesNotExistError)
    return ref


def _filters(from_date, to_date, channel, dept) -> dict:
    start, end = _window(from_date, to_date)
    return {
        "from_date": start,
        "to_date": end,
        "channel": _choice(channel, CHANNELS, _("channel")),
        "dept": _choice(dept, DEPARTMENTS, _("department")),
    }


def _note(value, label: str, max_length: int) -> str:
    """Optional text: "" when blank, else at most max_length characters."""
    value = value.strip() if isinstance(value, str) else ""
    if len(value) > max_length:
        frappe.throw(_("{0} must be at most {1} characters.").format(label, max_length))
    return value


def _flag(value) -> bool:
    return str(value).strip().lower() in ("1", "true", "yes")


def _issue_code(code) -> str:
    code = _code(code)
    if code == "NEW":
        frappe.throw(_("Pick a named issue, not Unclassified."))
    return code


def _insight(name, insight_type: str | None = None):
    name = _text(name, _("Insight"), 140)
    fields = ["name", "insight_type", "status", "decision", "issue_code", "output_json"]
    row = frappe.db.get_value(INSIGHT, name, fields, as_dict=True)
    if not row or (insight_type and row.insight_type != insight_type):
        frappe.throw(_("This result no longer exists. Refresh the page."), frappe.DoesNotExistError)
    return row


def _output(row) -> dict:
    try:
        out = json.loads(row.output_json or "{}")
    except ValueError:
        out = {}
    return out if isinstance(out, dict) else {}


def _plan(insight):
    """A finished Suggestions insight: the one a decider combines, adopts or rejects."""
    row = _insight(insight, "Suggestions")
    if row.status not in ("Done", "No synthesis"):
        frappe.throw(_("These suggestions are not ready yet."))
    return row


def _agent_user(value) -> str:
    """An enabled user who is an agent, and not a deactivated one."""
    user = _text(value, _("Assignee"), 140)
    active = frappe.db.get_value("HD Agent", {"user": user}, "is_active")
    deactivated = active is not None and not cint(active)
    if deactivated or not (frappe.db.exists("User", {"name": user, "enabled": 1}) and is_agent(user)):
        frappe.throw(_("Assign the action to an active agent."))
    return user


def _amount(value, label: str):
    """An optional number from 0 up to a million; None when blank."""
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = -1.0
    if not 0 <= number < 1e6:  # NaN and infinity fail too
        frappe.throw(_("{0} must be a number from 0.").format(label))
    return number


def _ai_ready():
    """Refuse an AI request before anything is queued: AI off, no worker, or this month's budget used."""
    from helpdesk.ai_analysis import jobs

    if not analysis_enabled():
        frappe.throw(_("AI Analysis is off, so this cannot run."))
    if not jobs.worker_running():
        frappe.throw(_("Background worker not running, so this cannot start."))
    if jobs.budget_left() <= 0:
        frappe.throw(_("Monthly AI budget reached"))


# --- reads -------------------------------------------------------------------------------------------


@frappe.whitelist()
@agent_only
def get_status():
    _reader()
    from helpdesk.ai_analysis import jobs

    return _public({**jobs.status(), "can_decide": is_decider()})


@frappe.whitelist()
@agent_only
def get_overview(from_date=None, to_date=None, channel=None, dept=None, kind="problems"):
    _reader()
    from helpdesk.ai_analysis import metrics

    kind = _choice(kind, KINDS, _("kind")) or "problems"
    return _public(metrics.overview(**_filters(from_date, to_date, channel, dept), kind=kind))


@frappe.whitelist()
@agent_only
def get_issue(code, from_date=None, to_date=None, channel=None, dept=None):
    _reader()
    from helpdesk.ai_analysis import metrics

    return _public(metrics.issue_detail(_code(code), **_filters(from_date, to_date, channel, dept)))


@frappe.whitelist()
@agent_only
def get_evidence(code, from_date=None, to_date=None, channel=None, dept=None, start=0, limit=30):
    _reader()
    from helpdesk.ai_analysis import metrics

    start, limit = cint(start), cint(limit)
    if not (0 <= start <= 100_000 and 1 <= limit <= 100):
        frappe.throw(_("Page through evidence 1 to 100 rows at a time."))
    filters = _filters(from_date, to_date, channel, dept)
    return _public(metrics.evidence(_code(code), **filters, start=start, limit=limit))


@frappe.whitelist()
@agent_only
def get_brief(week=None):
    """The Sunday-Saturday week holding `week`; blank means the last complete covered week."""
    _reader()
    from helpdesk.ai_analysis import metrics

    return _public(metrics.brief(_date(week, _("Week")) if week else None))


@frappe.whitelist()
@agent_only
def get_safety(from_date=None, to_date=None):
    _reader()
    from helpdesk.ai_analysis import metrics

    start, end = _window(from_date, to_date)
    return _public({"safety": metrics.safety_box(start, end), "state": metrics.window_state(start, end)})


@frappe.whitelist()
@agent_only
def get_data_health():
    _reader()
    from helpdesk.ai_analysis import metrics

    health = metrics.data_health()
    for item in health.get("suggested") or []:
        # A conversation name holds the customer's name: send a contact ref, which _exclusion resolves back.
        if item.get("type") == "Conversation":
            item["value"] = frappe.db.get_value(CONTACT, {"conversation": item["value"]}, "name")
    return _public(health)


@frappe.whitelist(methods=["GET"])
@agent_only
def open_case(ref):
    """Redirect to the ticket (else the chat) behind a contact ref, after that record's permission check."""
    _reader()
    ticket, conversation = frappe.db.get_value(CONTACT, _ref(ref), ["ticket", "conversation"])
    if ticket:
        doctype, name, url = "HD Ticket", ticket, f"/helpdesk/tickets/{quote(str(ticket), safe='')}"
    elif conversation:
        doctype, name, url = "Messenger Conversation", conversation, f"/crm/messenger/{quote(conversation, safe='')}"
    else:
        frappe.throw(_("This case has no ticket or chat to open."), frappe.DoesNotExistError)
    if not frappe.has_permission(doctype, "read", doc=name):
        frappe.throw(_("You do not have access to this ticket or chat."), frappe.PermissionError)
    frappe.local.response["type"] = "redirect"
    frappe.local.response["location"] = url


# --- actions -----------------------------------------------------------------------------------------


@frappe.whitelist(methods=["POST"])
@agent_only
def run_analysis():
    """Any agent: rebuild contacts, then label the Pending ones in the background."""
    _reader()
    from helpdesk.ai_analysis import jobs

    if not jobs.worker_running():
        return {"started": False, "message": _("Background worker not running, so the analysis cannot start.")}
    if not jobs.start_chain("Run analysis", frappe.session.user)["started"]:
        return {"started": False, "message": _("The analysis is already running.")}
    if analysis_enabled():
        message = _("Analysis started: contacts are rebuilt, then labelled in the background.")
    else:
        message = _("Contacts are being rebuilt. AI labelling is off, so only the counts refresh.")
    return {"started": True, "message": message}


def _review(ref: str, code: str, values: dict, only_unreviewed: bool = False) -> int:
    filters = {"parenttype": CONTACT, "parent": ref, "code": code}
    names = frappe.get_all(ISSUE, filters=filters, fields=["name", "review"])
    if not names:
        frappe.throw(_("This label no longer exists. Refresh the page."), frappe.DoesNotExistError)
    names = [r.name for r in names if not (only_unreviewed and r.review)]
    if names:
        frappe.db.set_value(ISSUE, {"name": ("in", names)}, values)
    return len(names)


@frappe.whitelist(methods=["POST"])
@agent_only
def flag_label(ref, code):
    """"Wrong label?": any agent flags a label for review. A decider's Confirm or Reject stands."""
    _reader()
    values = {"review": "Flagged", "reviewed_by": frappe.session.user, "reviewed_on": now_datetime()}
    return {"flagged": _review(_ref(ref), _code(code), values, only_unreviewed=True)}


@frappe.whitelist(methods=["POST"])
@agent_only
def set_review(ref, code, review):
    _reader()
    _decider()
    review = _choice(review, REVIEWS, _("review")) or ""
    by, on = (frappe.session.user, now_datetime()) if review else (None, None)
    return {"updated": _review(_ref(ref), _code(code), {"review": review, "reviewed_by": by, "reviewed_on": on})}


def _exclusion(kind: str, value, reason: str):
    """Insert one active exclusion; None when the same one is already active. A contact ref is accepted as
    the value of a Ticket or Conversation exclusion, so the page never needs the conversation name."""
    from helpdesk.helpdesk.doctype.hd_ai_exclusion.hd_ai_exclusion import last8

    value = _text(value, _("Value"), 140)
    if kind in ("Ticket", "Conversation") and frappe.db.exists(CONTACT, value):
        value = frappe.db.get_value(CONTACT, value, kind.lower())
        if not value:
            frappe.throw(_("That case has no {0}.").format(_(kind.lower())))
    stored = last8(value) if kind == "Phone" else value
    if frappe.db.exists("HD AI Exclusion", {"exclusion_type": kind, "value": stored, "active": 1}):
        return None
    doc = {"doctype": "HD AI Exclusion", "exclusion_type": kind, "value": value, "reason": reason}
    return frappe.get_doc(doc).insert()


def _apply_exclusions() -> int:
    from helpdesk.ai_analysis import cases

    return cases.apply_exclusions()


@frappe.whitelist(methods=["POST"])
@agent_only
def add_exclusion(exclusion_type, value, reason):
    _reader()
    _decider()
    kind = _choice(exclusion_type, EXCLUSION_TYPES, _("exclusion type"), required=True)
    doc = _exclusion(kind, value, _text(reason, _("Reason"), 500))
    if not doc:
        return {"name": None, "message": _("Already excluded.")}
    return {"name": doc.name, "changed": _apply_exclusions()}


@frappe.whitelist(methods=["POST"])
@agent_only
def remove_exclusion(name, reason):
    """Soft delete: the row stays, inactive, with who removed it, when and why."""
    _reader()
    _decider()
    reason = _text(reason, _("Reason"), 500)
    doc = frappe.get_doc("HD AI Exclusion", _text(name, _("Exclusion"), 140))
    if not doc.active:
        frappe.throw(_("This exclusion was already removed."))
    doc.update({"active": 0, "removed_reason": reason, "removed_by": frappe.session.user, "removed_on": now_datetime()})
    doc.save()
    return {"name": doc.name, "changed": _apply_exclusions()}


@frappe.whitelist(methods=["POST"])
@agent_only
def exclude_suggested(items, reason):
    """Bulk "Exclude selected": items is a JSON list of {type, value}; one reason covers them all."""
    _reader()
    _decider()
    reason = _text(reason, _("Reason"), 500)
    added = skipped = 0
    for item in _list(items, _("Items"), 200):
        if not isinstance(item, dict):
            frappe.throw(_("Each item needs a type and a value."))
        kind = _choice(item.get("type"), EXCLUSION_TYPES, _("exclusion type"), required=True)
        if _exclusion(kind, item.get("value"), reason):
            added += 1
        else:
            skipped += 1
    return {"added": added, "skipped": skipped, "changed": _apply_exclusions()}


def _new_rows(refs) -> list:
    """The NEW tag rows still NEW among `refs`, with their contact's channel. A ref is a tag row name or a
    contact ref (the NEW queue lists contacts; a contact has at most one NEW row)."""
    return frappe.db.sql(
        f"""select i.name, i.severity, c.channel from `tab{ISSUE}` i join `tab{CONTACT}` c on c.name = i.parent
        where i.parenttype = %(parenttype)s and i.code = 'NEW' and (i.name in %(refs)s or i.parent in %(refs)s)""",
        {"parenttype": CONTACT, "refs": tuple(_names(refs, _("Rows"), 500))},
        as_dict=True,
    )


@frappe.whitelist(methods=["POST"])
@agent_only
def map_new(refs, code):
    """NEW queue: move tags to an existing code. An SQL update, no model call; the decider's choice is Confirmed."""
    _reader()
    _decider()
    from helpdesk.ai_analysis import registry, tagging

    meta = registry.code_meta().get(_code(code))
    if not meta or meta.code == "NEW" or meta.status != "Active":
        frappe.throw(_("Map to an active code."))
    rows = _new_rows(refs)
    by, on = frappe.session.user, now_datetime()
    for row in rows:
        # the tagger's severity rules: the code's floor, S1 for food safety only, a public complaint one up
        severity = tagging._severity(row.severity, meta, row.channel in tagging.PUBLIC_CHANNELS)
        values = {"code": meta.code, "severity": severity, "review": "Confirmed", "reviewed_by": by, "reviewed_on": on}
        frappe.db.set_value(ISSUE, row.name, values)
    return {"mapped": len(rows)}


@frappe.whitelist(methods=["POST"])
@agent_only
def dismiss_new(refs):
    """NEW queue: the tags are Rejected, so they leave the queue and the counts."""
    _reader()
    _decider()
    rows = [r.name for r in _new_rows(refs)]
    if rows:
        values = {"review": "Rejected", "reviewed_by": frappe.session.user, "reviewed_on": now_datetime()}
        frappe.db.set_value(ISSUE, {"name": ("in", rows)}, values)
    return {"dismissed": len(rows)}


@frappe.whitelist(methods=["POST"])
@agent_only
def publish_version():
    """Contacts labelled under an older label version go back to Pending and are re-labelled in place."""
    _reader()
    _decider()
    from helpdesk.ai_analysis import jobs, metrics, tagging

    if not analysis_enabled():
        return {"started": False, "message": _("AI Analysis is off, so labels cannot be re-published.")}
    current, stale = tagging.current_version(), tagging.stale_count()
    if not stale:
        return {"started": False, "message": _("Every labelled contact already has the current label version.")}
    # the same estimate as the Data health card the decider just read
    estimate, left = stale * metrics.USD_PER_CONTACT, jobs.budget_left()
    if estimate > left:
        message = _("Re-labelling {0} contacts costs about ${1}, more than the ${2} left in this month's AI budget.")
        return {"started": False, "message": message.format(stale, f"{estimate:.2f}", f"{max(left, 0):.2f}")}
    if not jobs.worker_running():  # before the contacts go back to Pending
        return {"started": False, "message": _("Background worker not running, so labels cannot be re-published.")}
    frappe.db.sql(
        f"""update `tab{CONTACT}` set status = 'Pending', attempts = 0, error = null
        where status = 'Tagged' and ifnull(tagged_version, '') != %s""",
        current,
    )
    if jobs.start_chain("Publish label version", frappe.session.user)["started"]:
        message = _("Re-labelling {0} contacts.")
    else:
        message = _("The analysis already running re-labels {0} contacts.")
    return {"started": True, "contacts": stale, "message": message.format(stale)}


@frappe.whitelist(methods=["POST"])
@agent_only
def gold_sample(labellers):
    """Pre-create blind gold-label rows for up to 4 labellers."""
    _reader()
    _decider()
    from helpdesk.ai_analysis import tagging

    users = _names(labellers, _("Labellers"), 4)
    if any(not frappe.db.exists("User", {"name": u, "enabled": 1}) for u in users):
        frappe.throw(_("Every labeller must be an enabled user."))
    return {"created": tagging.gold_sample(users)}


# --- Phase 2: decide, research, follow through ----------------------------------------------------


@frappe.whitelist(methods=["POST"])
@agent_only
def request_suggestions(code, from_date=None, to_date=None, regenerate=0):
    """Any agent: the council's options and plans for one issue. The latest run for the same evidence is reused."""
    _reader()
    code = _issue_code(code)
    start, end = _window(from_date, to_date)
    _ai_ready()
    from helpdesk.ai_analysis import advisor

    insight, reused = advisor.request_suggestions(code, start, end, frappe.session.user, regenerate=_flag(regenerate))
    return {"insight": insight, "reused": bool(reused)}


@frappe.whitelist()
@agent_only
def get_insight(name):
    """Progress and result of one suggestions, research, summary or question run; never its alias map."""
    _reader()
    from helpdesk.ai_analysis import advisor

    return _public(advisor.insight_projection(_insight(name).name))


@frappe.whitelist(methods=["POST"])
@agent_only
def combine(insight, selected, note=""):
    """Decider: the chairman reruns on the ticked options only, saved as a new version of the plan."""
    _reader()
    _decider()
    row = _plan(insight)
    options = {o.get("id") for o in _output(row).get("options") or [] if isinstance(o, dict)}
    picked = _names(selected, _("Selected options"), 20)
    if any(p not in options for p in picked):
        frappe.throw(_("Pick options from these suggestions."))
    note = _note(note, _("Note"), 1000)
    _ai_ready()
    from helpdesk.ai_analysis import advisor

    return {"insight": advisor.combine(row.name, picked, note, frappe.session.user)}


@frappe.whitelist(methods=["POST"])
@agent_only
def adopt(insight, card, assigned_to, due_date=None, target=None):
    """Decider: one card of a plan becomes an HD AI Action, assigned to an agent (who gets a ToDo)."""
    _reader()
    _decider()
    row = _plan(insight)
    card = _choice(card, CARDS, _("card"), required=True)
    if card not in {c.get("type") for c in _output(row).get("cards") or [] if isinstance(c, dict)}:
        frappe.throw(_("This plan has no such card."))
    if row.decision == "Rejected":
        frappe.throw(_("This plan was rejected. Get new suggestions to adopt a plan."))
    if frappe.db.exists(ACTION, {"insight": row.name, "card": card, "status": ("!=", "Dropped")}):
        frappe.throw(_("This card is already an action."))
    user = _agent_user(assigned_to)
    due = _date(due_date, _("Due date")) if due_date else None
    if due and due < getdate():
        frappe.throw(_("The due date cannot be in the past."))
    target = _amount(target, _("Target"))
    from helpdesk.ai_analysis import advisor

    name = advisor.adopt(row.name, card, user, frappe.session.user, due_date=due, target=target)
    return {"action": name}


@frappe.whitelist(methods=["POST"])
@agent_only
def reject(insight, reason, note=""):
    """Decider: a plan is turned down, with a reason (Other needs a note)."""
    _reader()
    _decider()
    row = _plan(insight)
    reason = _choice(reason, REJECT_REASONS, _("reason"), required=True)
    note = _note(note, _("Note"), 1000)
    if reason == "Other" and not note:
        frappe.throw(_("Say why in a note when the reason is Other."))
    if row.decision != "Pending":
        frappe.throw(_("This plan was already decided."))
    from helpdesk.ai_analysis import advisor

    advisor.reject(row.name, reason, note, frappe.session.user)
    return {"ok": True}


@frappe.whitelist()
@agent_only
def get_actions(filter="open"):
    """Actions tab: open, overdue, verifying (done, a verdict check still to come) or all."""
    _reader()
    from helpdesk.ai_analysis import metrics

    return _public(metrics.actions(_choice(filter, ACTION_FILTERS, _("filter")) or "open"))


@frappe.whitelist(methods=["POST"])
@agent_only
def update_action(name, status=None, done_on=None, note=None):
    """The assignee or a decider: move an action on (status, the day it was done, a note)."""
    _reader()
    from helpdesk.ai_analysis import metrics

    doc = frappe.get_doc(ACTION, _text(name, _("Action"), 140))
    if doc.assigned_to != frappe.session.user and not is_decider():
        frappe.throw(_("Only the assignee or a manager can update this action."), frappe.PermissionError)
    status = _choice(status, ACTION_STATUSES, _("status"))
    note = _note(note, _("Note"), 1000)
    if not (status or done_on or note):
        frappe.throw(_("Nothing to update."))
    if status:
        doc.status = status
    if done_on:
        day = _date(done_on, _("Done on"))
        if doc.status != "Done" or day > getdate():
            frappe.throw(_("A done date needs the status Done and cannot be in the future."))
        doc.done_on = day
    elif doc.status != "Done":
        doc.done_on = None  # reopened: the verdict checks wait for the next Done
    if note:
        line = f"{getdate()} {get_fullname(frappe.session.user)}: {note}"
        doc.notes = f"{doc.notes}\n{line}" if doc.notes else line
    doc.save(ignore_permissions=True)  # the role check above is the permission (assignees have no Desk access)
    return _public(metrics.actions("all", names=[doc.name])[0])


@frappe.whitelist()
@agent_only
def get_decisions():
    """The Decisions log: adopted and rejected plans, newest first."""
    _reader()
    from helpdesk.ai_analysis import registry

    meta = registry.code_meta()
    rows = frappe.get_all(
        INSIGHT,
        filters={"insight_type": "Suggestions", "decision": ("in", ("Adopted", "Rejected"))},
        fields=["name", "issue_code", "decision", "decision_reason", "decision_note", "decided_by", "decided_on"],
        order_by="decided_on desc, creation desc",
        limit=100,
    )
    return _public(
        [
            {
                "insight": r.name,
                "issue_code": r.issue_code,
                "label": meta[r.issue_code].label if r.issue_code in meta else None,
                "decision": r.decision,
                "decision_reason": r.decision_reason or None,
                "decision_note": r.decision_note or None,
                "decided_by_name": get_fullname(r.decided_by) if r.decided_by else None,
                "decided_on": r.decided_on,
            }
            for r in rows
        ]
    )


@frappe.whitelist()
@agent_only
def preview_problem_card(code):
    """The exact de-identified text Research fixes would send to the web, with its privacy checks."""
    _reader()
    from helpdesk.ai_analysis import advisor

    return _public(advisor.problem_card(_issue_code(code)))


@frappe.whitelist(methods=["POST"])
@agent_only
def request_research(code, regenerate=0):
    """Any agent, after the preview: web research on the problem card. A code's research is reused for 30 days."""
    _reader()
    code = _issue_code(code)
    if not conf().web_research:
        frappe.throw(_("Web research is off in HD Settings."))
    _ai_ready()
    if not _flag(regenerate):
        recent = frappe.db.get_value(
            INSIGHT,
            {
                "insight_type": "Research",
                "issue_code": code,
                "status": ("in", ("Queued", "Running", "Done")),
                "creation": (">=", add_days(now_datetime(), -RESEARCH_DAYS)),
            },
            "name",
            order_by="creation desc",
        )
        if recent:
            return {"insight": recent, "reused": True}
    from helpdesk.ai_analysis import advisor

    return {"insight": advisor.request_research(code, frappe.session.user), "reused": False}


@frappe.whitelist(methods=["POST"])
@agent_only
def write_summary(week, regenerate=0):
    """Any agent: the AI headline for a Brief week, its numbers filled by code. Reused per week."""
    _reader()
    from helpdesk.ai_analysis import stats

    week = stats.week_start(_date(week, _("Week")))
    if week > getdate():
        frappe.throw(_("Pick a week that has started."))
    _ai_ready()
    if not _flag(regenerate):
        done = {"insight_type": "Brief", "week_start": week, "status": ("in", ("Queued", "Running", "Done"))}
        recent = frappe.db.get_value(INSIGHT, done, "name", order_by="creation desc")
        if recent:
            return {"insight": recent, "reused": True}
    from helpdesk.ai_analysis import advisor

    return {"insight": advisor.write_summary(week, frappe.session.user), "reused": False}


@frappe.whitelist(methods=["GET"])
@agent_only
def download_brief(week=None):
    """The week's Brief as a PDF: the code-built numbers, no quotes."""
    _reader()
    from frappe.utils.pdf import get_pdf

    from helpdesk.ai_analysis import metrics

    brief = metrics.brief(_date(week, _("Week")) if week else None)
    frappe.local.response.filename = f"ai-analysis-brief-{brief['week']}.pdf"
    frappe.local.response.filecontent = get_pdf(_brief_html(brief))
    frappe.local.response.type = "download"


def _spark_svg(values) -> str:
    """An 8-week bar sparkline as inline SVG."""
    values = [v or 0 for v in values or []]
    peak, width, height = max(values, default=0) or 1, 96, 24
    bar = width / max(len(values), 1)
    rects = "".join(
        f'<rect x="{i * bar + 1:.1f}" y="{height - v / peak * height:.1f}" width="{bar - 2:.1f}" '
        f'height="{v / peak * height:.1f}" fill="#6B7280"/>'
        for i, v in enumerate(values)
    )
    return f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}">{rects}</svg>'


def _brief_html(b: dict) -> str:
    """The Brief payload as PDF HTML, without a single quote. For wkhtmltopdf: the doctype, tables rather than
    flexbox, inline SVG, and complaints._esc, which escapes and drops emoji."""
    from helpdesk.api.complaints import PDF_CSS, _cards, _esc, _html_table

    def table(labels, rows, empty=""):
        if not rows:
            return f"<p>{_esc(empty)}</p>" if empty else ""
        body = ["<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>" for row in rows]
        return _html_table([(None, label) for label in labels], body)

    def section(title, content):
        return f"<div class='section'><h2>{_esc(title)}</h2>{content}</div>" if content else ""

    def day(value):
        return f"{value.day} {value:%b %Y}"

    def line(parts):
        return f"<p>{_esc(' · '.join(str(p) for p in parts if p))}</p>"

    week, head = getdate(b["week"]), b["headline"]
    values = head.get("values") or {}
    headline = PLACEHOLDER.sub(lambda m: str(values.get(m.group(1), "—")), head.get("text") or "")
    tiles = []
    for k in b["kpis"]:
        chip = k["chip"] or {}
        hint = " · ".join(x for x in (chip.get("label"), chip.get("text"), k["hint"]) if x)
        tiles.append(
            f"<div class='muted'>{_esc(k['label'])}</div><div class='value'>{_esc(k['display'])}</div>"
            f"<div class='hint'>{_esc(hint)}</div>"
        )
    top = table(
        [_("Problem"), _("Owner"), _("Badges"), _("Week: cases / customers"), _("4 weeks"), _("Channel"), _("8 weeks")],
        [
            [
                _esc(t["label"]),
                _esc(t["owner_department"]),
                _esc(", ".join(t["badges"])),
                _esc(f"{t['week_cases']} / {t['week_customers']}"),
                _esc(f"{t['cases']} / {t['customers']}"),
                _esc(t["top_channel"]),
                _spark_svg(t["sparkline"]),
            ]
            for t in b["top"]
        ],
        _("No complaint cases in these 4 weeks."),
    )
    changed = [[_esc(c["label"]), _esc(c["badge"]), _esc(c["text"])] for c in b["changed"]]
    changed = table([_("Issue"), _("Signal"), _("Change")], changed)
    demand = b["demand"]
    asked = table(
        [_("Asked about"), _("This week"), _("Weekly average before")],
        [[_esc(d["label"]), _esc(d["cases"]), _esc(d["prior"])] for d in demand["top"]],
    )
    share = demand["arabic_share"]
    asked += line(
        [
            _("Arabic or mixed: {0}").format("—" if share is None else f"{round(share * 100)}%"),
            _("Public comments: {0}").format(demand["public_comments"]),
            _("Praise: {0}").format(demand["praise"]),
            _("Suggestions: {0}").format(demand["suggestions"]),
        ]
    )
    safety, acts, footer = b["safety"], b["actions"], b["footer"]
    food = line(
        [
            _("Food-safety events: {0}").format(len(safety["events"])),
            _("Possible clusters: {0}").format(len(safety["clusters"])),
            _("Need review: {0}").format(len(safety["needs_review"])),
        ]
    )
    follow = line([f"{_(k.capitalize())}: {len(acts[k])}" for k in ("due", "overdue", "verdicts", "recurred")])
    decisions = table([_("Decision")], [[_esc(d["text"])] for d in b["decisions"]], _("Nothing is waiting."))
    notes = [
        footer["season"] and _("Season: {0}").format(footer["season"]),
        _("Chat data covers this week") if footer["chat_covered"] else _("No chat data this week"),
        _("Rates per 1,000 deliveries shown") if footer["delivery_rate"] else _("No delivery rate this week"),
        _("{0} contacts excluded").format(footer["excluded"]),
        _("Labels validated on the gold set") if footer["validated"] else _("Labels not yet validated"),
        _("Labelling model: {0}").format(footer["model"]),
    ]
    period = f"{day(week)} to {day(week + timedelta(days=6))}"
    notice = b["state"].get("notice")
    # without the doctype WebKit's quirks mode stops tables inheriting the 10px font
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>{PDF_CSS}</style></head><body>
        <h1>{_esc(_("AI Analysis: weekly brief"))}</h1>
        {line([period, _("Numbers are computed from data; AI only labels, quotes and suggests.")])}
        {line([notice]) if notice else ""}
        <h2>{_esc(headline)}</h2>
        {_cards(tiles[:3])}{_cards(tiles[3:])}
        {section(_("Top problems over 4 weeks"), top)}
        {section(_("What changed"), changed)}
        {section(_("Demand and requests"), asked)}
        {section(_("Food safety"), food)}
        {section(_("Actions and follow-through"), follow)}
        {section(_("Decisions needed"), decisions)}
        <div class="muted">{line(notes)}</div>
    </body></html>"""


# --- Phase 3 and 4: operations, Ask your tickets --------------------------------------------------


@frappe.whitelist()
@agent_only
def get_operations(from_date=None, to_date=None):
    _reader()
    from helpdesk.ai_analysis import metrics

    start, end = _window(from_date, to_date)
    return _public(metrics.operations(start, end))


@frappe.whitelist(methods=["POST"])
@agent_only
def ask(question):
    """Any agent: one question, answered in the background from counts that code makes."""
    _reader()
    question = _text(question, _("Question"), 500)
    _ai_ready()
    from helpdesk.ai_analysis import ask as asking

    return {"insight": asking.ask(question, frappe.session.user)}


@frappe.whitelist()
@agent_only
def get_questions():
    """This user's last 20 questions."""
    _reader()
    rows = frappe.get_all(
        INSIGHT,
        filters={"insight_type": "Question", "requested_by": frappe.session.user},
        fields=["name", "question", "status", "creation", "output_json"],
        order_by="creation desc",
        limit=20,
    )
    return _public(
        [
            {
                "insight": r.name,
                "question": r.question,
                "status": r.status,
                "creation": r.creation,
                "declined": _output(r).get("declined"),
            }
            for r in rows
        ]
    )
