"""AI Analysis contacts: every HD Ticket (with its comments and the chat folded into it) and every chat
session becomes one de-identified HD AI Contact.

Lines are rebuilt from the sources whenever they are needed (lines_for) and never stored; only their
hash is. Every source is read with SQL: nothing here writes HD Ticket, its comments or Messenger rows.
"""

import hashlib
import hmac
import json
import re
from collections import defaultdict
from datetime import timedelta

import frappe
from frappe import _
from frappe.utils import add_months, get_datetime, getdate, now_datetime
from frappe.utils.password import get_encryption_key

from helpdesk.ai_analysis import conf, safety, text
from helpdesk.api.complaints import _strip_html

# Auto-filled with their first option on almost every ticket (the options have no blank), so they
# carry no signal. Never selected anywhere in this module; test_cases checks the queries.
POLLUTED_TICKET_FIELDS = (
    "custom_select_type",
    "custom_select_channel",
    "custom_select_source",
    "custom_complaint_status",
    "custom_cs_complaints",
    "custom_dish_complaint",
    "custom_packaging",
    "custom_application",
    "custom_customer_request",
    "custom_customer_feedback",
    "custom_follow_up_status",
    "custom_account_status",
)

SESSION_GAP = timedelta(hours=12)
FOLD_BEFORE, FOLD_AFTER = timedelta(hours=24), timedelta(hours=72)
LINE_CAP, CONTACT_CAP = 600, 6000
COMMENTS_PER_TICKET, COMMENT_CHARS = 10, 2000
REPLY_SHARE = 0.05
BOT_OWNERS = ("Administrator", "Guest")
DM_CHANNEL = {"WhatsApp": "WhatsApp", "Instagram": "Instagram DM", "Messenger": "Messenger"}
MESSAGE_FLAGS = (
    "is_private",
    "is_auto_reply",
    "is_auto_generated_outgoing_message",
    "template_name",
    "message_type",
    "is_external_message",
    "is_instagram_comment",
    "is_facebook_comment",
)
ROW_FIELDS = (
    "source_key",
    "source",
    "ticket",
    "conversation",
    "session_start",
    "channel",
    "started_on",
    "ended_on",
    "customer_key",
    "language",
    "msg_count",
    "in_count",
    "has_text",
    "text_hash",
    "replies_captured",
    "folded",
    "safety_hits",
)

# Their text is coordinates and a maps link, or a name and a phone: always just the placeholder.
FORCED = {"location": "[Shared location]", "contact": "[Shared contact]"}
MEDIA = {kind: f"[{kind}]" for kind in ("image", "video", "audio", "file", "document", "sticker")}
# What the webhook writes when the customer sent no caption; kept, they would pass for customer text.
DEFAULT_CAPTIONS = {
    "image message",
    "video message",
    "audio message",
    "voice note",
    "voice message",
    "file message",
    "document message",
    "sticker message",
    "mentioned you in a story",
    "follow_up_message",
}
FILE_NAME = re.compile(
    r"/(?:private/)?files/\S+"
    r"|[^/\n]{1,150}\.(?:png|jpe?g|gif|webp|heic|pdf|docx?|xlsx?|csv|txt|mp4|mov|3gp|ogg|opus|mp3|m4a|aac|wav|amr)",
    re.I,
)
PLACEHOLDER = re.compile(r"\[[^\[\]\n]{1,40}\]|@user")
# MSG-CONV-{sender_name}-#####, e.g. a greeting template that rendered the conversation name as the customer's
CONV_NAME = re.compile(r"MSG-CONV-[^\n]{0,80}?-\d+|MSG-CONV-\S*")
_NOT_LETTER = re.compile(r"[\W_\d]+")
_TEST_WORD = re.compile(r"(?<![a-z])(?:test|dummy|sample|lorem|asdf|qwerty)", re.I)
_CONSONANTS = re.compile(r"[b-df-hj-np-tv-xz]+")


# --- keys and names ----------------------------------------------------------------------


def customer_key(identity: str) -> str:
    """First 16 hex chars of HMAC-SHA256 over "p:<last8>" | "ig:<id>" | "fb:<id>" | "c:<contact>"."""
    return hmac.new(get_encryption_key().encode(), identity.encode(), hashlib.sha256).hexdigest()[:16]


def staff_keys() -> set[str]:
    """customer_key of every staff phone: Employee mobile fields and System User mobile_no."""
    phones = []
    if frappe.db.table_exists("Employee"):
        for col in frappe.db.get_table_columns("Employee"):
            if col == "cell_number" or col.endswith("mobile_no"):
                phones += frappe.db.sql(
                    f"select `{col}` from `tabEmployee` where ifnull(`{col}`, '') != ''", pluck=True
                )
    phones += frappe.db.sql(
        "select mobile_no from `tabUser` where user_type = 'System User' and ifnull(mobile_no, '') != ''", pluck=True
    )
    return {customer_key(f"p:{p8}") for p in phones if (p8 := text.last8(p))}


def known_names() -> set[str]:
    """Name tokens of staff: Agent / Agent Manager users, drivers and employees."""
    names = frappe.db.sql(
        """select distinct u.full_name from `tabUser` u
        join `tabHas Role` r on r.parent = u.name and r.parenttype = 'User'
        where r.role in ('Agent', 'Agent Manager')""",
        pluck=True,
    )
    for doctype, col in (("Driver", "full_name"), ("Employee", "employee_name")):
        if frappe.db.table_exists(doctype):
            names += frappe.db.sql(f"select `{col}` from `tab{doctype}`", pluck=True)
    return text.name_tokens(names)


def text_hash(lines) -> str:
    return hashlib.sha1(
        json.dumps(lines, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _sha1(s: str) -> str:
    return hashlib.sha1(s.encode()).hexdigest()


def _person(*values) -> set[str]:
    """Name tokens of a person, also with handles split ("fatima_k92" -> "fatima")."""
    values = [str(v) for v in values if v]
    return text.name_tokens(values + [_NOT_LETTER.sub(" ", v) for v in values])


# --- message rules -----------------------------------------------------------------------


def _platform(conversation) -> str:
    platform = (conversation.get("platform") or "").strip()
    return platform if platform in ("WhatsApp", "Instagram") else "Messenger"  # blank, Messenger, Facebook


def _role(m) -> str:
    if m.get("message_direction") == "Incoming":
        return "customer"
    bot = (
        m.get("is_auto_reply")
        or m.get("is_auto_generated_outgoing_message")
        or m.get("template_name")
        or m.get("message_type") == "Template"
        or m.get("is_external_message")
        or m.get("owner") in BOT_OWNERS
    )
    return "bot" if bot else "agent"


def _message_text(m) -> str | None:
    """A message as line text, or None when it says nothing (reactions, empty texts)."""
    kind = (m.get("content_type") or "text").strip().lower()
    body = " ".join((m.get("message") or "").split())
    if kind == "reaction":
        return None
    if kind == "text":
        return body or None
    if kind in FORCED:
        return FORCED[kind]
    if kind in MEDIA:
        caption = "" if body.casefold() in DEFAULT_CAPTIONS or FILE_NAME.fullmatch(body) else body
        return f"{MEDIA[kind]} {caption}".rstrip()
    return f"[unsupported] {body}".rstrip()  # unsupported, unsupport, button, flow, link and any new type


def _is_card(note: str) -> bool:
    """CRM transcript cards ("📱 Conversation from CRM: … | Messages: n") and stub comments ("<name> -
    Conversation: MSG-CONV-… Total messages: n"), on stripped text: the chat itself is folded in from
    the messages."""
    return "Conversation from CRM" in note or "Conversation: MSG-CONV-" in note


def _chars(s: str) -> int:
    """Letters and digits outside placeholders: "Hi" is 2, "[image]" and emoji are 0."""
    return sum(ch.isalnum() for ch in PLACEHOLDER.sub(" ", s))


# --- assemble (pure) ---------------------------------------------------------------------


def assemble(tickets, comments, links, conversations, messages, *, names=frozenset()) -> list[dict]:
    """Source rows (dicts) in, contact drafts out; no database access.

    `names` are staff name tokens (known_names()); each contact also scrubs its own customer's names.
    Lines come back scrubbed and capped, so has_text, language and text_hash describe exactly what
    the tagger sees. links = Messenger Conversation Tickets rows {"conversation", "ticket"}.
    """
    names = frozenset(names)
    tickets = [{**t, "name": str(t["name"])} for t in tickets]  # HD Ticket names are integers, Link values strings
    tix = {t["name"]: t for t in tickets}
    convs = {c["name"]: c for c in conversations}
    created = {t["name"]: get_datetime(t["creation"]) for t in tickets}
    window = {
        n: (
            created[n] - FOLD_BEFORE,
            max(created[n], get_datetime(t["resolution_date"]) if t.get("resolution_date") else created[n])
            + FOLD_AFTER,
        )
        for n, t in tix.items()
    }

    # ticket <-> conversation, the ticket's own custom_messenger_conversation first
    t_convs, c_tix = defaultdict(list), defaultdict(list)
    pairs = [(t["name"], t.get("custom_messenger_conversation")) for t in tickets]
    pairs += sorted((str(link.get("ticket") or ""), link.get("conversation") or "") for link in links)
    for t, c in pairs:
        if c and t in tix and c not in t_convs[t]:
            t_convs[t].append(c)
            c_tix[c].append(t)

    # a ticket and its chats are one customer: each side also scrubs the other's names
    own = {n: _person(t.get("custom_customer_name"), t.get("contact"), t.get("contact_name")) for n, t in tix.items()}
    sender = {c: _person(cv.get("sender_name")) for c, cv in convs.items()}
    t_names = {n: own[n].union(*(sender.get(c, ()) for c in t_convs[n])) for n in tix}
    c_names = {c: sender[c].union(*(own[n] for n in c_tix.get(c, ()))) for c in convs}

    # "Platform:YYYY-MM" -> [customer messages, agent replies]
    # ponytail: counts every chat, staff tests included, so a test-heavy platform-month can look captured;
    # count after exclusions if that misleads the tagger
    replies = defaultdict(lambda: [0, 0])
    streams = defaultdict(list)
    for m in messages:
        cv = convs.get(m.get("conversation"))
        body = _message_text(m) if cv and not m.get("is_private") else None
        if not body:
            continue
        at, role, platform = get_datetime(m.get("timestamp") or m.get("creation")), _role(m), _platform(cv)
        if role != "bot":
            replies[f"{platform}:{at:%Y-%m}"][role == "agent"] += 1
        if m.get("is_instagram_comment"):
            channel = "Instagram comment"
        elif m.get("is_facebook_comment"):
            channel = "Facebook comment"
        else:
            channel = DM_CHANNEL[platform]
        streams[(cv["name"], channel)].append({"k": (at, m.get("name") or ""), "role": role, "raw": body})

    # sessions: per conversation and stream (DMs, Instagram comments, Facebook comments), split at 12 h gaps
    sessions = []
    for (conv, channel), rows in sorted(streams.items()):
        rows.sort(key=lambda x: x["k"])
        for x in rows:
            s = sessions[-1] if sessions else None
            if not s or (s["conversation"], s["channel"]) != (conv, channel) or x["k"][0] - s["end"] >= SESSION_GAP:
                s = {"conversation": conv, "channel": channel, "start": x["k"][0], "msgs": []}
                sessions.append(s)
            s["end"] = x["k"][0]
            s["msgs"].append(x)

    def nearest(candidates, at):
        return min(candidates, key=lambda n: (abs(created[n] - at), n))

    # folding: a session overlapping [creation - 24 h, (resolution or creation) + 72 h] of a linked ticket
    # joins the nearest such ticket; the rest stay chat contacts under the nearest linked ticket's identity
    folded, chats = defaultdict(list), []
    for s in sessions:
        linked = c_tix.get(s["conversation"], [])
        fits = [n for n in linked if s["start"] <= window[n][1] and s["end"] >= window[n][0]]
        if fits:
            folded[nearest(fits, s["start"])].append(s)
        else:
            s["ticket"] = nearest(linked, s["start"]) if linked else None
            chats.append(s)

    def conv_identity(c):
        cv = convs.get(c) or {}
        sid = str(cv.get("sender_id") or "").strip()
        if not sid:
            return None
        if _platform(cv) == "WhatsApp":
            return f"p:{p8}" if (p8 := text.last8(sid)) else None
        return f"{'ig' if _platform(cv) == 'Instagram' else 'fb'}:{sid}"

    def ticket_identity(n):
        if p8 := text.last8(tix[n].get("custom_customer_phone")):
            return f"p:{p8}"
        ids = [i for c in t_convs[n] if (i := conv_identity(c))]
        for prefix in ("p:", "ig:", "fb:"):
            if found := next((i for i in ids if i.startswith(prefix)), None):
                return found
        return f"c:{tix[n]['contact']}" if tix[n].get("contact") else None

    def captured(platform_month):
        incoming, out = replies.get(platform_month, (0, 0))
        return bool(incoming or out) and out >= REPLY_SHARE * incoming

    def clean(raw, scrub):
        return text.scrub(CONV_NAME.sub("[name]", raw), scrub)[:LINE_CAP]

    t_comments = defaultdict(list)
    for c in comments:
        ticket = str(c.get("reference_ticket"))
        note = _strip_html(c.get("content")) if ticket in tix else ""
        if note and not _is_card(note):
            t_comments[ticket].append((get_datetime(c["creation"]), c.get("name") or "", note))

    drafts = []
    for t in tickets:
        n = t["name"]
        scrub = names | t_names[n]
        subject = " ".join((t.get("subject") or "").split())
        desc = _strip_html(t.get("description"))
        head = [
            {"role": "ticket", "text": clean(raw, scrub)} for raw in [subject, desc if desc != subject else ""] if raw
        ]
        body, budget = [], COMMENT_CHARS
        for at, cname, note in sorted(t_comments[n], reverse=True)[:COMMENTS_PER_TICKET]:  # newest 10, <= 2k chars
            line = clean(note, scrub)[:budget]
            if not line:
                break
            budget -= len(line)
            body.append({"k": (at, cname), "role": "staff", "text": line})
        sess = sorted(folded[n], key=lambda s: s["start"])
        body += [{"k": x["k"], "role": x["role"], "text": clean(x["raw"], scrub)} for s in sess for x in s["msgs"]]
        times = [created[n]] + [x["k"][0] for x in body]
        platform_month = f"{_platform(convs[sess[0]['conversation']])}:{min(times):%Y-%m}" if sess else None
        drafts.append(
            _finish(head, body, is_ticket=True)
            | {
                "source_key": _sha1(f"T:{n}"),
                "source": "Ticket",
                "ticket": n,
                "conversation": t_convs[n][0] if t_convs[n] else None,
                "session_start": None,
                "channel": "Ticket",
                "started_on": min(times),
                "ended_on": max(times),
                "identity": ticket_identity(n),
                "folded": len(sess),
                "platform_month": platform_month,
                "replies_captured": captured(platform_month),
            }
        )

    seen = set()
    for s in chats:
        conv = s["conversation"]
        scrub = names | c_names[conv]
        body = [{"k": x["k"], "role": x["role"], "text": clean(x["raw"], scrub)} for x in s["msgs"]]
        key = f"C:{conv}|{s['start'].isoformat()}"
        if key in seen:  # a DM and a comment that start in the same instant
            key += f"|{s['channel']}"
        seen.add(key)
        platform_month = f"{_platform(convs[conv])}:{s['start']:%Y-%m}"
        drafts.append(
            _finish([], body, is_ticket=False)
            | {
                "source_key": _sha1(key),
                "source": "Chat",
                "ticket": None,
                "conversation": conv,
                "session_start": s["start"],
                "channel": s["channel"],
                "started_on": s["start"],
                "ended_on": s["end"],
                "identity": (s["ticket"] and ticket_identity(s["ticket"])) or conv_identity(conv),
                "folded": 0,
                "platform_month": platform_month,
                "replies_captured": captured(platform_month),
            }
        )
    return drafts


def _finish(head, body, is_ticket) -> dict:
    """Caps (bot lines go first, then the oldest agent lines, then the oldest customer lines; ticket and
    staff lines are bounded and kept), ids L1..Ln with ticket lines first, and the text-derived fields."""
    body.sort(key=lambda x: x["k"])
    every = head + body
    total = sum(len(x["text"]) for x in every)
    for role in ("bot", "agent", "customer"):
        for x in body:
            if total <= CONTACT_CAP:
                break
            if x["role"] == role:
                x["drop"] = True
                total -= len(x["text"])
    kept = (x for x in every if not x.get("drop"))
    lines = [{"id": f"L{i}", "role": x["role"], "text": x["text"]} for i, x in enumerate(kept, 1)]
    said = [x["text"] for x in lines if x["role"] == "customer"]
    notes = " ".join(x["text"] for x in lines if x["role"] in ("ticket", "staff"))
    return {
        "lines": lines,
        "msg_count": len(every),
        "in_count": sum(x["role"] == "customer" for x in every),
        "has_text": any(_chars(s) >= 3 for s in said) or (is_ticket and _chars(notes) >= 10),
        "language": text.language(said or [notes]),
        "safety_hits": safety.match("\n".join(x["text"] for x in every if x["role"] in text.QUOTABLE)),
        "text_hash": text_hash(lines),
    }


# --- sources (read-only SQL) -------------------------------------------------------------


def _optional(doctype, alias, fields) -> str:
    return ", ".join(f"{alias}.`{f}`" if frappe.db.has_column(doctype, f) else f"null as `{f}`" for f in fields)


def _tickets() -> list[dict]:
    custom = _optional(
        "HD Ticket", "t", ("custom_messenger_conversation", "custom_customer_phone", "custom_customer_name")
    )
    return frappe.db.sql(
        f"""select t.name, t.creation, t.subject, t.description, t.resolution_date, t.contact,
            c.full_name as contact_name, {custom}
        from `tabHD Ticket` t left join `tabContact` c on c.name = t.contact
        where ifnull(t.is_merged, 0) = 0
        order by t.creation, t.name""",
        as_dict=True,
    )


def _comments() -> list[dict]:
    return frappe.db.sql(
        """select c.name, c.reference_ticket, c.creation, c.content
        from `tabHD Ticket Comment` c join `tabHD Ticket` t on t.name = c.reference_ticket
        where ifnull(t.is_merged, 0) = 0
        order by c.reference_ticket, c.creation, c.name""",
        as_dict=True,
    )


def _links() -> list[dict]:
    if not frappe.db.table_exists("Messenger Conversation Tickets"):
        return []
    return frappe.db.sql(
        """select parent as conversation, hd_ticket as ticket from `tabMessenger Conversation Tickets`
        where parenttype = 'Messenger Conversation' and ifnull(hd_ticket, '') != ''
        order by parent, idx""",
        as_dict=True,
    )


def _conversations() -> list[dict]:
    if not frappe.db.table_exists("Messenger Conversation"):
        return []
    return frappe.db.sql(
        "select name, platform, sender_id, sender_name from `tabMessenger Conversation` order by name", as_dict=True
    )


def _messages() -> list[dict]:
    if not (frappe.db.table_exists("Messenger Message") and frappe.db.table_exists("Messenger Conversation")):
        return []
    return frappe.db.sql(
        f"""select m.name, m.conversation, m.`timestamp`, m.creation, m.message_direction, m.owner, m.message,
            m.content_type, {_optional("Messenger Message", "m", MESSAGE_FLAGS)}
        from `tabMessenger Message` m join `tabMessenger Conversation` c on c.name = m.conversation
        order by m.conversation, m.`timestamp`, m.name""",
        as_dict=True,
    )


def _load():
    return _tickets(), _comments(), _links(), _conversations(), _messages()


def _pairs() -> list[tuple[str, str]]:
    """Every (ticket, conversation) link: the ticket's own field plus Messenger Conversation Tickets."""
    pairs = []
    if frappe.db.has_column("HD Ticket", "custom_messenger_conversation"):
        pairs += frappe.db.sql(
            """select name, custom_messenger_conversation from `tabHD Ticket`
            where ifnull(custom_messenger_conversation, '') != '' and ifnull(is_merged, 0) = 0"""
        )
    return [(str(t), c) for t, c in pairs] + [(str(link.ticket), link.conversation) for link in _links()]


# --- build -------------------------------------------------------------------------------


def _row(draft) -> dict:
    row = {f: draft.get(f) for f in ROW_FIELDS}
    row.update(
        customer_key=customer_key(draft["identity"]) if draft["identity"] else None,
        has_text=int(draft["has_text"]),
        replies_captured=int(draft["replies_captured"]),
        safety_hits=json.dumps(draft["safety_hits"], ensure_ascii=False) if draft["safety_hits"] else None,
    )
    return row


def _same(old, new) -> bool:
    if isinstance(new, int):
        return int(old or 0) == new
    return (old or None) == (new or None)


def _next_status(old, row) -> str:
    if old.status == "Excluded":
        return old.status  # apply_exclusions decides
    if not row["has_text"]:
        return "No text"
    if old.status == "No text" or old.text_hash != row["text_hash"]:
        return "Pending"
    return old.status


def _delete_issues(names):
    if names:
        frappe.db.delete("HD AI Contact Issue", {"parenttype": "HD AI Contact", "parent": ("in", list(names))})


def build_contacts() -> dict:
    """Rebuild every contact from the sources and upsert by source_key, then apply exclusions.

    New rows start Pending (or No text); a changed text_hash goes back to Pending; contacts whose
    source vanished, was merged or passed the retention horizon are deleted with their issue rows.
    No commit: callers commit.
    """
    # ponytail: rebuilds every source on each run (seconds at ~3k contacts); load incrementally by
    # modified when the message table reaches the hundreds of thousands
    cutoff = add_months(now_datetime(), -conf().retention_months)
    drafts = assemble(*_load(), names=known_names())
    rows = {d["source_key"]: _row(d) for d in drafts if d["started_on"] >= cutoff}
    fields = ", ".join(f"`{f}`" for f in ROW_FIELDS)
    old = {
        r.source_key: r for r in frappe.db.sql(f"select name, status, {fields} from `tabHD AI Contact`", as_dict=True)
    }

    now, user = now_datetime(), frappe.session.user
    fresh, changed, emptied = [], 0, []
    for key, row in rows.items():
        o = old.get(key)
        if not o:
            status = "Pending" if row["has_text"] else "No text"
            fresh.append((frappe.generate_hash(length=10), now, now, user, user, status, *(row[f] for f in ROW_FIELDS)))
            continue
        values = {f: v for f, v in row.items() if not _same(o[f], v)}
        status = _next_status(o, row)
        if status != o.status:
            values["status"] = status
            if status == "Pending":
                values.update(attempts=0, error=None)
            elif status == "No text":
                emptied.append(o.name)
        if values:
            frappe.db.set_value("HD AI Contact", o.name, values)
            changed += 1
    if fresh:
        frappe.db.bulk_insert(
            "HD AI Contact",
            ["name", "creation", "modified", "owner", "modified_by", "status", *ROW_FIELDS],
            fresh,
            ignore_duplicates=True,  # two builds at once: the second skips what the first inserted
        )
    gone = [o.name for key, o in old.items() if key not in rows]
    _delete_issues(gone + emptied)
    if gone:
        frappe.db.delete("HD AI Contact", {"name": ("in", gone)})
    exclusions_changed = apply_exclusions()
    return {
        "contacts": len(rows),
        "new": len(fresh),
        "changed": changed,
        "deleted": len(gone),
        "excluded": frappe.db.count("HD AI Contact", {"status": "Excluded"}),
        "exclusions_changed": exclusions_changed,
    }


def apply_exclusions(names: list[str] | None = None) -> int:
    """Recompute Excluded from the rules, first match wins: before the start date, a staff phone, then
    an active HD AI Exclusion (Ticket, Conversation or a ticket linked to it, Phone, Contact).

    Newly excluded contacts lose their issue rows; excluded contacts that no longer match go back to
    Pending (or No text). SQL on our own table only; `names` limits it to those contacts. Returns how
    many contacts changed.
    """
    if names is not None and not names:
        return 0
    c = conf()
    where = "where name in %(names)s" if names is not None else ""
    rows = frappe.db.sql(
        f"""select name, ticket, conversation, customer_key, started_on, status, has_text, exclusion_reason
        from `tabHD AI Contact` {where}""",
        {"names": tuple(names or ())},
        as_dict=True,
    )
    staff = staff_keys() if c.exclude_staff_phones else set()
    rules = {kind: {} for kind in ("Ticket", "Conversation", "Phone", "Contact")}
    for e in frappe.get_all(
        "HD AI Exclusion", filters={"active": 1}, fields=["exclusion_type", "value", "reason"], order_by="creation asc"
    ):
        if e.exclusion_type in rules and e.value:
            value = customer_key(f"p:{e.value}") if e.exclusion_type == "Phone" else e.value
            rules[e.exclusion_type].setdefault(value, ("Excluded: " + " ".join((e.reason or "").split()))[:140])
    linked = {}
    if rules["Conversation"]:
        for ticket, conv in _pairs():
            if conv in rules["Conversation"]:
                linked.setdefault(ticket, rules["Conversation"][conv])

    def reason(r):
        if c.start_date and r.started_on and getdate(r.started_on) < c.start_date:
            return "Before start date"
        if r.customer_key in staff:
            return "Staff phone"
        return (
            rules["Ticket"].get(r.ticket)
            or rules["Conversation"].get(r.conversation)
            or linked.get(r.ticket)
            or rules["Phone"].get(r.customer_key)
            or rules["Contact"].get(r.name)
        )

    groups = defaultdict(list)
    for r in rows:
        why = reason(r)
        if why:
            want = ("Excluded", why)
        elif r.status == "Excluded":
            want = ("Pending" if r.has_text else "No text", None)
        else:
            continue
        if want != (r.status, r.exclusion_reason or None):
            groups[want].append(r.name)

    now = now_datetime()
    for (status, why), group in groups.items():
        reset = "claim_token = null, claimed_at = null" if status == "Excluded" else "attempts = 0, error = null"
        frappe.db.sql(
            f"""update `tabHD AI Contact`
            set status = %(status)s, exclusion_reason = %(why)s, modified = %(now)s, {reset}
            where name in %(names)s""",
            {"status": status, "why": why, "now": now, "names": tuple(group)},
        )
        if status == "Excluded":
            _delete_issues(group)
    return sum(len(group) for group in groups.values())


def lines_for(names: list[str]) -> dict[str, list[dict]]:
    """The scrubbed lines of these contacts, rebuilt from the sources (never stored). A contact whose
    source vanished is left out; compare text_hash(lines) with the stored hash before tagging."""
    if not names:
        return {}
    keys = dict(
        frappe.db.sql("select name, source_key from `tabHD AI Contact` where name in %(n)s", {"n": tuple(names)})
    )
    # ponytail: assembles every source per call (about a second at ~3k contacts); load only these
    # contacts' tickets and conversations (plus the tickets linked to them) when chunks get slow
    lines = {d["source_key"]: d["lines"] for d in assemble(*_load(), names=known_names())}
    return {name: lines[key] for name, key in keys.items() if key in lines}


# --- decider tools -----------------------------------------------------------------------


def _junk(subject) -> bool:
    """Test or keyboard-mash subjects: "test 3", "j", "jj", "nn", a bare number."""
    s = text.normalize(subject)
    return (
        sum(ch.isalpha() for ch in s) < 2
        or bool(_TEST_WORD.search(s))
        or all(_CONSONANTS.fullmatch(w) for w in s.split())
    )


def suggest_exclusions() -> list[dict]:
    """Likely test data among contacts that are not excluded, for a decider to confirm with a reason;
    nothing is applied here.

    Returns [{"type", "value", "label", "reason_hint", "contacts"}]. `value` is what add_exclusion takes
    (a ticket, conversation or contact name: decider-only data); `label` names no customer.
    """
    live = frappe.db.sql(
        """select name, ticket, conversation, channel, started_on, in_count, looks_like_test
        from `tabHD AI Contact` where status != 'Excluded'""",
        as_dict=True,
    )
    if not live:
        return []
    tickets = {str(t.name): t for t in _tickets()}
    convs = {c.name: c for c in _conversations()}
    by_ticket = {r.ticket: r for r in live if r.ticket}
    conv_contacts, conv_tickets, ticket_convs = defaultdict(set), defaultdict(set), defaultdict(set)
    for r in live:
        if r.conversation:
            conv_contacts[r.conversation].add(r.name)
    for ticket, conv in _pairs():
        conv_tickets[conv].add(ticket)
        ticket_convs[ticket].add(conv)
        if ticket in by_ticket:
            conv_contacts[conv].add(by_ticket[ticket].name)

    found = {}

    def add(kind, value, prefix, why, hint, contacts):
        entry = found.setdefault((kind, value), {"prefix": prefix, "why": [], "hint": hint, "contacts": len(contacts)})
        entry["why"].append(why)

    for conv, contacts in conv_contacts.items():
        cv = convs.get(conv)
        if cv and (_TEST_WORD.search(conv) or _TEST_WORD.search(cv.sender_name or "")):
            add("Conversation", conv, f"{_platform(cv)} chat", "test-like name", "Test conversation", contacts)
        if cv and len(conv_tickets[conv]) >= 10:
            add(
                "Conversation",
                conv,
                f"{_platform(cv)} chat",
                f"linked to {len(conv_tickets[conv])} tickets",
                "Test conversation",
                contacts,
            )
    for ticket, r in by_ticket.items():
        t = tickets.get(ticket)
        if not t:
            continue
        prefix = f"Ticket {ticket}"
        if _junk(t.subject):
            add("Ticket", ticket, prefix, "junk subject", "Test ticket", {r.name})
        if not r.in_count and len(_strip_html(t.description)) < 10:  # no chat, or a chat the customer never wrote in
            add(
                "Ticket",
                ticket,
                prefix,
                "description under 10 characters and no customer chat",
                "Test ticket",
                {r.name},
            )
        if any(conv not in convs for conv in ticket_convs[ticket]):
            add("Ticket", ticket, prefix, "its linked chat no longer exists", "Test ticket", {r.name})
    for r in live:
        if not r.looks_like_test:
            continue
        if r.ticket:
            add("Ticket", r.ticket, f"Ticket {r.ticket}", "the AI flagged it as a test", "Test ticket", {r.name})
        else:
            add(
                "Contact",
                r.name,
                f"{r.channel} chat, {r.started_on:%b %Y}",
                "the AI flagged it as a test",
                "Test chat",
                {r.name},
            )

    out = [
        {
            "type": kind,
            "value": value,
            "label": f"{e['prefix']}: {'; '.join(e['why'])}",
            "reason_hint": e["hint"],
            "contacts": e["contacts"],
        }
        for (kind, value), e in found.items()
    ]
    return sorted(out, key=lambda e: (-e["contacts"], e["type"], e["label"]))


def purge_customer(phone: str, reference: str) -> dict:
    """Erasure request: delete this customer's contacts, their issue rows and gold labels, blank the AI
    packs that cite them, and add an active Phone exclusion so rebuilt contacts stay Excluded.

    Rows are found through the source records (phone -> tickets and WhatsApp chats, then the tickets
    and chats linked to those), not by recomputing customer_key, which changes when a site is restored
    with another encryption key. No commit: callers commit.
    """
    p8 = text.last8(phone)
    reference = " ".join((reference or "").split())
    if not p8 or not reference:
        frappe.throw(_("Give a phone number with at least 8 digits and the erasure request reference."))
    tickets = {str(t.name) for t in _tickets() if text.last8(t.custom_customer_phone) == p8}
    convs = {c.name for c in _conversations() if _platform(c) == "WhatsApp" and text.last8(c.sender_id) == p8}
    pairs = _pairs()
    while True:  # a ticket and its chats are one customer, both ways
        more_tickets = {t for t, c in pairs if c in convs} - tickets
        more_convs = {c for t, c in pairs if t in tickets} - convs
        if not (more_tickets or more_convs):
            break
        tickets |= more_tickets
        convs |= more_convs

    names = []
    if tickets or convs:
        names = frappe.db.sql(
            "select name from `tabHD AI Contact` where ticket in %(t)s or conversation in %(c)s",
            {"t": tuple(tickets) or ("",), "c": tuple(convs) or ("",)},
            pluck=True,
        )
    gold = insights = 0
    if names:
        _delete_issues(names)
        if frappe.db.table_exists("HD AI Gold Label"):
            gold = frappe.db.count("HD AI Gold Label", {"contact": ("in", names)})
            frappe.db.delete("HD AI Gold Label", {"contact": ("in", names)})
        frappe.db.delete("HD AI Contact", {"name": ("in", names)})
        if frappe.db.table_exists("HD AI Insight"):
            for ins in frappe.get_all("HD AI Insight", fields=["name", "input_json", "alias_map", "output_json"]):
                blob = " ".join(filter(None, (ins.input_json, ins.alias_map, ins.output_json)))
                if any(name in blob for name in names):
                    frappe.db.set_value(
                        "HD AI Insight", ins.name, {"input_json": None, "alias_map": None, "output_json": None}
                    )
                    insights += 1

    exclusion = frappe.db.get_value("HD AI Exclusion", {"exclusion_type": "Phone", "value": p8, "active": 1})
    if not exclusion:
        exclusion = (
            frappe.get_doc(
                {
                    "doctype": "HD AI Exclusion",
                    "exclusion_type": "Phone",
                    "value": p8,
                    "reason": f"Erasure request {reference}",
                }
            )
            .insert(ignore_permissions=True)
            .name
        )
    apply_exclusions()
    return {"contacts": len(names), "gold_labels": gold, "insights": insights, "exclusion": exclusion}
