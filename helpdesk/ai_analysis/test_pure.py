"""Tests for the pure AI Analysis modules: text, safety and stats (no database needed)."""

import re
import unittest
from datetime import date, datetime, timedelta

from helpdesk.ai_analysis import safety, stats, text


class TestNormalize(unittest.TestCase):
    def test_arabic_diacritics_tatweel_and_letter_forms(self):
        self.assertEqual(text.normalize("الأَكْلُ بَـــارِدٌ"), "الاكل بارد")
        self.assertEqual(text.normalize("مستشفى الصحة إلى آخر ٱلبيت"), "مستشفي الصحه الي اخر البيت")

    def test_digits_case_punctuation_and_spaces(self):
        self.assertEqual(text.normalize("Hello,,,   WORLD!! ٣ وجبات ۵ Straße"), "hello world 3 وجبات 5 strasse")
        self.assertEqual(text.normalize("  ok\u200F done 👍🏻\n"), "ok done")
        self.assertEqual(text.normalize(None), "")

    def test_span_recovery_through_the_map(self):
        s = "قال: الأَكْلُ بَـــارِدٌ!!"
        norm, m = text.normalize_with_map(s)
        self.assertEqual(len(norm), len(m))
        i = norm.find("بارد")
        j = i + len("بارد")
        self.assertEqual(s[m[i] : m[j - 1] + 1], "بَـــارِد")

    def test_nfkc_expansion_maps_every_char_to_its_source(self):
        s = "ﬁsh ﬁllet"
        norm, m = text.normalize_with_map(s)
        self.assertEqual(norm, "fish fillet")
        i = norm.find("fillet")
        self.assertEqual(m[i], m[i + 1])  # "f" and "i" both come from the ligature
        self.assertEqual(s[m[i] : m[i + 5] + 1], "ﬁllet")


class TestScrub(unittest.TestCase):
    def test_phones(self):
        for raw in (
            "+974 5555 1234",
            "00974-5555-1234",
            "(+974) 5555 1234",
            "55551234",
            "5555 1234",
            "555-123-4567",
            "+44 7700 900123",
            "٥٥٥٥١٢٣٤",
        ):
            with self.subTest(raw=raw):
                self.assertEqual(text.scrub(f"call me on {raw} please"), "call me on [phone] please")

    def test_emails_urls_handles(self):
        self.assertEqual(text.scrub("mail a.b+x@gmail.com now"), "mail [email] now")
        self.assertEqual(text.scrub("see https://dieture.qa/x?y=1 and www.instagram.com/foo"), "see [link] and [link]")
        self.assertEqual(text.scrub("order at dieture.com/plans"), "order at [link]")
        self.assertEqual(text.scrub("dm @dieture_qa pls"), "dm @user pls")

    def test_addresses(self):
        self.assertEqual(text.scrub("zone 66 street 900"), "[address]")
        self.assertEqual(text.scrub("Building No. 12, Flat #3 near the mall"), "[address] near the mall")
        self.assertEqual(text.scrub("منطقة 45"), "[address]")
        self.assertEqual(text.scrub("ساكن في شارع رقم 900 مبنى 7"), "ساكن في [address]")
        self.assertEqual(text.scrub("منطقه ٤٥"), "[address]")

    def test_long_numbers(self):
        self.assertEqual(text.scrub("order 123456 ok"), "order [number] ok")
        self.assertEqual(text.scrub("order 12345 ok"), "order 12345 ok")

    def test_names_latin_and_arabic(self):
        names = text.name_tokens(["Ahmed bin Ali Al Thani", "علي الكواري"])
        self.assertEqual(
            text.scrub("Thanks AHMED, Alice and ali helped; quality ok. Thani", names),
            "Thanks [name], Alice and [name] helped; quality ok. [name]",
        )
        arabic = text.name_tokens(["أحمد الكواري", "علي"])
        self.assertEqual(
            text.scrub("شكرا احمد ومحمد فعلي علي أَحمد احـمد الكواري", arabic),
            # ومحمد stays (محمد is not a known name); فعلي is over-scrubbed on purpose (ف + علي): privacy wins
            "شكرا [name] ومحمد ف[name] [name] [name] [name] [name]",
        )
        joined = text.name_tokens(["محمد"])  # one-letter proclitics: and / so / with / for
        self.assertEqual(text.scrub("انا ومحمد وصلنا، شكرا لمحمد واتصلت بمحمد", joined), "انا و[name] وصلنا، شكرا ل[name] واتصلت ب[name]")
        self.assertEqual(text.scrub("المحمدي محمدي", joined), "المحمدي محمدي")  # other words that merely contain it stay
        once = text.scrub("ومحمد", joined)
        self.assertEqual(text.scrub(once, joined), once)  # still idempotent

    def test_no_false_hits_on_ordinary_words(self):
        names = text.name_tokens(["Ali Hassan", "Rose Mary"])
        s = "The chicken arrived late, the street was closed. 2 meals for 120 QAR at 10:30 on the 1st floor"
        self.assertEqual(text.scrub(s, names), s)
        self.assertEqual(text.scrub("[phone] and [email]", {"phone", "email"}), "[phone] and [email]")

    def test_scrub_is_idempotent(self):  # the research card's pre-send check is "scrubbing changes nothing"
        names = text.name_tokens(["Ali Hassan"])
        once = text.scrub("Ali: call +974 5555 1234 or a@b.com, @ali_q, https://x.qa, zone 66 street 9, ref 1234567890", names)
        self.assertEqual(once, "[name]: call [phone] or [email], @user, [link], [address], ref [phone]")
        self.assertEqual(text.scrub(once, names), once)

    def test_name_tokens(self):
        self.assertEqual(
            text.name_tokens(["Ahmed bin Ali Al Thani", "Administrator", "Guest", "Dieture Team", "Support Agent 007"]),
            {"ahmed", "ali", "thani"},
        )
        self.assertEqual(text.name_tokens(["أحمد الكواري", "عبد الله أبو محمد"]), {"أحمد", "الكواري", "عبد", "محمد"})
        self.assertEqual(text.name_tokens("Sara Khan"), {"sara", "khan"})

    def test_last8_and_language(self):
        self.assertEqual(text.last8("+974 5555 1234"), "55551234")
        self.assertEqual(text.last8("٥٥٥٥١٢٣٤"), "55551234")
        self.assertIsNone(text.last8("1234"))
        self.assertIsNone(text.last8(None))
        self.assertEqual(text.language(["مرحبا كيف الحال"]), "ar")
        self.assertEqual(text.language(["hello there"]), "en")
        self.assertEqual(text.language(["hello", "مرحبا"]), "mixed")
        self.assertAlmostEqual(text.arabic_share("ab مرحبا"), 5 / 7)


LINES = [
    {"id": "L1", "role": "ticket", "text": "Late delivery and cold food"},
    {"id": "L2", "role": "customer", "text": "Hi, the chicken was COLD!!"},
    {"id": "L3", "role": "agent", "text": "Sorry, we will send a replacement today"},
    {"id": "L4", "role": "bot", "text": "Thanks for contacting us, an agent will reply soon"},
    {"id": "L5", "role": "customer", "text": "the rice was"},
    {"id": "L6", "role": "customer", "text": "totally burnt..."},
    {"id": "L7", "role": "staff", "text": "Kitchen checked the batch, temperature log was fine"},
]


class TestVerifyQuote(unittest.TestCase):
    def test_verified_on_the_cited_line_returns_the_original_span(self):
        self.assertEqual(text.verify_quote("the chicken was cold", LINES, "L2"), ("Verified", "the chicken was COLD", "L2"))

    def test_found_on_another_line(self):
        self.assertEqual(
            text.verify_quote("kitchen checked the batch", LINES, "L2"), ("Verified", "Kitchen checked the batch", "L7")
        )

    def test_multi_bubble_quote(self):
        self.assertEqual(
            text.verify_quote("The rice was totally burnt", LINES, "L6"), ("Verified", "the rice was totally burnt", "L5")
        )

    def test_repaired_near_exact(self):
        self.assertEqual(
            text.verify_quote("Kitchen checked the batch, temprature log was fine", LINES, "L7"),
            ("Repaired", "Kitchen checked the batch, temperature log was fine", "L7"),
        )

    def test_unverified_and_too_short(self):
        self.assertEqual(text.verify_quote("the driver was rude to me", LINES, "L2"), ("Unverified", None, None))
        self.assertEqual(text.verify_quote("COLD!!", LINES, "L2")[0], "Unverified")  # one word
        self.assertEqual(text.verify_quote("so cold", LINES, "L2")[0], "Unverified")  # under 8 chars
        self.assertEqual(text.verify_quote(None, LINES, "L2")[0], "Unverified")

    def test_bot_and_agent_lines_never_match(self):
        self.assertEqual(text.verify_quote("an agent will reply soon", LINES, "L4"), ("Unverified", None, None))
        self.assertEqual(text.verify_quote("we will send a replacement", LINES, "L3"), ("Unverified", None, None))

    def test_a_short_line_inside_a_long_quote_is_not_repaired(self):
        quote = "the chicken was cold and the rice was raw and smelly"
        self.assertEqual(text.verify_quote(quote, LINES, "L2"), ("Unverified", None, None))

    def test_arabic_span_keeps_diacritics(self):
        lines = [{"id": "L1", "role": "customer", "text": "الأَكْلُ بَـــارِدٌ جداً"}]
        self.assertEqual(text.verify_quote("الاكل بارد جدا", lines, "L1"), ("Verified", "الأَكْلُ بَـــارِدٌ جداً", "L1"))


SAFETY_POSITIVES = [
    ("I got food poisoning after your meal", "illness"),
    ("my son was vomiting all night", "illness"),
    ("diarrhoea since lunch", "illness"),
    ("تسممت من الأكل", "illness"),
    ("عندي استفراغ", "illness"),
    ("عندي إسهال", "illness"),
    ("عندي مغص", "illness"),
    ("عندي وجع بطن", "illness"),
    ("I got ill after eating the chicken", "illness_after_eating"),
    ("I felt ill after the meal", "illness_after_eating"),
    ("I'm sick after eating your food", "illness_after_eating"),
    ("كنت مريض بعد الأكل", "illness_after_eating"),
    ("تعبت بعد الوجبة", "illness_after_eating"),
    ("I have a nut allergy and got a rash", "allergic_reaction"),
    ("allergic reaction after the salad", "allergic_reaction"),
    ("عندي حساسية وطلع لي طفح", "allergic_reaction"),
    ("there was glass in my rice", "hard_object"),
    ("found a piece of metal in the salad", "hard_object"),
    ("لقيت زجاج في الأكل", "hard_object"),
    ("لقيت حصى في الرز", "hard_object"),
    ("found a cockroach in the box", "pest"),
    ("I found a bug in my salad", "pest"),
    ("لقيت صرصور", "pest"),
    ("فيه حشرة في الأكل", "pest"),
    ("فيه دودة في السلطة", "pest"),
    ("went to the hospital after vomiting", "hospital_or_clinic"),
    ("ودوني المستشفى من التسمم", "hospital_or_clinic"),
    ("I will report you to the municipality", "authority"),
    ("بشتكي عليكم في البلدية", "authority"),
    ("برفع شكوى لوزارة الصحة", "authority"),
    ("the chicken was spoiled", "spoiled"),
    ("the yogurt was expired", "spoiled"),
    ("it smells bad", "spoiled"),
    ("الأكل فاسد", "spoiled"),
    ("اللبن منتهي الصلاحية", "spoiled"),
    ("الأكل خربان", "spoiled"),
    ("there was a hair in my food", "hair_or_plastic"),
    ("لقيت شعرة في الأكل", "hair_or_plastic"),
    ("found plastic in the rice", "hair_or_plastic"),
    ("the chicken was raw inside", "undercooked_chicken"),
    ("الدجاج نيء", "undercooked_chicken"),
    ("الدجاج مو مستوي", "undercooked_chicken"),
    ("the meal arrived warm", "warm_on_arrival"),
    ("وصلني الأكل حامي", "warm_on_arrival"),
]

SAFETY_TRAPS = [
    "My monthly package expired, how do I renew?",  # package = meal plan
    "I want to renew my monthly package",
    "اشتراكي منتهي",
    "الباقة منتهية ابي اجدد",
    "The plastic container was broken and the sauce leaked",
    "شعرت بالملل من نفس الأكل",  # "I felt", not شعرة (hair)
    "الدجاج ني",  # a bare ني
    "عطني دجاج زيادة",
    "Ill send the meal photo later",
    "I'll eat the meal later",
    "I’ll send the food tomorrow",
    "ابي برنامج يخفف دهون البطن",  # belly-fat diet question
    "عندي كرش وابي اخسر البطن، كم سعر الوجبات؟",
    "There is a bug in the app when I choose meals",
    "the app has a bug",
    "Please deliver to Hamad hospital reception",
    "what was your reaction",
    "rash driver almost hit me",
    "I'm allergic to nuts, please remove them",
    "I am sick of the same meals",
    "انا مريض سكر هل الوجبات مناسبة",
    "do you have a plan for hair loss",
    "I paid by wire transfer for my package",
    "عندي حصى في الكلى",
    "a glass of water please",
    "the meal came with hot sauce",
    "The food was great, thank you",
]


class TestSafety(unittest.TestCase):
    def test_positives(self):
        for s, rule in SAFETY_POSITIVES:
            with self.subTest(s=s):
                self.assertIn(rule, [h["rule"] for h in safety.match(s)])

    def test_traps_do_not_match(self):
        for s in SAFETY_TRAPS:
            with self.subTest(s=s):
                self.assertEqual(safety.match(s), [])

    def test_conditions(self):
        self.assertEqual(safety.match("my cat has a rash"), [])  # reaction needs allergy context
        self.assertEqual(safety.match("I work at the clinic"), [])  # hospital needs an illness term
        self.assertEqual(safety.match("I am sick"), [])  # sickness needs a food word
        self.assertEqual(safety.match("I have a stomach bug, pause my meals")[0]["rule"], "illness")  # not a pest

    def test_one_hit_per_rule_s1_first(self):
        hits = safety.match("Vomiting and diarrhoea after the meal, there was hair and a cockroach. Vomit again.")
        rules = [h["rule"] for h in hits]
        self.assertEqual(rules, ["illness", "pest", "hair_or_plastic"])
        self.assertEqual([h["severity"] for h in hits], ["S1", "S1", "S2"])
        self.assertTrue(all(isinstance(h["term"], str) and h["term"] for h in hits))

    def test_arabic_terms_are_written_normalised(self):
        forbidden = re.compile("[ةىأإآٱ\u0640\u064B-\u065F\u0670]")
        for _severity, rule, *patterns in safety.RULES:
            for p in patterns:
                if p is not None:
                    self.assertIsNone(forbidden.search(p.pattern), rule)


class TestStats(unittest.TestCase):
    def test_week_start(self):
        sunday = date(2026, 11, 1)
        for d in (date(2026, 11, 6), datetime(2026, 11, 7, 23, 0), "2026-11-04", sunday):
            self.assertEqual(stats.week_start(d), sunday)

    def test_seasons(self):
        self.assertEqual(stats.season_of(date(2026, 2, 15)), "Ramadan")  # the week reaches 18 Feb
        self.assertEqual(stats.season_of("2026-05-24"), "Eid al-Adha")
        self.assertEqual(stats.season_of(date(2026, 7, 5)), "Summer midday-work ban")
        self.assertEqual(stats.season_of(date(2026, 12, 13)), "National Day")
        self.assertIsNone(stats.season_of(date(2026, 4, 12)))
        self.assertIsNone(stats.season_of(date(2026, 9, 20)))

    def test_known_p_values_and_no_overflow(self):
        for x_cur, x_base, want in ((5, 3, 0.027), (8, 9, 0.040), (6, 6, 0.054)):
            self.assertAlmostEqual(stats.rate_test(x_cur, 1, x_base, 3)["up"], want, delta=0.001)
        big = stats.rate_test(1250, 1, 3750, 3)  # n = 5,000
        self.assertTrue(0.4 < big["up"] < 0.6)
        self.assertIsNone(stats.rate_test(0, 1, 0, 3))
        self.assertIsNone(stats.rate_test(3, 0, 2, 3))

    def test_poisson_upper(self):
        self.assertEqual(stats.poisson_upper(0, 2), 1.0)
        self.assertAlmostEqual(stats.poisson_upper(1, 2), 0.8646647, places=6)
        self.assertAlmostEqual(stats.poisson_upper(5, 1), 0.0036598, places=6)
        self.assertEqual(stats.poisson_upper(3, 0), 0.0)
        self.assertTrue(0 < stats.poisson_upper(1000, 900) < 0.01)

    def test_collapse_cases_fixed_window(self):
        t0 = datetime(2026, 4, 5, 9, 0)

        def row(day, customer="k1", code="DLV_LATE", severity="S3"):
            return {"customer": customer, "code": code, "at": t0 + timedelta(days=day), "contact": f"c{day}{code}", "severity": severity}

        cases = stats.collapse_cases([row(9), row(0), row(5, severity="S1")])
        self.assertEqual([c["contacts"] for c in cases], [["c0DLV_LATE", "c5DLV_LATE"], ["c9DLV_LATE"]])
        self.assertEqual([c["severity"] for c in cases], ["S1", "S3"])
        self.assertEqual(cases[0]["start"], t0)
        self.assertEqual(len(stats.collapse_cases([row(0), row(7)])), 2)  # day 7 is past the window
        self.assertEqual(len(stats.collapse_cases([row(0, customer=None), row(1, customer=None)])), 2)
        self.assertEqual(len(stats.collapse_cases([row(0), row(1, code="PKG_LEAK")])), 2)
        starts = [c["start"] for c in stats.collapse_cases([row(3, customer="k2"), row(1), row(2, customer=None)])]
        self.assertEqual(starts, sorted(starts))

    def test_pick_baseline_skips_excluded_weeks(self):
        weeks = [date(2026, 1, 4) + timedelta(weeks=i) for i in range(30)]
        current = weeks[26]
        base = stats.pick_baseline(weeks, current, excluded={weeks[25], weeks[20]})
        self.assertEqual(len(base), 12)
        self.assertEqual(base[-1], weeks[24])
        self.assertNotIn(weeks[20], base)
        self.assertTrue(all(w < current for w in base))
        self.assertIsNone(stats.pick_baseline(weeks, current, excluded=set(weeks[:25])))  # 1 clean week
        self.assertEqual(stats.pick_baseline(weeks, weeks[8], set()), weeks[0:8])  # fewer than 12 available

    def test_chip(self):
        self.assertEqual(stats.chip(9, 1000, 2, 1000)["label"], "Watch ▲")
        self.assertEqual(stats.chip(9, 1000, 2, 1000)["text"], "2 → 9")
        self.assertEqual(stats.chip(20, 1000, 5, 1000), {"label": "Unusual ▲", "p": stats.chip(20, 1000, 5, 1000)["p"], "text": "+300%"})
        self.assertEqual(stats.chip(5, 1000, 20, 1000)["label"], "Unusual ▼")
        self.assertEqual(stats.chip(5, 1000, 20, 1000)["text"], "-75%")
        self.assertEqual(stats.chip(2, 1000, 9, 1000)["label"], "Watch ▼")
        self.assertEqual(stats.chip(10, 1000, 10, 1000)["label"], "Usual")
        self.assertEqual(stats.chip(10, 2000, 10, 1000)["text"], "-50%")  # % of the rate, not the count
        self.assertEqual(stats.chip(3, None, 5, 1000), {"label": None, "p": None, "text": "5 → 3"})
        self.assertEqual(stats.chip(7, 0, 9, 1000)["label"], None)
        self.assertEqual(stats.chip(0, 1000, 0, 1000)["label"], "Usual")
        self.assertLess(stats.chip(20, 1000, 5, 1000)["p"], 0.01)

    def test_verdict(self):
        self.assertEqual(stats.verdict(30, 12, 2, 4)["verdict"], "Lower than before")
        self.assertEqual(stats.verdict(3, 12, 8, 4)["verdict"], "Higher than before")
        result = stats.verdict(6, 12, 2, 4)
        self.assertEqual(result["verdict"], "Inconclusive")
        self.assertEqual(result["p"], min(result["up"], result["down"]))
        self.assertEqual(stats.verdict(2, 12, 2, 4)["verdict"], "Not enough data")  # under 5 cases
        self.assertEqual(stats.verdict(30, 12, 2, 4, low_data_in_after=True)["verdict"], "Not enough data")
        self.assertEqual(stats.verdict(30, 0, 2, 4), {"verdict": "Not enough data", "p": None, "up": None, "down": None})

    def test_kappa(self):
        pairs = [("y", "y")] * 20 + [("y", "n")] * 5 + [("n", "y")] * 10 + [("n", "n")] * 15
        self.assertAlmostEqual(stats.kappa(pairs), 0.4)
        self.assertEqual(stats.kappa([("a", "a"), ("b", "b")]), 1.0)
        self.assertIsNone(stats.kappa([("a", "a")] * 3))  # one label only: undefined
        self.assertIsNone(stats.kappa([]))


START = date(2026, 1, 4)


def _series(cases, customers=None, **overrides):
    """A weekly series; by default every case comes from a different customer."""
    n = len(cases)
    weeks = [START + timedelta(weeks=i) for i in range(n)]
    first = next((weeks[i] for i, x in enumerate(cases) if x), None)
    series = {
        "weeks": weeks,
        "cases": cases,
        "customers_by_week": customers or [{f"k{i}-{j}" for j in range(x)} for i, x in enumerate(cases)],
        "exposure": [1000.0] * n,
        "covered": [True] * n,
        "flagged": [False] * n,
        "has_safety": False,
        "first_case": first,
        "history_start": START - timedelta(weeks=52),
        "public": False,
    }
    series.update(overrides)
    return series


class TestBadges(unittest.TestCase):
    def test_surge_and_chronic(self):
        self.assertEqual(stats.badges(_series([1] * 12 + [4] * 4)), ["SURGE", "CHRONIC"])

    def test_watch(self):
        cases = [1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0] + [3, 2, 0, 0]  # 3 -> 5, up = 0.027
        self.assertEqual(stats.badges(_series(cases)), ["WATCH"])

    def test_one_customer_is_never_a_surge_or_chronic(self):
        cases = [1] * 12 + [4] * 4
        customers = [{f"k{i}"} for i in range(12)] + [{"same"}] * 4
        self.assertEqual(stats.badges(_series(cases, customers)), [])

    def test_no_exposure_means_no_rate_badges(self):
        self.assertEqual(stats.badges(_series([1] * 12 + [4] * 4, exposure=None)), ["CHRONIC"])
        self.assertEqual(stats.badges(_series([3] * 12 + [0] * 4, exposure=None)), [])

    def test_improving(self):
        self.assertEqual(stats.badges(_series([3] * 12 + [0] * 4)), ["IMPROVING"])

    def test_improving_needs_a_covered_current_window(self):
        covered = [True] * 12 + [True, True, False, False]  # a feed that died is not an improvement
        self.assertEqual(stats.badges(_series([3] * 12 + [0] * 4, covered=covered)), [])

    def test_baseline_skips_flagged_and_uncovered_weeks(self):
        flagged = [True] * 6 + [False] * 10
        busy = [9] * 6 + [1] * 6 + [4] * 4  # the flagged weeks are busy; the 6 clean ones are quiet
        self.assertEqual(stats.badges(_series(busy, flagged=flagged)), ["SURGE", "CHRONIC"])
        covered = [False] * 7 + [True] * 9  # 5 clean baseline weeks: no test
        self.assertEqual(stats.badges(_series([1] * 12 + [4] * 4, covered=covered)), ["CHRONIC"])

    def test_chronic(self):
        self.assertIn("CHRONIC", stats.badges(_series([0] * 12 + [1, 1, 0, 1], exposure=None)))
        self.assertNotIn("CHRONIC", stats.badges(_series([0] * 12 + [1, 0, 0, 1], exposure=None)))
        same = [set()] * 12 + [{"k"}, {"k"}, set(), {"k"}]
        self.assertNotIn("CHRONIC", stats.badges(_series([0] * 12 + [1, 1, 0, 1], same, exposure=None)))

    def test_new_and_its_burn_in(self):
        cases = [0] * 14 + [1, 1]
        self.assertEqual(stats.badges(_series(cases, exposure=None)), ["NEW"])
        recent_start = _series(cases, exposure=None, history_start=START + timedelta(weeks=10))
        self.assertEqual(stats.badges(recent_start), [])  # first case within 8 weeks of history
        one_customer = [set()] * 14 + [{"k"}, {"k"}]
        self.assertEqual(stats.badges(_series(cases, one_customer, exposure=None)), [])
        older = _series(cases, exposure=None, first_case=START)  # an earlier case exists
        self.assertEqual(stats.badges(older), [])

    def test_resurfaced_needs_earlier_history_and_covered_quiet_weeks(self):
        cases = [0, 0, 2, 0, 0, 0, 0, 0] + [0] * 8 + [1, 1, 0, 0]  # weeks -12..-5 are quiet
        self.assertEqual(stats.badges(_series(cases, exposure=None)), ["RESURFACED"])
        fresh = [0] * 16 + [1, 1, 0, 0]
        self.assertEqual(stats.badges(_series(fresh, exposure=None, first_case=START)), [])
        gaps = [True] * 8 + [False] * 3 + [True] * 5 + [True] * 4  # only 5 of the 8 quiet weeks covered
        self.assertEqual(stats.badges(_series(cases, exposure=None, covered=gaps)), [])
        short = _series([0] * 8 + [1, 1, 0, 0], exposure=None, cases_before_minus12=1, first_case=START)
        self.assertEqual(stats.badges(short), ["RESURFACED"])

    def test_order_and_flags(self):
        series = _series([1] * 12 + [4] * 4, has_safety=True, public=True)
        self.assertEqual(stats.badges(series), ["SAFETY", "SURGE", "CHRONIC", "PUBLIC"])
        alias = _series([1] * 12 + [4] * 4)
        alias["customers"] = alias.pop("customers_by_week")
        self.assertEqual(stats.badges(alias), ["SURGE", "CHRONIC"])
