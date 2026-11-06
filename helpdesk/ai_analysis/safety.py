"""Food-safety keyword rules, English and Gulf Arabic, run over text.normalize() output.

Pure (no frappe import). Hits feed only the safety box's "Needs review" list and the rule-precision
table; they never add to counts. Arabic terms are written in normalised form (ة→ه, ى→ي, أ/إ/آ→ا,
no diacritics), and test_pure checks that.
"""

import re

from helpdesk.ai_analysis.text import normalize

_PREFIX = "(?:و|ف|ب|ل|ال|بال|وال|فال|لل)?"  # Arabic proclitics: and, so, with, for, the ...


def _en(*terms):
    return r"\b(?:" + "|".join(terms) + r")\b"


def _ar(*terms):
    return r"(?<!\w)" + _PREFIX + "(?:" + "|".join(terms) + r")(?!\w)"


def _rx(*parts):
    return re.compile("|".join(parts))


ILLNESS = _rx(
    _en(
        r"poison\w*", r"vomit\w*", r"threw up", r"throw\w* up", r"diarrh\w*", r"stomach ?aches?",
        r"stomach (?:pain|cramps?|upset|bug)", r"upset stomach", r"tummy (?:ache|pain)",
    ),
    # بطن alone is diet talk ("belly fat"); only pain/cramp phrases count
    _ar(
        r"تسمم\w*", r"مسموم\w*", r"استفراغ", r"استفرغ\w*", r"ترجيع", r"اسهال", r"مغص\w*",
        r"(?:وجع|اوجاع|الم|الام) (?:في )?(?:ال)?بطن\w*", r"بطن\w* (?:ي|ت)?(?:وجع|عور)\w*",
        r"(?:ي|ت)?(?:وجع|عور)\w* (?:ال)?بطن\w*",
    ),
)
# "ill" only after a verb: "Ill send the meal" and "I'll" (normalised to "i ll") never match
SICK = _rx(
    _en(
        r"(?:got|get|gets|getting|feel|feels|feeling|felt|fell|falling|am|m|im|is|are|was|were|be|been"
        r"|being|become|became|becoming) ill",
        r"unwell", r"sick(?! of)", r"sickness", r"pain", r"pains", r"painful", r"nause\w*", r"not feeling well",
    ),
    _ar(
        r"مريض\w*(?! (?:ب)?(?:ال)?(?:سكر\w*|ضغط))",  # not "diabetic": a diet question
        r"مرضت", r"مرضنا", r"تعبت", r"تعبنا", r"تعبان\w*", r"تعب", r"غثيان", r"وجع", r"اوجاع", r"الم",
    ),
)
FOOD = _rx(
    _en(r"eat", r"eats", r"eating", r"ate", r"eaten", r"food\w*", r"meals?", r"lunch", r"dinner", r"breakfast", r"dish\w*"),
    _ar(r"اكل\w*", r"وجب\w*", r"طعام", r"غداء", r"عشاء", r"عشا", r"فطور"),
)
ALLERGY = _rx(_en(r"allerg\w*", r"anaphyla\w*"), _ar(r"حساسي\w*", r"تحسس\w*"))
REACTION = _rx(
    _en(r"reaction\w*", r"rash\w*", r"hives", r"swell\w*", r"swollen", r"anaphyla\w*", r"itch\w*", r"epi ?pens?"),
    _ar(r"تحسس\w*", r"طفح", r"حكه", r"تورم\w*", r"انتفاخ", r"انتفخ\w*"),
)
HARD = _rx(
    _en(r"glass(?! of)", r"metal", r"wires?", r"stones?", r"pebbles?", r"blades?", r"screws?", r"sharp objects?"),
    _ar(r"زجاج", r"قزاز", r"حديد", r"حديده", r"حصي", r"حصاه", r"حجر", r"سلك", r"شفره", r"مسمار"),
)
PACKAGING = (
    _en(
        r"containers?", r"box\w*", r"bags?", r"jars?", r"bottles?", r"lids?", r"covers?", r"cups?", r"spoons?",
        r"forks?", r"knife", r"knives", r"cutlery", r"trays?", r"plates?", r"bowls?", r"straws?", r"packag\w*",
        r"wrap\w*",
    ),
    _ar(
        r"علب\w*", r"عبو\w*", r"كيس", r"اكياس", r"صحن", r"صحون", r"غطا\w*", r"ملعق\w*", r"ملاعق", r"كاس\w*",
        r"كوب\w*", r"تغليف", r"قنين\w*",
    ),
)
# glass container, wire transfer, kidney stones, iron in the diet
HARD_VETO = _rx(
    *PACKAGING,
    _en(r"transfer\w*", r"kidney\w*", r"gall\w*", r"iron", r"vitamin\w*"),
    _ar(r"كلي", r"كلاوي", r"مراره", r"نقص", r"نسبه", r"غني", r"فيتامين\w*"),
)
PEST = _rx(
    _en(
        r"cockroach\w*", r"roach\w*", r"insects?", r"worms?", r"maggots?", r"larva\w*", r"weevils?", r"ants?",
        r"(?:fly|flies) in", r"mouse", r"mice", r"rats?", r"rodents?", r"lizards?",
    ),
    _ar(r"صرصور\w*", r"صراصير", r"حشره", r"حشرات", r"دود\w*", r"نمل\w*", r"ذباب\w*", r"ذبان\w*", r"يرقه"),
)
BUG = _rx(_en(r"bugs?"))
# a software bug or a stomach bug is not a pest
BUG_VETO = _rx(
    _en(
        r"apps?", r"application", r"website", r"site", r"system", r"login", r"log in", r"payments?", r"pay",
        r"checkout", r"page", r"screen", r"software", r"updates?", r"version", r"glitch\w*", r"errors?",
        r"crash\w*", r"tech\w*", r"button", r"ios", r"android", r"iphone", r"browser", r"links?", r"code",
        r"stomach", r"tummy", r"flu", r"virus",
    ),
    _ar(r"تطبيق\w*", r"موقع", r"برنامج", r"خلل", r"تحديث"),
)
MEDICAL = _rx(
    _en(r"hospital\w*", r"clinic\w*", r"emergency", r"urgent care"),
    _ar(r"مستشفي\w*", r"مستوصف\w*", r"عياده", r"عيادات", r"طوارئ", r"طواري"),
)
ILLNESS_OR_SICK = re.compile(ILLNESS.pattern + "|" + SICK.pattern)
AUTHORITY = _rx(
    _en(r"moph", r"ministry of (?:public )?health", r"municipality", r"baladiya\w*"),
    _ar(r"وزاره (?:ال)?صحه", r"بلديه"),
)
SPOILED = _rx(
    _en(
        r"spoil\w*", r"rotten", r"rotting", r"mou?ldy?", r"mou?lds", r"stink\w*", r"smelly",
        r"(?:gone|went) (?:off|bad)",
        r"smel\w* (?:\w+ )?(?:bad|off|weird|strange|funny|awful|terrible|horrible|disgusting|sour|rotten)",
        r"(?:bad|weird|strange|funny|awful|terrible|horrible|disgusting|foul|sour|off) (?:smell\w*|odou?r\w*)",
    ),
    _ar(
        r"فاسد\w*", r"خايس\w*", r"معفن\w*", r"متعفن\w*", r"عفن\w*",
        r"(?:ريح|رائح)\w* (?:\w+ )?(?:خايس|كريه|معفن|عفن|غريب|فاسد|خربان|مو حلو|مو زين|مب زين|مو طيب)\w*",
    ),
)
BROKEN = _rx(_ar(r"خربان\w*"))  # Gulf "spoiled", but also "broken" (the app, the fridge)
BROKEN_VETO = _rx(_en(r"apps?", r"application", r"website", r"site"), _ar(r"تطبيق\w*", r"موقع", r"برنامج", r"ثلاج\w*", r"جهاز"))
EXPIRED = _rx(_en(r"expired"), _ar(r"منتهي\w*", r"انتهت صلاحي\w*"))
# "my monthly package expired", "اشتراكي منتهي": the meal plan, not the food
PLAN_VETO = _rx(
    _en(
        r"packages?", r"plans?", r"subscri\w*", r"membership", r"renew\w*", r"account", r"cards?", r"coupons?",
        r"codes?", r"promo\w*", r"offers?", r"vouchers?", r"links?", r"otp", r"trial", r"session", r"visa",
    ),
    _ar(
        r"باقه", r"باقت\w*", r"باقات", r"اشتراك\w*", r"مشترك\w*", r"عرض", r"كود", r"كوبون", r"بطاق\w*", r"رابط",
        r"تجربه", r"خطه", r"برنامج",
    ),
)
HAIR = _rx(_en(r"hairs?"), _ar(r"شعر", r"شعره", r"شعرات"))  # never شعرت ("I felt")
HAIR_VETO = _rx(_en(r"loss", r"fall\w*", r"growth"), _ar(r"تساقط\w*", r"يتساقط", r"تقصف", r"نمو"))  # diet talk
PLASTIC = _rx(_en(r"plastic\w*"), _ar(r"بلاستيك\w*"))
PLASTIC_VETO = _rx(*PACKAGING)  # "plastic container" is packaging
RAW = _rx(
    _en(
        r"raw", r"undercooked", r"under cooked", r"uncooked", r"not cooked", r"half cooked", r"not fully cooked",
        r"pink inside", r"pink in the middle", r"bloody",
    ),
    # a bare ني is a suffix ("عطني"), so raw needs نيء or "not cooked"
    _ar(r"نيء", r"نيئ\w*", r"(?:مو|مب|مش|غير|ما) (?:مستوي|مطبوخ|ناضج)\w*"),
)
CHICKEN = _rx(_en(r"chicken\w*", r"poultry"), _ar(r"دجاج\w*", r"دياي", r"فراخ"))
WARM = _rx(
    _en(
        r"(?:arrived|arrive|arrives|came|come|comes|delivered|received|reached) (?:\w+ ){0,2}"
        r"(?:warm|hot(?! sauce| chil\w*| pepper\w*))",
        r"(?:was|were) (?:\w+ ){0,2}warm", r"room temperature", r"not (?:cold|chilled|refrigerated)",
    ),
    _ar(
        r"(?:وصل\w*|جا|جات|جاني|جاتني|استلمت\w*) (?:\w+ ){0,2}(?:دافي|دافئ|حامي|حار|سخن|مو بارد|مب بارد|مش بارد)\w*",
    ),
)

# (severity, rule, terms, needs, veto): a hit is a `terms` match with no `veto` match among the 3
# words either side, in a text where `needs` (when given) also matches somewhere. A rule may be
# listed more than once with different vetoes; results keep the first hit per rule.
RULES = [
    ("S1", "illness", ILLNESS, None, None),
    ("S1", "illness_after_eating", SICK, FOOD, None),
    ("S1", "allergic_reaction", REACTION, ALLERGY, None),
    ("S1", "hard_object", HARD, None, HARD_VETO),
    ("S1", "pest", PEST, None, None),
    ("S1", "pest", BUG, None, BUG_VETO),
    ("S1", "hospital_or_clinic", MEDICAL, ILLNESS_OR_SICK, None),
    ("S1", "authority", AUTHORITY, None, None),
    ("S2", "spoiled", SPOILED, None, None),
    ("S2", "spoiled", BROKEN, None, BROKEN_VETO),
    ("S2", "spoiled", EXPIRED, None, PLAN_VETO),
    ("S2", "hair_or_plastic", HAIR, None, HAIR_VETO),
    ("S2", "hair_or_plastic", PLASTIC, None, PLASTIC_VETO),
    ("S2", "undercooked_chicken", RAW, CHICKEN, None),
    ("S2", "warm_on_arrival", WARM, None, None),
]


def _near(norm: str, start: int, end: int, n: int = 3) -> str:
    return " ".join(norm[:start].split()[-n:] + norm[end:].split()[:n])


def match(text) -> list[dict]:
    """[{"severity": "S1"|"S2", "rule", "term"}], one per rule, S1 rules first."""
    norm = normalize(text)
    hits, seen = [], set()
    for severity, rule, terms, needs, veto in RULES:
        if rule in seen:
            continue
        need = needs.search(norm) if needs else None
        if needs and not need:
            continue
        for m in terms.finditer(norm):
            if veto and veto.search(_near(norm, m.start(), m.end())):
                continue
            term = m.group() + (f" + {need.group()}" if need and need.group() != m.group() else "")
            hits.append({"severity": severity, "rule": rule, "term": term})
            seen.add(rule)
            break
    return hits
