"""Jobs and endpoints: the failure wrapper, DB claims, the chain's job ids, the budget and rate-limit stops,
publish, roles, open_case and the browser-payload leak guard.

cases.lines_for and tagging.tag_contact are patched (no model call), and so are frappe.db.commit/rollback
(each test is rolled back), frappe.enqueue and the hd-ai:* cache keys, so the live site's chain state is
never touched. Real HD AI Contact rows exist on the site: every claim here is limited to the test's own rows
through chunk's `_only`, and the leak test runs the real metrics over synthetic contacts.
"""

import json
import re
from collections import defaultdict
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, now_datetime

from helpdesk.ai_analysis import cases, jobs, metrics, tagging
from helpdesk.api import ai_analysis as api
from helpdesk.api.ticket_ai import TicketAIError

CONTACT = "HD AI Contact"
CONVERSATION = "MSG-CONV-Test Person-00001"
LINES = [{"id": "L1", "role": "customer", "text": "the driver came very late again"}]
RATE_LIMITED = "The AI provider is rate limiting us. Please try again in a moment."


class FakeCache:
    """hd-ai:* keys live in a dict; every other key goes to the real cache."""

    def __init__(self, real):
        self.real, self.data = real, {}

    def __getattr__(self, name):
        return getattr(self.real, name)

    def __call__(self):  # old-style frappe.cache(), still used by installed apps
        return self

    def get_value(self, key, *args, **kwargs):
        return self.data.get(key) if key.startswith("hd-ai:") else self.real.get_value(key, *args, **kwargs)

    def set_value(self, key, value, *args, **kwargs):
        if key.startswith("hd-ai:"):
            self.data[key] = value
        else:
            self.real.set_value(key, value, *args, **kwargs)

    def delete_value(self, key, *args, **kwargs):
        if isinstance(key, str) and key.startswith("hd-ai:"):
            self.data.pop(key, None)
        else:
            self.real.delete_value(key, *args, **kwargs)


class TestJobsAPI(FrappeTestCase):
    def setUp(self):
        super().setUp()
        self.addCleanup(frappe.db.rollback)  # the real one: cleanups run last-in first-out, after the patches end
        self.enterContext(patch.object(frappe.db, "commit"))
        self.enterContext(patch.object(frappe.db, "rollback"))
        # tabError Log is MyISAM here, so a rollback would not undo a real log row
        self.log_error = self.enterContext(patch.object(frappe, "log_error"))
        self.enqueue = self.enterContext(patch.object(frappe, "enqueue"))
        self.cache = FakeCache(frappe.cache)
        self.enterContext(patch.object(frappe, "cache", self.cache))
        self.enterContext(patch.object(jobs, "analysis_enabled", return_value=True))
        self.budget = self.enterContext(patch.object(jobs, "budget_left", return_value=50.0))
        self.enterContext(patch.object(cases, "lines_for", side_effect=lambda names: {n: LINES for n in names}))
        self.tagged = []
        self.tag = self.enterContext(patch.object(tagging, "tag_contact", side_effect=self.fake_tag))

    def fake_tag(self, name, lines):
        self.tagged.append(name)
        values = {"status": "Tagged", "claim_token": "", "claimed_at": None}
        frappe.db.set_value(CONTACT, name, values, update_modified=False)
        return {"issues": 1, "cost": 0.001}

    def contacts(self, n, **values):
        """n synthetic Pending chat contacts, newest first."""
        names = []
        for i in range(n):
            doc = {
                "doctype": CONTACT,
                "source_key": frappe.generate_hash(length=20),
                "source": "Chat",
                "conversation": CONVERSATION,
                "channel": "Instagram DM",
                "started_on": add_days(now_datetime(), -i),
                "status": "Pending",
                "has_text": 1,
                "text_hash": cases.text_hash(LINES),
                **values,
            }
            names.append(frappe.get_doc(doc).insert(ignore_permissions=True).name)
        return names

    def rows(self, names):
        fields = ["name", "status", "attempts", "error", "claim_token"]
        return {r.name: r for r in frappe.get_all(CONTACT, filters={"name": ("in", names)}, fields=fields)}

    def logged(self, title):
        """The message of the last log_error call with this title: exactly what the Error Log row stores."""
        calls = [c.kwargs for c in self.log_error.call_args_list if c.kwargs.get("title") == title]
        self.assertEqual(len(calls), 1, title)
        return calls[0]["message"]

    def test_safe_logs_type_and_stage_only_marks_failed_and_never_raises(self):
        (name,) = self.contacts(1, status="Tagging")
        secret = "Bearer sk-or-v1-abc123: العميل قال الأكل خربان, Test Person"

        @jobs.safe("suggest")
        def failing_job(contact):
            raise RuntimeError(secret)

        self.assertIsNone(failing_job(contact=name))
        row = self.rows([name])[name]
        self.assertEqual(row.status, "Failed")
        self.assertEqual(row.error, "AI Analysis suggest failed (RuntimeError). See the Error Log.")
        log = self.logged("AI Analysis suggest failed")
        self.assertRegex(log, rf"^RuntimeError at test_jobs_api\.py:failing_job:\d+ \({name}, HTTP None\)$")
        for leak in ("Bearer", "sk-or", "Test Person", secret):
            self.assertNotIn(leak, log)
        self.assertIsNone(re.search(r"[\u0600-\u06ff]", log))  # no Arabic letters

        @jobs.safe("tag")
        def rate_limited(run, n):
            raise TicketAIError(RATE_LIMITED, http_status=429)

        rate_limited(run="r1", n=0)
        self.assertRegex(self.logged("AI Analysis tag failed"), r"^TicketAIError at .+ \(run=r1 n=0, HTTP 429\)$")
        self.assertEqual(self.cache.data[jobs.STOPPED], RATE_LIMITED)  # a chain job with no record stops the chain

    def test_claims_prevent_double_tagging(self):
        names = self.contacts(12)
        second = []

        def tag(name, lines):
            self.fake_tag(name, lines)
            if not second:  # a second chain starts while the first is mid-batch
                second.append(name)
                jobs.chunk(run="second", n=0, _only=names)

        self.tag.side_effect = tag
        jobs.chunk(run="first", n=0, _only=names)
        jobs.chunk(run="third", n=0, _only=names)
        self.assertEqual(sorted(self.tagged), sorted(names))  # every contact exactly once
        self.assertEqual({r.status for r in self.rows(names).values()}, {"Tagged"})
        self.enqueue.assert_not_called()  # nothing left, so no chunk n+1

    def test_each_chain_step_gets_its_own_job_id(self):
        names = self.contacts(3)
        clock = SimpleNamespace(t=0.0)
        self.enterContext(patch.object(jobs, "time", SimpleNamespace(monotonic=lambda: clock.t)))

        def slow_tag(name, lines):  # each model call takes 100 s
            clock.t += 100
            return self.fake_tag(name, lines)

        self.tag.side_effect = slow_tag

        with patch.object(jobs, "_running", return_value=False), patch.object(cases, "build_contacts") as build:
            run = jobs.start_chain("test", "Administrator")["run"]
            jobs.build(run=run)
        build.assert_called_once()
        jobs.chunk(run=run, n=0, _only=names)  # 150 s budget: two contacts at 100 s each, then hand over
        self.assertEqual(len(self.tagged), 2)
        jobs.chunk(run=run, n=1, _only=names)
        self.assertEqual(len(self.tagged), 3)

        ids = [c.kwargs["job_id"] for c in self.enqueue.call_args_list]
        self.assertEqual(ids, [f"hd-ai::build::{run}", f"hd-ai::tag::{run}::0", f"hd-ai::tag::{run}::1"])
        for c in self.enqueue.call_args_list:
            self.assertEqual(
                (c.kwargs["queue"], c.kwargs["timeout"], c.kwargs["deduplicate"], c.kwargs["enqueue_after_commit"]),
                ("long", 360, True, True),
            )
        self.assertEqual(self.enqueue.call_args_list[2].kwargs["_only"], names)
        self.assertNotIn(jobs.HEARTBEAT, self.cache.data)  # the chain is done

    def test_budget_stop_releases_the_rest_and_ends_the_chain(self):
        names = self.contacts(3)
        self.budget.side_effect = [1.0, 0.0]
        jobs.chunk(run="b", n=0, _only=names)
        self.assertEqual(self.tagged, names[:1])
        self.assertEqual([self.rows(names)[n].status for n in names], ["Tagged", "Pending", "Pending"])
        self.assertEqual(self.cache.data[jobs.STOPPED], "Monthly AI budget reached")
        self.assertNotIn(jobs.HEARTBEAT, self.cache.data)
        self.enqueue.assert_not_called()

    def test_three_rate_limits_in_a_row_stop_the_chain(self):
        names = self.contacts(5)
        self.tag.side_effect = TicketAIError(RATE_LIMITED, http_status=429)
        jobs.chunk(run="rl", n=0, _only=names)
        rows = self.rows(names)
        for name in names[:3]:  # newest first: three attempts, then the stop
            self.assertEqual((rows[name].status, rows[name].attempts, rows[name].error), ("Pending", 1, RATE_LIMITED))
        for name in names[3:]:
            self.assertEqual((rows[name].status, rows[name].attempts, rows[name].claim_token), ("Pending", 0, None))
        self.assertEqual(self.cache.data[jobs.STOPPED], RATE_LIMITED)
        self.enqueue.assert_not_called()

    def test_a_changed_source_goes_back_to_pending_without_looping(self):
        names = self.contacts(2)
        frappe.db.set_value(CONTACT, names[1], "text_hash", "changed since the build", update_modified=False)
        jobs.chunk(run="cs", n=0, _only=names)
        self.assertEqual(self.tagged, names[:1])
        self.assertEqual((self.rows(names)[names[1]].status, self.rows(names)[names[1]].claim_token), ("Pending", "skip:cs"))
        self.enqueue.assert_not_called()  # only the skipped contact is Pending: no endless chain

    def test_publish_refuses_over_budget(self):
        (name,) = self.contacts(1, status="Tagged", tagged_version="tag-v1:old")
        self.budget.return_value = 5.0
        with (
            patch.object(api, "analysis_enabled", return_value=True),
            patch.object(tagging, "current_version", return_value="tag-v1:new"),
            patch.object(tagging, "stale_count", return_value=1000),
            patch.object(jobs, "start_chain") as start,
        ):
            out = api.publish_version()
        self.assertFalse(out["started"])
        self.assertIn(f"${1000 * metrics.USD_PER_CONTACT:.2f}", out["message"])
        self.assertIn("$5.00", out["message"])
        start.assert_not_called()
        self.assertEqual(self.rows([name])[name].status, "Tagged")

    def test_reader_denies_a_deactivated_agent_and_allows_a_role_only_one(self):
        with patch.object(frappe.db, "get_value", return_value=0) as get_value:
            self.assertRaises(frappe.PermissionError, api._reader)
            self.assertRaises(frappe.PermissionError, api.get_status)
        get_value.assert_called_with("HD Agent", {"user": frappe.session.user}, "is_active")
        for active in (None, 1):  # no HD Agent row (a role-only agent), or an active one
            with patch.object(frappe.db, "get_value", return_value=active):
                api._reader()

    def test_decision_endpoints_need_a_decider(self):
        (ref,) = self.contacts(1, status="Tagged", issues=[{"code": "DLV_LATE"}, {"code": "PKG_LEAK", "review": "Confirmed"}])
        decisions = {
            api.set_review: {"ref": ref, "code": "DLV_LATE", "review": "Confirmed"},
            api.add_exclusion: {"exclusion_type": "Contact", "value": ref, "reason": "test data"},
            api.remove_exclusion: {"name": "missing", "reason": "test"},
            api.exclude_suggested: {"items": json.dumps([{"type": "Contact", "value": ref}]), "reason": "test data"},
            api.map_new: {"refs": json.dumps([ref]), "code": "DLV_LATE"},
            api.dismiss_new: {"refs": json.dumps([ref])},
            api.publish_version: {},
            api.gold_sample: {"labellers": json.dumps(["Administrator"])},
        }
        with patch.object(frappe, "get_roles", return_value=["Agent"]):  # a plain agent: no manager role
            for endpoint, kwargs in decisions.items():
                with self.subTest(endpoint=endpoint.__name__):
                    self.assertRaises(frappe.PermissionError, endpoint, **kwargs)
            # a plain agent still flags a label (a decider's Confirm stands) and may run the analysis
            self.assertEqual(api.flag_label(ref=ref, code="DLV_LATE"), {"flagged": 1})
            self.assertEqual(api.flag_label(ref=ref, code="PKG_LEAK"), {"flagged": 0})
            self.assertFalse(api.run_analysis()["started"])  # no worker in tests
        reviews = dict(frappe.get_all("HD AI Contact Issue", filters={"parent": ref}, fields=["code", "review"], as_list=True))
        self.assertEqual(reviews, {"DLV_LATE": "Flagged", "PKG_LEAK": "Confirmed"})
        self.assertFalse(frappe.db.exists("HD AI Exclusion", {"value": ref}))

    def test_open_case_checks_permission_then_redirects_with_the_conversation_encoded(self):
        (chat,) = self.contacts(1)
        self.addCleanup(setattr, frappe.local, "response", frappe.local.response)
        frappe.local.response = frappe._dict()
        seen = []

        def has_permission(doctype, ptype="read", doc=None, **kwargs):
            seen.append((doctype, ptype, doc, frappe.local.response.get("location")))
            return True

        with patch.object(frappe, "has_permission", side_effect=has_permission):
            api.open_case(ref=chat)
        self.assertEqual(seen, [("Messenger Conversation", "read", CONVERSATION, None)])  # checked before redirecting
        self.assertEqual(frappe.local.response["type"], "redirect")
        self.assertEqual(frappe.local.response["location"], "/crm/messenger/MSG-CONV-Test%20Person-00001")

        frappe.local.response = frappe._dict()
        with patch.object(frappe, "has_permission", return_value=False):
            self.assertRaises(frappe.PermissionError, api.open_case, ref=chat)
        self.assertNotIn("location", frappe.local.response)

        ticket = frappe.db.get_value("HD Ticket", {"is_merged": 0}, "name")
        if ticket:
            (folded,) = self.contacts(1, source="Ticket", ticket=str(ticket), channel="Ticket")
            with patch.object(frappe, "has_permission", return_value=True) as check:
                api.open_case(ref=folded)
            check.assert_called_once_with("HD Ticket", "read", doc=str(ticket))
            self.assertEqual(frappe.local.response["location"], f"/helpdesk/tickets/{ticket}")

    def test_overview_and_evidence_never_carry_conversation_names(self):
        ticket = frappe.db.get_value("HD Ticket", {"is_merged": 0}, "name")
        if not ticket:
            self.skipTest("no live HD Ticket to hang a synthetic ticket contact on")
        quote = "the driver came very late again"
        issue = {
            "code": "DLV_LATE",
            "severity": "S3",
            "is_primary": 1,
            "confidence": "high",
            "quote": quote,
            "quote_en": quote,
            "quote_status": "Verified",
            "quote_role": "customer",
            "statement_en": "The delivery arrived late",
        }
        names = self.contacts(
            2,
            source="Ticket",
            ticket=str(ticket),
            channel="Ticket",
            status="Tagged",
            folded=1,
            customer_key="ck-test-0001",
            started_on="2026-04-15 10:00:00",
            issues=[issue],
        )
        self.addCleanup(setattr, frappe.local, "request_cache", defaultdict(dict))
        frappe.local.request_cache = defaultdict(dict)  # metrics memoises its loaders per request
        overview = api.get_overview(from_date="2026-04-01", to_date="2026-04-30")
        evidence = api.get_evidence(code="DLV_LATE", from_date="2026-04-01", to_date="2026-04-30", limit=100)
        for payload in (overview, evidence):
            dumped = json.dumps(payload, default=str, ensure_ascii=False)
            self.assertNotIn("MSG-CONV", dumped)
            self.assertNotIn("ck-test-0001", dumped)
        self.assertIn("DLV_LATE", [i["code"] for i in overview["issues"]])
        self.assertLessEqual(set(names), {r["ref"] for r in evidence["rows"]})  # the synthetic rows were counted

    def test_new_queue_maps_by_contact_or_row_and_applies_the_severity_rules(self):
        new = {"code": "NEW", "severity": "S4", "proposed_label": "Smells off"}
        (mapped,) = self.contacts(1, status="Tagged", issues=[new, {"code": "DLV_LATE", "severity": "S3"}])
        (dismissed,) = self.contacts(1, status="Tagged", issues=[new])
        row = frappe.get_all("HD AI Contact Issue", filters={"parent": dismissed}, pluck="name")[0]
        self.assertEqual(api.map_new(refs=json.dumps([mapped]), code="FS_SPOILED"), {"mapped": 1})  # a contact ref
        self.assertEqual(api.dismiss_new(refs=json.dumps([row])), {"dismissed": 1})  # a tag row name
        self.assertEqual(api.map_new(refs=json.dumps([mapped]), code="DLV_LATE"), {"mapped": 0})  # no NEW row left
        fields = ["parent", "code", "severity", "review"]
        rows = frappe.get_all("HD AI Contact Issue", filters={"parent": ("in", [mapped, dismissed])}, fields=fields)
        got = sorted((r.parent == mapped, r.code, r.severity, r.review or None) for r in rows)
        # food safety is never below S2; the DLV_LATE row is untouched
        self.assertEqual(got, [(False, "NEW", "S4", "Rejected"), (True, "DLV_LATE", "S3", None), (True, "FS_SPOILED", "S2", "Confirmed")])

    def test_exclusions_resolve_refs_skip_duplicates_and_soft_delete(self):
        (ref,) = self.contacts(1)
        with patch.object(cases, "apply_exclusions", return_value=1) as apply:
            items = [{"type": "Conversation", "value": ref}, {"type": "Conversation", "value": ref}, {"type": "Contact", "value": ref}]
            out = api.exclude_suggested(items=json.dumps(items), reason="Staff test chat")
            self.assertEqual(out, {"added": 2, "skipped": 1, "changed": 1})
            name = frappe.db.get_value("HD AI Exclusion", {"exclusion_type": "Conversation", "active": 1, "value": CONVERSATION})
            self.assertTrue(name)  # the contact ref became the conversation, server side
            self.assertEqual(api.add_exclusion(exclusion_type="Contact", value=ref, reason="again")["name"], None)
            self.assertRaises(frappe.ValidationError, api.remove_exclusion, name=name, reason="  ")
            api.remove_exclusion(name=name, reason="Real customer after all")
            self.assertEqual(apply.call_count, 2)
        row = frappe.db.get_value("HD AI Exclusion", name, ["active", "removed_reason", "removed_by"], as_dict=True)
        self.assertEqual((row.active, row.removed_reason, row.removed_by), (0, "Real customer after all", frappe.session.user))

    def test_get_status_shape(self):
        with (
            patch.object(metrics, "coverage", return_value={"chat": {"until": "2026-06-27"}, "excluded_contacts": 3}),
            patch.object(metrics, "default_window", return_value={"from_date": "2026-06-01", "to_date": "2026-06-28", "latest": True}),
            patch.object(tagging, "current_version", return_value="tag-v1:test"),
            patch.object(tagging, "stale_count", return_value=0),
        ):
            status = api.get_status()
            with patch.object(frappe, "get_roles", return_value=["Agent"]):
                self.assertFalse(api.get_status()["can_decide"])
        keys = {"enabled", "ai_ready", "ai_reason", "can_decide", "worker_running", "running", "stopped", "progress"}
        keys |= {"last_labelled", "version", "validation", "spend", "coverage", "default_window", "web_research"}
        self.assertEqual(set(status), keys)
        self.assertTrue(status["can_decide"])
        self.assertEqual(set(status["progress"]), {"total", "tagged", "pending", "tagging", "failed", "no_text", "excluded"})
        self.assertEqual(status["coverage"], {"chats_until": "2026-06-27", "deliveries_until": None, "calls_until": None, "excluded": 3})
        self.assertEqual(status["spend"]["budget_usd"], jobs.conf().budget_usd)
