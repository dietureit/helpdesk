"""Advisor (Phase 2): the evidence pack, the council chain, every validator rule, the chairman, combine, adopt,
reject, verdicts and recurrence, research, the weekly summary, the projection, retention and the maintenance hooks.

requests.post is mocked, so the real ticket_ai.chat_json builds every request; posted bodies are checked for
data_collection deny, and the leak test checks them for identifiers. Counted rows are synthetic (metrics.counted_rows
is patched) and the coverage loaders are patched as in test_metrics: chats and deliveries (400 a day) cover every
week from 31 Aug 2025 to 27 Jun 2026. frappe.flags.hd_ai_sync runs each job chain inline; frappe.db.commit is a
no-op, every test is rolled back, and frappe.log_error is patched (tabError Log is MyISAM).
"""

import io
import json
from collections import Counter
from contextlib import redirect_stdout
from datetime import date, datetime, time, timedelta
from unittest.mock import MagicMock, patch

import frappe
import requests
from frappe.tests.utils import FrappeTestCase
from frappe.utils import getdate

from helpdesk.ai_analysis import DEPARTMENTS, advisor, cases, conf, jobs, metrics
from helpdesk.api import ticket_ai

INSIGHT = "HD AI Insight"
START, END = date(2025, 8, 31), date(2026, 6, 27)  # Sunday .. Saturday
DAYS = [START + timedelta(days=i) for i in range((END - START).days + 1)]
CHAT = [{"platform": "Instagram", "at": w + timedelta(days=1), "in": 5, "conversation": f"chat-{i}"} for w in DAYS[::7] for i in range(6)]
FROM, TO = "2026-04-05", "2026-05-02"  # four Sunday weeks
COUNCIL = ["openai/gpt-test", "google/gemini-test"]
CHAIRMAN = "anthropic/claude-test"
CONFIG = {"enabled": True, "base_url": "https://openrouter.ai/api/v1", "model": "openai/gpt-4.1"}
USER = "Administrator"
SECRET_QUOTE = "Fatima here, call me on +974 5555 1234, the lid popped open again"
LENS_TEXT = {
    "Recipe & kitchen": (
        "Thicken the sauces that leak",
        "Kitchen & QA adds a starch thickener to the curry sauce recipe card and holds it at 3 °C before packing",
    ),
    "Packaging & materials": (
        "Heat-seal the soup containers",
        "Operations & Packing switches the soup container to a heat seal film lid and runs a leak test on every batch",
    ),
    "Cold chain & delivery": (
        "Keep bags upright in the van",
        "Delivery adds upright cooler bag racks to each van and checks them on the dispatch checklist every morning",
    ),
    "App, tech & process": (
        "Flag liquid meals in the packing app",
        "Tech marks liquid dishes on the packing checklist screen so packers place them in the sealed bag",
    ),
    "Customer communication & policy": (
        "Send a leak apology template",
        "Customer Service sends a WhatsApp template within 30 minutes of a leak report with a replacement offer",
    ),
    "Suppliers & people": (
        "Ask the supplier for deeper lids",
        "Operations & Packing asks the container supplier for a lid sample with a deeper rim and tests it on the packing line",
    ),
    "Offer & pricing": ("Publish a clear trial price", "Marketing & Sales posts the trial price in the Instagram DM auto reply"),
    "Content & self-service": ("Answer area questions in the FAQ", "Customer Service adds the delivery area map to the WhatsApp FAQ"),
    "Sales response": ("Reply to price comments quickly", "Marketing & Sales answers each Instagram comment within 60 minutes"),
}


def _fresh():
    getattr(frappe.local, "request_cache", {}).clear()


def data(body):
    """The user message of a posted body, parsed."""
    return json.loads(body["messages"][1]["content"])


def row(code, day, customer, severity="S3", quote="the soup leaked all over the bag again", **extra):
    """A metrics.counted_rows() row."""
    m = metrics._meta()[code]
    at = datetime.combine(getdate(day), time(10))
    values = {
        "contact": frappe.generate_hash(length=10),
        "ticket": None,
        "source": "Chat",
        "channel": "Instagram DM",
        "at": at,
        "day": at.date(),
        "customer": customer,
        "language": "en",
        "offered": None,
        "hits": [],
        "code": m.code,
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
    return {**values, **extra}


def option(lens, **over):
    title, step = LENS_TEXT[lens]
    values = {
        "lens": lens,
        "not_applicable": False,
        "title": title,
        "tier": "process_fix",
        "hypothesis": "Thin sauces spill when the bag tilts in the van",
        "evidence_refs": ["E1", "E2"],
        "counter_evidence": "Some leaks come from dry dishes",
        "check_first": "Inspect returned containers for a lifted lid",
        "action_steps": [step],
        "owner_department": "Operations & Packing",
        "effort": "M",
        "cost_band": "low",
        "time_to_effect": "this_month",
        "expected_effect": "Fewer leak reports within a month",
        "success_metric": "cases_per_week",
        "risks": "A thicker sauce may change the taste",
    }
    return {**values, **over}


def proposals(body):
    d = data(body)
    refs = [e["id"] for e in d["pack"]["evidence"]][:2]
    return {"options": [option(lens, evidence_refs=refs) for lens in d["lenses"]]}


def card(kind, ids, when="this_week"):
    steps = [
        {"when": when, "action": f"Operations & Packing changes the soup lid ({kind})", "owner_department": "Operations & Packing", "from_options": [i]}
        for i in ids
    ]
    return {
        "type": kind,
        "title": f"The {kind.replace('_', ' ')}",
        "why": "The evidence points at the lid",
        "steps": steps,
        "success_metric": "cases_per_week",
        "check_first": "Inspect returned containers",
        "risks": "The supplier may be slow",
    }


def chair(levels=None, default="strong", cards=None):
    """A chairman reply over whatever options the request carries."""

    def handler(body):
        ids = [o["id"] for o in data(body)["options"]]
        rate = lambda i: {c: {"rating": (levels or {}).get(i, default), "note": "fits the evidence"} for c in advisor.CRITERIA}  # noqa: E731
        return {
            "ratings": [{"option": i, **rate(i)} for i in ids],
            "cards": cards(ids) if cards else [card("quick_win", ids[:1]), card("structural_fix", ids[1:2]), card("combined_plan", ids[:2])],
            "disagreements": [{"about": "lid or sauce", "options": ids[:2], "check_first": "inspect returned containers"}],
            "what_would_change_my_mind": "Leaks on dry dishes would point away from the sauces",
        }

    return handler


def seq(*outs):
    """A handler that answers with each of outs in turn (a callable gets the body)."""
    it = iter(outs)

    def handler(body):
        out = next(it)
        return out(body) if callable(out) else out

    return handler


class FakeLLM:
    """requests.post stand-in. Answers by response_format name ("web" for the schema-free research call): a dict
    is the JSON reply, a str the text, (content, annotations) a web reply, an int an HTTP error status."""

    def __init__(self, **handlers):
        self.handlers, self.calls = handlers, []

    def __call__(self, url, **kwargs):
        body = kwargs["json"]
        self.calls.append(kwargs)
        out = self.handlers[self._name(body)](body)
        response = MagicMock(status_code=200)
        if isinstance(out, int):
            response.status_code = out
            response.raise_for_status.side_effect = requests.HTTPError(response=response)
            return response
        content, annotations = out if isinstance(out, tuple) else (out, [])
        message = {"content": content if isinstance(content, str) else json.dumps(content), "annotations": annotations}
        choice = {"message": message, "finish_reason": "stop"}
        response.json.return_value = {"model": body["model"], "usage": {"cost": 0.01}, "choices": [choice]}
        return response

    @staticmethod
    def _name(body):
        return (body.get("response_format") or {}).get("json_schema", {}).get("name", "web")

    def bodies(self, name=None):
        return [c["json"] for c in self.calls if name is None or self._name(c["json"]) == name]


class TestAdvisor(FrappeTestCase):
    def setUp(self):
        super().setUp()
        frappe.set_user(USER)
        self.addCleanup(frappe.db.rollback)  # the real one: cleanups run last-in first-out, after the patches end
        self.enterContext(patch.object(frappe.db, "commit"))
        self.enterContext(patch.object(frappe.db, "rollback"))
        self.log_error = self.enterContext(patch.object(frappe, "log_error"))
        self.enqueue = self.enterContext(patch.object(frappe, "enqueue"))
        self.conf = frappe._dict(
            conf(),
            enabled=True,
            legal_approval="TEST-REF",
            council_models=list(COUNCIL),
            chairman_model=CHAIRMAN,
            web_research=True,
            research_model="openai/gpt-research",
            model="openai/gpt-small",
            retention_months=18,
        )
        self.enterContext(patch.object(advisor, "conf", side_effect=lambda: self.conf))
        self.enterContext(patch.object(jobs, "analysis_enabled", return_value=True))
        self.budget = self.enterContext(patch.object(jobs, "budget_left", return_value=50.0))
        self.enterContext(patch.object(ticket_ai, "get_config", return_value=dict(CONFIG)))
        self.enterContext(patch.object(ticket_ai, "_api_key", return_value="sk-or-test"))
        self.enterContext(patch.object(cases, "known_names", return_value={"fatima", "kuwari"}))
        self.llm = FakeLLM(hd_ai_propose=proposals, hd_ai_chair=chair())
        self.enterContext(patch.object(ticket_ai.requests, "post", side_effect=lambda *a, **k: self.llm(*a, **k)))
        self.rows = []
        loaders = {
            "counted_rows": {"side_effect": lambda: self.rows},
            "_base": {"return_value": {}},
            "_chat_rows": {"return_value": CHAT},
            "_deliveries": {"return_value": dict.fromkeys(DAYS, 400)},
            "_calls": {"return_value": {"answered": [], "incoming": []}},
            "_money": {"side_effect": lambda frm, to: {"replacements": 0, "cost": 0.0, "value": 0.0, "refunds": 0, "refunds_qar": 0.0}},
            "_meals": {"return_value": Counter()},
            "_reply_months": {"return_value": {}},
        }
        for name, kwargs in loaders.items():
            self.enterContext(patch.object(metrics, name, **kwargs))
        frappe.flags.hd_ai_sync = True  # job chains run inline
        self.addCleanup(setattr, frappe.flags, "hd_ai_sync", False)
        _fresh()
        self.addCleanup(_fresh)

    def insight(self, kind, **values):
        doc = {"doctype": INSIGHT, "insight_type": kind, "requested_by": USER, **values}
        return frappe.get_doc(doc).insert(ignore_permissions=True).name

    def leak_rows(self):
        """PKG_LEAK in Apr 2026: 16 customers, k1 with 3 contacts, 3 S2 contacts with a dish, one contact whose
        stored quote missed the scrub (a name and a phone) on a ticket, and a co-occurring DLV_LATE tag."""
        rows = [
            row("PKG_LEAK", date(2026, 4, 5) + timedelta(days=i), f"k{i}", offered="replacement" if i % 3 == 0 else "apology_only")
            for i in range(16)
        ]
        rows += [row("PKG_LEAK", d, "k1") for d in ("2026-04-30", "2026-05-01")]
        rows += [row("PKG_LEAK", d, f"s{i}", "S2", dish_item="chicken curry") for i, d in enumerate(("2026-04-10", "2026-04-15", "2026-04-28"))]
        rows.append(row("PKG_LEAK", "2026-04-29", "ck-secret-0001", "S2", quote=SECRET_QUOTE, ticket="TEST-TKT-7731", source="Ticket"))
        rows.append({**row("DLV_LATE", "2026-04-08", "k3"), "contact": rows[3]["contact"]})
        return rows

    def assertDenied(self):
        self.assertTrue(self.llm.calls)
        for body in self.llm.bodies():
            self.assertEqual(body["provider"]["data_collection"], "deny")

    # --- the pack and the chain -----------------------------------------------------------------------------

    def test_pack_bands_evidence_caps_and_no_identifiers_in_any_posted_body(self):
        self.rows = self.leak_rows()
        frappe.get_doc(
            {"doctype": "HD AI Action", "title": "Call Fatima on 55551234 about the lids", "issue_code": "PKG_LEAK", "status": "Done", "verdict": "Inconclusive"}
        ).insert(ignore_permissions=True)
        note = "Kuwari tried this already, call +974 5555 1234"
        self.insight("Suggestions", issue_code="PKG_LEAK", status="Done", decision="Rejected", decision_reason="Already tried", decision_note=note)
        practice = {"title": "Use tamper seals on soup cups", "source_url": "https://www.example.org/seal", "domain": "example.org"}
        self.insight("Research", issue_code="PKG_LEAK", status="Done", output_json=json.dumps({"practices": [practice]}))

        pack, alias, pack_hash = advisor.build_pack("PKG_LEAK", FROM, TO)
        self.assertEqual(pack["bands"], {"volume": "high", "trend": "rising", "chronic": "yes", "safety": "no", "season": "none"})
        self.assertEqual(pack["where"]["channels"], ["Instagram DM"])
        self.assertEqual(pack["where"]["dishes"], ["chicken curry"])
        self.assertEqual(pack["co_occurring"], [metrics._meta()["DLV_LATE"].label])
        self.assertEqual(pack["offered"], [{"remedy": "Apology only", "band": "mostly"}, {"remedy": "Replacement", "band": "sometimes"}])
        self.assertEqual(pack["issue"]["code"], "PKG_LEAK")
        evidence = pack["evidence"]
        self.assertEqual([e["id"] for e in evidence], [f"E{i}" for i in range(1, 16)])  # capped at 15
        self.assertEqual([e["severity"] for e in evidence[:4]], ["S2"] * 4)  # worst first, then newest
        customer = {r["contact"]: r["customer"] for r in self.rows}
        per = Counter(customer[alias[e["id"]]["contact"]] for e in evidence)
        self.assertEqual((per["k1"], max(per.values())), (2, 2))  # k1 has 3 contacts: at most 2 quotes per customer
        self.assertEqual(evidence[0]["quote"], "[name] here, call me on [phone], the lid popped open again")  # re-scrubbed
        self.assertEqual(alias["E1"], {"contact": self.rows[-2]["contact"], "code": "PKG_LEAK", "quote": SECRET_QUOTE, "date": "2026-04-29"})
        self.assertEqual(set(evidence[0]), {"id", "quote", "quote_en", "channel", "severity", "role"})
        self.assertEqual(pack["tried"]["actions"], [{"title": "Call [name] on [phone] about the lids", "status": "Done", "verdict": "Inconclusive", "recurred": False}])
        self.assertEqual(pack["tried"]["rejected_plans"], [{"reason": "Already tried", "note": "[name] tried this already, call [phone]"}])
        self.assertEqual(pack["external"]["practices"], [{"id": "X1", "title": "Use tamper seals on soup cups", "domain": "example.org"}])
        self.assertEqual(alias["X1"], {"url": "https://www.example.org/seal"})
        self.assertEqual(pack["vocabulary"]["departments"], DEPARTMENTS)
        self.assertEqual(advisor.build_pack("PKG_LEAK", FROM, TO)[2], pack_hash)  # same evidence, same hash
        self.rows.append(row("PKG_LEAK", "2026-05-02", "k99"))
        self.assertNotEqual(advisor.build_pack("PKG_LEAK", FROM, TO)[2], pack_hash)
        self.rows.pop()

        name, reused = advisor.request_suggestions("PKG_LEAK", FROM, TO, USER)
        self.assertFalse(reused)
        self.assertDenied()
        secrets = ["ck-secret-0001", "TEST-TKT-7731", "Fatima", "Kuwari", "5555 1234", "55551234", "2026-04", "2026-05", "MSG-CONV", name]
        for body in self.llm.bodies():
            sent = json.dumps(body, ensure_ascii=False)
            for secret in secrets + [r["contact"] for r in self.rows]:
                self.assertNotIn(secret, sent)
        stored = frappe.get_doc(INSIGHT, name)
        self.assertEqual(json.loads(stored.input_json)["pack"], pack)  # exactly what the proposers got
        self.assertEqual(data(self.llm.bodies("hd_ai_propose")[0])["pack"], pack)
        out = json.loads(stored.output_json)
        self.assertEqual((out["evidence"][0]["ref"], out["evidence"][0]["date"]), (self.rows[-2]["contact"], "2026-04-29"))
        self.assertEqual(out["external"], [{"id": "X1", "title": "Use tamper seals on soup cups", "domain": "example.org", "url": "https://www.example.org/seal"}])

    def test_guard_needs_three_cases_or_one_food_safety_case(self):
        frappe.flags.hd_ai_sync = False
        self.enterContext(patch.object(jobs, "worker_running", return_value=True))
        self.rows = [row("PKG_LEAK", "2026-04-10", "g1"), row("PKG_LEAK", "2026-04-20", "g2"), row("PKG_LEAK", "2025-12-01", "g3")]
        with self.assertRaisesRegex(frappe.ValidationError, "at least 3 cases in the 90 days up to 2 May 2026; this issue has 2"):
            advisor.request_suggestions("PKG_LEAK", FROM, TO, USER)
        self.rows = [row("FS_ILLNESS", "2026-04-12", "f1", "S1", quote="I was sick all night after the lunch")]
        name, reused = advisor.request_suggestions("FS_ILLNESS", FROM, TO, USER)
        self.assertEqual((reused, frappe.db.get_value(INSIGHT, name, "status")), (False, "Queued"))
        self.assertEqual(self.enqueue.call_args.kwargs["job_id"], f"hd-ai::suggest::{name}::1")
        self.assertEqual(self.llm.calls, [])

    def test_reuse_by_pack_hash_regenerate_and_refusals(self):
        frappe.flags.hd_ai_sync = False
        self.rows = self.leak_rows()
        with self.assertRaisesRegex(frappe.ValidationError, "Background worker not running"):
            advisor.request_suggestions("PKG_LEAK", FROM, TO, USER)
        worker = self.enterContext(patch.object(jobs, "worker_running", return_value=True))
        first, reused = advisor.request_suggestions("PKG_LEAK", FROM, TO, USER)
        self.assertFalse(reused)
        call = self.enqueue.call_args
        self.assertEqual(call.args[0], "helpdesk.ai_analysis.advisor.run_suggestion_step")
        self.assertEqual(
            (call.kwargs["job_id"], call.kwargs["queue"], call.kwargs["insight"], call.kwargs["step"]),
            (f"hd-ai::suggest::{first}::1", "long", first, 1),
        )
        self.assertEqual(advisor.request_suggestions("PKG_LEAK", FROM, TO, USER), (first, True))  # same evidence
        again, reused = advisor.request_suggestions("PKG_LEAK", FROM, TO, USER, regenerate=True)
        self.assertNotEqual(again, first)
        self.assertFalse(reused)
        self.rows.append(row("PKG_LEAK", "2026-05-02", "k99"))  # new evidence: a new run
        self.assertNotIn(advisor.request_suggestions("PKG_LEAK", FROM, TO, USER)[0], (first, again))
        self.rows.append(row("PKG_LEAK", "2026-05-02", "k98"))
        worker.return_value = False
        for change, message in ((dict(enabled=False), "AI Analysis is off"), (dict(), "Monthly AI budget reached")):
            self.conf.update(change)
            self.budget.return_value = 50.0 if change else 0.0
            self.assertRaisesRegex(frappe.ValidationError, message, advisor.request_suggestions, "PKG_LEAK", FROM, TO, USER)
            self.conf.enabled = True
        self.assertEqual(self.llm.calls, [])

    def test_council_fans_out_one_proposer_per_step_and_splits_the_lenses(self):
        self.rows = self.leak_rows()
        name, _ = advisor.request_suggestions("PKG_LEAK", FROM, TO, USER)
        doc = frappe.get_doc(INSIGHT, name)
        self.assertEqual((doc.status, doc.step, doc.progress_label or "", doc.error or ""), ("Done", 3, "", ""))
        proposers = self.llm.bodies("hd_ai_propose")
        lenses = advisor.LENSES
        self.assertEqual([(b["model"], data(b)["lenses"]) for b in proposers], [(COUNCIL[0], lenses[0::2]), (COUNCIL[1], lenses[1::2])])
        for call in self.llm.calls:
            body = call["json"]
            self.assertNotIn("temperature", body)
            self.assertEqual((body["max_tokens"], call["timeout"]), (8000, (5, 240)))
            self.assertIs(body["response_format"]["json_schema"]["strict"], True)
            self.assertNotIn("tools", body)
        self.assertDenied()
        item = proposers[0]["response_format"]["json_schema"]["schema"]["properties"]["options"]["items"]
        self.assertEqual(item["properties"]["evidence_refs"]["items"]["enum"], [f"E{i}" for i in range(1, 16)])
        self.assertEqual(item["properties"]["time_to_effect"]["enum"], advisor.WHENS)
        (chair_body,) = self.llm.bodies("hd_ai_chair")
        self.assertEqual(chair_body["model"], CHAIRMAN)
        self.assertTrue(all(set(o) == set(advisor.SENT_FIELDS) for o in data(chair_body)["options"]))  # no model names
        out = json.loads(doc.output_json)
        self.assertEqual(sorted(o["id"] for o in out["options"]), [f"O{i}" for i in range(1, 7)])
        self.assertEqual(Counter(o["model"] for o in out["options"]), Counter({COUNCIL[0]: 3, COUNCIL[1]: 3}))
        self.assertEqual([c["type"] for c in out["cards"]], advisor.CARDS)
        self.assertEqual([s["id"] for s in out["cards"][2]["steps"]], ["combined_plan:1", "combined_plan:2"])
        self.assertEqual((out["proposers"], out["chairman"]), ([{"model": m, "ok": True} for m in COUNCIL], {"model": CHAIRMAN, "ok": True}))
        self.assertEqual(set(out), {"options", "rejected", "cards", "disagreements", "what_would_change_my_mind", "evidence", "external", "proposers", "chairman"})
        self.assertEqual(set(doc.models.split()), {*COUNCIL, CHAIRMAN})
        self.assertAlmostEqual(doc.cost_usd, 0.03)
        self.assertRegex(doc.prompt_version, r"^adv-v1:[0-9a-f]{10}$")
        self.assertEqual(advisor.suggestion_state("PKG_LEAK")["insight"], name)
        self.assertFalse(advisor.insight_projection(name)["stale"])
        self.rows.append(row("PKG_LEAK", "2026-05-02", "k99"))
        self.assertTrue(advisor.insight_projection(name)["stale"])  # new evidence since it ran

        self.rows += [row("ENQ_PRICE", date(2026, 4, 6) + timedelta(days=i), f"e{i}", "S4", quote="how much is the monthly plan please") for i in range(4)]
        advisor.request_suggestions("ENQ_PRICE", FROM, TO, USER)
        split = [data(b)["lenses"] for b in self.llm.bodies("hd_ai_propose")[2:]]
        self.assertEqual(split, [["Offer & pricing", "Sales response"], ["Content & self-service"]])

    def test_a_failed_proposer_is_recorded_and_two_answers_are_needed(self):
        self.rows = self.leak_rows()
        third = "mistral/m-test"
        self.conf.council_models = [*COUNCIL, third]
        self.llm = FakeLLM(hd_ai_propose=lambda b: 500 if b["model"] == COUNCIL[1] else proposals(b), hd_ai_chair=chair())
        name, _ = advisor.request_suggestions("PKG_LEAK", FROM, TO, USER)
        doc = frappe.get_doc(INSIGHT, name)
        out = json.loads(doc.output_json)
        self.assertEqual(doc.status, "Done")
        self.assertEqual(out["proposers"], [{"model": COUNCIL[0], "ok": True}, {"model": COUNCIL[1], "ok": False}, {"model": third, "ok": True}])
        self.assertEqual({o["model"] for o in out["options"]}, {COUNCIL[0], third})

        self.conf.council_models = list(COUNCIL)
        name, _ = advisor.request_suggestions("PKG_LEAK", FROM, TO, USER, regenerate=True)
        doc = frappe.get_doc(INSIGHT, name)
        self.assertEqual(doc.status, "Failed")
        self.assertIn("Only 1 of 2 proposer models answered", doc.error)
        self.assertEqual(len(self.llm.bodies("hd_ai_chair")), 1)  # only the first run reached the chairman

    def test_every_validator_rule(self):
        pack = {
            "evidence": [{"id": "E1"}, {"id": "E2"}],
            "external": {"practices": [{"id": "X1"}]},
            "vocabulary": {"departments": DEPARTMENTS, "channels": advisor.CHANNELS, "dishes": ["chicken curry"], "glossary": advisor.GLOSSARY},
        }
        a, b = COUNCIL

        def mk(title, step, **over):
            return option("Packaging & materials", title=title, action_steps=[step] if isinstance(step, str) else step, **over)

        raw = {
            a: {
                "options": [
                    mk("Heat seal the soup lids", "Operations & Packing switches the soup container to a heat seal film lid"),
                    mk("Ghost reference", "Kitchen & QA relabels the curry sauce cups with the allergen matrix", evidence_refs=["E9"]),
                    mk("No evidence at all", "Delivery straps every cooler bag upright in the van before the route plan", evidence_refs=[]),
                    mk("Outside idea only", "Tech adds a tamper seal reminder to the driver app proof of delivery", evidence_refs=["X1"]),
                    mk("Counted claim", "Kitchen & QA checks the chiller temperature log before dispatch", hypothesis="12 customers complained"),
                    mk("Percent claim", "Operations & Packing runs a drop test on each new tray batch", expected_effect="Leaks fall by 30%"),
                    mk("Words not digits", "Customer Service sends the leak WhatsApp template with a replacement", hypothesis="One customer and most others mention it"),
                    mk("Bare number", "Operations & Packing puts 2 ice packs in every insulated bag before dispatch"),
                    mk("Number with units", ["Kitchen & QA holds the curry sauce at 3 °C for 2 hours before the packing line", "Monitor closely"]),
                    mk("Generic only", ["Improve training", "Monitor closely"]),
                    mk("Generic but concrete", "Improve training on the packing line for the heat seal lid"),
                    mk("Not applicable here", "Finance reviews the refund policy for leaks", not_applicable=True),
                    mk("Wrong tier", "Operations & Packing changes the sleeve on the sauce cup for the van", tier="big_fix"),
                ]
            },
            b: {"options": [mk("Heat-seal soup lids", "Operations & Packing switches soup containers to heat seal film lids")]},
        }
        options, rejected = advisor.validate_options(raw, pack, seed="seed-1")
        self.assertEqual(
            {r["title"]: r["reason"] for r in rejected},
            {
                "Ghost reference": "cites evidence that is not in the pack",
                "No evidence at all": "cites no evidence",
                "Counted claim": "states counts or percentages as fact",
                "Percent claim": "states counts or percentages as fact",
                "Bare number": "a number in an action step has no unit",
                "Generic only": "only generic actions",
                "Wrong tier": "a field outside the allowed values",
            },
        )
        self.assertEqual({r["model"] for r in rejected}, {a})
        by_title = {o["title"]: o for o in options}
        self.assertEqual(set(by_title), {"Heat seal the soup lids", "Outside idea only", "Words not digits", "Number with units", "Generic but concrete"})
        self.assertEqual(sorted(o["id"] for o in options), [f"O{i}" for i in range(1, 6)])
        self.assertEqual(by_title["Heat seal the soup lids"]["also_proposed_by"], [b])  # the near-duplicate merged
        self.assertEqual({t for t, o in by_title.items() if o["external"]}, {"Outside idea only"})
        self.assertEqual(len(by_title["Number with units"]["action_steps"]), 1)  # the generic step is dropped
        self.assertEqual(by_title["Generic but concrete"]["action_steps"], ["Improve training on the packing line for the heat seal lid"])

        order = lambda seed: [o["title"] for o in advisor.validate_options(raw, pack, seed=seed)[0]]  # noqa: E731
        self.assertEqual(order("seed-1"), [o["title"] for o in options])  # deterministic per insight
        self.assertGreater(len({tuple(order(f"seed-{i}")) for i in range(8)}), 1)  # and shuffled

    # --- chairman, combine ----------------------------------------------------------------------------------

    def test_chairman_ratings_are_ranked_by_code_with_one_repair_then_no_synthesis(self):
        self.rows = self.leak_rows()
        self.llm = FakeLLM(hd_ai_propose=proposals, hd_ai_chair=chair(levels={"O2": "strong", "O3": "adequate"}, default="weak"))
        name, _ = advisor.request_suggestions("PKG_LEAK", FROM, TO, USER)
        out = json.loads(frappe.db.get_value(INSIGHT, name, "output_json"))
        self.assertEqual([(o["id"], o["score"]) for o in out["options"]], [("O2", 10), ("O3", 5), ("O1", 0), ("O4", 0), ("O5", 0), ("O6", 0)])
        self.assertEqual(out["options"][0]["ratings"], dict.fromkeys(advisor.CRITERIA, "strong"))
        self.assertEqual(out["options"][0]["rating_notes"]["risk"], "fits the evidence")

        two_cards = chair(cards=lambda ids: [card("quick_win", ids[:1]), card("structural_fix", ids[1:2])])
        self.llm = FakeLLM(hd_ai_propose=proposals, hd_ai_chair=seq(two_cards, chair()))
        name, _ = advisor.request_suggestions("PKG_LEAK", FROM, TO, USER, regenerate=True)
        first, repair = self.llm.bodies("hd_ai_chair")
        self.assertIn("exactly three cards", " ".join(data(repair)["errors"]))
        self.assertEqual(len(data(repair)["previous_reply"]["cards"]), 2)
        self.assertTrue(repair["messages"][0]["content"].endswith(advisor.REPAIR))
        self.assertEqual(frappe.db.get_value(INSIGHT, name, "status"), "Done")

        one_source = chair(
            levels={"O4": "strong"},
            default="weak",
            cards=lambda ids: [card("quick_win", ids[:1]), card("structural_fix", ids[1:2]), card("combined_plan", [ids[0], ids[0]])],
        )
        self.llm = FakeLLM(hd_ai_propose=proposals, hd_ai_chair=one_source)
        name, _ = advisor.request_suggestions("PKG_LEAK", FROM, TO, USER, regenerate=True)
        doc = frappe.get_doc(INSIGHT, name)
        out = json.loads(doc.output_json)
        self.assertEqual((doc.status, out["cards"], out["chairman"]["ok"]), ("No synthesis", [], False))
        self.assertEqual(len(self.llm.bodies("hd_ai_chair")), 2)  # one repair, no more
        self.assertIn("at least two different options", " ".join(data(self.llm.bodies("hd_ai_chair")[1])["errors"]))
        self.assertEqual(out["options"][0]["id"], "O4")  # still ranked by code
        self.assertIn("broke the rules twice", doc.error)

        reply = chair()({"messages": [{}, {"content": json.dumps({"options": [{"id": "O1"}, {"id": "O2"}]})}]})
        reply["ratings"].pop()
        reply["cards"] = [card("quick_win", ["O9"]), card("structural_fix", []), card("combined_plan", ["O1", "O1"])]
        reply["cards"][0]["why"] = "12 customers saw it"
        reply["disagreements"][0]["options"] = ["O7"]
        errors = " | ".join(advisor.check_chairman(reply, ["O1", "O2"]))
        for part in (
            "missing: O2",
            "quick_win: unknown option ids O9",
            "structural_fix: needs at least one step",
            "combined_plan: its steps must draw on at least two different options",
            "quick_win: no counts or percentages in why",
            "disagreements: unknown option ids",
        ):
            self.assertIn(part, errors)

    def test_combine_reruns_the_chairman_on_the_selected_ids_only(self):
        self.rows = self.leak_rows()
        parent, _ = advisor.request_suggestions("PKG_LEAK", FROM, TO, USER)
        out = json.loads(frappe.db.get_value(INSIGHT, parent, "output_json"))
        step = out["cards"][0]["steps"][0]
        self.assertEqual((step["id"], step["from_options"]), ("quick_win:1", ["O1"]))
        self.assertRaises(frappe.ValidationError, advisor.combine, parent, ["O99"], "", USER)
        self.assertRaises(frappe.ValidationError, advisor.combine, parent, ["O1"], "", USER)  # one option is no mix

        child = advisor.combine(parent, ["O3", "quick_win:1"], "Ask Fatima on 55551234 first", USER)
        body = self.llm.bodies("hd_ai_chair")[-1]
        sent = data(body)
        self.assertEqual([o["id"] for o in sent["options"]], ["O3", "O1"])
        schema = body["response_format"]["json_schema"]["schema"]
        steps = schema["properties"]["cards"]["items"]["properties"]["steps"]["items"]
        self.assertEqual(steps["properties"]["from_options"]["items"]["enum"], ["O3", "O1"])
        self.assertEqual([s["id"] for s in sent["selected_steps"]], ["quick_win:1"])
        self.assertEqual(sent["note"], "Ask [name] on [phone] first")
        self.assertIn(advisor.COMBINE_RULES, body["messages"][0]["content"])
        self.assertDenied()

        doc = frappe.get_doc(INSIGHT, child)
        result = json.loads(doc.output_json)
        self.assertEqual(
            (doc.status, doc.parent_insight, json.loads(doc.selected_json), doc.note, doc.pack_hash),
            ("Done", parent, ["O3", "quick_win:1"], "Ask [name] on [phone] first", frappe.db.get_value(INSIGHT, parent, "pack_hash")),
        )
        self.assertEqual(json.loads(doc.input_json)["options"], sent["options"])  # exactly what was sent
        by_id = {o["id"]: o for o in out["options"]}
        self.assertEqual({o["id"]: o["title"] for o in result["options"]}, {i: by_id[i]["title"] for i in ("O1", "O3")})
        self.assertEqual({o["id"]: o["model"] for o in result["options"]}, {i: by_id[i]["model"] for i in ("O1", "O3")})
        self.assertTrue(all(set(s["from_options"]) <= {"O1", "O3"} for c in result["cards"] for s in c["steps"]))
        self.assertEqual((result["evidence"], result["proposers"]), (out["evidence"], out["proposers"]))
        self.assertEqual([h["name"] for h in advisor.insight_projection(parent)["history"]], [parent, child])
        self.assertEqual(advisor.insight_projection(child)["history"][1]["note"], "Ask [name] on [phone] first")

    # --- decisions ------------------------------------------------------------------------------------------

    def test_adopt_creates_an_action_with_a_code_baseline_and_a_todo(self):
        today = date(2026, 5, 27)  # a Wednesday: the recent window is 26 Apr .. 23 May
        self.enterContext(patch.object(advisor, "_today", return_value=today))
        add = self.enterContext(patch("frappe.desk.form.assign_to.add"))
        weeks = [date(2025, 10, 26) + timedelta(weeks=i) for i in range(26)]
        self.rows = [row("PKG_LEAK", w + timedelta(days=2), f"b{i}") for i, w in enumerate(weeks)]  # one case a week
        self.rows += [row("PKG_LEAK", date(2026, 4, 26) + timedelta(weeks=w, days=d), f"r{w}-{d}") for w in range(4) for d in (0, 2, 4)]
        steps = [
            {"id": "quick_win:1", "when": "this_week", "action": "Heat-seal soup lids", "owner_department": "Operations & Packing", "from_options": ["O1"]},
            {"id": "quick_win:2", "when": "this_month", "action": "Add upright racks", "owner_department": "Delivery", "from_options": ["O2"]},
            {"id": "quick_win:3", "when": "this_week", "action": "Leak test each batch", "owner_department": "Operations & Packing", "from_options": ["O1"]},
        ]
        cards = [
            {"type": "quick_win", "title": "Seal the soup lids", "steps": steps, "success_metric": "cases_per_week"},
            {
                "type": "structural_fix",
                "title": "A new container",
                "steps": [{"id": "structural_fix:1", "when": "this_quarter", "action": "Switch supplier", "owner_department": "Delivery", "from_options": ["O2"]}],
                "success_metric": "rate_per_1000_deliveries",
            },
        ]
        plan = self.insight("Suggestions", issue_code="PKG_LEAK", status="Done", output_json=json.dumps({"cards": cards}))
        self.assertRaises(frappe.ValidationError, advisor.adopt, plan, "custom", USER, USER)
        name = advisor.adopt(plan, "quick_win", USER, USER)
        a = frappe.get_doc("HD AI Action", name)
        self.assertEqual(
            (a.title, a.issue_code, a.insight, a.card, a.status, a.assigned_to, a.owner_department),
            ("Seal the soup lids", "PKG_LEAK", plan, "quick_win", "Open", USER, "Operations & Packing"),
        )
        self.assertEqual(a.plan.splitlines()[1], "This month — Add upright racks (Delivery)")
        self.assertEqual(getdate(a.due_date), today + timedelta(days=28))  # the latest step: this_month
        self.assertEqual((a.success_metric, a.exposure_kind), ("cases_per_week", "Deliveries"))
        # 12 clean weeks (Ramadan and Eid left out) ending the Saturday before the 4 recent weeks
        self.assertEqual((getdate(a.baseline_from), getdate(a.baseline_to)), (date(2025, 12, 21), date(2026, 4, 25)))
        self.assertLessEqual(getdate(a.baseline_to), today - timedelta(weeks=4))
        self.assertEqual((a.baseline_value, a.recent_value, a.target_value), (1.0, 3.0, 0.5))  # target: half the baseline
        add.assert_called_once_with({"assign_to": [USER], "doctype": "HD AI Action", "name": name, "description": "Seal the soup lids"})
        self.assertEqual(frappe.db.get_value(INSIGHT, plan, ["decision", "decided_by"]), ("Adopted", USER))
        self.assertRaisesRegex(frappe.ValidationError, "already adopted", advisor.adopt, plan, "quick_win", USER, USER)
        self.assertEqual(advisor.action_state("PKG_LEAK"), {"name": name, "status": "Open", "overdue": False, "verdict": "Not yet"})
        with patch.object(advisor, "_today", return_value=today + timedelta(days=29)):
            self.assertTrue(advisor.action_state("PKG_LEAK")["overdue"])

        other = self.insight("Suggestions", issue_code="PKG_LEAK", status="Done", output_json=json.dumps({"cards": cards}))
        b = frappe.get_doc("HD AI Action", advisor.adopt(other, "structural_fix", USER, USER, target="0.2"))
        self.assertEqual((getdate(b.due_date), b.target_value, b.success_metric), (today + timedelta(days=90), 0.2, "rate_per_1000_deliveries"))
        self.assertEqual((b.baseline_value, b.recent_value), (round(12 / 33600 * 1000, 3), round(12 / 11200 * 1000, 3)))
        given = self.insight("Suggestions", issue_code="PKG_LEAK", status="Done", output_json=json.dumps({"cards": cards}))
        c = frappe.get_doc("HD AI Action", advisor.adopt(given, "quick_win", USER, USER, due_date="2026-06-30"))
        self.assertEqual(getdate(c.due_date), date(2026, 6, 30))
        running = self.insight("Suggestions", issue_code="PKG_LEAK", status="Running", output_json=json.dumps({"cards": cards}))
        self.assertRaises(frappe.ValidationError, advisor.adopt, running, "quick_win", USER, USER)

    def test_reject_needs_a_reason_and_other_needs_a_note(self):
        self.rows = self.leak_rows()
        plan = self.insight("Suggestions", issue_code="PKG_LEAK", status="Done", output_json="{}")
        self.assertRaisesRegex(frappe.ValidationError, "Choose a reason", advisor.reject, plan, "", "", USER)
        self.assertRaisesRegex(frappe.ValidationError, "Add a note", advisor.reject, plan, "Other", "   ", USER)
        advisor.reject(plan, "Other", "Kuwari says the lids are fine, call 55551234", USER)
        row_ = frappe.db.get_value(INSIGHT, plan, ["decision", "decision_reason", "decision_note", "decided_by"], as_dict=True)
        self.assertEqual(
            (row_.decision, row_.decision_reason, row_.decision_note, row_.decided_by),
            ("Rejected", "Other", "[name] says the lids are fine, call [phone]", USER),
        )
        pack = advisor.build_pack("PKG_LEAK", FROM, TO)[0]
        self.assertIn({"reason": "Other", "note": "[name] says the lids are fine, call [phone]"}, pack["tried"]["rejected_plans"])
        adopted = self.insight("Suggestions", issue_code="PKG_LEAK", status="Done", decision="Adopted")
        self.assertRaises(frappe.ValidationError, advisor.reject, adopted, "Too costly", "", USER)

    # --- verdicts -------------------------------------------------------------------------------------------

    def test_verdicts_after_four_and_eight_weeks_and_recurrence(self):
        base_weeks = [date(2025, 12, 28) + timedelta(weeks=i) for i in range(7)]  # 28 Dec .. 8 Feb: clean weeks
        start = date(2026, 4, 5)  # done on 29 Mar: the after-window starts 7 days later

        def scenario(code, per_week, after_days):
            out = [row(code, w + timedelta(days=d), f"{code}-b{i}-{d}") for i, w in enumerate(base_weeks) for d in range(per_week)]
            return out + [row(code, start + timedelta(days=d), f"{code}-a{d}") for d in after_days]

        self.rows = (
            scenario("PKG_LEAK", 3, [3])  # 21 before, 1 after
            + scenario("PKG_DAMAGED", 1, range(16))  # 7 before, 16 after
            + scenario("PKG_LABEL", 1, [1, 8, 15, 22])  # 7 before, 4 after
            + scenario("DLV_LATE", 0, [3, 10])  # 2 cases in all
        )

        def action(code):
            doc = {
                "doctype": "HD AI Action",
                "title": f"Fix {code}",
                "issue_code": code,
                "status": "Done",
                "done_on": date(2026, 3, 29),
                "success_metric": "cases_per_week",
                "exposure_kind": "Deliveries",
                "baseline_from": base_weeks[0],
                "baseline_to": date(2026, 2, 14),
                "target_value": 1.5,
            }
            return frappe.get_doc(doc).insert(ignore_permissions=True).name

        names = {code: action(code) for code in ("PKG_LEAK", "PKG_DAMAGED", "PKG_LABEL", "DLV_LATE")}
        self.assertEqual(advisor.next_check(date(2026, 3, 29), []), date(2026, 5, 3))

        def verdicts(as_of):
            out = advisor.update_verdicts(as_of)
            mine = set(names.values())
            return {c["action"]: c for c in out["checked"] if c["action"] in mine}, [n for n in out["recurred"] if n in mine]

        def field(code, *fields):
            return frappe.db.get_value("HD AI Action", names[code], fields, as_dict=True)

        checked, _ = verdicts("2026-05-05")
        self.assertEqual(
            {code: checked[name]["verdict"] for code, name in names.items()},
            {"PKG_LEAK": "Lower than before", "PKG_DAMAGED": "Higher than before", "PKG_LABEL": "Inconclusive", "DLV_LATE": "Not enough data"},
        )
        self.assertEqual({c["weeks"] for c in checked.values()}, {4})
        lower = field("PKG_LEAK", "verdict", "verdict_p", "target_met", "verdict_checked_on", "verdict_history", "recurred")
        (entry,) = json.loads(lower.verdict_history)
        self.assertEqual(
            {k: entry[k] for k in ("checked_on", "weeks", "verdict", "cases_after", "cases_baseline")},
            {"checked_on": "2026-05-05", "weeks": 4, "verdict": "Lower than before", "cases_after": 1, "cases_baseline": 21},
        )
        self.assertLess(entry["p"], 0.05)
        self.assertEqual((lower.verdict, lower.target_met, getdate(lower.verdict_checked_on)), ("Lower than before", 1, date(2026, 5, 5)))
        self.assertAlmostEqual(lower.verdict_p, entry["p"], places=4)
        self.assertEqual(field("PKG_DAMAGED", "target_met").target_met, 0)  # 4 a week against a target of 1.5
        self.assertEqual(advisor.next_check(date(2026, 3, 29), lower.verdict_history), date(2026, 5, 31))
        self.assertEqual(advisor.action_state("PKG_LEAK")["name"], names["PKG_LEAK"])  # verifying: a check is still to come
        self.assertEqual(verdicts("2026-05-05"), ({}, []))  # nothing is checked twice

        checked, recurred = verdicts("2026-06-01")
        self.assertEqual({c["weeks"] for c in checked.values()}, {8})
        self.assertEqual(checked[names["PKG_LEAK"]]["verdict"], "Lower than before")
        self.assertEqual(recurred, [])
        history = json.loads(field("PKG_LEAK", "verdict_history").verdict_history)
        self.assertEqual([h["weeks"] for h in history], [4, 8])
        self.assertIsNone(advisor.next_check(date(2026, 3, 29), history))
        self.assertIsNone(advisor.action_state("PKG_LEAK"))  # done and fully checked

        self.rows += [row("PKG_LEAK", date(2026, 6, 1) + timedelta(days=4 * i), f"back{i}") for i in range(6)]  # it came back
        checked, recurred = verdicts("2026-06-27")
        self.assertEqual((checked, recurred), ({}, [names["PKG_LEAK"]]))
        back = field("PKG_LEAK", "recurred", "recurred_on")
        self.assertEqual((back.recurred, getdate(back.recurred_on)), (1, date(2026, 6, 27)))
        self.assertEqual(field("PKG_LABEL", "recurred").recurred, 0)  # only a Lower verdict can recur
        self.assertEqual(verdicts("2026-06-28")[1], [])  # recurs once

    # --- research -------------------------------------------------------------------------------------------

    def test_problem_card_is_code_built_and_every_check_can_fail(self):
        self.rows = self.leak_rows()
        card = advisor.problem_card("PKG_LEAK")
        self.assertTrue(card["ok"], card["checks"])
        text_ = card["card"]
        self.assertTrue(text_.startswith(f"Company: {advisor.COMPANY}."))
        for part in (
            "Issue: ",
            "How often: ",
            "Context: mostly reported via Instagram DM",
            "dish: chicken curry",
            "remedies offered: mostly apology only, sometimes replacement",
            "Request: " + advisor.REQUEST,
        ):
            self.assertIn(part, text_)
        for secret in ("Fatima", "5555", "ck-secret", "TEST-TKT", "2026"):
            self.assertNotIn(secret, text_)
        self.assertNotIn("How often", advisor.problem_card("FS_ILLNESS")["card"])  # no frequency for food safety

        def checks(**change):
            meta = {k: frappe._dict(v) for k, v in metrics._meta().items()}
            meta["PKG_LEAK"].update(change)
            with patch.object(metrics, "_meta", return_value=meta):
                return {c["name"]: c["ok"] for c in advisor.problem_card("PKG_LEAK")["checks"]}

        names = [c["name"] for c in card["checks"]]
        scrub, digits, contact, quote = names
        self.assertEqual(checks(label="Leaks reported to Fatima"), {scrub: False, digits: True, contact: True, quote: True})
        self.assertEqual(checks(label="Leak batch 12345"), {scrub: True, digits: False, contact: True, quote: True})
        self.assertEqual(checks(label="Leak, see www.example.com")[contact], False)
        stored = "my soup leaks out of the container during the ride home"
        doc = frappe.get_doc(
            {
                "doctype": "HD AI Contact",
                "source_key": "test-advisor-" + frappe.generate_hash(),
                "source": "Chat",
                "channel": "WhatsApp",
                "status": "Tagged",
                "issues": [{"code": "PKG_LEAK", "severity": "S3", "quote": stored, "quote_status": "Verified"}],
            }
        )
        doc.flags.ignore_links = True
        doc.insert(ignore_permissions=True)
        definition = "Soup leaks out of the container during the ride. Include: leaks. Exclude: spills."
        self.assertEqual(checks(definition=definition), {scrub: True, digits: True, contact: True, quote: False})

        meta = {k: frappe._dict(v) for k, v in metrics._meta().items()}
        meta["PKG_LEAK"].label = "Leaks reported to Fatima"
        with patch.object(metrics, "_meta", return_value=meta):
            self.assertRaisesRegex(frappe.ValidationError, "privacy check", advisor.request_research, "PKG_LEAK", USER)
        self.assertEqual(self.llm.calls, [])

    def test_research_sends_only_the_card_and_keeps_only_cited_urls(self):
        self.rows = self.leak_rows()
        cites = [
            {"type": "url_citation", "url_citation": {"url": "https://www.cold.example/guide", "title": "Cold chain guide"}},
            {"type": "url_citation", "url_citation": {"url": "http://pack.example/seal", "title": "Seals"}},
            {"type": "url_citation", "url_citation": {"url": "ftp://files.example/x"}},
            {"type": "url_citation", "url_citation": {"url": "javascript:alert(1)"}},
            {"type": "url_citation", "url_citation": {"url": "https://"}},
            {"type": "file", "url": "https://other.example/y"},
            {"type": "url_citation", "url_citation": {"url": "https://www.cold.example/guide"}},
        ]
        practice = {"what_to_do": "Pre-chill bags before packing", "fit_for_dieture": "Fits the summer routes", "effort": "S"}
        reply = {
            "practices": [
                {**practice, "title": "Pre-chill the cooler bags", "source_url": "https://www.cold.example/guide"},
                {**practice, "title": "Unsourced idea", "source_url": "https://evil.example/x"},
            ],
            "caveats": ["c1", "c2", "c3", "c4"],
        }
        self.llm = FakeLLM(web=seq(400, ("Notes about cold chains", cites)), hd_ai_structure=lambda b: reply)
        name, reused = advisor.request_research("PKG_LEAK", USER)
        self.assertFalse(reused)
        doc = frappe.get_doc(INSIGHT, name)
        card = advisor.problem_card("PKG_LEAK")["card"]
        web, fallback, structure = self.llm.calls
        self.assertEqual((doc.input_json, web["json"]["messages"][1]["content"]), (card, card))  # the card, verbatim
        self.assertEqual(web["json"]["tools"], jobs.WEB_SEARCH["tools"])
        self.assertNotIn("response_format", web["json"])
        self.assertEqual((web["json"]["temperature"], web["json"]["max_tokens"], web["timeout"]), (0, 1500, (5, 90)))
        self.assertEqual((fallback["json"]["plugins"], "tools" in fallback["json"]), ([{"id": "web"}], False))
        item = structure["json"]["response_format"]["json_schema"]["schema"]["properties"]["practices"]["items"]
        self.assertEqual(item["properties"]["source_url"]["enum"], ["https://www.cold.example/guide", "http://pack.example/seal"])
        self.assertEqual(data(structure["json"])["notes"], "Notes about cold chains")
        self.assertDenied()
        out = json.loads(doc.output_json)
        self.assertEqual(doc.status, "Done")
        self.assertEqual([(p["title"], p["domain"]) for p in out["practices"]], [("Pre-chill the cooler bags", "cold.example")])
        self.assertEqual((out["dropped"], out["caveats"], out["no_sources"], out["card"]), (1, ["c1", "c2", "c3"], False, card))
        self.assertEqual(advisor.insight_projection(name)["card"], card)
        external = advisor.build_pack("PKG_LEAK", FROM, TO)[0]["external"]["practices"]
        self.assertEqual(external, [{"id": "X1", "title": "Pre-chill the cooler bags", "domain": "cold.example"}])  # feeds the council

        self.assertEqual(advisor.request_research("PKG_LEAK", USER), (name, True))  # cached for 30 days
        self.llm = FakeLLM(web=lambda b: ("Nothing found", []))
        again, _ = advisor.request_research("PKG_LEAK", USER, regenerate=True)
        self.assertEqual(len(self.llm.calls), 1)  # no citations: no structuring call
        self.assertEqual(
            json.loads(frappe.db.get_value(INSIGHT, again, "output_json")),
            {"card": card, "practices": [], "caveats": [], "dropped": 0, "no_sources": True},
        )
        self.conf.web_research = False
        self.assertRaisesRegex(frappe.ValidationError, "switched off", advisor.request_research, "PKG_LEAK", USER)

    # --- weekly summary -------------------------------------------------------------------------------------

    def test_summary_validator_rules(self):
        values = {"kpi.complaint_cases": "12", "top.1.cases": "9"}
        signals = {"PKG_LEAK": "surge", "DLV_LATE": "improving", "FS_SPOILED": "safety"}
        by_code = {"PKG_LEAK": ["E1", "E2"], "DLV_LATE": ["E3"]}

        def errors(headline="{{kpi.complaint_cases}} complaint cases this week", **bullet):
            b = {"code": "PKG_LEAK", "kind": "surge", "text": "Leaks rose to {{top.1.cases}} cases", "cites": ["E1"], **bullet}
            return " | ".join(advisor.validate_summary({"headline": headline, "bullets": [b]}, values, signals, by_code))

        self.assertEqual(errors(), "")
        self.assertEqual(errors(code="DLV_LATE", kind="improving", text="Late deliveries were lower", cites=["E3"]), "")
        for message, got in (
            ("a digit outside a placeholder", errors(text="Leaks rose to 9 cases")),
            ("a multiplier word", errors(text="Leaks doubled this week")),
            ("unknown placeholder {{kpi.nope}}", errors(text="Leaks rose to {{kpi.nope}}")),
            ("write placeholders exactly as {{key}}", errors(text="Leaks rose to {top.1.cases}")),
            ("kind must be surge for PKG_LEAK", errors(kind="watch")),
            ("rising words need", errors(code="DLV_LATE", kind="improving", text="Late deliveries increased", cites=["E3"])),
            ("rising words need", errors(code="DLV_LATE", kind="improving", text="ارتفاع في التأخير", cites=["E3"])),
            ("falling words need an improving signal", errors(text="Leaks dropped a little")),
            ("which belong to another issue", errors(cites=["E3"])),
            ("has no signal this week", errors(code="ACC_WRONG_MEAL", kind="none", cites=[])),
            ("headline: a digit outside a placeholder", errors(headline="12 complaint cases")),
        ):
            self.assertIn(message, got)
        falling = advisor.validate_summary({"headline": "Fewer complaints overall", "bullets": []}, values, {"PKG_LEAK": "surge"}, by_code)
        self.assertEqual(falling, ["headline: falling words but no improving signal this week"])
        many = {"headline": "A quiet week", "bullets": [{"code": "FS_SPOILED", "kind": "safety", "text": "x", "cites": []}] * 6}
        self.assertIn("at most 5 bullets", advisor.validate_summary(many, values, signals, by_code))
        self.assertEqual(advisor.check_narrative("{{ kpi.complaint_cases }} cases", values), ["unknown placeholder {{ kpi.complaint_cases }}"])
        self.assertEqual(advisor.check_narrative("Twice as many leaks", values), ["a multiplier word (double, twice, triple, half, times)"])
        self.assertEqual(advisor.check_narrative("", values), [])

    def test_weekly_summary_uses_placeholders_repairs_once_then_falls_back(self):
        self.rows = self.leak_rows() + [
            row("DLV_LATE", "2026-04-27", "d1", quote="the driver came two hours late"),
            row("FS_SPOILED", "2026-04-28", "f1", "S2", quote="the chicken smelled spoiled and sour"),
        ]
        label = lambda code: metrics._meta()[code].label  # noqa: E731
        brief = {
            "week": "2026-04-26",
            "headline": {"text": "Week of 26 Apr 2026: 12 complaint cases from 10 customers.", "source": "code", "model": None, "at": None},
            "kpis": [
                {"key": "complaint_cases", "value": 12, "prior": 6.5, "display": "12", "chip": {"label": "Unusual ▲", "p": 0.004, "text": "6.5 → 12"}, "hint": "1.07 per 1,000 deliveries"},
                {"key": "customers", "value": 10, "prior": 6.0, "display": "10", "chip": None, "hint": ""},
                {"key": "calls", "value": None, "prior": None, "display": "—", "chip": None, "hint": "No answered-call data in this period"},
            ],
            "top": [{"code": "PKG_LEAK", "label": label("PKG_LEAK"), "cases": 9, "customers": 8, "week_cases": 4, "week_customers": 4, "badges": ["SURGE", "CHRONIC"]}],
            "changed": [
                {"code": "PKG_LEAK", "label": label("PKG_LEAK"), "badge": "SURGE", "text": "2 → 9 · much higher than usual (p 0.004)"},
                {"code": "DLV_LATE", "label": label("DLV_LATE"), "badge": "IMPROVING", "text": "8 → 2 · lower than usual (p 0.008)"},
            ],
            "safety": {"events": [{"code": "FS_SPOILED", "label": label("FS_SPOILED")}]},
            "demand": {},
        }
        self.enterContext(patch.object(metrics, "brief", return_value=brief))
        bad = {"headline": "12 complaint cases this week", "bullets": []}
        good = {
            "headline": "{{kpi.complaint_cases}} complaint cases from {{kpi.customers}} customers; leaks surged",
            "bullets": [
                {"code": "PKG_LEAK", "kind": "surge", "text": "Leaks rose to {{top.1.cases}} cases in four weeks", "cites": ["E1"]},
                {"code": "DLV_LATE", "kind": "improving", "text": "Late deliveries were lower than usual", "cites": []},
            ],
        }
        self.llm = FakeLLM(hd_ai_summary=seq(bad, good))
        name, reused = advisor.write_summary("2026-04-29", USER)
        self.assertFalse(reused)
        first, repair = self.llm.bodies("hd_ai_summary")
        for call in self.llm.calls:
            body = call["json"]
            self.assertEqual((body["model"], body["temperature"], body["max_tokens"], call["timeout"]), ("openai/gpt-small", 0, 1500, (5, 90)))
        self.assertDenied()
        self.assertIn("headline: a digit outside a placeholder", data(repair)["errors"])
        sent = data(first)
        self.assertEqual(
            [(s["code"], s["kind"]) for s in sent["signals"]], [("PKG_LEAK", "surge"), ("DLV_LATE", "improving"), ("FS_SPOILED", "safety")]
        )
        values = sent["values"]
        self.assertEqual((values["kpi.complaint_cases"], values["kpi.complaint_rate"], values["top.1.cases"]), ("12", "1.07 per 1,000 deliveries", "9"))
        self.assertEqual((values["kpi.complaint_cases.change"], values["code.DLV_LATE.change"]), ("6.5 → 12", "8 → 2 · lower than usual (p 0.008)"))
        self.assertNotIn("kpi.calls", values)  # no coverage: no number at all
        self.assertEqual({e["code"] for e in sent["evidence"]}, {"PKG_LEAK", "DLV_LATE", "FS_SPOILED"})
        self.assertEqual(Counter(e["code"] for e in sent["evidence"])["PKG_LEAK"], 2)  # at most 2 per signalled code
        dumped = json.dumps(self.llm.bodies(), ensure_ascii=False)
        for secret in ["2026-04", "Fatima", "5555", "ck-secret", *[r["contact"] for r in self.rows]]:
            self.assertNotIn(secret, dumped)

        doc = frappe.get_doc(INSIGHT, name)
        self.assertEqual((doc.status, getdate(doc.week_start), json.loads(doc.input_json)), ("Done", date(2026, 4, 26), sent))
        out = json.loads(doc.output_json)
        self.assertEqual((out["headline"], out["bullets"], out["fallback"], out["values"]), (good["headline"], good["bullets"], False, values))
        shown = {e["id"]: e for e in out["evidence"]}
        self.assertEqual(set(shown["E1"]), {"id", "code", "quote", "quote_en", "ref", "channel", "date", "severity", "role"})
        spoiled = next(e for e in out["evidence"] if e["code"] == "FS_SPOILED")
        with patch.object(metrics, "_mask", return_value=True):  # non-deciders with the health mask on
            masked = {e["id"]: e["quote"] for e in advisor.insight_projection(name)["output"]["evidence"]}
        self.assertEqual((masked[spoiled["id"]], masked["E1"]), (metrics.HIDDEN, shown["E1"]["quote"]))
        self.assertEqual(advisor.write_summary("2026-04-26", USER), (name, True))  # cached per week

        self.llm = FakeLLM(hd_ai_summary=seq(bad, bad))
        again, _ = advisor.write_summary("2026-04-26", USER, regenerate=True)
        out = json.loads(frappe.db.get_value(INSIGHT, again, "output_json"))
        self.assertEqual((out["headline"], out["bullets"], out["fallback"]), (brief["headline"]["text"], [], True))
        self.assertEqual(len(self.llm.calls), 2)

    # --- projection, retention, jobs ------------------------------------------------------------------------

    def test_projection_hides_server_fields_masks_health_quotes_and_lists_history(self):
        ill = "I was vomiting all night after the lunch"
        evidence = [
            {"id": "E1", "quote": ill, "quote_en": ill, "ref": "abc", "channel": "WhatsApp", "date": "2026-04-10", "severity": "S1", "role": "customer"},
            {"id": "E2", "quote": "it came cold", "quote_en": "it came cold", "ref": "def", "channel": "WhatsApp", "date": "2026-04-11", "severity": "S3", "role": "customer"},
        ]
        name = self.insight(
            "Suggestions",
            issue_code="FS_ILLNESS",
            status="Done",
            period_start=FROM,
            period_end=TO,
            pack_hash="old",
            input_json='{"pack": {"server-only": 1}}',
            alias_map='{"E1": {"contact": "server-only"}}',
            output_json=json.dumps({"options": [], "cards": [], "evidence": evidence}),
        )
        child = self.insight("Suggestions", issue_code="FS_ILLNESS", status="Queued", parent_insight=name, note="v2")
        with patch.object(metrics, "_mask", return_value=True):
            p = advisor.insight_projection(name)
        keys = {"name", "insight_type", "issue_code", "status", "step", "progress_label", "error", "output", "decision"}
        keys |= {"decision_reason", "decision_note", "decided_by", "decided_on", "parent_insight", "creation", "requested_by"}
        self.assertEqual(set(p), keys | {"models", "stale", "history"})
        self.assertNotIn("server-only", json.dumps(p, default=str))
        self.assertEqual([(e["quote"], e["quote_en"]) for e in p["output"]["evidence"]], [(metrics.HIDDEN, metrics.HIDDEN), ("it came cold", "it came cold")])
        self.assertTrue(p["stale"])  # the pack would hash differently now
        self.assertEqual([(h["name"], h["parent_insight"], h["note"]) for h in p["history"]], [(name, None, None), (child, name, "v2")])
        self.assertEqual(advisor.insight_projection(name)["output"]["evidence"][0]["quote"], ill)  # deciders, or the mask off
        c = advisor.insight_projection(child)
        self.assertEqual((c["output"], c["stale"], [h["name"] for h in c["history"]]), (None, False, [name, child]))
        research = advisor.insight_projection(self.insight("Research", issue_code="PKG_LEAK", status="Running", input_json="Company: card"))
        self.assertEqual((research["card"], research["output"]), ("Company: card", None))

    def test_purge_insights_deletes_old_runs_and_blanks_old_evidence(self):
        old = [self.insight(kind, status="Done") for kind in ("Question", "Brief", "Research", "Evaluation")]
        output = {"cards": [{"type": "quick_win"}], "evidence": [{"id": "E1", "quote": "the soup leaked", "quote_en": "the soup leaked", "ref": "abc"}]}
        plan = self.insight("Suggestions", issue_code="PKG_LEAK", status="Done", input_json='{"pack": {}}', alias_map='{"E1": {}}', output_json=json.dumps(output))
        recent = self.insight("Brief", status="Done")
        for name in [*old, plan]:
            frappe.db.set_value(INSIGHT, name, "creation", "2024-01-01 10:00:00", update_modified=False)
        out = advisor.purge_insights(as_of="2026-11-06")
        self.assertGreaterEqual(out["deleted"], 4)
        self.assertGreaterEqual(out["blanked"], 1)
        self.assertEqual([n for n in old if frappe.db.exists(INSIGHT, n)], [])
        self.assertTrue(frappe.db.exists(INSIGHT, recent))
        kept = frappe.db.get_value(INSIGHT, plan, ["input_json", "alias_map", "output_json"], as_dict=True)
        self.assertEqual((kept.input_json or "", kept.alias_map or ""), ("", ""))
        self.assertEqual(json.loads(kept.output_json), {"cards": [{"type": "quick_win"}], "evidence": [{"id": "E1", "quote": "", "quote_en": "", "ref": None}]})
        self.assertEqual(advisor.purge_insights(as_of="2026-11-06")["blanked"], 0)  # nothing left to blank

    def test_maintenance_runs_each_advisor_step_guarded(self):
        # the SQL steps run on stand-ins, so the site's contacts and gold labels are never touched
        self.enterContext(patch.object(jobs, "_release_stale", return_value=0))
        self.enterContext(patch.object(jobs, "_vanished", return_value=[]))
        self.enterContext(patch.object(jobs, "_delete", side_effect=len))
        self.enterContext(patch.object(frappe.db, "delete"))
        clean = {"deleted": 0, "blanked": 0}
        with patch.object(advisor, "update_verdicts", side_effect=RuntimeError("Fatima 55551234")), patch.object(
            advisor, "purge_insights", return_value=clean
        ) as purge:
            out = jobs.maintenance(as_of="2026-11-06")
        purge.assert_called_once_with(date(2026, 11, 6))
        self.assertEqual(out["insights"], clean)
        self.assertNotIn("verdicts", out)
        logged = [c.kwargs for c in self.log_error.call_args_list if c.kwargs.get("title") == "AI Analysis maintenance failed"]
        self.assertEqual(logged, [{"title": "AI Analysis maintenance failed", "message": "RuntimeError at maintenance:verdicts"}])
        with patch.object(advisor, "update_verdicts", return_value={"checked": [], "recurred": []}), patch.object(
            advisor, "purge_insights", side_effect=KeyError("x")
        ):
            out = jobs.maintenance(as_of="2026-11-06")
        self.assertEqual((out["verdicts"], "insights" in out), ({"checked": [], "recurred": []}, False))

    def test_run_now_runs_the_job_bodies_inline(self):
        self.rows = self.leak_rows()
        frappe.flags.hd_ai_sync = False
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            jobs.run_now("suggest", code="PKG_LEAK", from_date=FROM, to_date=TO)
        printed = json.loads(buffer.getvalue())
        self.assertEqual((printed["status"], printed["insight_type"]), ("Done", "Suggestions"))
        self.assertFalse({"alias_map", "input_json"} & set(printed))
        self.assertFalse(frappe.flags.hd_ai_sync)
        self.enqueue.assert_not_called()
        with patch.object(advisor, "update_verdicts", return_value={"checked": [], "recurred": []}) as verdicts, redirect_stdout(io.StringIO()):
            jobs.run_now("verdicts", as_of="2026-06-27")
        verdicts.assert_called_once_with("2026-06-27")
