"""Every number on the AI Analysis page: coverage, KPIs, issues, the safety box, evidence, the Brief and data health.

Code counts; the LLM only labelled and quoted (tagging.py). Thin SQL loaders, memoised per request, feed plain
functions over row dicts. Public functions return JSON-safe dicts that never carry a conversation name, phone,
customer name or customer_key (counted_rows() is the server-only exception).
"""

import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import date, timedelta
from statistics import median

import frappe
from frappe import _
from frappe.utils import cint, flt, get_fullname, getdate, now_datetime
from frappe.utils.caching import request_cache

from helpdesk.ai_analysis import conf, is_decider, registry, stats, tagging, text
from helpdesk.api.complaints import _prior_bounds

PLATFORMS = ("WhatsApp", "Instagram", "Messenger")
PLATFORM_OF = {
    "WhatsApp": "WhatsApp",
    "Instagram DM": "Instagram",
    "Instagram comment": "Instagram",
    "Messenger": "Messenger",
    "Facebook comment": "Messenger",
}
PUBLIC = {"Instagram comment", "Facebook comment"}
KINDS = {"problems": {"Complaint"}, "demand": {"Enquiry", "Request"}, "feedback": {"Feedback"}, "all": None}
WEIGHTS = {"S1": 10, "S2": 5, "S3": 2, "S4": 1}
HIDDEN = "[health details hidden]"
HEALTH_CODES = {"NUT_EXCLUSION_IGNORED"}  # an allergen noticed before eating; FS codes mask via is_food_safety
SIGNALS = ("SURGE", "NEW", "RESURFACED", "WATCH", "IMPROVING")  # "What changed", most urgent first
WEEKDAYS = ("Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat")
USD_PER_CONTACT, SECONDS_PER_CONTACT = 0.0075, 5  # re-label estimate
MISSED_CALLS = "Missed calls are not recorded — only answered (recorded) calls are logged."

# CRM Call Log.start_time is UTC. The 3CX sync (apps/dieture/dieture/dieture/jobs/threecx_event_log_sync.py)
# strips the "Z" from 3CX's ISO StartTime. Checked on erp.localhost on 2026-11-06: creation is stamped in
# Asia/Qatar, yet none of the 77,414 rows was created less than 218 minutes after its end_time (Qatar-local
# times would give minutes for promptly synced rows), and raw incoming start hours run 04-18 (07-21 in Qatar).
UTC_TO_QATAR = timedelta(hours=3)

# Bot or automated Messenger messages (the claude_mcp._messages rule), as SQL per column, so a missing column
# is skipped; outgoing messages owned by Administrator or Guest count as bot too.
_BOT_SQL = {
    "is_auto_reply": "ifnull(m.is_auto_reply, 0) = 1",
    "is_auto_generated_outgoing_message": "ifnull(m.is_auto_generated_outgoing_message, 0) = 1",
    "template_name": "ifnull(m.template_name, '') != ''",
    "message_type": "ifnull(m.message_type, '') = 'Template'",
    "is_external_message": "ifnull(m.is_external_message, 0) = 1",
}

TILES = (  # key, label, exposure used by the change chip (None: "a → b" only)
    ("complaint_cases", "Complaint cases", "deliveries"),
    ("customers", "Customers affected", "deliveries"),
    ("food_safety", "Food-safety events", "deliveries"),
    ("calls", "Answered calls", "call_days"),
    ("copq", "Cost of poor quality", None),
    ("demand", "Demand & requests", "chat_days"),
)
BADGE_TEXT = {
    "SAFETY": "A verified food-safety case (S1 or S2) in this period.",
    "SURGE": "Far above its usual rate over the last 4 weeks (exact test, p < 0.01).",
    "WATCH": "Above its usual rate over the last 4 weeks (exact test, p < 0.05).",
    "IMPROVING": "Below its usual rate over the last 4 weeks (exact test, p < 0.01).",
    "CHRONIC": "Cases in at least 3 of the last 4 weeks, from 2 or more customers.",
    "NEW": "First seen in the last 14 days, from 2 or more customers.",
    "RESURFACED": "Back after 8 quiet weeks, from 2 or more customers.",
    "PUBLIC": "Raised in a public Instagram or Facebook comment.",
}
HOW_WE_COUNT = [
    "A case is one customer and one issue within a fixed 7-day window that starts at their first contact; "
    "the next contact after the window opens a new case.",
    "A contact without a customer key is its own case and counts as its own customer.",
    "Complaint cases apply the same rule across every complaint issue, so a contact with several issues counts "
    "once in the tile but once per issue in the table.",
    "Repeat contacts = contacts − cases.",
    "Only labels whose quote was found word for word in the source (Verified or Repaired) and that no reviewer "
    "rejected are counted.",
    "Priority weighs each affected customer by their worst case: S1 = 10, S2 = 5, S3 = 2, S4 = 1.",
    "Change chips use an exact test: per 1,000 deliveries for problems (only when deliveries cover 90% of the "
    "days in both periods), per covered chat day for demand and feedback.",
    "Weeks run Sunday to Saturday (Qatar time). Weeks without chat coverage are left out of baselines.",
]


# --- small helpers -------------------------------------------------------------------------------


def _js(v):
    """JSON-safe copy: dates and datetimes become ISO strings, dict keys included."""
    if isinstance(v, dict):
        return {(k.isoformat() if isinstance(k, date) else k): _js(x) for k, x in v.items()}
    if isinstance(v, list | tuple):
        return [_js(x) for x in v]
    if isinstance(v, date):
        return v.isoformat()
    return v


def _dates(from_date, to_date):
    frm, to = getdate(from_date), getdate(to_date)
    if frm > to:
        frappe.throw(_("The start date must be on or before the end date."))
    return frm, to


def _prior(frm, to):
    start, end = _prior_bounds(frm, to)  # end is exclusive
    return start, end - timedelta(days=1)


def _days(frm, to):
    return [frm + timedelta(days=i) for i in range((to - frm).days + 1)]


def _weeks(first, last):
    """The Sundays from first's week through last's week."""
    out, w, last = [], stats.week_start(first), stats.week_start(last)
    while w <= last:
        out.append(w)
        w += timedelta(weeks=1)
    return out


def _day_text(d):
    return f"{d.day} {d:%b %Y}"


def _num(v):
    return f"{v:,.0f}" if float(v).is_integer() else f"{v:,.2f}"


def _n(n, word):
    return f"{n:,} {word}{'' if n == 1 else 's'}"


def _who(case):
    """A case's customer; a contact without a customer key counts as its own customer."""
    return case["customer"] or "contact:" + case["contacts"][0]


def _person(row):
    return row["customer"] or "contact:" + row["contact"]


def _between(cases, frm, to):
    return [c for c in cases if frm <= c["day"] <= to]


def _filtered(rows, channel=None, dept=None):
    return [r for r in rows if (not channel or r["channel"] == channel) and (not dept or r["owner_department"] == dept)]


def _dish_key(name):
    """The dish catalogue's key (tagging.dish_catalogue), so meal counts line up with the stored dish_item."""
    return text.normalize(tagging.SIZE_SUFFIX.sub("", name or ""))


def _hits(raw):
    try:
        hits = json.loads(raw or "[]")
    except ValueError:
        return []
    return [h for h in hits if isinstance(h, dict) and h.get("rule")] if isinstance(hits, list) else []


def _mask():
    return bool(conf().mask_health) and not is_decider()


def _advisor(fn, code):
    """advisor.<fn>(code) for an issue row; None while advisor.py is missing or when it fails. Imported here, never
    at the top: advisor imports metrics."""
    try:
        from helpdesk.ai_analysis import advisor

        return getattr(advisor, fn)(code)
    except Exception:
        return None


# --- loaders (memoised per request; never mutate what they return) --------------------------------


@request_cache
def _meta():
    return registry.code_meta()


def _live_sources(tickets, conversations):
    """(names of live tickets: existing and not merged, {existing conversation: platform})."""
    live, platforms = set(), {}
    if tickets:
        live = {
            str(n)
            for (n,) in frappe.db.sql(
                "select name from `tabHD Ticket` where is_merged = 0 and name in %(t)s", {"t": tuple(tickets)}
            )
        }
    if conversations and frappe.db.table_exists("Messenger Conversation"):
        platforms = dict(
            frappe.db.sql(
                "select name, platform from `tabMessenger Conversation` where name in %(c)s",
                {"c": tuple(conversations)},
            )
        )
    return live, platforms


@request_cache
def _base():
    """Every HD AI Contact with its issues, liveness, platform and parsed safety hits (server-only)."""
    contacts = {
        c.name: c
        for c in frappe.db.sql(
            """select name, source, ticket, conversation, channel, started_on, customer_key, language, in_count,
                folded, status, exclusion_reason, safety_hits, offered, tagged_version
            from `tabHD AI Contact`""",
            as_dict=True,
        )
    }
    issues = defaultdict(list)
    for i in frappe.db.sql(
        """select parent, code, proposed_label, statement_en, severity, confidence, quote, quote_en, quote_status,
            quote_role, dish, dish_item, review
        from `tabHD AI Contact Issue` where parenttype = 'HD AI Contact'""",
        as_dict=True,
    ):
        issues[i.parent].append(i)
    live, platforms = _live_sources(
        {c.ticket for c in contacts.values() if c.ticket},
        {c.conversation for c in contacts.values() if c.conversation},
    )
    for c in contacts.values():
        c.live = c.ticket in live if c.source == "Ticket" else c.conversation in platforms
        c.platform = PLATFORM_OF.get(c.channel) or platforms.get(c.conversation)
        c.hits = _hits(c.safety_hits)
        c.issues = issues.get(c.name, [])
    return contacts


@request_cache
def counted_rows() -> list[dict]:
    """One row per counted label, oldest first: a Tagged contact with a live source, a Verified or Repaired quote,
    a review that is not Rejected, the code resolved to its merge target. Server-only: rows carry the customer
    key and datetimes, so never return them to the browser as they are.

    A contact waiting to be re-labelled (Publish label version, or its text changed) keeps its last tag set and
    counts until the new tags replace it, so numbers and the safety box never dip during a re-label."""
    meta, rows = _meta(), []
    for c in _base().values():
        labelled = c.status == "Tagged" or (c.tagged_version and c.status in ("Pending", "Tagging", "Failed"))
        if not labelled or not c.live or not c.started_on:
            continue
        for i in c.issues:
            if i.quote_status not in ("Verified", "Repaired") or i.review == "Rejected" or i.code not in meta:
                continue
            m = meta[meta[i.code]["target"]]
            rows.append(
                {
                    "contact": c.name,
                    "ticket": c.ticket or None,
                    "source": c.source,
                    "channel": c.channel,
                    "at": c.started_on,
                    "day": c.started_on.date(),
                    "customer": c.customer_key or None,
                    "language": c.language,
                    "offered": c.offered or None,
                    "hits": c.hits,
                    "code": m.code,
                    "raw_code": i.code,
                    "label": m.label,
                    "kind": m.kind,
                    "family": m.family,
                    "owner_department": m.owner_department,
                    "is_food_safety": bool(m.is_food_safety),
                    "severity": i.severity or "S4",
                    "confidence": i.confidence,
                    "quote": i.quote,
                    "quote_en": i.quote_en,
                    "quote_status": i.quote_status,
                    "role": i.quote_role,
                    "review": i.review or None,
                    "dish": i.dish or None,
                    "dish_item": i.dish_item or None,
                    "proposed_label": i.proposed_label,
                    "statement_en": i.statement_en,
                }
            )
    rows.sort(key=lambda r: r["at"])
    return rows


def _chat_rows():
    """Non-excluded contacts that carry chat (chat sessions, or tickets with folded sessions), by platform."""
    return [
        {"platform": c.platform, "at": c.started_on, "in": c.in_count or 0, "conversation": c.conversation}
        for c in _base().values()
        if c.status != "Excluded" and (c.source == "Chat" or c.folded) and c.platform in PLATFORMS and c.started_on
    ]


@request_cache
def _deliveries():
    """{day: normal deliveries}: submitted, not a return, type normal or blank (replacements and free boxes out)."""
    if not frappe.db.table_exists("Delivery Note"):
        return {}
    typed = frappe.db.has_column("Delivery Note", "custom_dieture_delivery_type")
    only_normal = "and ifnull(custom_dieture_delivery_type, '') in ('normal', '')" if typed else ""
    return dict(
        frappe.db.sql(
            f"""select posting_date, count(*) from `tabDelivery Note`
            where docstatus = 1 and is_return = 0 {only_normal} group by posting_date"""
        )
    )


@request_cache
def _calls():
    """Incoming calls. 3CX logs recordings only, so every row is an answered call. "answered": sorted
    [(Qatar datetime, caller)] after the exclusion rules (start date, staff phones, Phone exclusions, extensions
    of 4 digits or fewer); "incoming": [(day, completed)] for every incoming row, for the capture notice."""
    if not frappe.db.table_exists("CRM Call Log"):
        return {"answered": [], "incoming": []}
    c = conf()
    blocked = set(frappe.get_all("HD AI Exclusion", filters={"exclusion_type": "Phone", "active": 1}, pluck="value"))
    staff, keys = set(), {}
    if c.exclude_staff_phones:
        from helpdesk.ai_analysis import cases

        staff = cases.staff_keys()
    answered, incoming = [], []
    for phone, start, status in frappe.db.sql(
        "select `from`, start_time, status from `tabCRM Call Log` where type = 'Incoming' and start_time is not null"
    ):
        at = start + UTC_TO_QATAR
        incoming.append((at.date(), status == "Completed"))
        digits = re.sub(r"\D", "", phone or "")
        if status != "Completed" or len(digits) <= 4 or (c.start_date and at.date() < c.start_date):
            continue
        caller = text.last8(phone) or digits
        if caller in blocked:
            continue
        if staff:
            if caller not in keys:
                keys[caller] = cases.customer_key("p:" + caller)
            if keys[caller] in staff:
                continue
        answered.append((at, caller))
    answered.sort()
    return {"answered": answered, "incoming": incoming}


@request_cache
def _reply_months():
    """{(platform, "YYYY-MM"): (incoming, human replies)} over non-private Messenger messages."""
    if not frappe.db.table_exists("Messenger Message") or not frappe.db.table_exists("Messenger Conversation"):
        return {}
    has = set(frappe.db.get_table_columns("Messenger Message"))
    bot = " or ".join([sql for col, sql in _BOT_SQL.items() if col in has] + ["m.owner in ('Administrator', 'Guest')"])
    private = "ifnull(m.is_private, 0) = 0" if "is_private" in has else "1 = 1"
    rows = frappe.db.sql(
        f"""select c.platform, year(ifnull(m.timestamp, m.creation)), month(ifnull(m.timestamp, m.creation)),
            sum(m.message_direction = 'Incoming'), sum(m.message_direction = 'Outgoing' and not ({bot}))
        from `tabMessenger Message` m join `tabMessenger Conversation` c on c.name = m.conversation
        where {private} group by 1, 2, 3"""
    )
    return {(p, f"{y}-{mo:02d}"): (cint(i), cint(o)) for p, y, mo, i, o in rows if p in PLATFORMS and y}


@request_cache
def _money(frm, to):
    """Replacements at kitchen cost and selling value, and customer refunds (no reason is recorded)."""
    out = {"replacements": 0, "cost": 0.0, "value": 0.0, "refunds": 0, "refunds_qar": 0.0}
    if (
        frappe.db.table_exists("Delivery Note")
        and frappe.db.has_column("Delivery Note", "custom_dieture_delivery_type")
        and frappe.db.has_column("Delivery Note Item", "custom_dieture_cost_amount")
    ):
        n, cost, value = frappe.db.sql(
            """select count(distinct dn.name), sum(i.custom_dieture_cost_amount), sum(i.amount)
            from `tabDelivery Note` dn
            left join `tabDelivery Note Item` i on i.parent = dn.name and i.parenttype = 'Delivery Note'
            where dn.docstatus = 1 and dn.custom_dieture_delivery_type = 'replacement'
                and dn.posting_date between %s and %s""",
            (frm, to),
        )[0]
        out.update(replacements=cint(n), cost=flt(cost, 2), value=flt(value, 2))
    if frappe.db.table_exists("Payment Entry"):
        n, amount = frappe.db.sql(
            """select count(*), sum(paid_amount) from `tabPayment Entry`
            where payment_type = 'Pay' and party_type = 'Customer' and docstatus = 1
                and posting_date between %s and %s""",
            (frm, to),
        )[0]
        out.update(refunds=cint(n), refunds_qar=flt(amount, 2))
    return out


@request_cache
def _meals(frm, to):
    """Counter {normalised dish name: meals delivered in normal deliveries in the window}."""
    if not frappe.db.table_exists("Delivery Note"):
        return Counter()
    typed = frappe.db.has_column("Delivery Note", "custom_dieture_delivery_type")
    only_normal = "and ifnull(dn.custom_dieture_delivery_type, '') in ('normal', '')" if typed else ""
    meals = Counter()
    for name, n in frappe.db.sql(
        f"""select i.item_name, count(*) from `tabDelivery Note Item` i
        join `tabDelivery Note` dn on dn.name = i.parent and i.parenttype = 'Delivery Note'
        where dn.docstatus = 1 and dn.is_return = 0 {only_normal} and dn.posting_date between %s and %s
        group by i.item_name""",
        (frm, to),
    ):
        meals[_dish_key(name)] += n
    return meals


def _evaluation():
    """The latest gold-set score (HD AI Insight of type Evaluation, output_json), or None."""
    rows = frappe.get_all(
        "HD AI Insight",
        filters={"insight_type": "Evaluation"},
        fields=["output_json"],
        order_by="creation desc",
        limit=1,
    )
    try:
        score = json.loads(rows[0].output_json or "null") if rows else None
    except ValueError:
        return None
    return score if isinstance(score, dict) else None


# --- coverage --------------------------------------------------------------------------------------


def _covered(counts, weeks, ok):
    """{week: covered} for one feed: ok(week, n) and n >= 20% of the median of the last 26 weeks that had data
    (this one included). A trailing median of all weeks falls to ~0 once a feed dies, and stray messages would
    then read as covered; the weeks with data keep the reference at the feed's real level."""
    seen, out = [], {}
    for w in weeks:
        n = counts.get(w, 0)
        if n:
            seen.append(n)
        out[w] = bool(n) and ok(w, n) and n >= 0.2 * median(seen[-26:])
    return out


def chat_coverage(rows, today) -> dict:
    """Chat coverage per platform and Sunday week. rows: [{"platform", "at", "in", "conversation"}].
    A platform-week is covered with >= 10 incoming messages from >= 5 conversations at >= 20% of its reference;
    a week is covered when any platform is. "until" is the last covered week's Saturday; a platform is stopped
    when its last covered week is more than 2 weeks before the current week."""
    ins, convs = defaultdict(Counter), defaultdict(lambda: defaultdict(set))
    for r in rows:
        w = stats.week_start(r["at"])
        ins[r["platform"]][w] += r["in"]
        convs[r["platform"]][w].add(r["conversation"])
    current = stats.week_start(today)
    if not ins:
        return {"weeks": {}, "until": None, "stopped": []}
    weeks = _weeks(min(min(c) for c in ins.values()), current)
    out = {w: {"platforms": {}, "covered": False} for w in weeks}
    last = {}
    for p, counts in ins.items():
        covered = _covered(counts, weeks, lambda w, n, by_week=convs[p]: n >= 10 and len(by_week[w]) >= 5)
        for w in weeks:
            if counts.get(w):
                out[w]["platforms"][p] = {"in": counts[w], "conversations": len(convs[p][w]), "covered": covered[w]}
            if covered[w]:
                out[w]["covered"] = True
                last[p] = w
    return {
        "weeks": out,
        "until": max(last.values()) + timedelta(days=6) if last else None,
        "stopped": sorted(p for p, w in last.items() if (current - w).days > 14),
    }


def call_coverage(answered, today) -> dict:
    """Answered calls per Sunday week, covered at >= 5 calls and >= 20% of the 26-data-week reference.
    "until" is the last answered call's day in the last covered week."""
    counts = Counter(stats.week_start(at) for at, _ in answered)
    if not counts:
        return {"weeks": {}, "until": None}
    weeks = _weeks(min(counts), stats.week_start(today))
    covered = _covered(counts, weeks, lambda w, n: n >= 5)
    last = max((w for w in weeks if covered[w]), default=None)
    return {
        "weeks": {w: {"answered": counts.get(w, 0), "covered": covered[w]} for w in weeks},
        "until": max((at.date() for at, _ in answered if stats.week_start(at) == last), default=None),
    }


@request_cache
def _cov():
    # ponytail: rebuilt in every request, ~0.6 s cold here (the Delivery Note GROUP BY and ~17k call rows, each
    # caller HMAC'd once); put _deliveries/_calls in frappe.cache for a few minutes if the page feels slow.
    today, days = getdate(), _deliveries()
    return {
        "chat": chat_coverage(_chat_rows(), today),
        "deliveries": {"days": days, "until": max((d for d, n in days.items() if n >= 30), default=None)},
        "calls": call_coverage(_calls()["answered"], today),
        "excluded_contacts": sum(1 for c in _base().values() if c.status == "Excluded"),
    }


def coverage() -> dict:
    return _js(_cov())


def _covered_days(feed, frm, to):
    weeks = _cov()[feed]["weeks"]
    return sum(1 for d in _days(frm, to) if weeks.get(stats.week_start(d), {}).get("covered"))


def _delivery(frm, to):
    """(normal deliveries, days with >= 30 of them, whether those days are >= 90% of the window)."""
    days = _cov()["deliveries"]["days"]
    span = _days(frm, to)
    covered = sum(1 for d in span if days.get(d, 0) >= 30)
    return sum(days.get(d, 0) for d in span), covered, covered >= 0.9 * len(span)


def _capture_notices(frm=None, to=None):
    """Live notices for what the sources cannot show: missed calls, and replies per platform-month."""
    inside = lambda d: (frm is None or d >= frm) and (to is None or d <= to)  # noqa: E731
    out = []
    calls = [ok for d, ok in _calls()["incoming"] if inside(d)]
    if calls and all(calls):
        out.append({"key": "missed_calls", "text": MISSED_CALLS})
    months = None if frm is None else {f"{d.year}-{d.month:02d}" for d in _days(frm, to)}
    for (platform, month), (incoming, replies) in sorted(_reply_months().items(), key=lambda kv: kv[0][::-1]):
        if incoming and replies < 0.05 * incoming and (months is None or month in months):
            when = date(int(month[:4]), int(month[5:]), 1)
            word = "reply" if replies == 1 else "replies"
            out.append(
                {
                    "key": f"replies:{platform}:{month}",
                    "text": f"Replies are not recorded for {platform} "
                    f"({when:%b %Y}: {replies:,} {word} vs {incoming:,} messages)",
                }
            )
    return out


def default_window(days=28) -> dict:
    """The latest `days` days ending at the last covered chat week's Saturday (today if this week is covered)."""
    chat, today = _cov()["chat"], getdate()
    current = chat["weeks"].get(stats.week_start(today), {}).get("covered")
    to = today if current or not chat["until"] else chat["until"]
    return _js({"from_date": to - timedelta(days=cint(days) - 1), "to_date": to, "latest": to < today})


def window_state(from_date, to_date) -> dict:
    frm, to = _dates(from_date, to_date)
    chat = _cov()["chat"]
    weeks = _weeks(frm, to)
    covered = sum(1 for w in weeks if chat["weeks"].get(w, {}).get("covered"))
    notice = jump = None
    if not covered:
        until = chat["until"]
        notice = f"No chat data in this period (last data {_day_text(until)})" if until else "No chat data yet"
        if until:
            jump = {"from_date": until - (to - frm), "to_date": until}
    return _js(
        {
            "covered": bool(covered),
            "covered_weeks": covered,
            "weeks": len(weeks),
            "notice": notice,
            "jump": jump,
            "delivery_rate": _delivery(frm, to)[2],
            "capture_notices": _capture_notices(frm, to),
        }
    )


# --- cases and KPI tiles ---------------------------------------------------------------------------


def _collapse(rows, key=lambda r: r["code"]):
    """stats.collapse_cases over all the rows given, one row per (contact, key) at its worst severity. key()
    replaces the code, e.g. with one constant for the code-agnostic KPIs."""
    one = {}
    for r in rows:
        k = (r["contact"], key(r))
        if k not in one or r["severity"] < one[k]["severity"]:
            one[k] = {
                "customer": r["customer"],
                "code": k[1],
                "at": r["at"],
                "contact": r["contact"],
                "severity": r["severity"],
            }
    channel = {r["contact"]: r["channel"] for r in rows}
    cases = stats.collapse_cases(list(one.values()))
    for c in cases:
        c["day"] = c["start"].date()
        c["channel"] = channel[c["contacts"][0]]
    return cases


def _agnostic(rows, frm, to, keep):
    """Cases starting in the window when every code that passes keep() counts as one code."""
    return _between(_collapse([r for r in rows if keep(r)], key=lambda r: "*"), frm, to)


def _repeat_share(rows):
    """Percent of customers with contacts on 2+ different days less than 7 days apart."""
    days = defaultdict(set)
    for r in rows:
        days[_person(r)].add(r["day"])
    repeat = 0
    for ds in days.values():
        ds = sorted(ds)
        repeat += any(b - a < timedelta(days=7) for a, b in zip(ds, ds[1:]))
    return round(100 * repeat / len(days)) if days else 0


def _repeat_callers(calls):
    """Callers with 2+ answered calls less than 7 days apart (calls sorted by time)."""
    by = defaultdict(list)
    for at, caller in calls:
        by[caller].append(at)
    return sum(1 for ts in by.values() if any(b - a < timedelta(days=7) for a, b in zip(ts, ts[1:])))


def _tiles(rows, frm, to, needs_review=0):
    """The six tile values for one window, with their exposures and hints. A tile is None (never a fake 0) when
    its source has no coverage in the window: chats for contact tiles, calls, deliveries for money."""
    chat_days, call_days = _covered_days("chat", frm, to), _covered_days("calls", frm, to)
    deliveries, delivered_days, rate_ok = _delivery(frm, to)
    complaints = _agnostic(rows, frm, to, lambda r: r["kind"] == "Complaint")
    food = _agnostic(rows, frm, to, lambda r: r["is_food_safety"] and r["severity"] in ("S1", "S2"))
    demand = _agnostic(rows, frm, to, lambda r: r["kind"] in ("Enquiry", "Request"))
    calls = [c for c in _calls()["answered"] if frm <= c[0].date() <= to]
    money = _money(frm, to)
    window = [r for r in rows if frm <= r["day"] <= to]
    asked = Counter(
        r["label"]
        for r in {(r["contact"], r["code"]): r for r in window if r["kind"] in ("Enquiry", "Request")}.values()
    )
    chat = chat_days > 0
    no_chat = "No chat data in this period"
    if not chat:
        rate_hint = no_chat
    elif rate_ok and deliveries:
        rate_hint = f"{len(complaints) / deliveries * 1000:.2f} per 1,000 deliveries"
    else:
        rate_hint = "No rate: delivery data covers under 90% of these days"
    complained = [r for r in window if r["kind"] == "Complaint"]
    return {
        "complaint_cases": len(complaints) if chat else None,
        "customers": len({_who(c) for c in complaints}) if chat else None,
        "food_safety": len(food) if chat else None,
        "calls": len(calls) if call_days else None,
        "copq": money["cost"] if delivered_days else None,
        "demand": len(demand) if chat else None,
        "deliveries": deliveries if rate_ok else None,
        "chat_days": chat_days,
        "call_days": call_days,
        "hints": {
            "complaint_cases": rate_hint,
            "customers": f"{_repeat_share(complained)}% contacted us on 2+ days within 7 days" if chat else no_chat,
            "food_safety": f"{needs_review} need review",
            "calls": f"{_n(_repeat_callers(calls), 'repeat caller')} (2+ answered calls within 7 days); "
            "missed calls are not logged"
            if call_days
            else "No answered-call data in this period",
            "copq": f"Kitchen cost of {money['replacements']:,} replacement deliveries; selling value "
            f"{money['value']:,.2f} QAR. Refunds (all reasons): {money['refunds']:,}, {money['refunds_qar']:,.2f} QAR, "
            "not added"
            if delivered_days
            else "No delivery data in this period",
            "demand": (f"Top: {asked.most_common(1)[0][0]}" if asked else "") if chat else no_chat,
        },
    }


def _chip(x, e, px, pe, weeks=None):
    """stats.chip; with weeks, the prior is a sum over that many weeks and the "a → b" text shows its average."""
    chip = stats.chip(x, e, px, pe)
    if weeks and "→" in chip["text"]:
        chip["text"] = f"{_num(px / weeks)} → {_num(x)}"
    return chip


def _display(key, v):
    if v is None:
        return "—"
    return f"{v:,.2f} QAR" if key == "copq" else f"{v:,}"


def _kpis(cur, prev, weeks=None):
    out = []
    for key, label, exposure in TILES:
        v, p = cur[key], prev[key]
        chip = None
        if v is not None and p is not None:
            chip = _chip(v, cur[exposure] if exposure else None, p, prev[exposure] if exposure else None, weeks)
        if weeks and p is not None:
            p = round(p / weeks, 2)
        out.append(
            {
                "key": key,
                "label": label,
                "value": v,
                "prior": p,
                "display": _display(key, v),
                "chip": chip,
                "hint": cur["hints"][key],
            }
        )
    return out


# --- issues ----------------------------------------------------------------------------------------


def _history_start():
    """NEW's burn-in runs from the later of the start date and the first covered chat week."""
    first = min((w for w, x in _cov()["chat"]["weeks"].items() if x["covered"]), default=None)
    starts = [d for d in (conf().start_date, first) if d]
    return max(starts) if starts else None


def _week_ctx(to):
    """30 Sunday weeks ending at to's week, with per-week delivery exposure (0 when under 90% covered), chat
    coverage and days, each counted only up to `to`."""
    weeks = _weeks(to - timedelta(weeks=29), to)
    chat = _cov()["chat"]["weeks"]
    ctx = {"weeks": weeks, "deliveries": {}, "covered": {}, "days": {}, "history_start": _history_start()}
    for w in weeks:
        end = min(w + timedelta(days=6), to)
        total, _covered_n, ok = _delivery(w, end)
        ctx["deliveries"][w] = float(total) if ok else 0.0
        ctx["covered"][w] = bool(chat.get(w, {}).get("covered"))
        ctx["days"][w] = (end - w).days + 1
    return ctx


def _series(m, cases, crow, ctx, frm, to):
    """The stats.badges input for one code. Complaint codes use deliveries as exposure; other kinds covered days."""
    weeks, count, who = ctx["weeks"], Counter(), defaultdict(set)
    for c in cases:
        w = stats.week_start(c["day"])
        count[w] += 1
        who[w].add(_who(c))
    complaint = m.kind == "Complaint"
    return {
        "weeks": weeks,
        "cases": [count[w] for w in weeks],
        "customers_by_week": [who[w] for w in weeks],
        "exposure": [ctx["deliveries"][w] if complaint else float(ctx["days"][w] * ctx["covered"][w]) for w in weeks],
        "covered": [ctx["covered"][w] for w in weeks],
        "flagged": [stats.season_of(w) is not None for w in weeks],
        "has_safety": bool(m.is_food_safety) and any(c["severity"] in ("S1", "S2") for c in _between(cases, frm, to)),
        "first_case": cases[0]["day"] if cases else None,
        "history_start": ctx["history_start"],
        "public": complaint and any(r["channel"] in PUBLIC and frm <= r["day"] <= to for r in crow),
        "cases_before_minus12": sum(1 for c in cases if c["day"] < weeks[-12]),
    }


def _signal(series):
    """(current 4-week cases, cases expected at the baseline rate, rate test) as stats.badges computes them."""
    # ponytail: re-derives the baseline stats.badges uses, to word "3 → 7 (p 0.004)"; if the two ever drift,
    # have badges() return its test as well.
    weeks, cases, exposure = series["weeks"], series["cases"], series["exposure"]
    cur = sum(cases[-4:])
    skip = {w for i, w in enumerate(weeks) if series["flagged"][i] or not series["covered"][i] or not exposure[i]}
    base = stats.pick_baseline(weeks, weeks[-4], skip)
    if not base or not all(exposure[-4:]) or not all(series["covered"][-4:]):
        return cur, None, None
    index = {w: i for i, w in enumerate(weeks)}
    base_x, base_e, cur_e = (
        sum(cases[index[w]] for w in base),
        sum(exposure[index[w]] for w in base),
        sum(exposure[-4:]),
    )
    return cur, base_x * cur_e / base_e, stats.rate_test(cur, cur_e, base_x, base_e)


def _p_text(p):
    return "p < 0.001" if p < 0.001 else f"p {p:.3f}"


def _signal_text(badge, series):
    cur, expected, test = _signal(series)
    if badge == "NEW":
        return f"0 → {cur} · first seen in the last 14 days"
    if badge == "RESURFACED":
        return f"0 → {cur} · back after 8 quiet weeks"
    words = {"SURGE": "much higher than usual", "WATCH": "higher than usual", "IMPROVING": "lower than usual"}[badge]
    if test is None:
        return words
    p = test["down"] if badge == "IMPROVING" else test["up"]
    return f"{expected:.0f} → {cur} · {words} ({_p_text(p)})"


def _dishes(cur, window, frm, to):
    """The funnel test per matched dish: the issue's matched cases spread by each dish's share of meals delivered
    in the window give the expected count; flag at Poisson p < 0.01, only with >= 3 cases and >= 300 meals."""
    case_of = {contact: i for i, c in enumerate(cur) for contact in c["contacts"]}
    by_dish, names = defaultdict(set), {}
    for r in window:
        if r["dish_item"] and r["contact"] in case_of:
            key = _dish_key(r["dish_item"])
            by_dish[key].add(case_of[r["contact"]])
            names.setdefault(key, r["dish_item"])
    if not by_dish:
        return []
    meals = _meals(frm, to)
    total, matched = sum(meals.values()), len(set().union(*by_dish.values()))
    out = []
    for key, ids in by_dish.items():
        n = meals.get(key, 0)
        expected = matched * n / total if total else 0.0
        p = stats.poisson_upper(len(ids), expected) if expected > 0 else None
        flag = len(ids) >= 3 and n >= 300 and p is not None and p < 0.01
        out.append(
            {"dish": names[key], "cases": len(ids), "meals": n, "expected": round(expected, 2), "p": p, "flag": flag}
        )
    return sorted(out, key=lambda d: (d["p"] is None, d["p"] or 0, -d["cases"]))


def _exposures(frm, to, pfrm, pto):
    """Chip exposures by kind: deliveries for complaints only when both windows have a delivery rate."""
    (cur, _n_cur, cur_ok), (prev, _n_prev, prev_ok) = _delivery(frm, to), _delivery(pfrm, pto)
    return {
        "Complaint": (cur, prev) if cur_ok and prev_ok else (None, None),
        "other": (_covered_days("chat", frm, to), _covered_days("chat", pfrm, pto)),
    }


def _code_stats(m, crow, frm, to, pfrm, pto, ctx, exposures):
    """One issue-table row for code m from its counted rows, plus the pieces the panel and the Brief reuse."""
    cases = [c for c in _collapse(crow) if c["day"] <= to]  # all history up to the window's end
    cur, prev = _between(cases, frm, to), _between(cases, pfrm, pto)
    window = [r for r in crow if frm <= r["day"] <= to]
    series = _series(m, cases, crow, ctx, frm, to)
    worst = {}
    for c in cur:
        worst[_who(c)] = min(worst.get(_who(c), "S4"), c["severity"])
    e_cur, e_prev = exposures["Complaint" if m.kind == "Complaint" else "other"]
    dishes = _dishes(cur, window, frm, to)
    channels = Counter(c["channel"] for c in cur)
    row = {
        "code": m.code,
        "label": m.label,
        "family": m.family,
        "kind": m.kind,
        "owner_department": m.owner_department,
        "cases": len(cur),
        "prior_cases": len(prev),
        "customers": len(worst),
        "contacts": len({r["contact"] for r in window}),
        "chip": stats.chip(len(cur), e_cur, len(prev), e_prev),
        "trend": series["cases"][-12:],
        "weeks_active": sum(1 for x in series["cases"][-8:] if x),
        "severity": {s: sum(1 for c in cur if c["severity"] == s) for s in WEIGHTS},
        "top_channel": channels.most_common(1)[0][0] if channels else None,
        "dish": next((d["dish"] for d in dishes if d["flag"]), None),
        "badges": stats.badges(series),
        "priority": sum(WEIGHTS[s] for s in worst.values()),
    }
    return {"row": row, "cases": cases, "cur": cur, "window": window, "series": series, "dishes": dishes}


def _issue_rows(rows, frm, to, pfrm, pto):
    """Issue-table rows (NEW excluded) by priority, and the per-code stats behind them."""
    meta, ctx, exposures = _meta(), _week_ctx(to), _exposures(frm, to, pfrm, pto)
    by_code = defaultdict(list)
    for r in rows:
        if r["code"] != "NEW":
            by_code[r["code"]].append(r)
    per_code = {
        code: _code_stats(meta[code], crow, frm, to, pfrm, pto, ctx, exposures) for code, crow in by_code.items()
    }
    out = [s["row"] for s in per_code.values() if s["row"]["cases"] or s["row"]["prior_cases"] or s["row"]["badges"]]
    for row in out:
        row["action"] = _advisor("action_state", row["code"])
        row["suggestions"] = _advisor("suggestion_state", row["code"])
    out.sort(key=lambda r: (-r["priority"], -r["cases"], r["code"]))
    return out, per_code


def _quote_row(r, mask):
    """An evidence row; S1/S2 food-safety and allergy quotes are hidden from non-deciders when masking is on."""
    hide = (
        mask
        and r["severity"] in ("S1", "S2")
        and (r["is_food_safety"] or r["code"] in HEALTH_CODES or (r["code"] == "NEW" and r["hits"]))
    )
    return {
        "ref": r["contact"],
        "date": r["day"],
        "channel": r["channel"],
        "severity": r["severity"],
        "role": r["role"],
        "quote": HIDDEN if hide else r["quote"],
        "quote_en": HIDDEN if hide else r["quote_en"],
        "quote_status": r["quote_status"],
        "review": r["review"],
        "ticket": r["ticket"],
        "has_ticket": bool(r["ticket"]),
        "safety": r["is_food_safety"] or bool(r["hits"]),
    }


def _one_per_contact(rows):
    """The worst-severity row per contact, newest first."""
    best = {}
    for r in rows:
        if r["contact"] not in best or r["severity"] < best[r["contact"]]["severity"]:
            best[r["contact"]] = r
    return sorted(best.values(), key=lambda r: r["at"], reverse=True)


def overview(from_date, to_date, channel=None, dept=None, kind="problems") -> dict:
    if kind not in KINDS:
        frappe.throw(_("Unknown kind: {0}").format(kind))
    frm, to = _dates(from_date, to_date)
    pfrm, pto = _prior(frm, to)
    by_channel = _filtered(counted_rows(), channel)
    rows = _filtered(by_channel, dept=dept)
    safety = safety_box(frm, to)
    kinds = KINDS[kind]
    issues = _issue_rows([r for r in rows if kinds is None or r["kind"] in kinds], frm, to, pfrm, pto)[0]
    return _js(
        {
            "window": {"from_date": frm, "to_date": to, "prior_from": pfrm, "prior_to": pto},
            "state": window_state(frm, to),
            "kpis": _kpis(_tiles(rows, frm, to, len(safety["needs_review"])), _tiles(rows, pfrm, pto)),
            "issues": issues,
            "unclassified": len({r["contact"] for r in by_channel if r["code"] == "NEW" and frm <= r["day"] <= to}),
            "safety": safety,
            "how_we_count": HOW_WE_COUNT,
        }
    )


# --- safety box ------------------------------------------------------------------------------------


def _clusters(rows):
    """Possible clusters: 2+ distinct customers with food-safety labels within 4 days (the dish is ignored by the
    rule and only shown). Overlapping qualifying spans merge into one cluster."""
    events = _one_per_contact(rows)[::-1]  # oldest first
    spans = []
    for i, r in enumerate(events):
        j = i
        while j + 1 < len(events) and events[j + 1]["at"] - r["at"] <= timedelta(days=4):
            j += 1
        if len({_person(x) for x in events[i : j + 1]}) >= 2:
            if spans and spans[-1][1] >= i:
                spans[-1][1] = max(spans[-1][1], j)
            else:
                spans.append([i, j])
    out = []
    for i, j in spans:
        group = events[i : j + 1]
        refs = {x["contact"] for x in group}
        tags = [r for r in rows if r["contact"] in refs]
        out.append(
            {
                "from": group[0]["day"],
                "to": group[-1]["day"],
                "customers": len({_person(x) for x in group}),
                "contacts": len(group),
                "labels": sorted({t["label"] for t in tags}),
                "dishes": sorted({t["dish_item"] or t["dish"] for t in tags if t["dish_item"] or t["dish"]}),
                "refs": [x["contact"] for x in group],
            }
        )
    return out


def _needs_review(frm, to):
    """Never counted, never hidden: food-safety labels with an unverified quote or low confidence, safety-rule
    hits without any food-safety label, and rule hits on contacts whose labelling is pending or failed."""
    meta = _meta()
    fs = {code for code, m in meta.items() if meta[m["target"]]["is_food_safety"]}
    out = []
    for c in _base().values():
        if not c.live or not c.started_on or not frm <= c.started_on.date() <= to:
            continue
        tags = [i for i in c.issues if i.code in fs]
        open_tags = [i for i in tags if i.review != "Rejected"]
        reason = None
        if c.status == "Tagged":
            if any(i.quote_status not in ("Verified", "Repaired") for i in open_tags):
                reason = "Food-safety label whose quote could not be verified"
            elif any(i.confidence == "low" for i in open_tags):
                reason = "Low-confidence food-safety label"
            elif c.hits and not tags:
                reason = "Food-safety words but no food-safety label"
        elif c.hits and c.status in ("Pending", "Tagging"):
            reason = "Food-safety words; labelling pending"
        elif c.hits and c.status == "Failed":
            reason = "Food-safety words; labelling failed"
        if reason:
            out.append(
                {
                    "ref": c.name,
                    "date": c.started_on.date(),
                    "channel": c.channel,
                    "reason": reason,
                    "rules": sorted({h["rule"] for h in c.hits}),
                    "ticket": c.ticket or None,
                    "has_ticket": bool(c.ticket),
                }
            )
    return sorted(out, key=lambda x: x["date"], reverse=True)


def safety_box(from_date, to_date) -> dict:
    """Food-safety events, possible clusters and needs-review rows. Only the date window applies."""
    frm, to = _dates(from_date, to_date)
    mask = _mask()
    rows = [
        r for r in counted_rows() if r["is_food_safety"] and r["severity"] in ("S1", "S2") and frm <= r["day"] <= to
    ]
    events = [
        {**_quote_row(r, mask), "code": r["code"], "label": r["label"]}
        for r in sorted(rows, key=lambda r: r["at"], reverse=True)
    ]
    return _js({"events": events, "clusters": _clusters(rows), "needs_review": _needs_review(frm, to)})


# --- issue panel and evidence ----------------------------------------------------------------------


def _code(code):
    meta = _meta()
    if code not in meta:
        frappe.throw(_("Unknown issue code: {0}").format(code))
    return meta[meta[code]["target"]]


def issue_detail(code, from_date, to_date, channel=None, dept=None) -> dict:
    frm, to = _dates(from_date, to_date)
    pfrm, pto = _prior(frm, to)
    m = _code(code)
    by_channel = _filtered(counted_rows(), channel)
    crow = [r for r in _filtered(by_channel, dept=dept) if r["code"] == m.code]
    ctx = _week_ctx(to)
    s = _code_stats(m, crow, frm, to, pfrm, pto, ctx, _exposures(frm, to, pfrm, pto))
    row, cur, window = s["row"], s["cur"], s["window"]

    contacts = {r["contact"] for r in window}
    pairs = {
        (r["contact"], r["code"]) for r in by_channel if r["contact"] in contacts and r["code"] not in (m.code, "NEW")
    }
    labels = {r["code"]: r["label"] for r in by_channel}
    offered = Counter(o for o in {r["contact"]: r["offered"] for r in window}.values() if o)

    deliveries, _covered_n, rate_ok = _delivery(frm, to)
    if m.kind == "Complaint":
        rate = round(len(cur) / deliveries * 1000, 2) if rate_ok and deliveries else None
        exposure_kind, unit = "Deliveries", "per 1,000 deliveries"
    else:
        days = _covered_days("chat", frm, to)
        rate = round(len(cur) / days * 7, 2) if days else None
        exposure_kind, unit = "Days", "per covered week"
    seen = [r["day"] for r in crow if r["day"] <= to]

    weekly = []
    for i, w in enumerate(ctx["weeks"][-26:], start=len(ctx["weeks"]) - 26):
        e = ctx["deliveries"][w] if ctx["covered"][w] else 0  # no chat coverage: no rate, never a fake 0
        weekly_rate = round(s["series"]["cases"][i] / e * 1000, 2) if m.kind == "Complaint" and e else None
        weekly.append(
            {
                "week": w,
                "cases": s["series"]["cases"][i],
                "rate": weekly_rate,
                "covered": ctx["covered"][w],
                "season": stats.season_of(w),
            }
        )

    return _js(
        {
            "code": m.code,
            "label": m.label,
            "definition": m.definition,
            "owner_department": m.owner_department,
            "kind": m.kind,
            "family": m.family,
            "is_food_safety": bool(m.is_food_safety),
            "numbers": {
                "cases": len(cur),
                "customers": row["customers"],
                "contacts": row["contacts"],
                "repeat_contacts": row["contacts"] - len(cur),
                "weeks_active": row["weeks_active"],
                "first_seen": s["cases"][0]["day"] if s["cases"] else None,
                "last_seen": max(seen) if seen else None,
                "rate": rate,
                "exposure_kind": exposure_kind if rate is not None else None,
                "rate_text": f"{rate:,.2f} {unit}" if rate is not None else None,
            },
            "badges": [{"key": b, "text": BADGE_TEXT[b]} for b in row["badges"]],
            "season": next((x for x in map(stats.season_of, _weeks(frm, to)) if x), None),
            "co_occurring": [
                {"code": c, "label": labels[c], "n": n} for c, n in Counter(c for _, c in pairs).most_common(5)
            ],
            "offered": [
                {
                    "key": k,
                    "label": k.replace("_", " ").capitalize(),
                    "n": n,
                    "share": round(n / sum(offered.values()), 2),
                }
                for k, n in offered.most_common()
            ],
            "weekly": weekly,
            "where": {
                "channels": [{"channel": ch, "cases": n} for ch, n in Counter(c["channel"] for c in cur).most_common()],
                "weekdays": [
                    {"weekday": day, "cases": sum(1 for c in cur if WEEKDAYS[(c["day"].weekday() + 1) % 7] == day)}
                    for day in WEEKDAYS
                ],
                "dishes": s["dishes"],
            },
            "ticket_ids": sorted({r["ticket"] for r in window if r["ticket"]}, key=lambda t: (len(t), t)),
            # the latest of each, so the panel shows past results without starting a run
            "suggestions": _latest_insight("Suggestions", m.code, "status", "decision"),
            "research": _latest_insight("Research", m.code, "status"),
            "action": _advisor("action_state", m.code),
        }
    )


def _latest_insight(insight_type, code, *fields):
    row = frappe.db.get_value(
        "HD AI Insight",
        {"insight_type": insight_type, "issue_code": code},
        ["name", "creation", *fields],
        as_dict=True,
        order_by="creation desc",
    )
    return {"insight": row.name, **{f: row[f] for f in fields}, "created": row.creation} if row else None


def evidence(code, from_date, to_date, channel=None, dept=None, start=0, limit=30) -> dict:
    """The verified quotes behind a code in the window, one per contact, worst severity first, then newest."""
    frm, to = _dates(from_date, to_date)
    m = _code(code)
    rows = [r for r in _filtered(counted_rows(), channel, dept) if r["code"] == m.code and frm <= r["day"] <= to]
    rows = sorted(_one_per_contact(rows), key=lambda r: r["severity"])
    start, limit, mask = max(cint(start), 0), min(max(cint(limit), 1), 100), _mask()
    return _js({"total": len(rows), "rows": [_quote_row(r, mask) for r in rows[start : start + limit]]})


# --- Brief -----------------------------------------------------------------------------------------


def _best_quotes(crow, frm, to, mask, n=2):
    """Up to n quotes from different customers: customer lines first, then Verified, then worst and newest."""
    ranked = sorted(
        _one_per_contact([r for r in crow if frm <= r["day"] <= to]),
        key=lambda r: (r["role"] != "customer", r["quote_status"] != "Verified", r["severity"]),
    )
    out, seen = [], set()
    for r in ranked:
        if _person(r) not in seen and len(out) < n:
            seen.add(_person(r))
            out.append({**_quote_row(r, mask), "code": r["code"], "label": r["label"]})
    return out


def _headline(week, kpis, top):
    k = {t["key"]: t for t in kpis}
    cases, customers, food = k["complaint_cases"], k["customers"], k["food_safety"]
    if cases["value"] is None:
        return f"Week of {_day_text(week)}: no chat data, so complaint counts are not shown."
    out = f"Week of {_day_text(week)}: {_n(cases['value'], 'complaint case')} from {_n(customers['value'], 'customer')}"
    if cases["chip"] and cases["chip"]["label"]:
        out += f" ({cases['chip']['label']} against the previous 4 weeks)"
    out += "."
    if top:
        out += f" Top problem: {top[0]['label']} ({_n(top[0]['cases'], 'case')} in 4 weeks)."
    out += f" {_n(food['value'], 'food-safety event')}." if food["value"] else " No food-safety events."
    return out


def _ai_headline(week):
    """The week's latest Done Brief insight (Write summary) as the headline; None when there is none or it fell back
    to the code headline. Its text holds {{key}} placeholders that the page fills from values."""
    row = frappe.db.get_value(
        "HD AI Insight",
        {"insight_type": "Brief", "week_start": week, "status": "Done"},
        ["name", "output_json", "models", "modified"],
        as_dict=True,
        order_by="creation desc",
    )
    try:
        out = json.loads(row.output_json or "null") if row else None
    except ValueError:
        out = None
    if not isinstance(out, dict) or out.get("fallback") or not out.get("headline"):
        return None
    return {
        "text": out["headline"],
        "values": out.get("values") or {},
        "bullets": out.get("bullets") or [],
        "source": "ai",
        "model": row.models,
        "at": row.modified,
        "insight": row.name,
    }


# Actions tab rows (HD AI Action); verdict fields are written by advisor.update_verdicts
ACTION_FIELDS = [
    "name",
    "title",
    "issue_code",
    "owner_department",
    "assigned_to",
    "status",
    "due_date",
    "done_on",
    "plan",
    "baseline_value",
    "recent_value",
    "target_value",
    "exposure_kind",
    "verdict",
    "verdict_p",
    "target_met",
    "verdict_checked_on",
    "verdict_history",
    "recurred",
    "insight",
]
OPEN_ACTION = ("Open", "In progress")
DECISION_BADGES = ("SAFETY", "SURGE", "NEW", "RESURFACED", "CHRONIC")  # problems that need an owner


def _next_check(a):
    """A Done action's next verdict check: 4 and 8 weeks after done_on + 7 days (advisor.update_verdicts)."""
    if a.status != "Done" or not a.done_on:
        return None
    start = getdate(a.done_on) + timedelta(days=7)
    checked = getdate(a.verdict_checked_on) if a.verdict_checked_on else None
    checks = (start + timedelta(weeks=4), start + timedelta(weeks=8))
    return next((d for d in checks if not checked or checked < d), None)


def actions(filter="open", names=None) -> list[dict]:
    """Actions tab rows, newest first. filter: open (Open, In progress), overdue (open, due before today), verifying
    (Done with a verdict check still to come) or all; names limits the rows to those actions."""
    today, meta = getdate(), _meta()
    filters = {"name": ("in", names)} if names else {}
    if filter in ("open", "overdue"):
        filters["status"] = ("in", OPEN_ACTION)
    elif filter == "verifying":
        filters["status"] = "Done"
    out = []
    # ponytail: the newest 500 actions; page the query if a site ever keeps more
    for a in frappe.get_all("HD AI Action", filters=filters, fields=ACTION_FIELDS, order_by="creation desc", limit=500):
        overdue = a.status in OPEN_ACTION and bool(a.due_date) and getdate(a.due_date) < today
        next_check = _next_check(a)
        if (filter == "overdue" and not overdue) or (filter == "verifying" and not next_check):
            continue
        try:
            history = json.loads(a.verdict_history or "[]")
        except ValueError:
            history = []
        out.append(
            {
                **a,
                "label": meta[a.issue_code].label if a.issue_code in meta else None,
                "assigned_to_name": get_fullname(a.assigned_to) if a.assigned_to else None,
                "overdue": overdue,
                "next_check": next_check,
                "recurred": bool(a.recurred),
                "target_met": bool(a.target_met),
                "verdict_history": history if isinstance(history, list) else [],
            }
        )
    return _js(out)


def _brief_actions(acts):
    """Follow-through as of today: due in the next 7 days, overdue, the latest verdicts and the fixes that recurred."""
    today = getdate()
    live = [a for a in acts if a["status"] in OPEN_ACTION]
    verdicts = [a for a in acts if a["verdict"] not in (None, "", "Not yet")]
    return {
        "due": [a for a in live if a["due_date"] and today <= getdate(a["due_date"]) <= today + timedelta(days=7)],
        "overdue": [a for a in live if a["overdue"]],
        "verdicts": sorted(verdicts, key=lambda a: a["verdict_checked_on"] or "", reverse=True)[:10],
        "recurred": [a for a in acts if a["recurred"]],
    }


def _decisions(week, to, rows, issues, safety, state, added, acts) -> list[dict]:
    """Decisions needed, built by code in the plan's order: safety, problems without an owner, plans and actions,
    customers who want to cancel, then data and process. Each row: kind, text, tab, issue, action and refs
    (contact refs for the call-back list; never names or phones)."""
    meta, cov, today, now, out = _meta(), _cov(), getdate(), now_datetime(), []

    def add(kind, text, tab, issue=None, action=None, refs=None):
        out.append({"kind": kind, "text": text, "tab": tab, "issue": issue, "action": action, "refs": refs or []})

    for (code, label), n in Counter((e["code"], e["label"]) for e in safety["events"]).most_common():
        text = f"{label}: {_n(n, 'food-safety event')} this week. Kitchen & QA should check each one."
        add("safety_event", text, "brief", code)
    for c in safety["clusters"]:
        span = f"{_day_text(getdate(c['from']))} to {_day_text(getdate(c['to']))}"
        text = f"Possible cluster: {_n(c['customers'], 'customer')} with food-safety labels from {span}."
        add("safety_cluster", text + " Look for a shared cause.", "brief")

    handled = {a["issue_code"] for a in acts if a["status"] in OPEN_ACTION or a["next_check"]}
    for r in issues:
        badge = next((b for b in DECISION_BADGES if b in r["badges"]), None)
        if badge and r["code"] not in handled:
            text = f"{r['label']} is {badge} with no open action. Get suggestions, then adopt or reject a plan."
            add("problem_no_action", text, "issues", r["code"])

    latest = {}
    for s in frappe.get_all(
        "HD AI Insight",
        filters={"insight_type": "Suggestions"},
        fields=["issue_code", "status", "decision", "creation"],
        order_by="creation desc",
    ):
        latest.setdefault(s.issue_code, s)  # a regenerated or combined run replaces the plan it came from
    for code, s in latest.items():
        if s.status == "Done" and s.decision == "Pending" and s.creation < now - timedelta(days=2):
            label = meta[code].label if code in meta else code
            text = f"A plan for {label} has waited {_n((now - s.creation).days, 'day')} for a decision."
            add("plan_waiting", text + " Adopt or reject it.", "issues", code)
    for a in acts:
        if a["overdue"]:
            who = ", ".join(x for x in (a["owner_department"], a["assigned_to_name"]) if x)
            text = f"Overdue since {_day_text(getdate(a['due_date']))}: {a['title']}" + (f" ({who})." if who else ".")
            add("action_overdue", text, "actions", a["issue_code"], a["name"])
    for a in acts:
        if a["verdict"] == "Higher than before":
            text = f"Cases were higher than before after “{a['title']}” (association, not proof). Review the plan."
            add("verdict_higher", text, "actions", a["issue_code"], a["name"])
    for a in acts:
        if a["recurred"]:
            text = f"{a['label'] or a['issue_code']} came back after “{a['title']}”. Decide on a new plan."
            add("recurred", text, "actions", a["issue_code"], a["name"])

    callback = {}
    for r in rows:  # oldest first, so each customer keeps their latest contact
        if r["code"] == "SUB_CANCEL_INTENT" and week <= r["day"] <= to:
            callback[_person(r)] = r["contact"]
    if callback:
        text = f"{_n(len(callback), 'customer')} said they would cancel because they are unhappy. Call them back."
        add("cancel_intent", text, "issues", "SUB_CANCEL_INTENT", refs=list(callback.values()))

    for p in cov["chat"]["stopped"]:
        last = max(w for w, x in cov["chat"]["weeks"].items() if x["platforms"].get(p, {}).get("covered"))
        text = f"No {p} chats since {_day_text(last + timedelta(days=6))}."
        add("stopped_feed", text + " Decide whether the feed is broken or the channel was closed.", "health")
    for until, what, why in (
        (cov["deliveries"]["until"], "deliveries", "rates per 1,000 deliveries stay blank"),
        (cov["calls"]["until"], "answered calls", "call counts stay blank"),
    ):
        if until and (stats.week_start(today) - stats.week_start(until)).days > 14:
            text = f"No {what} since {_day_text(until)}, so {why}. Decide whether the sync is broken."
            add("stopped_feed", text, "health")
    for notice in state["capture_notices"]:
        if notice["key"] == "missed_calls":
            need = "decide whether to sync missed calls from 3CX"
        else:
            need = "decide whether agents should reply from the CRM, so replies are recorded"
        add("capture_gap", f"{notice['text'].rstrip('.')}: {need}.", "health")
    if added:
        who = ", ".join(f"{get_fullname(owner)} ({n})" for owner, n in added)
        add("exclusions_added", f"Exclusions added this week by {who}. Check that each one is right.", "health")
    waiting = len({r["contact"] for r in rows if r["code"] == "NEW"})
    if waiting:
        text = f"{_n(waiting, 'unclassified contact')} wait in the NEW queue."
        add("unclassified", text + " Map each to a code, create a code or dismiss it.", "health")
    stale = tagging.stale_count()
    if stale:
        text = f"The label registry changed: {_n(stale, 'contact')} carry an older label version."
        add("registry_unpublished", text + " Publish the new version.", "health")
    return out


def brief(week=None) -> dict:
    """The company-wide Sunday-Saturday week (default: the last complete covered week). Phase 1 is code-built."""
    chat, today = _cov()["chat"], getdate()
    done = sorted((w for w, x in chat["weeks"].items() if x["covered"] and w + timedelta(days=6) < today), reverse=True)
    week = stats.week_start(week) if week else (done[0] if done else stats.week_start(today) - timedelta(weeks=1))
    to, last = week + timedelta(days=6), week - timedelta(days=1)
    four, p4 = week - timedelta(weeks=3), week - timedelta(weeks=4)
    rows, meta, mask = counted_rows(), _meta(), _mask()

    safety = safety_box(week, to)
    state = window_state(week, to)
    kpis = _kpis(_tiles(rows, week, to, len(safety["needs_review"])), _tiles(rows, p4, last), weeks=4)

    issues, per_code = _issue_rows(
        [r for r in rows if r["kind"] == "Complaint"], four, to, four - timedelta(weeks=4), four - timedelta(days=1)
    )
    top = []
    for row in [r for r in issues if r["cases"]][:3]:
        s = per_code[row["code"]]
        wk = _between(s["cases"], week, to)
        top.append(
            {
                **row,
                "week_cases": len(wk),
                "week_customers": len({_who(c) for c in wk}),
                "sparkline": s["series"]["cases"][-8:],
                "quotes": _best_quotes(s["window"], four, to, mask),
            }
        )
    changed = []
    for row in issues:
        badge = next((b for b in SIGNALS if b in row["badges"]), None)
        if badge:
            changed.append(
                {
                    "code": row["code"],
                    "label": row["label"],
                    "badge": badge,
                    "text": _signal_text(badge, per_code[row["code"]]["series"]),
                }
            )
    changed.sort(key=lambda c: SIGNALS.index(c["badge"]))  # stable: priority order within a badge

    asked = [r for r in rows if r["kind"] in ("Enquiry", "Request")]
    chat_wk, chat_p4 = _covered_days("chat", week, to), _covered_days("chat", p4, last)
    by_code = defaultdict(list)
    for r in asked:
        by_code[r["code"]].append(r)
    demand_top = []
    for code, crow in by_code.items():
        cases = _collapse(crow)
        x, px = len(_between(cases, week, to)), len(_between(cases, p4, last))
        if x:
            demand_top.append(
                {
                    "code": code,
                    "label": meta[code].label,
                    "cases": x,
                    "prior": round(px / 4, 2),
                    "chip": _chip(x, chat_wk, px, chat_p4, 4),
                }
            )
    demand_top.sort(key=lambda d: (-d["cases"], d["code"]))
    week_asked = _one_per_contact([r for r in asked if week <= r["day"] <= to])
    feedback = lambda code: len(_between(_collapse([r for r in rows if r["code"] == code]), week, to))  # noqa: E731

    by_reason = Counter(c.exclusion_reason or "Excluded" for c in _base().values() if c.status == "Excluded")
    added = frappe.db.sql(
        "select owner, count(*) from `tabHD AI Exclusion` where creation >= %s and creation < %s group by owner",
        (week, to + timedelta(days=1)),
    )
    score = _evaluation()
    acts = actions("all")
    code_headline = {"text": _headline(week, kpis, top), "values": {}, "source": "code", "model": None, "at": None}
    return _js(
        {
            "week": week,
            "weeks": done[:26],
            "state": state,
            "headline": _ai_headline(week) or code_headline,
            "kpis": kpis,
            "top": top,
            "changed": changed[:5],
            "demand": {
                "top": demand_top[:5],
                "arabic_share": round(
                    sum(1 for r in week_asked if r["language"] in ("ar", "mixed")) / len(week_asked), 2
                )
                if week_asked
                else None,
                "public_comments": sum(1 for r in week_asked if r["channel"] in PUBLIC),
                "praise": feedback("FB_PRAISE"),
                "suggestions": feedback("FB_SUGGESTION"),
            },
            "safety": safety,
            "footer": {
                "season": stats.season_of(week),
                "chat_covered": state["covered"],
                "delivery_rate": state["delivery_rate"],
                "excluded": sum(by_reason.values()),
                "exclusions_by_reason": dict(by_reason),
                "exclusions_added": [{"by": get_fullname(owner), "n": n} for owner, n in added],
                "validated": bool(
                    score and score.get("safety_recall") == 1 and (score.get("quote_validity") or 0) >= 0.95
                ),
                "model": conf().model,
            },
            "actions": _brief_actions(acts),
            "decisions": _decisions(week, to, rows, issues, safety, state, added, acts),
        }
    )


# --- Operations (Phase 3) --------------------------------------------------------------------------

OPS_CAPTIONS = (
    MISSED_CALLS,
    "Cost of poor quality is replacement deliveries at kitchen cost; their selling value is shown beside it.",
    "Refunds (all reasons) are shown separately and never added: no refund reason is recorded.",
    "Rates per 1,000 deliveries only where deliveries cover 90% of the days; contact load also needs chat and call "
    "coverage that week.",
)


def _months(frm, to):
    """(first, last) day of each calendar month in [frm, to], clipped to the window."""
    out, m = [], date(frm.year, frm.month, 1)
    while m <= to:
        nxt = date(m.year + m.month // 12, m.month % 12 + 1, 1)
        out.append((max(m, frm), min(nxt - timedelta(days=1), to)))
        m = nxt
    return out


def operations(from_date, to_date) -> dict:
    """Cost of poor quality by month, contact load by week and repeat callers. A value is None, never a fake 0, where
    its source has no coverage: replacements without delivery days, chats or calls in an uncovered week."""
    frm, to = _dates(from_date, to_date)
    months = []
    for a, b in _months(frm, to):
        money, (deliveries, delivered_days, rate_ok) = _money(a, b), _delivery(a, b)
        has = delivered_days > 0
        months.append(
            {
                "month": f"{a:%Y-%m}",
                "refunds_n": money["refunds"],
                "refunds_qar": money["refunds_qar"],
                "replacements_n": money["replacements"] if has else None,
                "replacements_cost": money["cost"] if has else None,
                "replacements_value": money["value"] if has else None,
                "per_1000": round(money["replacements"] / deliveries * 1000, 2) if rate_ok and deliveries else None,
            }
        )

    cov, calls = _cov(), [c for c in _calls()["answered"] if frm <= c[0].date() <= to]
    load = Counter(
        (stats.week_start(c.started_on), c.source)
        for c in _base().values()
        if c.live and c.status != "Excluded" and c.started_on and frm <= c.started_on.date() <= to
    )
    answered = Counter(stats.week_start(at) for at, _caller in calls)
    weeks = []
    for w in _weeks(frm, to):
        deliveries, _days_n, rate_ok = _delivery(max(w, frm), min(w + timedelta(days=6), to))
        chats = load[(w, "Chat")] if cov["chat"]["weeks"].get(w, {}).get("covered") else None
        phoned = answered[w] if cov["calls"]["weeks"].get(w, {}).get("covered") else None
        tickets = load[(w, "Ticket")]
        per_1000 = None
        if rate_ok and deliveries and chats is not None and phoned is not None:
            per_1000 = round((chats + tickets + phoned) / deliveries * 1000, 2)
        weeks.append(
            {
                "week": w,
                "chat_sessions": chats,
                "ticket_contacts": tickets,
                "answered_calls": phoned,
                "deliveries": deliveries if rate_ok else None,
                "per_1000": per_1000,
            }
        )

    # the call tile's rules: answered calls after the exclusions; a repeat caller has 2+ calls within 7 days
    callers, repeat = len({caller for _at, caller in calls}), _repeat_callers(calls)
    repeat_callers = {"callers": None, "repeat_callers": None, "share": None}
    if _covered_days("calls", frm, to):
        share = round(repeat / callers, 3) if callers else None
        repeat_callers = {"callers": callers, "repeat_callers": repeat, "share": share}
    return _js(
        {
            "copq": {"months": months},
            "contact_load": {"weeks": weeks},
            "repeat_callers": repeat_callers,
            "captions": list(OPS_CAPTIONS),
        }
    )


# --- Ask your tickets (Phase 4) --------------------------------------------------------------------

ASK_GROUPS = {"week": "Week starting", "code": "Issue", "channel": "Channel", "dish": "Dish", "weekday": "Weekday"}
ASK_MAX_ROWS = 52
NO_DISH = "No dish named"


def _ask_scope(plan):
    """(rows, cases, from, to, codes, agnostic) for an Ask plan: the page's case rules (fixed 7-day windows over all
    history, counted by start), code-agnostic when the plan names no codes and does not group by code."""
    frm, to = _dates(plan["from"], plan["to"])
    meta = _meta()
    codes = {meta[c]["target"] for c in plan.get("codes") or () if c in meta}
    kinds, channels = set(plan.get("kinds") or ()), set(plan.get("channels") or ())
    rows = [
        r
        for r in counted_rows()
        if r["code"] != "NEW"
        and (not codes or r["code"] in codes)
        and (not kinds or r["kind"] in kinds)
        and (not channels or r["channel"] in channels)
    ]
    agnostic = not codes and plan.get("group_by") != "code"
    cases = _between(_collapse(rows, key=(lambda r: "*") if agnostic else (lambda r: r["code"])), frm, to)
    return rows, cases, frm, to, codes, agnostic


def ask_table(plan) -> dict:
    """The Ask table for a validated plan {codes, kinds, channels, from, to, group_by, metric}: one row per group with
    cases and customers, plus a rate per 1,000 deliveries when the metric is rate and deliveries cover the window
    (otherwise cases, and filters_text says so). A week without chat coverage and without cases shows None, never 0."""
    rows, cases, frm, to, codes, agnostic = _ask_scope(plan)
    meta, group, metric = _meta(), plan.get("group_by") or "week", plan.get("metric") or "cases"
    dish = {}
    for r in rows:
        if r["dish_item"]:
            dish.setdefault(r["contact"], r["dish_item"])

    def key(c):
        if group == "week":
            return stats.week_start(c["day"])
        if group == "weekday":
            return (c["day"].weekday() + 1) % 7  # Sunday first
        if group == "dish":
            return next((dish[x] for x in c["contacts"] if x in dish), None)
        return c[group]  # code or channel

    def label(k):
        if group == "week":
            return _day_text(k)
        if group == "weekday":
            return WEEKDAYS[k]
        if group == "code":
            return meta[k].label if k in meta else k
        return NO_DISH if group == "dish" and k is None else k

    groups = defaultdict(list)
    for c in cases:
        groups[key(c)].append(c)
    keys = _weeks(frm, to) if group == "week" else range(7) if group == "weekday" else list(groups)
    deliveries, _days_n, covered = _delivery(frm, to)
    with_rate = metric == "rate" and covered
    chat_weeks = _cov()["chat"]["weeks"]
    out = []
    for k in keys:
        cs = groups.get(k, [])
        n, who = len(cs), len({_who(c) for c in cs})
        if group == "week" and not cs and not chat_weeks.get(k, {}).get("covered"):
            n = who = None
        row = [label(k), n, who]
        if with_rate:
            if group == "week":
                e, _d, ok = _delivery(max(k, frm), min(k + timedelta(days=6), to))
                row.append(round(n / e * 1000, 2) if ok and e and n is not None else None)
            else:
                row.append(round(n / deliveries * 1000, 2) if deliveries else None)
        out.append(row)
    if group not in ("week", "weekday"):
        col = 2 if metric == "customers" else 1
        out.sort(key=lambda r: (r[0] == NO_DISH, -(r[col] or 0), str(r[0])))
    total = len(out)
    out = out[-ASK_MAX_ROWS:] if group == "week" else out[:ASK_MAX_ROWS]  # the latest weeks, else the largest groups

    kinds, channels = plan.get("kinds") or [], plan.get("channels") or []
    parts = [f"Cases starting {_day_text(frm)} to {_day_text(to)}"]
    if codes:
        parts.append("issues: " + ", ".join(sorted(meta[c].label for c in codes)))
    if kinds:
        parts.append("kinds: " + ", ".join(sorted(kinds)))
    if not codes and not kinds:
        parts.append("every issue")
    parts.append("channels: " + ", ".join(sorted(channels)) if channels else "every channel")
    parts.append(f"grouped by {group}")
    if agnostic:
        parts.append("a case is one customer within 7 days, across these issues")
    else:
        parts.append("a case is one customer and one issue within 7 days")
    if metric == "rate" and not with_rate:
        parts.append("no rate: deliveries cover under 90% of these days, so this shows cases")
    if total > len(out):
        parts.append(f"showing {len(out)} of {total} rows")
    columns = [ASK_GROUPS[group], "Cases", "Customers"] + (["Per 1,000 deliveries"] if with_rate else [])
    return _js({"columns": columns, "rows": out, "n_cases": len(cases), "filters_text": " · ".join(parts)})


def ask_evidence(plan, limit=10) -> list[dict]:
    """Up to `limit` verified quotes behind an Ask table, one per customer, customer lines first. An Ask answer is
    stored and anyone may open it, so health quotes are hidden whenever the mask switch is on, deciders included."""
    rows, cases, frm, to, _codes, _agnostic = _ask_scope(plan)
    started = {x for c in cases for x in c["contacts"]}
    return _js(_best_quotes([r for r in rows if r["contact"] in started], frm, to, bool(conf().mask_health), limit))


# --- Data health -----------------------------------------------------------------------------------


def _exclusion_value(kind, value, decider):
    """Tickets and contact refs are safe to show. Phones and conversation names (which hold the customer's name)
    never leave the server, even for deciders: they see the last 4 digits or the conversation's serial."""
    if kind in ("Ticket", "Contact"):
        return value
    if not decider:
        return "hidden"
    if kind == "Phone":
        return "••••" + (value or "")[-4:]
    serial = re.search(r"(\d+)$", value or "")
    return "…" + serial.group(1) if serial else "hidden"


def _new_queue(rows, mask):
    """Counted NEW labels grouped by rapidfuzz token_set_ratio >= 80 on proposed label + statement."""
    # ponytail: greedy first match against each group's first label, O(labels x groups); fine to a few
    # thousand NEW labels, cluster properly (or embed, per the plan) past that.
    from rapidfuzz import fuzz

    groups = []
    for r in sorted((r for r in rows if r["code"] == "NEW"), key=lambda r: r["at"], reverse=True):
        key = text.normalize(f"{r['proposed_label'] or ''} {r['statement_en'] or ''}")
        for g in groups:
            if g["text"] == key or fuzz.token_set_ratio(key, g["text"]) >= 80:
                g["rows"].append(r)
                break
        else:
            groups.append({"text": key, "rows": [r]})
    out = []
    for g in groups:
        refs = list(dict.fromkeys(r["contact"] for r in g["rows"]))
        out.append(
            {
                "key": hashlib.sha1(g["text"].encode()).hexdigest()[:10],
                "label": g["rows"][0]["proposed_label"] or "Unlabelled",
                "n": len(refs),
                "examples": [_quote_row(r, mask)["quote"] for r in g["rows"][:3]],
                "refs": refs,
            }
        )
    return sorted(out, key=lambda g: -g["n"])


def data_health() -> dict:
    from helpdesk.ai_analysis import cases, jobs

    c, decider, mask, today = conf(), is_decider(), _mask(), getdate()
    cov, contacts, meta = _cov(), list(_base().values()), _meta()
    stopped = lambda until: bool(until) and (stats.week_start(today) - stats.week_start(until)).days > 14  # noqa: E731

    def source(key, label, seen, until, is_stopped):
        return {
            "key": key,
            "label": label,
            "rows": len(seen),
            "first": getdate(min(seen)) if seen else None,
            "last": getdate(max(seen)) if seen else None,
            "until": until,
            "stopped": is_stopped,
        }

    sources, chat_rows, weeks = [], _chat_rows(), cov["chat"]["weeks"]
    for p in PLATFORMS:
        seen = [r["at"] for r in chat_rows if r["platform"] == p]
        if seen:
            last = max((w for w, x in weeks.items() if x["platforms"].get(p, {}).get("covered")), default=None)
            until = last + timedelta(days=6) if last else None
            sources.append(source(p, p, seen, until, p in cov["chat"]["stopped"]))
    tickets = [x.started_on for x in contacts if x.source == "Ticket" and x.status != "Excluded" and x.started_on]
    sources.append(source("Tickets", "Tickets", tickets, None, False))
    days, until = cov["deliveries"]["days"], cov["deliveries"]["until"]
    sources.append(
        {**source("Deliveries", "Normal deliveries", list(days), until, stopped(until)), "rows": sum(days.values())}
    )
    answered, until = [at for at, _caller in _calls()["answered"]], cov["calls"]["until"]
    sources.append(source("Calls", "Answered incoming calls", answered, until, stopped(until)))

    exclusions = frappe.get_all(
        "HD AI Exclusion",
        filters={"active": 1},
        fields=["name", "exclusion_type", "value", "reason", "owner", "creation"],
        order_by="creation desc",
    )
    tagged = [x for x in contacts if x.status == "Tagged" and x.live]
    issues = [i for x in tagged for i in x.issues]
    kept = [i for i in issues if i.review != "Rejected"]
    confirmed = {r["contact"] for r in counted_rows() if r["is_food_safety"]}
    rule_hits = defaultdict(set)
    for x in contacts:
        if x.status != "Excluded" and x.live:
            for h in x.hits:
                rule_hits[h["rule"]].add(x.name)
    stale = tagging.stale_count()
    version = tagging.current_version()
    score = _evaluation()
    total, unspecified = frappe.db.sql(
        "select count(*), sum(ticket_type = 'Unspecified') from `tabHD Ticket` where is_merged = 0"
    )[0]
    return _js(
        {
            "sources": sources,
            "capture_notices": _capture_notices(),
            "exclusions": {
                "rules": {"start_date": c.start_date, "exclude_staff_phones": c.exclude_staff_phones},
                "rows": [
                    {
                        "name": e.name,
                        "type": e.exclusion_type,
                        "value": _exclusion_value(e.exclusion_type, e.value, decider),
                        "reason": e.reason,
                        "owner": get_fullname(e.owner),
                        "creation": e.creation,
                    }
                    for e in exclusions
                ],
                "by_reason": dict(
                    Counter(x.exclusion_reason or "Excluded" for x in contacts if x.status == "Excluded")
                ),
            },
            "suggested": cases.suggest_exclusions() if decider else [],
            "new_queue": _new_queue(counted_rows(), mask),
            "registry": [
                {
                    k: m.get(k)
                    for k in (
                        "code",
                        "label",
                        "kind",
                        "family",
                        "owner_department",
                        "severity_floor",
                        "is_food_safety",
                        "status",
                        "merged_into",
                        "target",
                        "definition",
                    )
                }
                for m in sorted(meta.values(), key=lambda m: (m.family or "", m.code))
            ],
            "version": {
                "current": version,
                "stale": stale,
                "estimate_usd": round(stale * USD_PER_CONTACT, 2),
                "estimate_hours": round(stale * SECONDS_PER_CONTACT / 3600, 1),
                "budget_left": jobs.budget_left(),
            },
            "quality": {
                "quote_status": dict(Counter(i.quote_status or "Unverified" for i in issues)),
                "wrong_label_rate": round(
                    sum(1 for i in issues if i.review in ("Flagged", "Rejected")) / len(issues), 3
                )
                if issues
                else None,
                "new_share": round(sum(1 for i in kept if i.code == "NEW") / len(kept), 3) if kept else None,
                "failed": sum(1 for x in contacts if x.status == "Failed"),
                "safety_rules": [
                    {"rule": rule, "hits": len(names), "confirmed": len(names & confirmed)}
                    for rule, names in sorted(rule_hits.items())
                ],
            },
            "gold": {
                "sampled": frappe.db.count("HD AI Gold Label"),
                "labelled": frappe.db.count("HD AI Gold Label", {"is_final": 1}),
                "kappa": (score or {}).get("kappa"),
                "score": score,
            },
            "spend": {"month_usd": jobs.spend_month(), "budget_usd": c.budget_usd},
            "models": {
                "tagging": c.model,
                "council": c.council_models,
                "chairman": c.chairman_model,
                "research": c.research_model,
                "prompt_version": version,
            },
            "hygiene": {
                "tickets": cint(total),
                "unspecified": cint(unspecified),
                "unspecified_share": round(cint(unspecified) / total, 3) if total else None,
                "ignored_fields": list(cases.POLLUTED_TICKET_FIELDS),
            },
        }
    )
