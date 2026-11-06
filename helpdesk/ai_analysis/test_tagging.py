"""Tagging: the strict schema, post-processing rules, dish matching, what tag_contact stores and sends,
the label version and the gold set. The model is always mocked (no API key is configured locally), and
the registry is a fixed synthetic one so manager edits to the live codes never move these numbers.
"""

import json
from collections import Counter
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import now_datetime

import helpdesk.ai_analysis as ai_analysis
from helpdesk.ai_analysis import registry, tagging, text
from helpdesk.api import ticket_ai


def _code(code, kind, floor, fs=0):
    return frappe._dict(
        code=code,
        label=code.title(),
        kind=kind,
        family=code.split("_")[0],
        owner_department="Customer Service",
        severity_floor=floor,
        is_food_safety=fs,
        definition=f"{code}. Include: the obvious cases. Exclude: the rest.",
        examples="It came late\nتأخر الطلب",
    )


CODES = [
    _code("DLV_LATE", "Complaint", "S3"),
    _code("ENQ_PRICE", "Enquiry", "S4"),
    _code("FS_SPOILED", "Complaint", "S2", fs=1),
    _code("PKG_LEAK", "Complaint", "S3"),
]
META = {c.code: frappe._dict(c, status="Active", merged_into=None, target=c.code) for c in [*CODES, _code("NEW", "Other", "S4")]}
CATALOGUE = ["butter chicken with rice", "chicken caesar salad"]
LINES = [
    {"id": "L1", "role": "customer", "text": "السلام عليكم، الدجاج ريحته خايسة"},
    {"id": "L2", "role": "customer", "text": "and the order came two hours late"},
    {"id": "L3", "role": "agent", "text": "Sorry, we will send a replacement today"},
    {"id": "L4", "role": "customer", "text": "How much is the monthly plan?"},
]
CONFIG = {"enabled": True, "base_url": "https://openrouter.ai/api/v1", "model": "openai/gpt-4.1"}


def issue(code, severity="S3", quote="", line="L1", primary=False, **values):
    return {
        "code": code,
        "proposed_label": "",
        "statement_en": "",
        "severity": severity,
        "is_primary": primary,
        "quote": quote,
        "quote_line": line,
        "quote_en": "",
        "dish": "",
        "confidence": "high",
        **values,
    }


class TestTagging(FrappeTestCase):
    def setUp(self):
        super().setUp()
        self.enterContext(patch.object(frappe.db, "commit"))
        self.enterContext(patch.object(registry, "active_codes", return_value=[frappe._dict(c) for c in CODES]))
        self.enterContext(patch.object(registry, "code_meta", return_value=META))

    def tearDown(self):
        frappe.db.rollback()
        super().tearDown()

    def contact(self, issues=(), **values):
        doc = frappe.get_doc(
            {
                "doctype": "HD AI Contact",
                "source_key": "test-" + frappe.generate_hash(),
                "source": "Chat",
                "channel": "WhatsApp",
                "status": "Pending",
                "has_text": 1,
                "language": "en",
                **values,
            }
        )
        for row in issues:
            doc.append("issues", row)
        doc.flags.ignore_links = True
        doc.insert(ignore_permissions=True)
        return doc.name

    def test_schema_is_strict_without_max_items(self):
        s = tagging.schema(["DLV_LATE", "NEW"], ["L1", "L2"])
        item = s["properties"]["issues"]["items"]
        for obj in (s, item):
            self.assertIs(obj["additionalProperties"], False)
            self.assertEqual(obj["required"], list(obj["properties"]))
        self.assertEqual(item["properties"]["code"]["enum"], ["DLV_LATE", "NEW"])  # NEW once
        self.assertEqual(item["properties"]["quote_line"]["enum"], ["L1", "L2"])
        self.assertEqual(s["required"], ["issues", "offered", "looks_like_test"])
        self.assertNotIn("maxItems", json.dumps(s))

    def test_postprocess_drops_merges_caps_and_checks_quotes(self):
        raw = {
            "issues": [
                # the model under-rates food safety: the S2 floor lifts it
                issue("FS_SPOILED", "S4", quote="الدجاج ريحته خايسة", dish="Butter chicken with rice"),
                # S1 only on food-safety codes; the statement loses the phone and every digit
                issue("DLV_LATE", "S1", quote="the order came too hours late", line="L2", dish="chicken", statement_en="Order 2 hours late, call 55551234 now"),
                issue("DLV_LATE", "S3", quote="came two hours late", line="L2", primary=True),  # duplicate: merged
                issue("NOT_A_CODE", "S1"),  # unknown code: dropped
                issue("NEW", "S2"),  # NEW without a label: dropped
                issue("PKG_LEAK", "S3", quote="we will send a replacement today", line="L3"),  # agent words
                issue("NEW", "S4", proposed_label="Invoice request", quote="How much is the monthly plan", line="L4"),
                issue("ENQ_PRICE", "S4", quote="How much is the monthly plan", line="L4"),  # fifth: cut
            ]
        }
        rows = tagging.postprocess(raw, LINES, META, "WhatsApp", CATALOGUE)
        self.assertEqual([r["code"] for r in rows], ["DLV_LATE", "FS_SPOILED", "PKG_LEAK", "NEW"])
        by = {r["code"]: r for r in rows}
        self.assertEqual([r["is_primary"] for r in rows], [1, 0, 0, 0])  # the duplicate's primary flag survives the merge
        self.assertEqual((by["FS_SPOILED"]["severity"], by["DLV_LATE"]["severity"], by["NEW"]["severity"]), ("S2", "S2", "S4"))
        self.assertEqual(by["FS_SPOILED"]["quote"], "الدجاج ريحته خايسة")
        self.assertEqual((by["FS_SPOILED"]["quote_status"], by["FS_SPOILED"]["quote_role"]), ("Verified", "customer"))
        self.assertEqual(by["FS_SPOILED"]["dish_item"], "butter chicken with rice")
        # the most severe duplicate is the one kept, and its near-miss quote is repaired to the source span
        self.assertEqual((by["DLV_LATE"]["quote_status"], by["DLV_LATE"]["quote"]), ("Repaired", "the order came two hours late"))
        self.assertEqual(by["DLV_LATE"]["statement_en"], "Order hours late, call [phone] now")
        self.assertEqual((by["DLV_LATE"]["dish"], by["DLV_LATE"]["dish_item"]), ("chicken", ""))
        self.assertEqual((by["PKG_LEAK"]["quote_status"], by["PKG_LEAK"]["quote"], by["PKG_LEAK"]["quote_role"]), ("Unverified", "", ""))
        self.assertEqual(by["NEW"]["proposed_label"], "Invoice request")
        self.assertEqual(by["PKG_LEAK"]["proposed_label"], "")

    def test_postprocess_primary_and_public_severity(self):
        public = tagging.postprocess(
            {"issues": [issue("DLV_LATE", "S3"), issue("FS_SPOILED", "S2"), issue("ENQ_PRICE", "S4"), issue("PKG_LEAK", "S2")]},
            LINES,
            META,
            "Instagram comment",
            [],
        )
        severity = {r["code"]: r["severity"] for r in public}
        # complaints move up one level in public; non-food-safety stops at S2; enquiries stay
        self.assertEqual(severity, {"FS_SPOILED": "S1", "DLV_LATE": "S2", "PKG_LEAK": "S2", "ENQ_PRICE": "S4"})
        self.assertEqual([r["code"] for r in public if r["is_primary"]], ["FS_SPOILED"])  # none flagged: most severe

        def primaries(*issues):
            rows = tagging.postprocess({"issues": list(issues)}, LINES, META, "WhatsApp", [])
            return [r["code"] for r in rows if r["is_primary"]]

        self.assertEqual(primaries(issue("DLV_LATE", "S3", primary=True), issue("FS_SPOILED", "S2", primary=True)), ["FS_SPOILED"])
        self.assertEqual(primaries(issue("DLV_LATE", "S3", primary=True), issue("FS_SPOILED", "S2")), ["DLV_LATE"])
        self.assertEqual(tagging.postprocess({"issues": [issue("NOT_A_CODE")]}, LINES, META, "WhatsApp", []), [])

    def test_match_dish_needs_a_clear_winner(self):
        catalogue = ["butter chicken with rice", "chicken caesar salad", "keto butter chicken with rice"]
        self.assertIsNone(tagging.match_dish("chicken", catalogue))  # ties with every chicken dish
        self.assertEqual(tagging.match_dish("Butter Chicken with Rice!", catalogue), "butter chicken with rice")
        self.assertEqual(tagging.match_dish("chicken ceasar salad", catalogue), "chicken caesar salad")
        self.assertIsNone(tagging.match_dish("butter chicken", catalogue))  # two butter chicken dishes
        self.assertIsNone(tagging.match_dish("", catalogue))
        self.assertIsNone(tagging.match_dish("salad", []))

    def test_dish_catalogue_is_normalised_and_unique(self):
        with patch.object(frappe.cache, "get_value", return_value=None), patch.object(frappe.cache, "set_value") as cache:
            dishes = tagging.dish_catalogue()
        self.assertEqual(dishes, sorted(set(dishes)))
        self.assertTrue(all(d and d == text.normalize(d) for d in dishes))
        cache.assert_any_call(tagging.DISH_CACHE_KEY, dishes, expires_in_sec=3600)

    def test_version_follows_definitions_not_labels(self):
        codes = registry.active_codes.return_value
        before = tagging.current_version()
        self.assertRegex(before, r"^tag-v1:[0-9a-f]{10}$")
        codes[0].label = "Renamed"
        self.assertEqual(tagging.current_version(), before)
        codes[0].definition = "A sharper definition. Include: more. Exclude: less."
        self.assertNotEqual(tagging.current_version(), before)

    def test_tag_contact_replaces_rows_and_carries_reviews(self):
        reviewed = {"reviewed_by": "Administrator", "reviewed_on": "2026-11-01 10:00:00"}
        name = self.contact(
            issues=[
                {"code": "DLV_LATE", "severity": "S3", "review": "Rejected", **reviewed},
                {"code": "PKG_LEAK", "severity": "S3", "review": "Confirmed", **reviewed},
            ],
            status="Tagging",
            claim_token="run:0",
            claimed_at=now_datetime(),
            attempts=2,
            cost_usd=0.001,
        )
        reply = {
            "issues": [
                issue("DLV_LATE", "S3", quote="the order came two hours late", line="L2", primary=True),
                issue("FS_SPOILED", "S2", quote="الدجاج ريحته خايسة"),
                issue("RETIRED_CODE", "S3"),
            ],
            "offered": "replacement",
            "looks_like_test": False,
        }
        with patch.object(tagging, "dish_catalogue", return_value=CATALOGUE), patch.object(
            ticket_ai, "chat_json", return_value=(reply, {"cost": 0.004})
        ) as call:
            out = tagging.tag_contact(name, LINES)
        self.assertEqual(out, {"issues": 2, "cost": 0.004, "dropped": 1})
        kwargs = call.call_args.kwargs
        self.assertEqual(
            (kwargs["name"], kwargs["temperature"], kwargs["max_tokens"], kwargs["timeout"], kwargs["model"]),
            ("hd_ai_tag", 0, 1200, (5, 90), ai_analysis.conf().model),
        )
        self.assertEqual(kwargs["provider"], ai_analysis.ai_provider())

        doc = frappe.get_doc("HD AI Contact", name)
        version = tagging.current_version()
        self.assertEqual((doc.status, doc.tagged_version, doc.offered, doc.looks_like_test), ("Tagged", version, "replacement", 0))
        self.assertAlmostEqual(doc.cost_usd, 0.005)
        self.assertEqual((doc.attempts, doc.claim_token or "", doc.claimed_at, doc.error or ""), (0, "", None, ""))
        self.assertTrue(doc.tagged_on)
        by = {r.code: r for r in doc.issues}
        self.assertEqual(set(by), {"DLV_LATE", "FS_SPOILED"})  # PKG_LEAK is gone, with its review
        self.assertEqual((by["DLV_LATE"].review, by["DLV_LATE"].reviewed_by), ("Rejected", "Administrator"))
        self.assertFalse(by["FS_SPOILED"].review)
        self.assertEqual({r.prompt_version for r in doc.issues}, {version})

    def test_request_body_carries_no_identifiers(self):
        name = self.contact(ticket="LEAK-TKT-7731", conversation="MSG-CONV-Fatima Al-Kuwari-00042", customer_key="c0ffee1234567890")
        lines = [
            {"id": "L1", "role": "customer", "text": "Hi it's [name], call me on +974 5555 1234", "at": "2026-04-02 10:00"},
            {"id": "L2", "role": "customer", "text": "the order came two hours late"},
        ]
        content = json.dumps({"issues": [issue("DLV_LATE", quote="the order came two hours late", line="L2", primary=True)], "offered": "none", "looks_like_test": False})
        response = MagicMock(status_code=200)
        response.json.return_value = {"choices": [{"message": {"content": content}, "finish_reason": "stop"}], "usage": {"cost": 0.002}}
        with patch.object(ticket_ai, "get_config", return_value=dict(CONFIG)), patch.object(ticket_ai, "_api_key", return_value="sk-or-test"), patch.object(
            ticket_ai.requests, "post", return_value=response
        ) as post, patch.object(tagging, "dish_catalogue", return_value=CATALOGUE):
            out = tagging.tag_contact(name, lines)
        self.assertEqual(out["issues"], 1)
        body = post.call_args.kwargs["json"]
        sent = json.dumps(body, ensure_ascii=False)
        for secret in ("LEAK-TKT-7731", "MSG-CONV", "Fatima", "Kuwari", "c0ffee1234567890", "5555 1234", "2026-04-02", "sk-or-test", name):
            self.assertNotIn(secret, sent)
        data = json.loads(body["messages"][1]["content"])
        self.assertEqual(list(data), ["registry", "contact"])  # the registry first: a cacheable prefix
        self.assertEqual(list(data["contact"]), ["channel", "replies_captured", "lines"])
        self.assertEqual(data["contact"]["lines"][0], {"id": "L1", "role": "customer", "text": "Hi it's [name], call me on [phone]"})
        self.assertEqual(post.call_args.kwargs["timeout"], (5, 90))
        self.assertEqual((body["temperature"], body["max_tokens"]), (0, 1200))
        self.assertEqual(body["response_format"]["json_schema"]["name"], "hd_ai_tag")
        self.assertIs(body["response_format"]["json_schema"]["strict"], True)
        self.assertEqual(body["provider"]["data_collection"], "deny")

    def test_gold_sample_meets_quotas_and_only_tops_up(self):
        pool = [
            {"name": f"test-gold-{i:03}", "arabic": i % 6 == 0, "safety": i % 10 == 0, "multi": i % 7 == 0, "family": "DLV" if i % 2 else "ENQ"}
            for i in range(150)
        ]
        self.assertEqual(tagging._pick(list(reversed(pool)), 80), tagging._pick(pool, 80))  # order-free
        cases = SimpleNamespace(lines_for=lambda names: {n: [{"id": "L1", "role": "customer", "text": "late again"}] for n in names})
        with patch.object(tagging, "_gold_pool", return_value=pool), patch.object(ai_analysis, "cases", cases, create=True):
            created = tagging.gold_sample(["Administrator", "Guest"], n=80)
            again = tagging.gold_sample('["Administrator", "Guest"]', n=80)
        self.assertEqual((created, again), (100, 0))  # 20 for both labellers + 60 dealt; a rerun adds nothing
        rows = frappe.get_all("HD AI Gold Label", filters={"contact": ["like", "test-gold-%"]}, fields=["contact", "labeller", "lines"])
        per_contact = Counter(r.contact for r in rows)
        self.assertEqual(len(per_contact), 80)
        self.assertEqual(Counter(per_contact.values()), {1: 60, 2: 20})
        self.assertEqual(Counter(r.labeller for r in rows), {"Administrator": 50, "Guest": 50})
        by_name = {p["name"]: p for p in pool}
        for key, quota in tagging.GOLD_QUOTAS:
            self.assertGreaterEqual(sum(by_name[c][key] for c in per_contact), quota, key)
        self.assertEqual(rows[0].lines, "L1 [customer] late again")

    def test_score_gold_on_synthetic_labels(self):
        if frappe.db.count("HD AI Gold Label"):
            self.skipTest("the site already has gold labels, which score_gold would mix in")

        def tag(code, status="Verified", primary=0, review=""):
            return {"code": code, "severity": "S3", "quote_status": status, "is_primary": primary, "review": review}

        c1 = self.contact(status="Tagged", issues=[tag("DLV_LATE", primary=1), tag("FS_SPOILED", "Unverified")])
        c2 = self.contact(status="Tagged", issues=[tag("DLV_LATE", "Repaired", 1), tag("PKG_LEAK")])
        c3 = self.contact(status="Tagged", issues=[tag("ENQ_PRICE", primary=1), tag("DLV_LATE", review="Rejected")])
        c4 = self.contact(status="Tagged", issues=[tag("DLV_LATE", primary=1)])
        c5 = self.contact(status="Pending")  # not tagged yet: not scored
        c6 = self.contact(status="Tagged", issues=[tag("PKG_LEAK", primary=1)])  # its gold row is still blank
        for contact, labeller, codes, primary, final in (
            (c1, "Administrator", "DLV_LATE\nFS_SPOILED", "DLV_LATE", 0),
            (c1, "Guest", "DLV_LATE", "DLV_LATE", 0),
            (c2, "Administrator", "DLV_LATE", "DLV_LATE", 0),
            (c2, "Guest", "PKG_LEAK\nDLV_LATE", "PKG_LEAK", 1),  # the final label wins over the earlier one
            (c3, "Administrator", "ENQ_PRICE\nDLV_LATE", "ENQ_PRICE", 0),
            (c4, "Administrator", "FS_SPOILED", "FS_SPOILED", 0),
            (c5, "Administrator", "DLV_LATE", "DLV_LATE", 0),
            (c6, "Administrator", "", "", 0),
        ):
            row = {"doctype": "HD AI Gold Label", "contact": contact, "labeller": labeller, "codes": codes, "primary_code": primary, "is_final": final}
            frappe.get_doc(row).insert(ignore_permissions=True)

        old = frappe.cache.get_value(tagging.GOLD_CACHE_KEY)
        try:
            score = tagging.score_gold()
            cached = frappe.cache.get_value(tagging.GOLD_CACHE_KEY)
        finally:  # never leave a synthetic score on the site's status strip
            if old:
                frappe.cache.set_value(tagging.GOLD_CACHE_KEY, old)
            else:
                frappe.cache.delete_value(tagging.GOLD_CACHE_KEY)

        self.assertEqual(score["n"], 4)
        self.assertEqual(score["per_code"]["DLV_LATE"], {"gold": 3, "ai": 3, "tp": 2, "precision": 0.667, "recall": 0.667, "f1": 0.667})
        self.assertEqual(score["per_code"]["FS_SPOILED"], {"gold": 2, "ai": 0, "tp": 0, "precision": None, "recall": 0.0, "f1": 0.0})
        self.assertEqual(score["per_code"]["PKG_LEAK"]["f1"], 1.0)
        self.assertEqual(score["macro_f1"], 0.667)  # only DLV_LATE has 3 gold cases
        self.assertEqual(score["safety_recall"], 0.5)  # the Unverified FS tag on c1 still counts; c4 is missed
        self.assertEqual(score["quote_validity"], 0.833)  # 5 of 6 non-rejected tags
        self.assertEqual((score["kappa"], score["kappa_pairs"]), (0.0, 2))
        self.assertFalse(score["ok"])
        self.assertEqual(cached, score)
        insight = frappe.get_all("HD AI Insight", filters={"insight_type": "Evaluation"}, fields=["status", "output_json"], order_by="creation desc", limit=1)[0]
        self.assertEqual((insight.status, json.loads(insight.output_json)), ("Done", score))
