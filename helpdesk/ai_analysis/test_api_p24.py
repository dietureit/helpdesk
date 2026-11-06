"""Phase 2-4: the decision, action, research, summary, operations and Ask endpoints, the Brief's Phase 2 keys and
Ask itself.

No model is called: requests.post is mocked, so the real chat_json builds every body. advisor.py is replaced by a
stand-in module (its own tests are in test_advisor.py). frappe.db.commit/rollback, frappe.enqueue and
frappe.log_error are patched and every test rolls back. Users come from the site by query, never created. Counted
rows, coverage, deliveries, calls and money come from patched loaders as in test_metrics; the real-data operations
check only reads.
"""

import json
import re
import sys
import types
from collections import Counter
from datetime import date, datetime, time, timedelta
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, getdate, now_datetime

import helpdesk.ai_analysis
from helpdesk.ai_analysis import ask, jobs, metrics, tagging
from helpdesk.api import ai_analysis as api
from helpdesk.api import ticket_ai

START, END = date(2025, 12, 28), date(2026, 6, 27)  # Sunday .. Saturday: every feed is covered in between
DAYS = [START + timedelta(days=i) for i in range((END - START).days + 1)]
CHAT = [{"platform": "Instagram", "at": w + timedelta(days=1), "in": 5, "conversation": f"chat-{i}"} for w in DAYS[::7] for i in range(6)]
CALLERS = [f"77719{n:03d}" for n in range(len(DAYS))]  # phone-like; must never reach an output
CALLS = {
    "answered": [(datetime.combine(d, time(10)), caller) for d, caller in zip(DAYS, CALLERS)],
    "incoming": [(d, True) for d in DAYS],
}
MONEY = {"replacements": 2, "cost": 12.5, "value": 60.0, "refunds": 1, "refunds_qar": 30.0}
WEEK = date(2026, 5, 17)  # a covered Sunday
PLAN = {"codes": ["DLV_LATE"], "kinds": [], "channels": [], "from": "2026-05-17", "to": "2026-05-30"}
PLAN.update(group_by="week", metric="cases")
TOO_FEW = "Too few cases to answer this question."
UNRELIABLE = "Could not write a reliable answer; the table above is exact."


def _fresh():
    getattr(frappe.local, "request_cache", {}).clear()


def _check_narrative(text, values):
    """Stand-in for advisor.check_narrative with the contract's rules."""
    errors = [f"Unknown placeholder {k}" for k in re.findall(r"\{\{\s*([\w.]+)\s*\}\}", text) if k not in values]
    bare = re.sub(r"\{\{[^}]*\}\}", " ", text)
    if re.search(r"[0-9]", bare):
        errors.append("Digits outside placeholders")
    if re.search(r"\b(double|doubled|twice|triple|tripled|half|halved|times|x2)\b", bare, re.I):
        errors.append("A multiplier word")
    return errors


def _row(code, at, customer, severity="S3", channel="Instagram DM", **extra):
    """A counted_rows() row."""
    m = metrics._meta()[code]
    at = datetime.fromisoformat(at) if isinstance(at, str) else at
    quote = f"customer {customer} says it went wrong again"
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
        "quote": quote,
        "quote_en": quote,
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


def _users():
    """(plain agents, deactivated agents) with the Agent role and no manager role, from the site."""
    rows = frappe.db.sql(
        """select u.name, a.is_active from `tabUser` u left join `tabHD Agent` a on a.user = u.name
        where u.enabled = 1 and u.user_type = 'System User' and u.name not in ('Administrator', 'Guest')
        and exists (select 1 from `tabHas Role` r where r.parent = u.name and r.parenttype = 'User' and r.role = 'Agent')
        and not exists (select 1 from `tabHas Role` r where r.parent = u.name and r.parenttype = 'User'
            and r.role in ('System Manager', 'Agent Manager', 'Messenger Admin', 'Messenger Manager'))
        order by u.name""",
        as_dict=True,
    )
    plain = [r.name for r in rows if r.is_active is None or r.is_active]
    return plain, [r.name for r in rows if r.is_active is not None and not r.is_active]


def _reply(content):
    response = MagicMock()
    response.raise_for_status.return_value = None
    message = {"content": json.dumps(content, ensure_ascii=False)}
    response.json.return_value = {
        "model": "openai/gpt-4.1",
        "usage": {"cost": 0.002},
        "choices": [{"finish_reason": "stop", "message": message}],
    }
    return response


class TestAPIPhase24(FrappeTestCase):
    def setUp(self):
        super().setUp()
        self.addCleanup(frappe.db.rollback)  # the real one: cleanups run last-in first-out, after the patches end
        self.addCleanup(frappe.set_user, "Administrator")
        frappe.set_user("Administrator")
        self.enterContext(patch.object(frappe.db, "commit"))
        self.enterContext(patch.object(frappe.db, "rollback"))
        self.log_error = self.enterContext(patch.object(frappe, "log_error"))  # tabError Log is MyISAM
        self.enqueue = self.enterContext(patch.object(frappe, "enqueue"))
        self.enterContext(patch.object(tagging, "stale_count", return_value=0))
        self.advisor = types.ModuleType("helpdesk.ai_analysis.advisor")
        self.advisor.check_narrative = _check_narrative
        self.advisor.action_state = self.advisor.suggestion_state = lambda code: None
        for fn in ("request_suggestions", "insight_projection", "combine", "adopt", "reject", "problem_card"):
            setattr(self.advisor, fn, MagicMock(name=fn))
        for fn in ("request_research", "write_summary"):
            setattr(self.advisor, fn, MagicMock(name=fn))
        self.enterContext(patch.dict(sys.modules, {"helpdesk.ai_analysis.advisor": self.advisor}))
        self.enterContext(patch.object(helpdesk.ai_analysis, "advisor", self.advisor, create=True))
        _fresh()
        self.addCleanup(_fresh)

    # --- fixtures ---------------------------------------------------------------------------------

    def loaders(self, rows, contacts=None):
        """counted_rows() and the coverage feeds: Instagram, deliveries and calls covered 28 Dec 2025 - 27 Jun 2026."""
        patches = {
            "counted_rows": {"return_value": rows},
            "_base": {"return_value": contacts or {}},
            "_chat_rows": {"return_value": CHAT},
            "_deliveries": {"return_value": dict.fromkeys(DAYS, 400)},
            "_calls": {"return_value": CALLS},
            "_money": {"side_effect": lambda frm, to: dict(MONEY)},
            "_meals": {"return_value": Counter()},
            "_reply_months": {"return_value": {}},
        }
        for name, kwargs in patches.items():
            self.enterContext(patch.object(metrics, name, **kwargs))
        _fresh()

    def ready(self, enabled=True, worker=True, budget=50.0):
        """The AI request guard: analysis on, a worker, budget left."""
        self.enterContext(patch.object(api, "analysis_enabled", return_value=enabled))
        self.enterContext(patch.object(jobs, "worker_running", return_value=worker))
        self.enterContext(patch.object(jobs, "budget_left", return_value=budget))
        self.enterContext(patch.object(api, "conf", return_value=frappe._dict(api.conf(), web_research=True)))

    def model(self, replies):
        """The real chat_json against a mocked requests.post that answers with these replies in order."""
        self.enterContext(patch.object(ask, "analysis_enabled", return_value=True))
        self.enterContext(patch.object(jobs, "budget_left", return_value=50.0))
        config = {"enabled": True, "base_url": "https://openrouter.ai/api/v1", "model": "openai/gpt-4.1"}
        self.enterContext(patch.object(ticket_ai, "get_config", return_value=config))
        self.enterContext(patch.object(ticket_ai, "_api_key", return_value="test-key"))
        return self.enterContext(patch.object(ticket_ai.requests, "post", side_effect=[_reply(r) for r in replies]))

    def insight(self, **values):
        doc = {"doctype": "HD AI Insight", "status": "Done", "requested_by": "Administrator", **values}
        if isinstance(doc.get("output_json"), dict):
            doc["output_json"] = json.dumps(doc["output_json"])
        return frappe.get_doc(doc).insert(ignore_permissions=True).name

    def suggestions(self, code="DLV_LATE", **values):
        output = {
            "options": [{"id": "O1", "title": "Seal check"}, {"id": "O2", "title": "Cooler bags"}],
            "cards": [{"type": t, "title": t} for t in ("quick_win", "structural_fix", "combined_plan")],
        }
        return self.insight(insight_type="Suggestions", issue_code=code, output_json=output, **values)

    def action(self, **values):
        doc = {"doctype": "HD AI Action", "title": "Test action", "issue_code": "PKG_LEAK", "status": "Open", **values}
        return frappe.get_doc(doc).insert(ignore_permissions=True).name

    def backdate(self, doctype, name, when):
        frappe.db.set_value(doctype, name, "creation", when, update_modified=False)

    # --- roles, methods, inputs, payloads, refusals -----------------------------------------------

    def test_writes_are_post_only_and_the_pdf_is_get(self):
        methods = frappe.allowed_http_methods_for_whitelisted_func
        writes = (api.request_suggestions, api.combine, api.adopt, api.reject, api.update_action)
        writes += (api.request_research, api.write_summary, api.ask, api.publish_version)
        for fn in writes:
            self.assertEqual(methods[fn], ["POST"], fn.__name__)
        self.assertEqual(methods[api.download_brief], ["GET"])
        reads = (api.get_insight, api.get_actions, api.get_decisions, api.preview_problem_card, api.get_operations)
        for fn in (*reads, api.get_questions):
            self.assertIn("GET", methods[fn], fn.__name__)

    def test_only_deciders_decide_and_only_the_assignee_or_a_decider_updates(self):
        plain, inactive = _users()
        if len(plain) < 2:
            self.skipTest("needs two plain agents on this site")
        first, second = plain[:2]
        plan = self.suggestions()
        action = self.action(assigned_to=first)
        frappe.set_user(first)
        decisions = {
            api.combine: {"insight": plan, "selected": json.dumps(["O1", "O2"])},
            api.adopt: {"insight": plan, "card": "quick_win", "assigned_to": first},
            api.reject: {"insight": plan, "reason": "Too costly"},
        }
        for fn, kwargs in decisions.items():
            with self.subTest(endpoint=fn.__name__):
                self.assertRaises(frappe.PermissionError, fn, **kwargs)
        row = api.update_action(name=action, status="In progress", note="Started the seal check")
        self.assertEqual((row["name"], row["status"], row["assigned_to"]), (action, "In progress", first))
        self.assertIn("Started the seal check", frappe.db.get_value("HD AI Action", action, "notes"))

        frappe.set_user(second)
        self.assertRaises(frappe.PermissionError, api.update_action, name=action, status="Done")
        if inactive:
            frappe.set_user(inactive[0])
            self.assertRaises(frappe.PermissionError, api.get_actions)
            self.assertRaises(frappe.PermissionError, api.get_questions)
        self.assertEqual(frappe.db.get_value("HD AI Action", action, "status"), "In progress")
        for fn in ("combine", "adopt", "reject"):
            getattr(self.advisor, fn).assert_not_called()

    def test_inputs_are_checked(self):
        self.ready()
        plan = self.suggestions()
        action = self.action(assigned_to="Administrator")
        adopt = {"insight": plan, "card": "quick_win", "assigned_to": "Administrator"}
        bad = [
            (api.request_suggestions, {"code": "NOT_A_CODE"}, "Unknown issue code"),
            (api.request_suggestions, {"code": "NEW"}, "Unclassified"),
            (api.request_suggestions, {"code": "DLV_LATE", "from_date": "2026-13-01", "to_date": "2026-06-30"}, "a date"),
            (api.request_research, {"code": "dlv_late"}, "Unknown issue code"),
            (api.preview_problem_card, {"code": "DLV LATE"}, "Unknown issue code"),
            (api.write_summary, {"week": "last week"}, "a date"),
            (api.write_summary, {"week": str(add_days(getdate(), 14))}, "has started"),
            (api.reject, {"insight": plan, "reason": "Bored"}, "Unknown reason"),
            (api.reject, {"insight": plan, "reason": "Other"}, "note"),
            (api.reject, {"insight": "no-such-insight", "reason": "Too costly"}, "no longer exists"),
            (api.combine, {"insight": plan, "selected": json.dumps(["O1", "O9"])}, "Pick options"),
            (api.combine, {"insight": plan, "selected": "O1"}, "a list"),
            (api.adopt, {**adopt, "card": "big_bang"}, "Unknown card"),
            (api.adopt, {**adopt, "assigned_to": "Guest"}, "active agent"),
            (api.adopt, {**adopt, "target": "half"}, "a number"),
            (api.adopt, {**adopt, "due_date": "2020-01-01"}, "past"),
            (api.update_action, {"name": action, "status": "Finished"}, "Unknown status"),
            (api.update_action, {"name": action, "done_on": "2026-01-05"}, "status Done"),
            (api.update_action, {"name": action}, "Nothing to update"),
            (api.get_actions, {"filter": "mine"}, "Unknown filter"),
            (api.ask, {"question": "   "}, "Question"),
            (api.ask, {"question": "x" * 501}, "Question"),
            (api.get_insight, {"name": "no-such-insight"}, "no longer exists"),
        ]
        for fn, kwargs, message in bad:
            with self.subTest(endpoint=fn.__name__, kwargs=kwargs):
                self.assertRaisesRegex(frappe.ValidationError, message, fn, **kwargs)
        frappe.db.set_value("HD AI Insight", plan, "status", "Running")
        self.assertRaisesRegex(frappe.ValidationError, "not ready", api.adopt, **adopt)
        for fn in ("request_suggestions", "combine", "adopt", "reject", "problem_card", "request_research"):
            getattr(self.advisor, fn).assert_not_called()
        self.enqueue.assert_not_called()

    def test_ai_requests_refuse_when_off_down_or_over_budget(self):
        plan = self.suggestions()
        requests = {
            api.request_suggestions: {"code": "DLV_LATE", "from_date": "2026-04-01", "to_date": "2026-04-30"},
            api.request_research: {"code": "DLV_LATE"},
            api.write_summary: {"week": str(WEEK)},
            api.ask: {"question": "How many late deliveries were there in May?"},
            api.combine: {"insight": plan, "selected": json.dumps(["O1", "O2"])},
        }
        questions = frappe.db.count("HD AI Insight", {"insight_type": "Question"})
        for state, message in (
            ((False, True, 50.0), "AI Analysis is off"),
            ((True, False, 50.0), "Background worker not running"),
            ((True, True, 0.0), "Monthly AI budget reached"),
        ):
            with (
                patch.object(api, "analysis_enabled", return_value=state[0]),
                patch.object(jobs, "worker_running", return_value=state[1]),
                patch.object(jobs, "budget_left", return_value=state[2]),
                patch.object(api, "conf", return_value=frappe._dict(api.conf(), web_research=True)),
            ):
                for fn, kwargs in requests.items():
                    with self.subTest(endpoint=fn.__name__, refusal=message):
                        self.assertRaisesRegex(frappe.ValidationError, message, fn, **kwargs)
        for fn in ("request_suggestions", "request_research", "write_summary", "combine"):
            getattr(self.advisor, fn).assert_not_called()
        self.enqueue.assert_not_called()
        self.assertEqual(frappe.db.count("HD AI Insight", {"insight_type": "Question"}), questions)

        with (
            patch.object(jobs, "worker_running", return_value=False),
            patch.object(api, "analysis_enabled", return_value=True),
            patch.object(tagging, "stale_count", return_value=3),
            patch.object(jobs, "start_chain") as start,
        ):
            out = api.publish_version()
        self.assertEqual(out["started"], False)
        self.assertIn("Background worker not running", out["message"])
        start.assert_not_called()

    def test_reuse_and_regenerate(self):
        self.ready()
        done = self.insight(insight_type="Research", issue_code="DLV_LATE")
        self.assertEqual(api.request_research(code="DLV_LATE"), {"insight": done, "reused": True})
        self.advisor.request_research.return_value = "fresh-research"
        self.assertEqual(api.request_research(code="DLV_LATE", regenerate=1), {"insight": "fresh-research", "reused": False})
        self.backdate("HD AI Insight", done, now_datetime() - timedelta(days=31))  # older than 30 days: run again
        self.assertEqual(api.request_research(code="DLV_LATE")["reused"], False)

        summary = self.insight(insight_type="Brief", week_start=WEEK, status="Running")
        self.assertEqual(api.write_summary(week=str(WEEK + timedelta(days=3))), {"insight": summary, "reused": True})
        self.advisor.write_summary.return_value = "fresh-summary"
        self.assertEqual(api.write_summary(week=str(WEEK), regenerate="true")["insight"], "fresh-summary")
        self.advisor.write_summary.assert_called_once_with(WEEK, "Administrator")

        self.advisor.request_suggestions.return_value = ("s-1", True)
        self.assertEqual(api.request_suggestions(code="DLV_LATE", from_date="2026-04-01", to_date="2026-04-30"), {"insight": "s-1", "reused": True})
        args = self.advisor.request_suggestions.call_args
        self.assertEqual((args.args, args.kwargs), (("DLV_LATE", date(2026, 4, 1), date(2026, 4, 30), "Administrator"), {"regenerate": False}))

    def test_adopt_reject_and_combine_reach_the_advisor(self):
        self.ready()
        plan = self.suggestions()
        self.advisor.combine.return_value = "v2"
        self.assertEqual(api.combine(insight=plan, selected=json.dumps(["O2", "O1", "O2"]), note=" only these "), {"insight": "v2"})
        self.advisor.combine.assert_called_once_with(plan, ["O2", "O1"], "only these", "Administrator")
        self.advisor.adopt.return_value = "HD-AIA-TEST"
        out = api.adopt(insight=plan, card="structural_fix", assigned_to="Administrator", due_date=str(add_days(getdate(), 7)), target="2.5")
        self.assertEqual(out, {"action": "HD-AIA-TEST"})
        args = self.advisor.adopt.call_args
        self.assertEqual(args.args, (plan, "structural_fix", "Administrator", "Administrator"))
        self.assertEqual(args.kwargs, {"due_date": add_days(getdate(), 7), "target": 2.5})
        self.action(insight=plan, card="quick_win")
        self.assertRaisesRegex(frappe.ValidationError, "already an action", api.adopt, insight=plan, card="quick_win", assigned_to="Administrator")
        self.assertEqual(api.reject(insight=plan, reason="Other", note="Too slow for summer"), {"ok": True})
        self.advisor.reject.assert_called_once_with(plan, "Other", "Too slow for summer", "Administrator")
        frappe.db.set_value("HD AI Insight", plan, "decision", "Rejected")
        self.assertRaisesRegex(frappe.ValidationError, "already decided", api.reject, insight=plan, reason="Too costly")
        self.assertRaisesRegex(frappe.ValidationError, "was rejected", api.adopt, insight=plan, card="combined_plan", assigned_to="Administrator")

    def test_responses_never_carry_private_keys(self):
        plan = self.suggestions()
        leaky = {"conversation": "MSG-CONV-Fatima Alkhaldi-00042", "customer_key": "ck-secret-1", "phone": "55512345"}
        self.advisor.insight_projection.return_value = {
            "name": plan,
            "output": {"evidence": [{"id": "E1", "ref": "abc123", **leaky}]},
            "alias_map": {"E1": "abc123"},
            "input_json": "{}",
        }
        self.advisor.problem_card.return_value = {"card": "Late delivery in Qatar", "checks": [], "ok": True, **leaky}
        out = api.get_insight(name=plan)
        self.assertEqual(out["output"]["evidence"][0]["ref"], "abc123")
        payloads = [out, api.preview_problem_card(code="DLV_LATE"), api.get_actions(filter="all"), api.get_decisions()]
        payloads.append(api.get_questions())
        self.loaders([])
        payloads.append(api.get_operations(from_date="2026-04-01", to_date="2026-04-30"))
        blob = json.dumps(payloads, default=str, ensure_ascii=False)
        for secret in ("MSG-CONV", "Fatima", "ck-secret", "55512345", "77719", "alias_map", "input_json", "customer_key"):
            self.assertNotIn(secret, blob)

    # --- reads ------------------------------------------------------------------------------------

    def test_get_questions_is_this_users_last_20(self):
        mine = [self.insight(insight_type="Question", question=f"Question {i}") for i in range(22)]
        declined = self.insight(insight_type="Question", question="Rare one", output_json={"declined": TOO_FEW})
        plain, _inactive = _users()
        theirs = self.insight(insight_type="Question", question="Someone else's", requested_by=plain[0]) if plain else None
        out = api.get_questions()
        self.assertEqual(len(out), 20)
        self.assertEqual(out[0], {**out[0], "insight": declined, "question": "Rare one", "declined": TOO_FEW})
        self.assertLessEqual({q["insight"] for q in out}, {*mine, declined})
        self.assertEqual(set(out[0]), {"insight", "question", "status", "creation", "declined"})
        if theirs:
            frappe.set_user(plain[0])
            names = {q["insight"] for q in api.get_questions()}
            self.assertIn(theirs, names)
            self.assertFalse(names & {*mine, declined})

    def test_decision_log_and_action_filters(self):
        adopted = self.suggestions(decision="Adopted", decided_by="Administrator", decided_on=now_datetime() - timedelta(days=1))
        rejected = self.suggestions(
            code="PKG_LEAK", decision="Rejected", decision_reason="Too costly", decided_by="Administrator", decided_on=now_datetime()
        )
        self.suggestions()  # still Pending: not in the log
        log = [d for d in api.get_decisions() if d["insight"] in (adopted, rejected)]
        self.assertEqual([d["insight"] for d in log], [rejected, adopted])
        self.assertEqual(
            {k: log[0][k] for k in ("issue_code", "decision", "decision_reason", "decided_by_name")},
            {"issue_code": "PKG_LEAK", "decision": "Rejected", "decision_reason": "Too costly", "decided_by_name": "Administrator"},
        )
        self.assertEqual(log[0]["label"], metrics._meta()["PKG_LEAK"].label)

        today = getdate()
        names = {
            "overdue": self.action(due_date=add_days(today, -1)),
            "going": self.action(status="In progress", due_date=add_days(today, 6)),
            "verifying": self.action(status="Done", done_on=add_days(today, -10)),
            "checked": self.action(status="Done", done_on=add_days(today, -120), verdict="Lower than before", verdict_checked_on=add_days(today, -40)),
            "dropped": self.action(status="Dropped"),
        }
        mine = set(names.values())

        def shown(f):
            return {r["name"] for r in api.get_actions(filter=f) if r["name"] in mine}

        self.assertEqual(shown("open"), {names["overdue"], names["going"]})
        self.assertEqual(shown("overdue"), {names["overdue"]})
        self.assertEqual(shown("verifying"), {names["verifying"]})
        self.assertEqual(shown("all"), mine)
        rows = {r["name"]: r for r in api.get_actions(filter="all")}
        self.assertEqual(rows[names["verifying"]]["next_check"], str(add_days(today, 25)))  # done + 7 days + 4 weeks
        self.assertIsNone(rows[names["checked"]]["next_check"])  # both checks ran
        self.assertEqual((rows[names["overdue"]]["overdue"], rows[names["going"]]["overdue"]), (True, False))
        keys = {"name", "title", "issue_code", "label", "owner_department", "assigned_to", "assigned_to_name", "status"}
        keys |= {"due_date", "overdue", "baseline_value", "recent_value", "target_value", "exposure_kind", "verdict"}
        keys |= {"verdict_p", "target_met", "next_check", "recurred", "insight", "plan", "verdict_history"}
        self.assertLessEqual(keys, set(rows[names["overdue"]]))

        row = api.update_action(name=names["going"], status="Done")  # a decider; done_on defaults to today
        self.assertEqual((row["status"], row["done_on"], row["next_check"]), ("Done", str(today), str(add_days(today, 35))))
        row = api.update_action(name=names["going"], status="In progress")
        self.assertEqual((row["done_on"], row["next_check"]), (None, None))

    def test_issue_detail_carries_the_latest_suggestions_research_and_action(self):
        self.loaders([_row("DLV_LATE", "2026-04-05 10:00", "k1")])
        older = self.suggestions(status="Failed")
        self.backdate("HD AI Insight", older, now_datetime() - timedelta(days=3))
        latest = self.suggestions()
        research = self.insight(insight_type="Research", issue_code="DLV_LATE")
        self.advisor.action_state = lambda code: {"name": "HD-AIA-1", "status": "Open", "overdue": False, "verdict": "Not yet"}
        self.advisor.suggestion_state = lambda code: {"insight": latest, "status": "Done", "decision": "Pending"}
        detail = metrics.issue_detail("DLV_LATE", "2026-04-01", "2026-04-30")
        self.assertEqual({k: detail["suggestions"][k] for k in ("insight", "status", "decision")}, {"insight": latest, "status": "Done", "decision": "Pending"})
        self.assertIn("created", detail["suggestions"])
        self.assertEqual(detail["research"]["insight"], research)
        self.assertEqual(detail["action"]["name"], "HD-AIA-1")
        self.assertIsNone(metrics.issue_detail("PKG_LEAK", "2026-04-01", "2026-04-30")["research"])
        row = metrics.overview("2026-04-01", "2026-04-30")["issues"][0]
        self.assertEqual((row["action"]["name"], row["suggestions"]["insight"]), ("HD-AIA-1", latest))

        def broken(code):
            raise RuntimeError("advisor bug")

        self.advisor.action_state = broken
        _fresh()
        self.assertIsNone(metrics.overview("2026-04-01", "2026-04-30")["issues"][0]["action"])  # never breaks the page

    def test_dish_flag_needs_three_matched_cases(self):
        rows = [_row("DLV_LATE", f"2026-04-{d:02d} 12:00", f"d{d}", dish_item="Chicken Biryani") for d in (5, 6)]
        rows += [_row("DLV_LATE", "2026-04-07 12:00", "d7")]
        self.loaders(rows)
        with patch.object(metrics, "_meals", return_value=Counter({"chicken biryani": 300, "everything else": 99700})):
            dishes = metrics.issue_detail("DLV_LATE", "2026-04-01", "2026-04-30")["where"]["dishes"]
            self.assertEqual([(d["cases"], d["flag"]) for d in dishes], [(2, False)])  # p < 0.01, 300 meals, 2 cases
            rows.append(_row("DLV_LATE", "2026-04-08 12:00", "d8", dish_item="Chicken Biryani"))
            _fresh()
            dishes = metrics.issue_detail("DLV_LATE", "2026-04-01", "2026-04-30")["where"]["dishes"]
            self.assertEqual([(d["cases"], d["flag"]) for d in dishes], [(3, True)])

    # --- Brief ------------------------------------------------------------------------------------

    def test_brief_headline_switches_to_a_done_summary(self):
        self.loaders([])
        self.assertEqual(metrics.brief(WEEK)["headline"]["source"], "code")
        output = {"headline": "Complaints held at {{kpi.cases}}.", "values": {"kpi.cases": "4"}, "bullets": [], "fallback": False}
        name = self.insight(insight_type="Brief", week_start=WEEK, models="openai/gpt-4.1", output_json=output)
        _fresh()
        head = metrics.brief(WEEK)["headline"]
        self.assertEqual(
            {k: head[k] for k in ("source", "text", "values", "model", "insight")},
            {"source": "ai", "text": output["headline"], "values": output["values"], "model": "openai/gpt-4.1", "insight": name},
        )
        self.assertIn("Complaints held at 4.", api._brief_html(metrics.brief(WEEK)))  # the PDF fills placeholders
        for values in ({"output_json": json.dumps({**output, "fallback": True})}, {"status": "Running"}, {"week_start": WEEK - timedelta(weeks=1)}):
            frappe.db.set_value("HD AI Insight", name, {"output_json": json.dumps(output), "status": "Done", "week_start": WEEK, **values})
            _fresh()
            self.assertEqual(metrics.brief(WEEK)["headline"]["source"], "code", values)

    def test_decisions_needed_are_built_by_code(self):
        def at(day, hour=9):
            return datetime.combine(day, time(hour))

        four = [WEEK - timedelta(weeks=i) for i in range(4)]
        rows = [_row("DLV_LATE", at(w + timedelta(days=1)), f"late-{i}") for i, w in enumerate(four)]
        rows += [_row("PKG_LEAK", at(w + timedelta(days=2)), f"leak-{i}") for i, w in enumerate(four)]
        rows += [_row("FS_SPOILED", at(WEEK + timedelta(days=d)), f"fs-{d}", "S2") for d in (1, 3)]
        rows += [_row("SUB_CANCEL_INTENT", at(WEEK + timedelta(days=d), h), c) for d, h, c in ((1, 9, "c1"), (2, 9, "c2"), (4, 11, "c1"))]
        rows += [_row("NEW", at(WEEK + timedelta(days=2)), "n1", proposed_label="Gift card")]
        rows.sort(key=lambda r: r["at"])
        self.loaders(rows)
        today, cancel = getdate(), [r["contact"] for r in rows if r["code"] == "SUB_CANCEL_INTENT"]
        overdue = self.action(due_date=add_days(today, -3), assigned_to="Administrator", owner_department="Operations & Packing")
        higher = self.action(issue_code="ACC_WRONG_MEAL", status="Done", done_on=add_days(today, -70), verdict="Higher than before", verdict_checked_on=add_days(today, -1))
        recurred = self.action(issue_code="QLT_REPETITION", status="Done", done_on=add_days(today, -200), recurred=1, verdict_checked_on=add_days(today, -100))
        waiting = self.suggestions()
        self.backdate("HD AI Insight", waiting, now_datetime() - timedelta(days=3))
        self.suggestions(code="FS_SPOILED")  # 0 days old: not waiting yet
        exclusion = frappe.get_doc({"doctype": "HD AI Exclusion", "exclusion_type": "Contact", "value": frappe.generate_hash(length=10), "reason": "Staff test"})
        exclusion.insert(ignore_permissions=True)
        self.backdate("HD AI Exclusion", exclusion.name, at(WEEK + timedelta(days=2)))

        with patch.object(tagging, "stale_count", return_value=5):
            b = metrics.brief(WEEK)
        decisions = b["decisions"]
        kinds = {d["kind"] for d in decisions}
        expected = {"safety_event", "safety_cluster", "problem_no_action", "plan_waiting", "action_overdue", "verdict_higher"}
        expected |= {"recurred", "cancel_intent", "stopped_feed", "capture_gap", "exclusions_added", "unclassified", "registry_unpublished"}
        self.assertLessEqual(expected, kinds)
        self.assertEqual([d["kind"] for d in decisions][:2], ["safety_event", "safety_cluster"])  # safety first
        no_action = {d["issue"] for d in decisions if d["kind"] == "problem_no_action"}
        self.assertIn("DLV_LATE", no_action)
        self.assertNotIn("PKG_LEAK", no_action)  # it has an open (if overdue) action
        self.assertEqual([d["issue"] for d in decisions if d["kind"] == "plan_waiting"], ["DLV_LATE"])
        by_action = {d["action"]: d["kind"] for d in decisions if d["action"]}
        self.assertEqual((by_action[overdue], by_action[higher], by_action[recurred]), ("action_overdue", "verdict_higher", "recurred"))
        callback = next(d for d in decisions if d["kind"] == "cancel_intent")
        self.assertEqual(callback["refs"], [cancel[2], cancel[1]])  # one ref per customer: their latest contact
        self.assertTrue(callback["text"].startswith("2 customers said they would cancel"))
        self.assertTrue(all(set(d) == {"kind", "text", "tab", "issue", "action", "refs"} for d in decisions))
        self.assertTrue({d["tab"] for d in decisions} <= {"brief", "issues", "actions", "health"})
        self.assertIn("Administrator", next(d["text"] for d in decisions if d["kind"] == "exclusions_added"))
        acts = b["actions"]
        self.assertEqual([a["name"] for a in acts["overdue"]], [overdue])
        self.assertIn(higher, [a["name"] for a in acts["verdicts"]])
        self.assertEqual([a["name"] for a in acts["recurred"]], [recurred])
        blob = json.dumps(b, ensure_ascii=False)
        for secret in ("late-0", "leak-1", "fs-1", "c1", "c2"):  # customer keys
            self.assertNotIn(f'"{secret}"', blob)

    def test_brief_pdf_has_no_quotes(self):
        quote = "the chicken smelled off and the box was warm"
        rows = [_row("FS_SPOILED", datetime.combine(WEEK + timedelta(days=d), time(12)), f"q{d}", "S2", quote=quote, quote_en=quote) for d in (0, 2)]
        self.loaders(rows)
        b = metrics.brief(WEEK)
        self.assertIn(quote, json.dumps(b))  # the page shows the quotes
        html = api._brief_html(b)
        self.assertTrue(html.startswith("<!DOCTYPE html>"))
        self.assertNotIn("smelled", html)
        self.assertIn("<svg", html)
        self.addCleanup(setattr, frappe.local, "response", frappe.local.response)
        frappe.local.response = frappe._dict()
        api.download_brief(week=str(WEEK))
        self.assertEqual((frappe.local.response.type, frappe.local.response.filename), ("download", f"ai-analysis-brief-{WEEK}.pdf"))
        self.assertTrue(frappe.local.response.filecontent.startswith(b"%PDF"))

    # --- Operations -------------------------------------------------------------------------------

    def test_operations_shape_and_coverage_rules(self):
        def contact(source, day, status="Tagged", live=True):
            at = datetime.combine(day, time(10))
            return frappe._dict(name=frappe.generate_hash(length=10), source=source, status=status, live=live, started_on=at)

        june = date(2026, 6, 22)
        contacts = [contact("Chat", june) for _ in range(3)] + [contact("Ticket", june), contact("Chat", june, "Excluded"), contact("Chat", june, live=False)]
        self.loaders([], {c.name: c for c in contacts})
        ops = metrics.operations("2026-06-01", "2026-07-31")
        months = {m["month"]: m for m in ops["copq"]["months"]}
        self.assertEqual(months["2026-06"], {"month": "2026-06", "refunds_n": 1, "refunds_qar": 30.0, "replacements_n": 2, "replacements_cost": 12.5, "replacements_value": 60.0, "per_1000": round(2 / (27 * 400) * 1000, 2)})
        self.assertEqual((months["2026-07"]["refunds_n"], months["2026-07"]["replacements_n"], months["2026-07"]["per_1000"]), (1, None, None))
        weeks = {w["week"]: w for w in ops["contact_load"]["weeks"]}
        self.assertEqual(weeks["2026-06-21"], {"week": "2026-06-21", "chat_sessions": 3, "ticket_contacts": 1, "answered_calls": 7, "deliveries": 2800, "per_1000": round(11 / 2800 * 1000, 2)})
        self.assertEqual({k: weeks["2026-06-28"][k] for k in ("chat_sessions", "answered_calls", "deliveries", "per_1000")}, dict.fromkeys(("chat_sessions", "answered_calls", "deliveries", "per_1000")))
        self.assertEqual(ops["repeat_callers"], {"callers": 27, "repeat_callers": 0, "share": 0.0})  # 1-27 Jun, one call each
        self.assertIn(metrics.MISSED_CALLS, ops["captions"])
        self.assertNotIn("77719", json.dumps(ops))
        nothing = metrics.operations("2026-09-01", "2026-09-30")
        self.assertEqual(nothing["repeat_callers"], {"callers": None, "repeat_callers": None, "share": None})

    def test_operations_numbers_on_real_data(self):
        """Read-only, against the mid-2026 production snapshot the plan was checked on."""
        april = {"docstatus": 1, "posting_date": ["between", ["2026-04-01", "2026-04-30"]]}
        if frappe.db.count("Delivery Note", april) < 10000:
            self.skipTest("needs the mid-2026 production snapshot (April 2026 deliveries)")
        _fresh()
        self.assertEqual(metrics._delivery(date(2026, 4, 1), date(2026, 4, 30))[0], 13289)
        month = metrics.operations("2026-04-01", "2026-04-30")["copq"]["months"][0]
        self.assertEqual((month["refunds_n"], month["refunds_qar"]), (3, 212.0))
        year = metrics.operations("2026-01-01", "2026-12-31")["copq"]["months"]
        self.assertEqual(sum(m["replacements_n"] or 0 for m in year), 39)
        self.assertAlmostEqual(sum(m["replacements_cost"] or 0 for m in year), 228.52, places=2)
        self.assertAlmostEqual(sum(m["replacements_value"] or 0 for m in year), 1130.0, places=2)

    # --- Ask ----------------------------------------------------------------------------------------

    def test_plan_is_checked_against_the_enums_and_clamped(self):
        lo, hi, active = date(2026, 1, 4), date(2026, 6, 27), {"DLV_LATE", "PKG_LEAK"}
        raw = {"codes": ["PKG_LEAK", "DLV_LATE", "DROP TABLE", "NEW", 7, {"x": 1}], "kinds": ["Complaint", "Gossip"]}
        raw.update(channels=["WhatsApp", "Fax"], group_by="month", metric="vibes", **{"from": "2025-01-01", "to": "2026-03-31"})
        plan, note = ask.clean_plan(raw, active, lo, hi)
        self.assertEqual(
            plan,
            {"codes": ["DLV_LATE", "PKG_LEAK"], "kinds": ["Complaint"], "channels": ["WhatsApp"], "from": lo, "to": date(2026, 3, 31), "group_by": "week", "metric": "cases"},
        )
        self.assertIsNone(note)
        swapped, _note = ask.clean_plan({"from": "2026-05-31", "to": "2026-02-01", "group_by": "dish", "metric": "rate"}, active, lo, hi)
        self.assertEqual((swapped["from"], swapped["to"], swapped["group_by"], swapped["metric"]), (date(2026, 2, 1), date(2026, 5, 31), "dish", "rate"))
        blank, _note = ask.clean_plan({"from": "", "to": "next Tuesday"}, active, lo, hi)
        self.assertEqual((blank["from"], blank["to"]), (lo, hi))
        later, note = ask.clean_plan({"from": "2026-10-01", "to": "2026-10-31"}, active, lo, hi)
        self.assertEqual((later["from"], later["to"]), (hi - timedelta(days=27), hi))
        self.assertIn("latest 28 days", note)
        junk, _note = ask.clean_plan("not a plan", active, lo, hi)
        self.assertEqual(junk, {"codes": [], "kinds": [], "channels": [], "from": lo, "to": hi, "group_by": "week", "metric": "cases"})

    def test_ask_table_follows_the_page_case_rules(self):
        rows = [_row("DLV_LATE", "2026-05-18 09:00", "k1"), _row("PKG_LEAK", "2026-05-18 09:00", "k1")]
        rows += [_row("DLV_LATE", "2026-05-20 09:00", "k1"), _row("DLV_LATE", "2026-05-26 09:00", "k2", channel="WhatsApp")]
        self.loaders(rows)
        plan = {**PLAN, "codes": [], "kinds": ["Complaint"]}
        table = metrics.ask_table({**plan, "from": date(2026, 5, 17), "to": date(2026, 6, 13)})
        self.assertEqual(table["columns"], ["Week starting", "Cases", "Customers"])
        self.assertEqual(table["rows"], [["17 May 2026", 1, 1], ["24 May 2026", 1, 1], ["31 May 2026", 0, 0], ["7 Jun 2026", 0, 0]])
        self.assertEqual(table["n_cases"], 2)  # code-agnostic: k1's three labels are one case
        self.assertIn("across these issues", table["filters_text"])
        by_code = metrics.ask_table({**plan, "group_by": "code", "from": date(2026, 5, 17), "to": date(2026, 5, 30)})
        self.assertEqual(by_code["rows"], [[metrics._meta()["DLV_LATE"].label, 2, 2], [metrics._meta()["PKG_LEAK"].label, 1, 1]])
        rate = metrics.ask_table({**PLAN, "group_by": "channel", "metric": "rate", "from": date(2026, 5, 17), "to": date(2026, 5, 30)})
        self.assertEqual(rate["rows"], [["Instagram DM", 1, 1, round(1 / 5600 * 1000, 2)], ["WhatsApp", 1, 1, round(1 / 5600 * 1000, 2)]])
        late = metrics.ask_table({**PLAN, "metric": "rate", "from": date(2026, 6, 21), "to": date(2026, 7, 11)})
        self.assertEqual(late["columns"], ["Week starting", "Cases", "Customers"])  # deliveries stop 27 Jun: no rate
        self.assertIn("no rate", late["filters_text"])
        self.assertEqual(late["rows"][1:], [["28 Jun 2026", None, None], ["5 Jul 2026", None, None]])  # no chat data: never 0

    def test_ask_scrubs_the_question_and_declines_below_three_cases_without_a_second_call(self):
        self.ready()
        self.loaders([_row("DLV_LATE", "2026-05-18 09:00", "k1"), _row("DLV_LATE", "2026-05-25 09:00", "k2")])
        post = self.model([PLAN])
        with patch.object(ask.cases, "known_names", return_value={"fatima"}):
            name = api.ask(question="Fatima on 55123456 asks: how many late deliveries in late May?")["insight"]
        doc = frappe.get_doc("HD AI Insight", name)
        self.assertEqual((doc.insight_type, doc.status, doc.requested_by), ("Question", "Queued", "Administrator"))
        self.assertEqual(doc.question, "[name] on [phone] asks: how many late deliveries in late May?")
        call = self.enqueue.call_args
        self.assertEqual((call.args[0], call.kwargs["job_id"], call.kwargs["insight"]), ("helpdesk.ai_analysis.ask.run_ask", f"hd-ai::ask::{name}::1", name))

        self.enqueue.reset_mock()
        ask.run_ask(insight=name, step=1)
        self.log_error.assert_not_called()
        doc.reload()
        out = json.loads(doc.output_json)
        self.assertEqual((doc.status, out["n_cases"], out["declined"], out["answer"]), ("Done", 2, TOO_FEW, ""))
        self.assertEqual(out["plan"], {**PLAN, "from": "2026-05-17", "to": "2026-05-30"})
        self.assertEqual(out["table"]["rows"], [["17 May 2026", 1, 1], ["24 May 2026", 1, 1]])
        self.assertEqual(post.call_count, 1)  # no second call
        self.enqueue.assert_not_called()
        body = post.call_args.kwargs["json"]
        self.assertEqual((body["provider"]["data_collection"], body["temperature"], body["max_tokens"]), ("deny", 0, 1200))
        self.assertTrue(body["response_format"]["json_schema"]["strict"])
        content = body["messages"][1]["content"]
        self.assertNotIn("Fatima", content)
        self.assertNotIn("55123456", content)
        sent = json.loads(content)
        self.assertEqual(sent["question"], doc.question)
        self.assertEqual(set(sent["registry"][0]), {"code", "label", "kind"})
        self.assertEqual(doc.cost_usd, 0.002)
        self.assertEqual(json.loads(doc.input_json)["plan"], sent)

    def test_ask_answers_with_placeholders_after_one_repair(self):
        rows = [_row("DLV_LATE", f"2026-05-{d:02d} 09:00", f"k{d}") for d in (17, 18, 19, 24, 25)]
        self.loaders(rows)
        bad = {"answer": "There were 5 late deliveries, double the week before.", "cites": ["E1"]}
        good = {"answer": "Late deliveries came to {{total.cases}} cases, {{r2.cases}} in the week of {{r2.group}}.", "cites": ["E2", "E1"]}
        post = self.model([PLAN, bad, good])
        name = ask.ask("How many late deliveries in late May?", "Administrator")
        ask.run_ask(insight=name, step=1)
        self.assertEqual(self.enqueue.call_args.kwargs["job_id"], f"hd-ai::ask::{name}::2")
        ask.run_ask(insight=name, step=2)
        self.log_error.assert_not_called()
        doc = frappe.get_doc("HD AI Insight", name)
        out = json.loads(doc.output_json)
        self.assertEqual((doc.status, out["answer"], out["declined"]), ("Done", good["answer"], None))
        self.assertEqual([e["id"] for e in out["evidence"]], ["E1", "E2"])
        self.assertEqual({k: out["values"][k] for k in ("total.cases", "r2.cases", "r2.group")}, {"total.cases": "5", "r2.cases": "2", "r2.group": "24 May 2026"})
        self.assertEqual(post.call_count, 3)
        answer = post.call_args_list[1].kwargs["json"]
        self.assertEqual(answer["response_format"]["json_schema"]["schema"]["properties"]["cites"]["items"]["enum"], ["E1", "E2", "E3", "E4", "E5"])
        sent = json.loads(answer["messages"][1]["content"])
        self.assertEqual(set(sent["quotes"][0]), {"id", "issue", "channel", "quote", "english"})  # no contact refs
        repair = json.loads(post.call_args_list[2].kwargs["json"]["messages"][1]["content"])
        self.assertEqual(repair["previous_answer"], bad["answer"])
        self.assertTrue(repair["problems"])
        self.assertEqual(set(json.loads(doc.alias_map)), {"E1", "E2", "E3", "E4", "E5"})
        self.assertAlmostEqual(doc.cost_usd, 0.006)

        post = self.model([PLAN, bad, {"answer": "See {{r9.cases}} for the answer.", "cites": []}])
        name = ask.ask("How many late deliveries in late May?", "Administrator")
        ask.run_ask(insight=name, step=1)
        ask.run_ask(insight=name, step=2)
        out = json.loads(frappe.db.get_value("HD AI Insight", name, "output_json"))
        self.assertEqual((out["answer"], out["evidence"], out["declined"]), ("", [], UNRELIABLE))
        self.assertEqual(len(out["table"]["rows"]), 2)  # the exact table stands alone

    def test_answer_errors(self):
        values, ids = {"r1.cases": "4", "total.cases": "9"}, ["E1", "E2"]
        self.assertEqual(ask.answer_errors({"answer": "Late deliveries: {{r1.cases}} of {{total.cases}}.", "cites": ["E2"]}, values, ids), [])
        self.assertEqual(ask.answer_errors({"answer": " ", "cites": []}, values, ids), ["The answer is empty."])
        self.assertTrue(ask.answer_errors({"answer": "There were ٤ cases.", "cites": []}, values, ids))  # Arabic-Indic digit
        self.assertTrue(ask.answer_errors({"answer": "{{r1.cases}} cases.", "cites": ["E7"]}, values, ids))
        self.assertTrue(ask.answer_errors({"answer": "{{r3.cases}} cases.", "cites": []}, values, ids))
        self.assertTrue(ask.answer_errors("not a reply", values, ids))
