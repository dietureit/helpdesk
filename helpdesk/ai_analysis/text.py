"""Pure text helpers for AI Analysis (no frappe import): normalisation with an index map back to
the original, de-identification, phone keys, language and quote verification."""

import re
import unicodedata
from functools import lru_cache

from rapidfuzz import fuzz

QUOTABLE = {"customer", "staff", "ticket"}

# Arabic-Indic (U+0660..) and Persian (U+06F0..) digits -> ASCII
_DIGITS = {0x0660 + d: str(d) for d in range(10)} | {0x06F0 + d: str(d) for d in range(10)}
_ARABIC_FOLD = {ord(c): "ا" for c in "أإآٱ"} | {ord("ى"): "ي", ord("ة"): "ه"}
_AR_DROP = {*range(0x064B, 0x0660), 0x0670, 0x0640}  # diacritics, superscript alef, tatweel
# Also dropped: other combining marks and invisible format/control chars (RLM, ZWJ, BOM, emoji
# variation selectors), so they never break a substring match.
_DROP_CATS = {"Mn", "Me", "Cf", "Cc"}


def _str(s) -> str:
    return "" if s is None else str(s)


@lru_cache(maxsize=8192)
def _fold(c: str) -> str:
    """What one source char becomes: "" (dropped), " " (separator) or its folded letters."""
    out = []
    for d in unicodedata.normalize("NFKC", c).casefold():
        cat = unicodedata.category(d)
        if d.isspace() or cat[0] in "PS":
            out.append(" ")
        elif ord(d) not in _AR_DROP and cat not in _DROP_CATS:
            out.append(_DIGITS.get(ord(d)) or _ARABIC_FOLD.get(ord(d)) or d)
    return "".join(out)


def normalize_with_map(s) -> tuple[str, list[int]]:
    """NFKC + casefold + Arabic folding; punctuation and symbols become spaces; spaces collapsed.

    map[i] is the index in s of the char that produced norm[i], so the original span of a
    normalised match norm[i:j] is s[map[i]:map[j - 1] + 1].
    """
    out, src = [], []
    for i, c in enumerate(_str(s)):
        for d in _fold(c):
            if d == " " and (not out or out[-1] == " "):
                continue
            out.append(d)
            src.append(i)
    if out and out[-1] == " ":
        out.pop()
        src.pop()
    return "".join(out), src


def normalize(s) -> str:
    return normalize_with_map(s)[0]


# --- de-identification -------------------------------------------------------------------

_AR_PREFIX = "(?:و|ف|ب|ل|ال|بال|وال|فال|لل)?"
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_URL_END = r"(?=[.,;:!?)\]}،؟]*(?:\s|$))"  # stop before trailing punctuation
_URL = re.compile(
    rf"(?:https?://|www\.)\S+?{_URL_END}|\b[\w-]+(?:\.[\w-]+)*\.(?:com|net|org|qa|io|me|ly)\b(?:/\S*?{_URL_END})?",
    re.I,
)
_HANDLE = re.compile(r"(?<![\w@])@\w(?:[\w.]*\w)?")
# +974/00974 forms, 8-digit numbers and any 7+ digit run with spaces or dashes between groups
_PHONE = re.compile(r"(?:\(?(?:\+|00)\s?974\)?[\s-]*)?\+?\d(?:[\s-]?\d){6,}")
_ADDRESS_UNIT = (
    r"(?:\b(?:zone|street|st|building|bldg|villa|flat|apartment|apt)\b\.?"
    rf"|(?<!\w){_AR_PREFIX}(?:منطق[ةه]|شارع|مبن[ىي]|عمار[ةه]|فيلا|شق[ةه])(?!\w))"
    r"\s*(?:(?:no|number|رقم)\b\.?|#)?\s*[:#]?\s*\d+(?:[a-z]\b)?"
)
_ADDRESS = re.compile(rf"{_ADDRESS_UNIT}(?:[\s,،/-]*{_ADDRESS_UNIT})*", re.I)  # "zone 66 street 900" -> one
_LONG_NUMBER = re.compile(r"\d{6,}")
_WORD = re.compile(r"[\w\u064B-\u065F\u0670]+")  # a word, Arabic diacritics included
_NAME_FOLD = _ARABIC_FOLD | dict.fromkeys(_AR_DROP)  # alef forms, ى/ي, ة/ه, diacritics and tatweel never hide a name
_PLACEHOLDER_WORDS = {"name", "phone", "email", "link", "user", "address", "number"}


def _name_key(word: str) -> str:
    return word.casefold().translate(_NAME_FOLD)


# Generic words that show up in staff/system "full names" ("Support Agent", "Test User") would
# otherwise wipe ordinary words from every line, so they are dropped too.
_NAME_STOP = {
    _name_key(w)
    for w in (
        "bin", "bint", "ibn", "abu", "al", "the", "and", "admin", "administrator", "guest", "user", "team",
        "dieture", "agent", "support", "customer", "service", "manager", "test", "driver", "delivery",
        "kitchen", "staff", "allah",
        "بن", "بنت", "ابن", "ابو", "ال", "آل", "الله",
    )
}


def name_tokens(full_names) -> set[str]:
    """Casefolded name tokens of 3+ letters, minus stopwords (bin, abu, admin, team, الله ...)."""
    if isinstance(full_names, str):
        full_names = [full_names]
    return {
        tok
        for full in full_names or ()
        for tok in _WORD.findall(_str(full).casefold())
        if len(_name_key(tok)) >= 3 and not tok.isdigit() and _name_key(tok) not in _NAME_STOP
    }


@lru_cache(maxsize=256)
def _name_keys(names: frozenset) -> frozenset:
    keys = (_name_key(w) for name in names for w in _WORD.findall(name))
    return frozenset(k for k in keys if len(k) >= 3 and k not in _PLACEHOLDER_WORDS)


def scrub(s, names: set[str] = frozenset()) -> str:
    """Replace, in order: emails, URLs, @handles, phones, addresses, 6+ digit runs, then known names
    (whole words, case-insensitive, Arabic alef/ya/ta-marbuta variants and diacritics ignored)."""
    s = _str(s).translate(_DIGITS)
    s = _EMAIL.sub("[email]", s)
    s = _URL.sub("[link]", s)
    s = _HANDLE.sub("@user", s)
    s = _PHONE.sub("[phone]", s)
    s = _ADDRESS.sub("[address]", s)
    s = _LONG_NUMBER.sub("[number]", s)
    # Token lookup per word, not one big alternation regex: hundreds of staff names stay O(words).
    # Whole tokens only, so "longest first" never matters.
    keys = _name_keys(frozenset(names or ()))
    if keys:
        s = _WORD.sub(lambda m: _scrub_word(m.group(), keys), s)
    return s


_AR_PROCLITICS = "وفبل"  # and / so / with / for, written joined to the next word


def _scrub_word(word: str, keys: frozenset) -> str:
    if _name_key(word) in keys:
        return "[name]"
    # "ومحمد" is "and Mohammed": try once without a one-letter proclitic. Keys are 3+ letters, so the rest is too.
    # ponytail: this over-scrubs rare words such as "فعلي" when a staff member is called علي; privacy wins.
    if word[0] in _AR_PROCLITICS and _name_key(word[1:]) in keys:
        return word[0] + "[name]"
    return word


def last8(phone) -> str | None:
    digits = re.sub(r"[^0-9]", "", _str(phone).translate(_DIGITS))
    return digits[-8:] if len(digits) >= 8 else None


_ARABIC_LETTER = re.compile(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]")


def arabic_share(s) -> float:
    letters = "".join(c for c in _str(s) if c.isalpha())
    return len(_ARABIC_LETTER.findall(letters)) / len(letters) if letters else 0.0


def language(texts: list[str]) -> str:
    if isinstance(texts, str):
        texts = [texts]
    share = arabic_share(" ".join(_str(t) for t in texts or ()))
    return "ar" if share >= 0.6 else "en" if share <= 0.2 else "mixed"


# --- quote verification ------------------------------------------------------------------


def _span(s, m, i, j):
    """Original [a, b) of norm[i:j], widened over trailing marks the normaliser dropped."""
    a, b = m[i], m[j - 1] + 1
    while b < len(s) and not _fold(s[b]):
        b += 1
    return a, b


def _runs(lines):
    """Runs of 2+ consecutive quotable lines with the same role (one sentence split over bubbles)."""
    runs, cur = [], []
    for ln in lines:
        if cur and ln.get("role") == cur[-1].get("role"):
            cur.append(ln)
            continue
        if len(cur) >= 2:
            runs.append(cur)
        cur = [ln] if ln.get("role") in QUOTABLE else []
    if len(cur) >= 2:
        runs.append(cur)
    return runs


def _joined(run):
    """(lines joined with " ", [(offset, line id)]) for a run."""
    text, starts = "", []
    for ln in run:
        text += " " if text else ""
        starts.append((len(text), ln.get("id")))
        text += _str(ln.get("text"))
    return text, starts


def verify_quote(quote, lines, cited_id) -> tuple[str, str | None, str | None]:
    """Find the model's quote in this contact's own quotable lines (customer, staff, ticket).

    Returns (status, exact original span, line id). Checks, in order: 1 the cited line, 2 any other
    quotable line, 3 a run of 2+ consecutive same-role lines joined with " " (Verified); 4 a
    partial_ratio_alignment >= 95 on a line or run (Repaired); else Unverified. The returned text is
    always cut from the source, never the model's words; a run match may cover several lines.
    """
    q = normalize(quote)
    if len(q) < 8 or len(q.split()) < 2:
        return "Unverified", None, None
    lines = list(lines or ())
    quotable = [ln for ln in lines if ln.get("role") in QUOTABLE and _str(ln.get("text")).strip()]
    quotable.sort(key=lambda ln: ln.get("id") != cited_id)  # cited line first, others in order
    candidates = [(_str(ln.get("text")), [(0, ln.get("id"))]) for ln in quotable]
    candidates += [_joined(run) for run in _runs(lines)]
    candidates = [(text, starts, *normalize_with_map(text)) for text, starts in candidates]

    def found(text, starts, m, i, j):
        a, b = _span(text, m, i, j)
        return text[a:b], next(lid for off, lid in reversed(starts) if off <= a)

    for text, starts, norm, m in candidates:
        i = norm.find(q)
        if i >= 0:
            return "Verified", *found(text, starts, m, i, i + len(q))

    best = None
    for text, starts, norm, m in candidates:
        al = fuzz.partial_ratio_alignment(q, norm, score_cutoff=95)
        if not al:
            continue
        i, j = al.dest_start, al.dest_end
        while i < j and norm[i] == " ":
            i += 1
        while j > i and norm[j - 1] == " ":
            j -= 1
        while i > 0 and norm[i - 1] != " ":  # whole words only
            i -= 1
        while j < len(norm) and norm[j] != " ":
            j += 1
        # the span itself must match the whole quote: a short line inside a long quote scores 100 on
        # partial_ratio but fails here
        score = fuzz.ratio(q, norm[i:j]) if j > i else 0
        if score >= 95 and (best is None or score > best[0]):
            best = (score, *found(text, starts, m, i, j))
    if best:
        return "Repaired", best[1], best[2]
    return "Unverified", None, None
