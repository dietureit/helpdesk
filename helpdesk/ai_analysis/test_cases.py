"""Tests for the contact builder (cases.py): assemble() on dict rows; exclusions and lines_for on
HD AI Contact rows the tests create (rolled back after each test)."""

import hashlib
import itertools
from collections import Counter
from datetime import date, datetime, timedelta
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from helpdesk.ai_analysis import cases, text

T0 = datetime(2026, 4, 5, 10, 0)
SECOND, MINUTE, H, DAY = timedelta(seconds=1), timedelta(minutes=1), timedelta(hours=1), timedelta(days=1)
_ids = itertools.count(1)


def conv(name, platform="WhatsApp", sender_id="97455123456", sender_name="Fatima Alkuwari"):
    return {"name": name, "platform": platform, "sender_id": sender_id, "sender_name": sender_name}


def msg(conversation, at, message="the meal was cold", direction="Incoming", **fields):
    return {
        "name": f"msg-{next(_ids):05d}",
        "conversation": conversation,
        "timestamp": at,
        "creation": at,
        "message_direction": direction,
        "owner": "Administrator" if direction == "Incoming" else "agent@example.com",  # webhooks own incoming rows
        "message": message,
        "content_type": "text",
        **fields,
    }


def ticket(name, at, **fields):
    return {
        "name": name,
        "creation": at,
        "subject": "Wrong meal delivered",
        "description": "<p>The customer received the wrong meal.</p>",
        "resolution_date": None,
        "contact": None,
        "contact_name": None,
        "custom_messenger_conversation": None,
        "custom_customer_phone": None,
        "custom_customer_name": None,
        **fields,
    }


def build(tickets=(), comments=(), links=(), conversations=(), messages=(), names=frozenset()):
    return cases.assemble(list(tickets), list(comments), list(links), list(conversations), list(messages), names=names)


def texts(draft):
    return [line["text"] for line in draft["lines"]]


def insert_contact(**fields):
    doc = frappe.get_doc(
        {
            "doctype": "HD AI Contact",
            "source_key": frappe.generate_hash(length=24),
            "source": "Chat",
            "started_on": datetime(2026, 4, 1, 9),
            "status": "Pending",
            "has_text": 1,
            **fields,
        }
    )
    return doc.insert(ignore_permissions=True, ignore_links=True).name


class TestSessions(FrappeTestCase):
    def test_split_at_12_hours(self):
        msgs = [
            msg("C1", T0, "first"),
            msg("C1", T0 + 12 * H - SECOND, "second"),
            msg("C1", T0 + 24 * H - SECOND, "third"),
        ]
        drafts = build(conversations=[conv("C1")], messages=msgs)
        self.assertEqual(sorted(texts(d) for d in drafts), [["first", "second"], ["third"]])

    def test_comments_are_separate_sessions(self):
        ig = conv("IG1", platform="Instagram", sender_id="1789")
        fb = conv("FB1", platform="Facebook", sender_id="5550001")
        msgs = [
            msg("IG1", T0, "dm one"),
            msg("IG1", T0 + H, "nice post", is_instagram_comment=1),
            msg("IG1", T0 + 2 * H, "dm two"),
            msg("FB1", T0, "price please", is_facebook_comment=1),
            msg("FB1", T0 + H, "hello from messenger"),
        ]
        got = sorted((d["channel"], texts(d)) for d in build(conversations=[ig, fb], messages=msgs))
        self.assertEqual(
            got,
            [
                ("Facebook comment", ["price please"]),
                ("Instagram DM", ["dm one", "dm two"]),
                ("Instagram comment", ["nice post"]),
                ("Messenger", ["hello from messenger"]),
            ],
        )

    def test_source_keys(self):
        drafts = build(
            tickets=[ticket(164, T0)], conversations=[conv("C1")], messages=[msg("C1", T0 + 40 * DAY, "later")]
        )
        by_source = {d["source"]: d for d in drafts}
        self.assertEqual(by_source["Ticket"]["ticket"], "164")  # HD Ticket names come from SQL as integers
        self.assertEqual(by_source["Ticket"]["source_key"], hashlib.sha1(b"T:164").hexdigest())
        start = (T0 + 40 * DAY).isoformat()
        self.assertEqual(by_source["Chat"]["source_key"], hashlib.sha1(f"C:C1|{start}".encode()).hexdigest())
        self.assertEqual(by_source["Chat"]["session_start"], T0 + 40 * DAY)


class TestFolding(FrappeTestCase):
    def test_window_edges(self):
        tickets = [
            ticket("A", T0, custom_messenger_conversation="CA"),
            ticket("B", T0, custom_messenger_conversation="CB"),
            ticket("R", T0, resolution_date=T0 + DAY, custom_messenger_conversation="CR"),
            ticket("S", T0, resolution_date=T0 + DAY, custom_messenger_conversation="CS"),
        ]
        msgs = [
            msg("CA", T0 - 24 * H, "a on the edge"),
            msg("CB", T0 - 24 * H - SECOND, "b just outside"),
            msg("CR", T0 + DAY + 72 * H, "r on the edge"),
            msg("CS", T0 + DAY + 72 * H + SECOND, "s just outside"),
        ]
        drafts = build(tickets=tickets, conversations=[conv(c) for c in ("CA", "CB", "CR", "CS")], messages=msgs)
        folded = {d["ticket"]: d for d in drafts if d["source"] == "Ticket"}
        chats = {d["conversation"]: texts(d) for d in drafts if d["source"] == "Chat"}
        self.assertIn("a on the edge", texts(folded["A"]))
        self.assertIn("r on the edge", texts(folded["R"]))
        self.assertEqual((folded["A"]["folded"], folded["B"]["folded"]), (1, 0))
        self.assertEqual(chats, {"CB": ["b just outside"], "CS": ["s just outside"]})
        self.assertEqual(folded["A"]["started_on"], T0 - 24 * H)  # a folded chat can start the contact

    def test_nearest_ticket_wins(self):
        tickets = [ticket("X", T0, custom_messenger_conversation="CN"), ticket("Y", T0 + 48 * H)]
        links = [{"conversation": "CN", "ticket": "Y"}]
        drafts = build(
            tickets=tickets, links=links, conversations=[conv("CN")], messages=[msg("CN", T0 + 36 * H, "which one")]
        )
        by_ticket = {d["ticket"]: d for d in drafts}
        self.assertEqual(len(drafts), 2)
        self.assertEqual((by_ticket["X"]["folded"], by_ticket["Y"]["folded"]), (0, 1))
        self.assertIn("which one", texts(by_ticket["Y"]))

    def test_unfolded_sessions_take_the_ticket_identity(self):
        ig = conv("IG1", platform="Instagram", sender_id="1790")
        t = ticket("T1", T0, custom_customer_phone="+974 6600 1122", custom_messenger_conversation="IG1")
        msgs = [msg("IG1", T0 + H, "about my order"), msg("IG1", T0 + 30 * DAY, "a month later")]
        drafts = {d["source"]: d for d in build(tickets=[t], conversations=[ig], messages=msgs)}
        self.assertEqual(drafts["Ticket"]["folded"], 1)
        self.assertEqual(texts(drafts["Chat"]), ["a month later"])
        self.assertEqual(drafts["Chat"]["identity"], "p:66001122")
        self.assertEqual(drafts["Ticket"]["identity"], "p:66001122")
        self.assertIsNone(drafts["Chat"]["ticket"])

    def test_every_message_lands_in_exactly_one_contact(self):
        tickets = [ticket("T1", T0, custom_messenger_conversation="C1"), ticket("T2", T0 + 10 * DAY)]
        links = [{"conversation": "C1", "ticket": "T2"}]
        times = [T0 - 3 * DAY, T0 - 2 * H, T0 + H, T0 + 5 * DAY, T0 + 10 * DAY + H, T0 + 30 * DAY]
        msgs = [msg("C1", at, f"message number {i}") for i, at in enumerate(times)] + [msg("C2", T0, "another chat")]
        drafts = build(tickets=tickets, links=links, conversations=[conv("C1"), conv("C2")], messages=msgs)
        seen = Counter(line["text"] for d in drafts for line in d["lines"] if line["role"] == "customer")
        self.assertEqual(seen, Counter(m["message"] for m in msgs))
        self.assertEqual({d["ticket"]: d["folded"] for d in drafts if d["ticket"]}, {"T1": 1, "T2": 1})
        self.assertEqual(sum(d["source"] == "Chat" for d in drafts), 4)


class TestLines(FrappeTestCase):
    def test_roles(self):
        bots = [
            {"is_auto_reply": 1},
            {"is_auto_generated_outgoing_message": 1},
            {"template_name": "welcome"},
            {"message_type": "Template"},
            {"is_external_message": 1},
            {"owner": "Administrator"},
            {"owner": "Guest"},
        ]
        msgs = [msg("C1", T0, "customer says hello"), msg("C1", T0 + H, "agent answers", "Outgoing")]
        msgs += [msg("C1", T0 + 2 * H + i * MINUTE, f"bot line {i}", "Outgoing", **f) for i, f in enumerate(bots)]
        msgs.append(msg("C1", T0 + 3 * H, "private note", "Outgoing", is_private=1))
        [d] = build(conversations=[conv("C1")], messages=msgs)
        roles = {line["text"]: line["role"] for line in d["lines"]}
        self.assertEqual(roles.pop("customer says hello"), "customer")
        self.assertEqual(roles.pop("agent answers"), "agent")
        self.assertEqual(roles, {f"bot line {i}": "bot" for i in range(len(bots))})  # private note dropped

    def test_ticket_and_staff_lines_come_first_in_order(self):
        t = ticket(
            "T1",
            T0,
            subject="Leaking box",
            description="<p>Soup leaked in the <b>bag</b></p>",
            custom_messenger_conversation="C1",
        )
        comments = [
            {"name": "cm1", "reference_ticket": "T1", "creation": T0 + 2 * H, "content": "<p>Called the customer</p>"}
        ]
        msgs = [msg("C1", T0 - H, "my soup leaked"), msg("C1", T0 + 3 * H, "thanks")]
        [d] = build(tickets=[t], comments=comments, conversations=[conv("C1")], messages=msgs)
        self.assertEqual(
            [(line["id"], line["role"], line["text"]) for line in d["lines"]],
            [
                ("L1", "ticket", "Leaking box"),
                ("L2", "ticket", "Soup leaked in the bag"),
                ("L3", "customer", "my soup leaked"),
                ("L4", "staff", "Called the customer"),
                ("L5", "customer", "thanks"),
            ],
        )

    def test_placeholders(self):
        table = [
            (
                "location",
                '{"latitude": 25.2854, "longitude": 51.531, "url": "https://maps.google.com/?q=25.2854,51.531"}',
                "[Shared location]",
            ),
            ("contact", '[{"name": "Some Body", "phones": ["+974 5512 3456"]}]', "[Shared contact]"),
            ("image", "the lid was open", "[image] the lid was open"),
            ("image", "Image message", "[image]"),
            ("video", "Mentioned you in a story", "[video]"),
            ("audio", "Audio message", "[audio]"),
            ("file", "File message", "[file]"),
            ("document", "menu (keto).pdf", "[document]"),
            ("sticker", "", "[sticker]"),
            ("unsupported", "shared a reel", "[unsupported] shared a reel"),
            ("unsupport", "", "[unsupported]"),
            ("button", "Plans", "[unsupported] Plans"),
            ("flow", '{"label": "Very satisfied"}', '[unsupported] {"label": "Very satisfied"}'),
            ("link", "look at this", "[unsupported] look at this"),
        ]
        msgs = [msg("C1", T0 + i * MINUTE, body, content_type=kind) for i, (kind, body, _) in enumerate(table)]
        msgs += [msg("C1", T0 + H, "👍", content_type="reaction"), msg("C1", T0 + H, "   ")]
        [d] = build(conversations=[conv("C1")], messages=msgs)
        self.assertEqual(texts(d), [want for *_, want in table])

    def test_crm_cards_and_stubs_are_dropped(self):
        comments = [
            {
                "name": "c1",
                "reference_ticket": "T1",
                "creation": T0 + H,
                "content": "<div>📱 Conversation from CRM: Fatima Conversation: MSG-CONV-Fatima-00001 | Messages: 4"
                '<img src="x.png"></div>',
            },
            {
                "name": "c2",
                "reference_ticket": "T1",
                "creation": T0 + 2 * H,
                "content": "Fatima - Conversation: MSG-CONV-Fatima-00001 Total messages: 4 Fatima Hello",
            },
            {
                "name": "c3",
                "reference_ticket": "T1",
                "creation": T0 + 3 * H,
                "content": "<p>Please <b>refund</b> the meal</p>",
            },
            {"name": "c4", "reference_ticket": "T1", "creation": T0 + 4 * H, "content": "<p> </p>"},
            {
                "name": "c5",
                "reference_ticket": "T1",
                "creation": T0 + 5 * H,
                "content": "<p>see MSG-CONV-Some One-00042 first</p>",
            },
        ]
        [d] = build(tickets=[ticket("T1", T0)], comments=comments)
        staff = [line["text"] for line in d["lines"] if line["role"] == "staff"]
        self.assertEqual(staff, ["Please refund the meal", "see [name] first"])  # a mentioned chat name is stripped

    def test_newest_ten_comments_within_2k_chars(self):
        comments = [
            {
                "name": f"c{i:02d}",
                "reference_ticket": "T1",
                "creation": T0 + i * H,
                "content": f"<p>note{i:02d} {'n' * 400}</p>",
            }
            for i in range(12)
        ]
        [d] = build(tickets=[ticket("T1", T0, description="")], comments=comments)
        staff = [line["text"] for line in d["lines"] if line["role"] == "staff"]
        self.assertEqual(sum(map(len, staff)), 2000)
        self.assertEqual([s[:6] for s in staff], [f"note{i:02d}" for i in range(7, 12)])

    def test_caps_drop_bot_then_oldest_agent_then_oldest_customer(self):
        t = ticket("T1", T0, subject="Leaking box", description="", custom_messenger_conversation="C1")
        msgs = []
        for i in range(4):
            msgs.append(msg("C1", T0 + i * 10 * MINUTE, f"bot{i} {'b' * 700}", "Outgoing", is_auto_reply=1))
            msgs.append(msg("C1", T0 + i * 10 * MINUTE + MINUTE, f"agent{i} {'a' * 700}", "Outgoing"))
        msgs += [msg("C1", T0 + H + i * MINUTE, f"cust{i} {'c' * 700}") for i in range(8)]
        [d] = build(tickets=[t], conversations=[conv("C1")], messages=msgs)
        lines = d["lines"]
        self.assertLessEqual(sum(len(line["text"]) for line in lines), cases.CONTACT_CAP)
        self.assertTrue(all(len(line["text"]) <= cases.LINE_CAP for line in lines))
        self.assertEqual(lines[0], {"id": "L1", "role": "ticket", "text": "Leaking box"})
        self.assertEqual([line["id"] for line in lines], [f"L{i}" for i in range(1, len(lines) + 1)])
        self.assertEqual([line["text"].split()[0] for line in lines[1:]], ["agent3"] + [f"cust{i}" for i in range(8)])
        self.assertEqual((d["msg_count"], d["in_count"]), (17, 8))

        msgs = [msg("C2", T0 + i * MINUTE, f"cust{i} {'c' * 700}") for i in range(12)]
        [d] = build(conversations=[conv("C2")], messages=msgs)
        self.assertEqual([line["text"].split()[0] for line in d["lines"]], [f"cust{i}" for i in range(2, 12)])
        self.assertEqual(d["lines"][0]["id"], "L1")

    def test_has_text(self):
        def chat(*bodies, **fields):
            msgs = [msg("C9", T0 + i * MINUTE, b, **fields) for i, b in enumerate(bodies)]
            return build(conversations=[conv("C9")], messages=msgs)[0]["has_text"]

        self.assertFalse(chat("Hi"))
        self.assertFalse(chat("👏👏👏", "Ok"))
        self.assertTrue(chat("Hey"))
        self.assertFalse(chat("55123456"))  # scrubbed to [phone]
        self.assertFalse(chat("Image message", content_type="image"))
        self.assertFalse(chat("ok", content_type="image"))
        self.assertTrue(chat("the box leaked", content_type="image"))
        [d] = build(
            conversations=[conv("C9")],
            messages=[msg("C9", T0, "Hi"), msg("C9", T0 + MINUTE, "How can we help you today?", "Outgoing")],
        )
        self.assertFalse(d["has_text"])  # agent text never counts
        self.assertFalse(build(tickets=[ticket("T1", T0, subject="Test", description="test")])[0]["has_text"])
        self.assertTrue(build(tickets=[ticket("T1", T0, subject="Wrong meal again", description="")])[0]["has_text"])

    def test_language_and_replies_captured(self):
        wa, ig = conv("WA1"), conv("IG1", platform="Instagram", sender_id="1789")
        msgs = [msg("WA1", T0 + i * MINUTE, "الأكل وصل بارد جدا") for i in range(10)]
        msgs.append(msg("WA1", T0 + 11 * MINUTE, "sorry, we will replace it", "Outgoing"))
        msgs += [msg("IG1", T0 + i * MINUTE, "what is the price") for i in range(30)]
        msgs.append(msg("IG1", T0 + 40 * MINUTE, "auto answer", "Outgoing", is_auto_reply=1))
        drafts = {d["conversation"]: d for d in build(conversations=[wa, ig], messages=msgs)}
        self.assertEqual((drafts["WA1"]["language"], drafts["IG1"]["language"]), ("ar", "en"))
        self.assertEqual(drafts["WA1"]["platform_month"], "WhatsApp:2026-04")
        self.assertTrue(drafts["WA1"]["replies_captured"])  # 1 reply per 10 incoming
        self.assertFalse(drafts["IG1"]["replies_captured"])  # bot lines are not replies


class TestIdentity(FrappeTestCase):
    def test_identity_rules(self):
        convs = [
            conv("WA1", sender_id="+974 5512 3456"),
            conv("WA2", sender_id="97455123456"),
            conv("IG1", platform="Instagram", sender_id="1789"),
            conv("IG2", platform="Instagram", sender_id="2468"),
            conv("FB1", platform="", sender_id="5550001"),
            conv("WA3", sender_id="123"),
        ]
        tickets = [
            ticket("T1", T0, custom_customer_phone="+974 5512 3456", custom_messenger_conversation="IG1"),
            ticket("T2", T0, custom_messenger_conversation="IG1"),
            ticket("T3", T0, custom_messenger_conversation="FB1"),
            ticket("T4", T0, contact="Some Contact-1"),
            ticket("T5", T0, custom_messenger_conversation="IG2"),
        ]
        links = [{"conversation": "WA1", "ticket": "T5"}]  # a WhatsApp link beats the Instagram one
        msgs = [
            msg("WA2", T0, "unlinked whatsapp"),
            msg("WA3", T0, "short sender id"),
            msg("IG2", T0 + 40 * DAY, "much later"),
        ]
        drafts = build(tickets=tickets, links=links, conversations=convs, messages=msgs)
        ids = {d["ticket"] or d["conversation"]: d["identity"] for d in drafts}
        self.assertEqual(
            ids,
            {
                "T1": "p:55123456",
                "T2": "ig:1789",
                "T3": "fb:5550001",
                "T4": "c:Some Contact-1",
                "T5": "p:55123456",
                "WA2": "p:55123456",  # the same customer as T1 and T5
                "WA3": None,
                "IG2": "p:55123456",  # an unfolded session of T5's chat takes T5's identity
            },
        )

    def test_customer_key_is_stable_and_keyed(self):
        key = cases.customer_key("p:55123456")
        self.assertEqual(key, cases.customer_key("p:55123456"))
        self.assertRegex(key, r"^[0-9a-f]{16}$")
        self.assertNotEqual(key, cases.customer_key("ig:55123456"))
        self.assertNotEqual(key, cases.customer_key("p:55123457"))
        self.assertNotEqual(key, hashlib.sha256(b"p:55123456").hexdigest()[:16])


class TestDeidentification(FrappeTestCase):
    def test_no_fixture_name_phone_or_email_survives(self):
        staff = text.name_tokens(["Rashid Hamdan"])
        convs = [
            conv("WA1", sender_name="فاطمة الكواري"),
            conv("IG1", platform="Instagram", sender_id="1789", sender_name="noora_m92"),
        ]
        t = ticket(
            "T1",
            T0,
            subject="Call back 55123456",
            description="<p>Fatima says the meal was cold, email fatima.k@example.com</p>",
            custom_customer_name="Fatima Alkuwari",
            contact="Fatima Alkuwari-2",
            custom_customer_phone="+974 5512 3456",
            custom_messenger_conversation="WA1",
        )
        comments = [
            {
                "name": "c1",
                "reference_ticket": "T1",
                "creation": T0 + H,
                "content": "<p>@Rashid Hamdan please call +97455123456</p>",
            }
        ]
        msgs = [
            msg("WA1", T0 + H, "Hi I am Fatima Alkuwari, call me on +974 5512 3456 or 5512-3456"),
            msg("WA1", T0 + 2 * H, "Rashid told me it would come, mail fatima.k@example.com", "Outgoing"),
            msg("WA1", T0 + 3 * H, "أنا فاطمة الكواري ورقمي ٥٥١٢٣٤٥٦"),
            msg("WA1", T0 + 4 * H, "Hi MSG-CONV-CRMDEAL260119012-00034, welcome!", "Outgoing", is_auto_reply=1),
            msg("IG1", T0, "this is Noora from zone 66 street 900 building 12"),
        ]
        drafts = build(tickets=[t], comments=comments, conversations=convs, messages=msgs, names=staff)
        blob = " ".join(line["text"] for d in drafts for line in d["lines"]).casefold()
        leaks = (
            "fatima",
            "alkuwari",
            "noora",
            "rashid",
            "hamdan",
            "5512",
            "3456",
            "example.com",
            "فاطمة",
            "الكواري",
            "٥٥١٢",
            "street 900",
        )
        for leak in (*leaks, "msg-conv", "crmdeal"):
            self.assertNotIn(leak, blob)
        self.assertIn("[name]", blob)
        self.assertIn("[phone]", blob)


class TestPollutedFields(FrappeTestCase):
    def test_polluted_fields_are_never_selected(self):
        self.assertEqual(len(set(cases.POLLUTED_TICKET_FIELDS)), 12)
        real, seen = frappe.db.sql, []

        def spy(query, *args, **kwargs):
            seen.append(str(query))
            return real(query, *args, **kwargs)

        with patch.object(frappe.db, "sql", side_effect=spy):
            cases._load()
            cases._pairs()
            cases.suggest_exclusions()
        self.assertTrue(any("`tabHD Ticket`" in q for q in seen))
        for field in cases.POLLUTED_TICKET_FIELDS:
            self.assertEqual([q for q in seen if field in q], [], field)


class TestExclusions(FrappeTestCase):
    def tearDown(self):
        frappe.db.rollback()

    def exclude(self, kind, value, reason):
        doc = {"doctype": "HD AI Exclusion", "exclusion_type": kind, "value": value, "reason": reason}
        frappe.get_doc(doc).insert(ignore_permissions=True)

    def run_rules(self, rows, exclude_staff_phones=True):
        settings = frappe._dict(start_date=date(2026, 3, 1), exclude_staff_phones=exclude_staff_phones)
        with (
            patch.object(cases, "conf", return_value=settings),
            patch.object(cases, "staff_keys", return_value={cases.customer_key("p:55990002")}),
            patch.object(cases, "_pairs", return_value=[("zz-ai-T2", "zz-ai-C1")]),
        ):
            changed = cases.apply_exclusions(list(rows.values()))
            again = cases.apply_exclusions(list(rows.values()))
        state = {
            k: tuple(frappe.db.get_value("HD AI Contact", n, ["status", "exclusion_reason"])) for k, n in rows.items()
        }
        return changed, again, state

    def make_rows(self):
        rows = {
            "ticket": insert_contact(source="Ticket", ticket="zz-ai-T1", issues=[{"code": "NEW", "quote": "a quote"}]),
            "conversation": insert_contact(conversation="zz-ai-C1"),
            "linked": insert_contact(source="Ticket", ticket="zz-ai-T2", conversation="zz-ai-C9"),
            "phone": insert_contact(customer_key=cases.customer_key("p:55990001")),
            "contact": insert_contact(),
            "early": insert_contact(source="Ticket", ticket="zz-ai-T1", started_on=datetime(2026, 2, 1)),
            "staff": insert_contact(customer_key=cases.customer_key("p:55990002")),
            "stale": insert_contact(status="Excluded", exclusion_reason="Excluded: an old reason"),
            "stale_empty": insert_contact(status="Excluded", exclusion_reason="Excluded: an old reason", has_text=0),
            "plain": insert_contact(),
        }
        self.exclude("Ticket", "zz-ai-T1", "test ticket")
        self.exclude("Conversation", "zz-ai-C1", "test chat")
        self.exclude("Phone", "+974 5599 0001", "staff test phone")
        self.exclude("Phone", "55990002", "another phone rule")
        self.exclude("Contact", rows["contact"], "one-off test")
        return rows

    def test_rules_in_order_and_unexclude(self):
        rows = self.make_rows()
        changed, again, state = self.run_rules(rows)
        self.assertEqual(
            state,
            {
                "ticket": ("Excluded", "Excluded: test ticket"),
                "conversation": ("Excluded", "Excluded: test chat"),
                "linked": ("Excluded", "Excluded: test chat"),  # a ticket linked to the excluded chat
                "phone": ("Excluded", "Excluded: staff test phone"),
                "contact": ("Excluded", "Excluded: one-off test"),
                "early": ("Excluded", "Before start date"),  # beats its Ticket rule
                "staff": ("Excluded", "Staff phone"),  # beats its Phone rule
                "stale": ("Pending", None),
                "stale_empty": ("No text", None),
                "plain": ("Pending", None),
            },
        )
        self.assertEqual((changed, again), (9, 0))
        self.assertFalse(frappe.db.exists("HD AI Contact Issue", {"parent": rows["ticket"]}))

    def test_staff_phone_rule_can_be_off(self):
        rows = self.make_rows()
        _, _, state = self.run_rules(rows, exclude_staff_phones=False)
        self.assertEqual(state["staff"], ("Excluded", "Excluded: another phone rule"))

    def test_removed_exclusion_releases_the_contact(self):
        rows = {"one": insert_contact(ticket="zz-ai-T7", source="Ticket")}
        self.exclude("Ticket", "zz-ai-T7", "test ticket")
        self.assertEqual(self.run_rules(rows)[2]["one"], ("Excluded", "Excluded: test ticket"))
        exclusion = frappe.get_doc("HD AI Exclusion", {"exclusion_type": "Ticket", "value": "zz-ai-T7"})
        exclusion.update({"active": 0, "removed_reason": "real customer"})
        exclusion.save(ignore_permissions=True)
        self.assertEqual(self.run_rules(rows)[2]["one"], ("Pending", None))


class TestSuggestAndPurge(FrappeTestCase):
    def tearDown(self):
        frappe.db.rollback()

    def test_suggestions_cover_each_heuristic_and_name_no_customer(self):
        tickets = [
            frappe._dict(name="zz-ai-T1", subject="test", description="<p>hi</p>", custom_customer_phone=None),
            frappe._dict(
                name="zz-ai-T3", subject="Lunch arrived late", description="<p>Lunch arrived an hour late</p>"
            ),
        ]
        convs = [
            frappe._dict(name="zz-ai-C1", platform="WhatsApp", sender_id="55990003", sender_name="Test Account"),
            frappe._dict(name="zz-ai-C2", platform="Instagram", sender_id="1789", sender_name="Maryam Alsulaiti"),
            frappe._dict(name="zz-ai-C3", platform="WhatsApp", sender_id="55990004", sender_name="tester"),
        ]
        pairs = [("zz-ai-T1", "zz-ai-gone")] + [(f"zz-ai-T{i}", "zz-ai-C2") for i in range(10, 20)]
        insert_contact(source="Ticket", ticket="zz-ai-T1", in_count=0)
        insert_contact(source="Ticket", ticket="zz-ai-T3", in_count=0)
        insert_contact(conversation="zz-ai-C1")
        insert_contact(conversation="zz-ai-C2")
        flagged = insert_contact(conversation="zz-ai-C5", channel="Instagram DM", looks_like_test=1)
        insert_contact(conversation="zz-ai-C3", status="Excluded", exclusion_reason="Staff phone")
        with (
            patch.object(cases, "_tickets", return_value=tickets),
            patch.object(cases, "_conversations", return_value=convs),
            patch.object(cases, "_pairs", return_value=pairs),
        ):
            got = {
                (s["type"], s["value"]): s
                for s in cases.suggest_exclusions()
                if s["value"].startswith(("zz-ai", flagged))
            }
        self.assertEqual(
            {key: s["label"] for key, s in got.items()},
            {
                (
                    "Ticket",
                    "zz-ai-T1",
                ): "Ticket zz-ai-T1: junk subject; description under 10 characters and no customer chat; "
                "its linked chat no longer exists",
                ("Conversation", "zz-ai-C1"): "WhatsApp chat: test-like name",
                ("Conversation", "zz-ai-C2"): "Instagram chat: linked to 10 tickets",
                ("Contact", flagged): "Instagram DM chat, Apr 2026: the AI flagged it as a test",
            },
        )
        self.assertEqual(got[("Conversation", "zz-ai-C1")]["contacts"], 1)
        self.assertEqual(got[("Ticket", "zz-ai-T1")]["reason_hint"], "Test ticket")
        labels = " ".join(s["label"] for s in got.values()).casefold()
        self.assertNotIn("maryam", labels)
        self.assertNotIn("account", labels)

    def test_purge_goes_through_the_source_records(self):
        tickets = [frappe._dict(name="zz-ai-T1", custom_customer_phone="+974 5599 0009"), frappe._dict(name="zz-ai-T2")]
        convs = [
            frappe._dict(name="zz-ai-WA", platform="WhatsApp", sender_id="97455990009"),
            frappe._dict(name="zz-ai-IG", platform="Instagram", sender_id="1789"),
        ]
        pairs = [("zz-ai-T2", "zz-ai-WA"), ("zz-ai-T2", "zz-ai-IG")]  # T2 is reached through the WhatsApp chat
        gone = [
            insert_contact(source="Ticket", ticket="zz-ai-T1", issues=[{"code": "NEW", "quote": "a quote"}]),
            insert_contact(source="Ticket", ticket="zz-ai-T2"),
            insert_contact(conversation="zz-ai-IG"),  # took T2's identity, so it is the same customer
        ]
        kept = insert_contact(conversation="zz-ai-other")
        frappe.get_doc({"doctype": "HD AI Gold Label", "contact": gone[0], "labeller": "Administrator"}).insert(
            ignore_permissions=True
        )
        cited = frappe.get_doc({"doctype": "HD AI Insight", "alias_map": f'{{"E1": "{gone[2]}"}}', "output_json": "{}"})
        cited.insert(ignore_permissions=True)
        with (
            patch.object(cases, "_tickets", return_value=tickets),
            patch.object(cases, "_conversations", return_value=convs),
            patch.object(cases, "_pairs", return_value=pairs),
            patch.object(cases, "apply_exclusions") as apply_exclusions,
        ):
            result = cases.purge_customer("+974 5599 0009", "PDPPL-42")
        self.assertEqual((result["contacts"], result["gold_labels"], result["insights"]), (3, 1, 1))
        self.assertFalse([n for n in gone if frappe.db.exists("HD AI Contact", n)])
        self.assertTrue(frappe.db.exists("HD AI Contact", kept))
        self.assertFalse(frappe.db.exists("HD AI Contact Issue", {"parent": gone[0]}))
        self.assertIsNone(frappe.db.get_value("HD AI Insight", cited.name, "alias_map"))
        exclusion = frappe.get_doc("HD AI Exclusion", result["exclusion"])
        self.assertEqual(
            (exclusion.exclusion_type, exclusion.value, exclusion.reason),
            ("Phone", "55990009", "Erasure request PDPPL-42"),
        )
        apply_exclusions.assert_called_once()


class TestLinesFor(FrappeTestCase):
    def tearDown(self):
        frappe.db.rollback()

    def test_rebuilds_lines_of_the_named_contacts(self):
        source = ([], [], [], [conv("WA1")], [msg("WA1", T0, "the soup leaked everywhere")])
        [draft] = cases.assemble(*source)
        mine, vanished = insert_contact(source_key=draft["source_key"]), insert_contact()
        with patch.object(cases, "_load", return_value=source), patch.object(cases, "known_names", return_value=set()):
            got = cases.lines_for([mine, vanished])
        self.assertEqual(got, {mine: draft["lines"]})
        self.assertEqual(cases.text_hash(got[mine]), draft["text_hash"])


class TestHelpers(FrappeTestCase):
    def test_next_status(self):
        def old(status, h="h1"):
            return frappe._dict(status=status, text_hash=h)

        def row(has_text=1, h="h1"):
            return {"has_text": has_text, "text_hash": h}

        self.assertEqual(cases._next_status(old("Tagged"), row()), "Tagged")
        self.assertEqual(cases._next_status(old("Tagged"), row(h="h2")), "Pending")
        self.assertEqual(cases._next_status(old("Tagged"), row(has_text=0, h="h2")), "No text")
        self.assertEqual(cases._next_status(old("No text"), row()), "Pending")
        self.assertEqual(cases._next_status(old("Excluded"), row(h="h2")), "Excluded")
        self.assertEqual(cases._next_status(old("Failed"), row()), "Failed")

    def test_junk_subjects(self):
        for subject in ("test", "Test 12/10/2025", "j", "jj", "nn", "55123456", "", "Testing again"):
            self.assertTrue(cases._junk(subject), subject)
        for subject in ("Wrong meal delivered", "Late delivery", "مرحبا", "latest order", "Leaking box"):
            self.assertFalse(cases._junk(subject), subject)
