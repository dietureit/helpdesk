"""Pure statistics for AI Analysis: Qatar weeks, seasons, exact tests, cases, baselines, badges,
change chips, verdicts and kappa. Stdlib only, no frappe import. Run this file for the self-check."""

from collections import Counter
from datetime import date, datetime, timedelta
from math import exp, lgamma, log, log1p


def _pmf(k, n, p):  # log space: comb(n,k)*p**k overflows above n≈1,050
    if p <= 0: return 1.0 if k == 0 else 0.0
    if p >= 1: return 1.0 if k == n else 0.0
    return exp(lgamma(n + 1) - lgamma(k + 1) - lgamma(n - k + 1) + k * log(p) + (n - k) * log1p(-p))


def tail(x, n, p, upper=True):
    ks = range(x, n + 1) if upper else range(0, x + 1)
    return min(1.0, sum(_pmf(k, n, p) for k in ks))


def rate_test(x_cur, e_cur, x_base, e_base):  # exact conditional test, two Poisson counts with exposures
    n = x_cur + x_base
    if n == 0 or e_cur <= 0 or e_base <= 0:
        return None
    p0 = e_cur / (e_cur + e_base)
    return {"up": tail(x_cur, n, p0), "down": tail(x_cur, n, p0, upper=False)}


def _day(d):
    """A date from a date, a datetime or a 'YYYY-MM-DD...' string; None stays None."""
    if d is None or type(d) is date:
        return d
    if isinstance(d, datetime):
        return d.date()
    return date.fromisoformat(str(d)[:10])


def week_start(d) -> date:
    """The Sunday on or before d (Qatar weeks run Sunday to Saturday)."""
    d = _day(d)
    return d - timedelta(days=(d.weekday() + 1) % 7)


# ponytail: edit yearly. A hand-kept calendar; upgrade to a doctype if non-developers must edit it.
SEASONS = [
    (date(2026, 2, 18), date(2026, 3, 19), "Ramadan"),
    (date(2026, 3, 20), date(2026, 3, 22), "Eid al-Fitr"),
    (date(2026, 5, 26), date(2026, 5, 29), "Eid al-Adha"),  # to confirm
    (date(2026, 6, 1), date(2026, 9, 15), "Summer midday-work ban"),
    (date(2026, 12, 18), date(2026, 12, 18), "National Day"),
    (date(2027, 2, 8), date(2027, 3, 8), "Ramadan"),  # approximate, to confirm
]


def season_of(week) -> str | None:
    """The season label when any day of that Sunday-Saturday week falls in a season."""
    first = week_start(week)
    last = first + timedelta(days=6)
    return next((label for start, end, label in SEASONS if start <= last and end >= first), None)


def poisson_upper(x, mu) -> float:
    """P(X >= x) for X ~ Poisson(mu), terms in log space."""
    if x <= 0:
        return 1.0
    if mu <= 0:
        return 0.0
    # 1 - lower tail: tails below ~1e-16 read as 0, which is fine for p < 0.01 flags
    return max(0.0, 1.0 - sum(exp(k * log(mu) - mu - lgamma(k + 1)) for k in range(x)))


def collapse_cases(rows, window_days=7) -> list[dict]:
    """One case per customer and code per fixed window opened by its first contact.

    The first contact on or after start + window_days opens a new case (no chaining). A row
    without a customer is its own case. Severity is the worst seen (S1 is worst).
    """
    window = timedelta(days=window_days)
    cases, open_cases = [], {}
    for r in sorted(rows, key=lambda r: r["at"]):
        key = (r.get("customer"), r["code"])
        case = open_cases.get(key) if r.get("customer") else None
        if case is None or r["at"] >= case["start"] + window:
            case = {"customer": r.get("customer"), "code": r["code"], "start": r["at"], "contacts": [], "severity": None}
            cases.append(case)
            if r.get("customer"):
                open_cases[key] = case
        if r.get("contact") not in case["contacts"]:
            case["contacts"].append(r.get("contact"))
        if r.get("severity") and (case["severity"] is None or r["severity"] < case["severity"]):
            case["severity"] = r["severity"]
    return cases


def pick_baseline(weeks, current_first, excluded, max_weeks=12, lookback=26, min_weeks=6) -> list[date] | None:
    """The latest max_weeks weeks before current_first, within lookback weeks, skipping excluded
    (season-flagged or low-data) weeks; None when fewer than min_weeks remain (no test)."""
    earliest = current_first - timedelta(weeks=lookback)
    clean = sorted(w for w in set(weeks) if earliest <= w < current_first and w not in excluded)[-max_weeks:]
    return clean if len(clean) >= min_weeks else None


def _num(v) -> str:
    return str(int(v)) if float(v).is_integer() else f"{v:.2f}"


def chip(x_cur, e_cur, x_prev, e_prev) -> dict:
    """Change chip for a count tile: exact-test label, plus "prev → cur" for small counts (or with no
    exposure) and otherwise the signed % change of the rate."""
    exposed = e_cur is not None and e_prev is not None and e_cur > 0 and e_prev > 0
    if min(x_cur, x_prev) < 5 or not exposed:
        text = f"{_num(x_prev)} → {_num(x_cur)}"
    else:
        text = f"{round((x_cur / e_cur) / (x_prev / e_prev) * 100 - 100):+d}%"
    if not exposed:
        return {"label": None, "p": None, "text": text}
    test = rate_test(x_cur, e_cur, x_prev, e_prev) or {"up": 1.0, "down": 1.0}  # 0 vs 0
    up, down = test["up"], test["down"]
    if up < 0.01:
        label, p = "Unusual ▲", up
    elif up < 0.05:
        label, p = "Watch ▲", up
    elif down < 0.01:
        label, p = "Unusual ▼", down
    elif down < 0.05:
        label, p = "Watch ▼", down
    else:
        label, p = "Usual", min(up, down)
    return {"label": label, "p": p, "text": text}


def badges(series: dict) -> list[str]:
    """The plan's badge table for one code. series: "weeks" (consecutive Sundays, oldest first, the last
    is the current week), per-week lists "cases" (case starts), "customers_by_week" (sets), "exposure"
    (None = no rate test), "covered" and "flagged" (season), plus "has_safety", "first_case",
    "history_start", "public" and optionally "cases_before_minus12". Current window = last 4 weeks."""
    weeks, cases = list(series["weeks"]), list(series["cases"])
    n = len(weeks)
    customers = series.get("customers_by_week", series.get("customers")) or [set()] * n
    covered = series.get("covered") or [True] * n
    flagged = series.get("flagged") or [False] * n
    exposure = series.get("exposure")
    cur_x = sum(cases[-4:])
    cur_customers = len(set().union(*customers[-4:]))
    out = ["SAFETY"] if series.get("has_safety") else []

    # Rate test: needs exposure and a fully covered current window (a dead feed must not read as
    # IMPROVING), against up to 12 clean baseline weeks from the last 26 (none with fewer than 6).
    test = None
    if exposure is not None and n >= 4 and all(covered[-4:]) and all(exposure[-4:]):
        excluded = {w for i, w in enumerate(weeks) if flagged[i] or not covered[i] or not exposure[i]}
        base = pick_baseline(weeks, weeks[-4], excluded)
        if base:
            index = {w: i for i, w in enumerate(weeks)}
            base_x = sum(cases[index[w]] for w in base)
            base_e = sum(exposure[index[w]] for w in base)
            cur_e = sum(exposure[-4:])
            test = rate_test(cur_x, cur_e, base_x, base_e)
    if test and test["up"] < 0.05 and cur_x >= 3 and cur_customers >= 2:
        ratio = (cur_x / cur_e) / (base_x / base_e) if base_x else float("inf")
        if ratio >= 2:
            out.append("SURGE" if test["up"] < 0.01 else "WATCH")

    first, start = _day(series.get("first_case")), _day(series.get("history_start"))
    if (
        first
        and start
        and first >= weeks[-1] - timedelta(days=7)  # the last 14 days
        and first >= start + timedelta(weeks=8)  # burn-in: early history makes every code look new
        and sum(cases[-2:]) >= 2
        and len(set().union(*customers[-2:])) >= 2
    ):
        out.append("NEW")

    if n >= 12:  # weeks -12..-5 are cases[-12:-4]
        before = series.get("cases_before_minus12", sum(cases[:-12]))
        quiet = sum(cases[-12:-4]) == 0 and sum(1 for c in covered[-12:-4] if c) >= 6
        if before >= 1 and quiet and cur_x >= 2 and cur_customers >= 2:
            out.append("RESURFACED")

    if sum(1 for x in cases[-4:] if x) >= 3 and cur_customers >= 2:
        out.append("CHRONIC")
    if test and test["down"] < 0.01 and base_x >= 3:
        out.append("IMPROVING")
    if series.get("public"):
        out.append("PUBLIC")
    return out


def verdict(base_x, base_e, after_x, after_e, low_data_in_after=False) -> dict:
    """Before/after verdict for an adopted action (association, not proof)."""
    test = None
    if not low_data_in_after and base_x + after_x >= 5:
        test = rate_test(after_x, after_e or 0, base_x, base_e or 0)
    if not test:
        return {"verdict": "Not enough data", "p": None, "up": None, "down": None}
    up, down = test["up"], test["down"]
    if down < 0.05:
        result, p = "Lower than before", down
    elif up < 0.05:
        result, p = "Higher than before", up
    else:
        result, p = "Inconclusive", min(up, down)
    return {"verdict": result, "p": p, "up": up, "down": down}


def kappa(pairs) -> float | None:
    """Cohen's kappa for two raters labelling the same items; None when undefined."""
    pairs = list(pairs)
    n = len(pairs)
    if not n:
        return None
    observed = sum(a == b for a, b in pairs) / n
    first, second = Counter(a for a, _ in pairs), Counter(b for _, b in pairs)
    expected = sum(first[k] * second[k] for k in first) / (n * n)
    return None if expected >= 1 else (observed - expected) / (1 - expected)


if __name__ == "__main__":
    # known exact-test values at p0 = 0.25 (current exposure 1, baseline 3)
    for x_cur, x_base, want in ((5, 3, 0.027), (8, 9, 0.040), (6, 6, 0.054)):
        got = rate_test(x_cur, 1, x_base, 3)["up"]
        assert abs(got - want) < 0.001, (x_cur, x_base, got)
    big = rate_test(1250, 1, 3750, 3)  # n = 5,000 must not overflow
    assert 0.4 < big["up"] < 0.6 and 0.4 < big["down"] < 0.6, big
    assert abs(poisson_upper(1, 2) - (1 - exp(-2))) < 1e-12

    # fixed case window: one customer on days 0, 5 and 9 is two cases (day 9 is past day 0 + 7)
    t0 = datetime(2026, 4, 5, 9, 0)
    rows = [{"customer": "k1", "code": "DLV_LATE", "at": t0 + timedelta(days=d), "contact": f"c{d}", "severity": "S3"} for d in (0, 5, 9)]
    assert [c["contacts"] for c in collapse_cases(rows)] == [["c0", "c5"], ["c9"]]

    # badge: 1 case a week for 12 weeks, then 4 a week from different customers -> SURGE and CHRONIC
    weeks = [date(2026, 1, 4) + timedelta(weeks=i) for i in range(16)]
    cases = [1] * 12 + [4] * 4
    series = {
        "weeks": weeks,
        "cases": cases,
        "customers_by_week": [{f"k{i}-{j}" for j in range(x)} for i, x in enumerate(cases)],
        "exposure": [1000.0] * 16,
        "covered": [True] * 16,
        "flagged": [False] * 16,
        "has_safety": False,
        "first_case": weeks[0],
        "history_start": weeks[0],
        "public": False,
    }
    assert badges(series) == ["SURGE", "CHRONIC"], badges(series)
    print("stats self-check ok")
