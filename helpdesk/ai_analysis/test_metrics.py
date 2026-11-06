"""Tests for metrics.py: counting, filters, coverage, window state, chips, badges, the safety box, masking, PII.

Contacts are our own HD AI Contact rows (never HD Ticket or Messenger rows), rolled back with the test
class. The liveness helper is patched to know only the conversations a test creates, so contacts built on
the site by anyone else are never counted here. Deliveries, calls, money and chat coverage come from patched
loaders: Instagram, deliveries and calls are covered every week from 28 Dec 2025 to 27 Jun 2026.
"""

import json
from collections import Counter
from datetime import date, datetime, time, timedelta
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from helpdesk.ai_analysis import conf, metrics, stats

START, END = date(2025, 12, 28), date(2026, 6, 27)  # Sunday .. Saturday
DAYS = [START + timedelta(days=i) for i in range((END - START).days + 1)]
WEEKS = DAYS[::7]
CHAT = [
    {"platform": "Instagram", "at": w + timedelta(days=1), "in": 5, "conversation": f"chat-{i}"}
    for w in WEEKS
    for i in range(6)
]
CALLERS = [f"77719{n:03d}" for n in range(len(DAYS))]  # phone-like; must never reach an output
CALLS = {
    "answered": [(datetime.combine(d, time(10)), caller) for d, caller in zip(DAYS, CALLERS)],
    "incoming": [(d, True) for d in DAYS],
}
MONEY = {"replacements": 2, "cost": 12.5, "value": 60.0, "refunds": 1, "refunds_qar": 30.0}
HITS = [{"severity": "S1", "rule": "illness", "term": "vomit"}]
ISSUE = {
    "severity": "S3",
    "quote": "the order came two hours late again",
    "quote_en": "the order came two hours late again",
    "quote_status": "Verified",
    "quote_role": "customer",
    "confidence": "high",
}


def _fresh():
    getattr(frappe.local, "request_cache", {}).clear()


def _row(code, at, customer, severity="S3", channel="Instagram DM", **extra):
    """A counted_rows() row, for the tests that need no database rows."""
    m = metrics._meta()[code]
    at = datetime.fromisoformat(at) if isinstance(at, str) else at
    row = {
        "contact": frappe.generate_hash(length=10),
        "ticket": None,
        "source": "Chat",
        "channel": channel,
        "at": at,
        "day": at.date(),
        "customer": customer,
        "language": "en",
        "offered": None,
        "hits": [],
        "code": code,
        "raw_code": code,
        "label": m.label,
        "kind": m.kind,
        "family": m.family,
        "owner_department": m.owner_department,
        "is_food_safety": bool(m.is_food_safety),
        "severity": severity,
        "confidence": "high",
        "quote": "it came late again today",
        "quote_en": "it came late again today",
        "quote_status": "Verified",
        "role": "customer",
        "review": None,
        "dish": None,
        "dish_item": None,
        "proposed_label": None,
        "statement_en": None,
    }
    row.update(extra)
    return row


class TestMetrics(FrappeTestCase):
    def setUp(self):
        frappe.set_user("Administrator")
        self.convs, self.tickets = {}, set()
        loaders = {
            "_live_sources": {
                "side_effect": lambda tickets, convs: (
                    self.tickets & set(tickets),
                    {c: p for c, p in self.convs.items() if c in convs},
                )
            },
            "_chat_rows": {"return_value": CHAT},
            "_deliveries": {"return_value": dict.fromkeys(DAYS, 400)},
            "_calls": {"return_value": CALLS},
            "_money": {"side_effect": lambda frm, to: dict(MONEY)},
            "_meals": {"return_value": Counter()},
            "_reply_months": {
                "return_value": {("Instagram", "2026-04"): (1792, 11), ("Instagram", "2026-05"): (900, 300)}
            },
        }
        for name, kwargs in loaders.items():
            patcher = patch.object(metrics, name, **kwargs)
            patcher.start()
            self.addCleanup(patcher.stop)
        _fresh()
        self.addCleanup(_fresh)

    def _contact(
        self,
        at,
        customer="k1",
        channel="Instagram DM",
        status="Tagged",
        issues=(),
        hits=None,
        live=True,
        conversation=None,
        ticket=None,
    ):
        conversation = conversation or f"test-metrics-{frappe.generate_hash(length=10)}"
        if live:
            self.convs[conversation] = metrics.PLATFORM_OF.get(channel, "Instagram")
            if ticket:
                self.tickets.add(ticket)
        doc = frappe.get_doc(
            {
                "doctype": "HD AI Contact",
                "source_key": frappe.generate_hash(length=20),
                "source": "Ticket" if ticket else "Chat",
                "ticket": ticket,
                "conversation": conversation,
                "channel": "Ticket" if ticket else channel,
                "started_on": at,
                "customer_key": customer,
                "language": "en",
                "in_count": 3,
                "has_text": 1,
                "status": status,
                "safety_hits": json.dumps(hits) if hits else None,
                "issues": [{**ISSUE, **i} for i in issues],
            }
        )
        doc.flags.ignore_links = True  # a ticket name here is a test value, never a real HD Ticket
        doc.insert(ignore_permissions=True)
        _fresh()
        return doc.name

    # --- counting --------------------------------------------------------------------------------

    def test_cases_contacts_repeats_and_the_code_agnostic_kpi(self):
        self._contact(
            "2026-04-05 10:00", "k1", issues=[{"code": "DLV_LATE"}, {"code": "PKG_LEAK"}, {"code": "ACC_WRONG_MEAL"}]
        )
        for day in ("2026-04-06", "2026-04-08", "2026-04-11"):  # one customer within 7 days: 1 case, 2 repeats
            self._contact(f"{day} 09:00", "k2", issues=[{"code": "DLV_LATE"}])
        self._contact("2026-04-20 09:00", None, issues=[{"code": "DLV_LATE"}, {"code": "PKG_LEAK"}])  # no key: own case
        # never counted: unverified quote, rejected review, not tagged yet, source gone
        self._contact("2026-04-07 09:00", "k3", issues=[{"code": "DLV_LATE", "quote_status": "Unverified"}])
        self._contact("2026-04-07 10:00", "k4", issues=[{"code": "DLV_LATE", "review": "Rejected"}])
        self._contact("2026-04-07 11:00", "k5", status="Pending", issues=[{"code": "DLV_LATE"}])
        self._contact("2026-04-07 12:00", "k6", issues=[{"code": "DLV_LATE"}], live=False)

        o = metrics.overview("2026-04-01", "2026-04-30")
        rows = {r["code"]: (r["cases"], r["contacts"], r["customers"]) for r in o["issues"]}
        self.assertEqual(rows, {"DLV_LATE": (3, 5, 3), "PKG_LEAK": (2, 2, 2), "ACC_WRONG_MEAL": (1, 1, 1)})
        kpi = {k["key"]: k for k in o["kpis"]}
        # code-agnostic: the 3-issue contact is one case, k2 one case, the keyless 2-issue contact one case
        self.assertEqual((kpi["complaint_cases"]["value"], kpi["customers"]["value"]), (3, 3))
        self.assertEqual(
            o["window"],
            {"from_date": "2026-04-01", "to_date": "2026-04-30", "prior_from": "2026-03-02", "prior_to": "2026-03-31"},
        )

        n = metrics.issue_detail("DLV_LATE", "2026-04-01", "2026-04-30")["numbers"]
        self.assertEqual((n["cases"], n["contacts"], n["repeat_contacts"], n["customers"]), (3, 5, 2, 3))
        self.assertEqual(metrics.evidence("DLV_LATE", "2026-04-01", "2026-04-30")["total"], 5)

    def test_contacts_waiting_to_be_relabelled_keep_counting(self):
        # Publish label version (or a changed text) moves Tagged contacts back to Pending: their last tag set
        # still counts, so the safety box keeps working; a contact never labelled has no tagged_version.
        spoiled = [{"code": "FS_SPOILED", "severity": "S2"}]
        for status in ("Pending", "Tagging", "Failed"):
            name = self._contact("2026-04-07 09:00", f"r-{status}", status=status, issues=spoiled)
            frappe.db.set_value("HD AI Contact", name, "tagged_version", "tag-v1:old", update_modified=False)
        self._contact("2026-04-08 09:00", "never", status="Pending", issues=spoiled)
        _fresh()
        self.assertEqual(len(metrics.safety_box("2026-04-01", "2026-04-30")["events"]), 3)

    def test_weekly_rate_is_blank_without_chat_coverage(self):
        self._contact("2026-06-10 09:00", "w1", issues=[{"code": "DLV_LATE"}])
        days = dict.fromkeys(DAYS + [END + timedelta(days=i) for i in range(1, 8)], 400)  # deliveries run a week longer
        with patch.object(metrics, "_deliveries", return_value=days):
            _fresh()
            weekly = {w["week"]: w for w in metrics.issue_detail("DLV_LATE", "2026-06-01", "2026-07-04")["weekly"]}
        self.assertEqual((weekly["2026-06-28"]["covered"], weekly["2026-06-28"]["rate"]), (False, None))
        self.assertEqual(weekly["2026-06-07"]["rate"], round(1 / 2800 * 1000, 2))

    def test_cases_run_over_all_history_and_count_by_start(self):
        self._contact("2026-03-30 09:00", "k1", issues=[{"code": "DLV_LATE"}])
        self._contact("2026-04-02 09:00", "k1", issues=[{"code": "DLV_LATE"}])  # same case, started in March
        self._contact("2026-04-06 10:00", "k1", issues=[{"code": "DLV_LATE"}])  # day 7: a new case
        n = metrics.issue_detail("DLV_LATE", "2026-04-01", "2026-04-30")["numbers"]
        self.assertEqual((n["cases"], n["contacts"], n["first_seen"]), (1, 2, "2026-03-30"))

    def test_channel_dept_and_kind_filters(self):
        self._contact("2026-04-05 10:00", "w1", channel="WhatsApp", issues=[{"code": "DLV_LATE"}])
        self._contact(
            "2026-04-05 11:00",
            "i1",
            issues=[
                {"code": "FS_SPOILED", "severity": "S2"},
                {"code": "ENQ_PRICE", "severity": "S4"},
                {"code": "FB_PRAISE", "severity": "S4"},
            ],
        )

        def codes(**kw):
            return {r["code"] for r in metrics.overview("2026-04-01", "2026-04-30", **kw)["issues"]}

        self.assertEqual(codes(), {"DLV_LATE", "FS_SPOILED"})
        self.assertEqual(codes(channel="WhatsApp"), {"DLV_LATE"})
        self.assertEqual(codes(dept="Kitchen & QA"), {"FS_SPOILED"})
        self.assertEqual(codes(kind="demand"), {"ENQ_PRICE"})
        self.assertEqual(codes(kind="feedback"), {"FB_PRAISE"})
        self.assertEqual(codes(kind="all"), {"DLV_LATE", "FS_SPOILED", "ENQ_PRICE", "FB_PRAISE"})
        kpi = {k["key"]: k["value"] for k in metrics.overview("2026-04-01", "2026-04-30", channel="WhatsApp")["kpis"]}
        self.assertEqual((kpi["complaint_cases"], kpi["food_safety"], kpi["demand"]), (1, 0, 0))
        kpi = {k["key"]: k["value"] for k in metrics.overview("2026-04-01", "2026-04-30", dept="Kitchen & QA")["kpis"]}
        self.assertEqual((kpi["complaint_cases"], kpi["food_safety"]), (1, 1))
        self.assertRaises(frappe.ValidationError, metrics.overview, "2026-04-01", "2026-04-30", kind="nope")

    # --- coverage and window state ---------------------------------------------------------------

    def test_a_stopped_feed_with_stray_messages_stays_uncovered(self):
        first = date(2026, 1, 4)
        week = lambda n: first + timedelta(weeks=n)  # noqa: E731
        real = [
            {"platform": "Instagram", "at": week(w) + timedelta(days=1), "in": 10, "conversation": f"c{w}-{i}"}
            for w in range(26)
            for i in range(30)
        ]
        # weeks 36 and 37: 18 messages from 6 conversations clear the floors, but not 20% of the ~300 reference
        stray = [
            {"platform": "Instagram", "at": week(w) + timedelta(days=2), "in": 3, "conversation": f"s{w}-{i}"}
            for w in (36, 37)
            for i in range(6)
        ]
        # a small feed that never stops is its own reference: 12 messages from 6 conversations every week
        small = [
            {"platform": "WhatsApp", "at": week(w) + timedelta(days=3), "in": 2, "conversation": f"w{w}-{i}"}
            for w in range(39)
            for i in range(6)
        ]
        cov = metrics.chat_coverage(real + stray, today=week(38))
        self.assertTrue(all(cov["weeks"][week(w)]["covered"] for w in range(26)))
        self.assertEqual([cov["weeks"][week(w)]["covered"] for w in (26, 36, 37)], [False, False, False])
        self.assertEqual(
            cov["weeks"][week(36)]["platforms"]["Instagram"], {"in": 18, "conversations": 6, "covered": False}
        )
        self.assertEqual((cov["until"], cov["stopped"]), (week(25) + timedelta(days=6), ["Instagram"]))

        both = metrics.chat_coverage(real + stray + small, today=week(38))
        self.assertTrue(both["weeks"][week(37)]["covered"])  # covered because WhatsApp is
        self.assertEqual((both["until"], both["stopped"]), (week(38) + timedelta(days=6), ["Instagram"]))
        thin = [dict(r, conversation="one") for r in small]  # 12 messages but one conversation a week
        self.assertEqual(metrics.chat_coverage(thin, today=week(38))["until"], None)

        calls = [(datetime.combine(week(w), time(9)) + timedelta(days=d), f"c{d}") for w in range(10) for d in range(6)]
        calls.append((datetime.combine(week(10), time(9)), "late"))  # one stray call: under 20% of the reference
        self.assertEqual(metrics.call_coverage(calls, today=week(12))["until"], week(9) + timedelta(days=5))

    def test_window_state_notice_jump_and_default_window(self):
        april = metrics.window_state("2026-04-01", "2026-04-30")
        self.assertEqual(
            (april["covered"], april["covered_weeks"], april["weeks"], april["delivery_rate"]), (True, 5, 5, True)
        )
        self.assertEqual(
            april["capture_notices"],
            [
                {
                    "key": "missed_calls",
                    "text": "Missed calls are not recorded — only answered (recorded) calls are logged.",
                },
                {
                    "key": "replies:Instagram:2026-04",
                    "text": "Replies are not recorded for Instagram (Apr 2026: 11 replies vs 1,792 messages)",
                },
            ],
        )
        nov = metrics.window_state("2026-11-01", "2026-11-28")
        self.assertEqual((nov["covered"], nov["covered_weeks"], nov["delivery_rate"]), (False, 0, False))
        self.assertEqual(nov["notice"], "No chat data in this period (last data 27 Jun 2026)")
        self.assertEqual(nov["jump"], {"from_date": "2026-05-31", "to_date": "2026-06-27"})
        self.assertEqual(metrics.default_window(), {"from_date": "2026-05-31", "to_date": "2026-06-27", "latest": True})
        self.assertEqual(metrics.coverage()["chat"]["until"], "2026-06-27")

        kpis = metrics.overview("2026-11-01", "2026-11-28")["kpis"]
        self.assertEqual(
            {k["key"]: (k["value"], k["display"], k["chip"]) for k in kpis},
            {k: (None, "—", None) for k, _l, _e in metrics.TILES},
        )

    # --- chips and badges ------------------------------------------------------------------------

    def test_change_chip_needs_exposure_in_both_windows(self):
        rows = [_row("DLV_LATE", f"2026-03-{d:02d} 09:00", f"m{d}") for d in range(2, 26, 4)]
        rows += [_row("DLV_LATE", f"2026-04-{d:02d} 09:00", f"a{d}") for d in range(1, 25, 2)]
        rows += [_row("ENQ_PRICE", f"2026-04-{d:02d} 11:00", f"e{d}", "S4") for d in (3, 9)]
        with patch.object(metrics, "counted_rows", return_value=rows):
            o = metrics.overview("2026-04-01", "2026-04-30")
            kpi, issue = {k["key"]: k for k in o["kpis"]}, {r["code"]: r for r in o["issues"]}
            self.assertEqual((kpi["complaint_cases"]["value"], kpi["complaint_cases"]["prior"]), (12, 6))
            self.assertIsNotNone(kpi["complaint_cases"]["chip"]["label"])
            self.assertEqual(kpi["complaint_cases"]["chip"]["text"], "+100%")  # 12 vs 6 cases over equal deliveries
            self.assertEqual(kpi["complaint_cases"]["hint"], "1.00 per 1,000 deliveries")
            self.assertIsNotNone(issue["DLV_LATE"]["chip"]["label"])
            self.assertIsNotNone(kpi["demand"]["chip"]["label"])  # covered chat days
            self.assertEqual(kpi["copq"]["chip"], {"label": None, "p": None, "text": "12.50 → 12.50"})

            with patch.object(metrics, "_deliveries", return_value={d: 400 for d in DAYS if d >= date(2026, 4, 1)}):
                _fresh()
                o = metrics.overview("2026-04-01", "2026-04-30")
            kpi, issue = {k["key"]: k for k in o["kpis"]}, {r["code"]: r for r in o["issues"]}
            self.assertEqual(kpi["complaint_cases"]["chip"], {"label": None, "p": None, "text": "6 → 12"})
            self.assertIsNone(issue["DLV_LATE"]["chip"]["label"])
            self.assertIsNone(kpi["copq"]["prior"])  # no deliveries in March: no money tile, never a fake 0

    def test_badge_wiring_dish_flag_and_the_brief(self):
        early = [date(2026, 1, 4) + timedelta(weeks=i) for i in range(6)] + [
            date(2026, 3, 29) + timedelta(weeks=i) for i in range(4)
        ]
        rows = [
            _row("DLV_LATE", datetime.combine(w + timedelta(days=1), time(9)), f"b{i}") for i, w in enumerate(early)
        ]
        current = [date(2026, 4, 26) + timedelta(weeks=i) for i in range(4)]
        for i, w in enumerate(current):
            for j in range(4):
                dish = "Chicken Biryani-L" if j < 2 else ("Salad" if j == 2 else None)
                rows.append(
                    _row("DLV_LATE", datetime.combine(w + timedelta(days=j), time(12)), f"s{i}-{j}", dish_item=dish)
                )
        for i, w in enumerate(current[1:]):
            rows.append(
                _row(
                    "FS_SPOILED",
                    datetime.combine(w + timedelta(days=2), time(13)),
                    f"f{i}",
                    "S2",
                    quote="the chicken smelled off",
                )
            )
        meals = Counter({"chicken biryani": 400, "salad": 200, "everything else": 99400})
        seen, badges = [], stats.badges
        with (
            patch.object(metrics, "counted_rows", return_value=rows),
            patch.object(metrics, "_meals", return_value=meals),
            patch.object(metrics.stats, "badges", side_effect=lambda s: seen.append(s) or badges(s)),
        ):
            issues = {r["code"]: r for r in metrics.overview("2026-04-26", "2026-05-23")["issues"]}
            self.assertEqual(issues["DLV_LATE"]["badges"], ["SURGE", "CHRONIC"])
            self.assertEqual(
                issues["FS_SPOILED"]["badges"], ["SAFETY", "WATCH", "CHRONIC"]
            )  # 3 vs a 0 baseline: p 0.019
            self.assertEqual(issues["DLV_LATE"]["dish"], "Chicken Biryani-L")  # salad: 200 meals, never flagged
            self.assertEqual(issues["DLV_LATE"]["trend"][-4:], [4, 4, 4, 4])
            self.assertEqual(issues["DLV_LATE"]["weeks_active"], 8)  # Mar 29 .. May 17
            series = next(s for s in seen if s["cases"][-1] == 4)
            self.assertEqual((len(series["weeks"]), series["weeks"][-1]), (30, date(2026, 5, 17)))
            self.assertEqual(
                (series["exposure"][-1], series["covered"][-1], series["history_start"]),
                (2800.0, True, date(2025, 12, 28)),
            )
            self.assertTrue(series["flagged"][series["weeks"].index(date(2026, 3, 1))])  # Ramadan

            dishes = metrics.issue_detail("DLV_LATE", "2026-04-26", "2026-05-23")["where"]["dishes"]
            self.assertEqual(
                [(d["dish"], d["cases"], d["meals"], d["flag"]) for d in dishes],
                [("Chicken Biryani-L", 8, 400, True), ("Salad", 4, 200, False)],
            )

            b = metrics.brief("2026-05-17")
            self.assertEqual([t["code"] for t in b["top"]][:2], ["DLV_LATE", "FS_SPOILED"])
            self.assertEqual(
                (b["top"][0]["week_cases"], b["top"][0]["sparkline"][-4:], len(b["top"][0]["quotes"])),
                (4, [4, 4, 4, 4], 2),
            )
            self.assertRegex(b["changed"][0]["text"], r"^\d+ → 16 · much higher than usual \(p")
            self.assertEqual((b["changed"][0]["code"], b["changed"][0]["badge"]), ("DLV_LATE", "SURGE"))
            self.assertEqual((b["headline"]["source"], b["actions"], b["decisions"]), ("code", None, None))
            self.assertEqual(b["kpis"][0]["value"], 5)  # 4 delivery + 1 food-safety case this week
            self.assertEqual(b["safety"]["events"][0]["code"], "FS_SPOILED")

    # --- safety box and masking ------------------------------------------------------------------

    def test_safety_box_events_clusters_and_needs_review(self):
        unverified = self._contact(
            "2026-04-03 09:00", "s1", issues=[{"code": "FS_ILLNESS", "severity": "S1", "quote_status": "Unverified"}]
        )
        low = self._contact(
            "2026-04-08 09:00",
            "s2",
            issues=[{"code": "FS_SPOILED", "severity": "S2", "confidence": "low", "dish": "chicken wrap"}],
        )
        hard = self._contact("2026-04-10 09:00", "s3", issues=[{"code": "FS_FOREIGN_HARD", "severity": "S1"}])
        words = self._contact("2026-04-12 09:00", "s4", hits=HITS, issues=[{"code": "DLV_LATE"}])
        pending = self._contact("2026-04-13 09:00", "s5", status="Pending", hits=HITS)
        failed = self._contact("2026-04-14 09:00", "s6", status="Failed", hits=HITS)
        self._contact("2026-04-15 09:00", "s7", status="Excluded", hits=HITS)
        self._contact(
            "2026-04-16 09:00", "s8", hits=HITS, issues=[{"code": "FS_ILLNESS", "severity": "S1", "review": "Rejected"}]
        )

        box = metrics.safety_box("2026-04-01", "2026-04-30")
        self.assertEqual([e["ref"] for e in box["events"]], [hard, low])
        self.assertEqual(len(box["clusters"]), 1)
        self.assertEqual(
            {k: box["clusters"][0][k] for k in ("from", "to", "customers", "dishes")},
            {"from": "2026-04-08", "to": "2026-04-10", "customers": 2, "dishes": ["chicken wrap"]},
        )
        reasons = {r["ref"]: r["reason"] for r in box["needs_review"]}
        self.assertEqual(
            reasons,
            {
                unverified: "Food-safety label whose quote could not be verified",
                low: "Low-confidence food-safety label",
                words: "Food-safety words but no food-safety label",
                pending: "Food-safety words; labelling pending",
                failed: "Food-safety words; labelling failed",
            },
        )
        self.assertTrue(all("quote" not in r and r["rules"] in ([], ["illness"]) for r in box["needs_review"]))
        # the box ignores the page filters
        o = metrics.overview("2026-04-01", "2026-04-30", channel="WhatsApp", dept="Delivery")
        self.assertEqual(len(o["safety"]["events"]), 2)
        self.assertEqual({k["key"]: k["hint"] for k in o["kpis"]}["food_safety"], "5 need review")

    def test_health_quotes_are_masked_for_non_deciders_when_switched_on(self):
        ill = "I was vomiting all night after the lunch"
        self._contact(
            "2026-04-05 09:00",
            "h1",
            issues=[{"code": "FS_ILLNESS", "severity": "S1", "quote": ill, "quote_en": ill}, {"code": "DLV_LATE"}],
        )
        window = ("2026-04-01", "2026-04-30")

        def quotes():
            _fresh()
            return {
                "evidence": metrics.evidence("FS_ILLNESS", *window)["rows"][0]["quote"],
                "event": metrics.safety_box(*window)["events"][0]["quote_en"],
                "brief": metrics.brief("2026-04-05")["safety"]["events"][0]["quote"],
                "other": metrics.evidence("DLV_LATE", *window)["rows"][0]["quote"],
            }

        masked = frappe._dict(conf(), mask_health=True)
        with (
            patch.object(metrics, "conf", return_value=masked),
            patch.object(metrics, "is_decider", return_value=False),
        ):
            self.assertEqual(
                quotes(),
                {"evidence": metrics.HIDDEN, "event": metrics.HIDDEN, "brief": metrics.HIDDEN, "other": ISSUE["quote"]},
            )
        with patch.object(metrics, "conf", return_value=masked), patch.object(metrics, "is_decider", return_value=True):
            self.assertEqual(quotes()["evidence"], ill)
        self.assertEqual(quotes()["event"], ill)  # the switch is off by default

    def test_outputs_carry_no_names_phones_keys_or_conversation_names(self):
        conversation = "MSG-CONV-Fatima Alkhaldi-00042"
        self._contact(
            "2026-04-05 09:00",
            "ck-secret-0001",
            conversation=conversation,
            hits=HITS,
            issues=[
                {"code": "FS_ILLNESS", "severity": "S1"},
                {
                    "code": "NEW",
                    "severity": "S3",
                    "proposed_label": "Gift card balance",
                    "statement_en": "Customer asks about a gift card balance",
                },
            ],
        )
        self._contact("2026-04-06 09:00", "ck-secret-0002", ticket="TEST-METRICS-T1", issues=[{"code": "DLV_LATE"}])
        window = ("2026-04-01", "2026-04-30")
        with patch("helpdesk.ai_analysis.cases.suggest_exclusions", return_value=[]):
            outputs = [
                metrics.overview(*window, kind="all"),
                metrics.issue_detail("FS_ILLNESS", *window),
                metrics.issue_detail("DLV_LATE", *window),
                metrics.evidence("FS_ILLNESS", *window),
                metrics.safety_box(*window),
                metrics.brief("2026-04-05"),
                metrics.data_health(),
                metrics.coverage(),
                metrics.window_state(*window),
                metrics.default_window(),
            ]
        blob = json.dumps(outputs, ensure_ascii=False)  # JSON-safe, or this raises
        for secret in ("MSG-CONV", "Fatima", "Alkhaldi", "ck-secret", "77719"):
            self.assertNotIn(secret, blob)
        self.assertEqual(outputs[0]["unclassified"], 1)
        self.assertEqual(outputs[2]["ticket_ids"], ["TEST-METRICS-T1"])
        queue = outputs[6]["new_queue"]
        self.assertEqual([(g["label"], g["n"]) for g in queue], [("Gift card balance", 1)])
