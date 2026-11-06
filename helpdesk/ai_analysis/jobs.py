"""AI Analysis background jobs: the build + tag chain, budget, status, nightly maintenance and run_now.

Web requests and the scheduler only enqueue: queue long, one job id per chunk or step, so a re-enqueue
of a running id (which RQ silently skips) never stalls the chain. Every job body is wrapped in `safe()`,
which never re-raises, so execute_job never logs frame locals holding keys or customer text.

    bench --site erp.localhost execute helpdesk.ai_analysis.jobs.run_now --kwargs "{'kind': 'smoke'}"
"""

import functools
import json
import os
import time
import traceback
from datetime import timedelta

import frappe
from frappe import _
from frappe.utils import add_days, add_months, add_to_date, cint, flt, get_first_day, getdate, now_datetime

from helpdesk.ai_analysis import ai_provider, analysis_enabled, conf

CONTACT = "HD AI Contact"
HEARTBEAT = "hd-ai:tag:heartbeat"  # fresh while a chain works (expires in 300 s)
STOPPED = "hd-ai:tag:stopped"  # why the last chain stopped early, until the next start
GOLD_SCORE = "hd-ai:gold:score"  # written by tagging.score_gold
BATCH = 10  # contacts per claim
CHUNK_SECONDS = 150  # tagging time per chunk: one more call (<= 95 s) still ends inside the 360 s job timeout
STALE_MINUTES = 20  # a Tagging claim older than this was abandoned
MAX_ATTEMPTS = 3
BLOCKING = (401, 403, 429)  # three in a row stop the chain
QATAR = timedelta(hours=3)  # CRM Call Log start_time is UTC (3CX strips the Z)


def safe(kind: str):
    """Job wrapper: catch everything (TicketAIError too), roll back, put the Failed state on the
    `contact`/`insight` kwarg (else stop the chain for build/tag), log type + stage only, commit."""

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except Exception as e:
                failure = e
            # Handled outside the except block: no live exception for log_error's Sentry hook to read locals from.
            try:
                frappe.db.rollback()
                message = _message(failure, kind)
                contact, insight = kwargs.get("contact"), kwargs.get("insight")
                if contact and frappe.db.exists(CONTACT, contact):
                    failed = {"status": "Failed", "error": message, "claim_token": None, "claimed_at": None}
                    frappe.db.set_value(CONTACT, contact, failed, update_modified=False)
                elif insight and frappe.db.exists("HD AI Insight", insight):
                    failed = {"status": "Failed", "error": message}
                    frappe.db.set_value("HD AI Insight", insight, failed, update_modified=False)
                elif kind in ("build", "tag"):
                    _stop(message)
                _log(kind, failure, contact or insight or _job_ref(kwargs))
                frappe.db.commit()
            except Exception as e:
                print(f"AI Analysis {kind}: failure handling failed ({type(e).__name__})")

        return wrapper

    return decorator


def _message(e: Exception, kind: str) -> str:
    """Agent-safe text: TicketAIError messages are fixed strings; anything else is named by type only."""
    from helpdesk.api.ticket_ai import TicketAIError

    if isinstance(e, TicketAIError):
        return str(e)[:200]
    return _("AI Analysis {0} failed ({1}). See the Error Log.").format(kind, type(e).__name__)


def _stage(e: Exception) -> str:
    """file:function:line of the innermost helpdesk frame: code locations, never values."""
    where = "?"
    for frame, lineno in traceback.walk_tb(e.__traceback__):
        code = frame.f_code
        if f"{os.sep}helpdesk{os.sep}" in code.co_filename:
            where = f"{os.path.basename(code.co_filename)}:{code.co_name}:{lineno}"
    return where


def _log(kind: str, e: Exception, record: str):
    status = getattr(e, "http_status", None)
    message = f"{type(e).__name__} at {_stage(e)} ({record}, HTTP {status})"
    frappe.log_error(title=f"AI Analysis {kind} failed", message=message)


def _job_ref(kwargs: dict) -> str:
    return " ".join(f"{k}={kwargs[k]}" for k in ("run", "n", "as_of", "week") if kwargs.get(k) is not None) or "-"


def enqueue(kind: str, job_id: str, **kwargs):
    """One long-queue job. `kind` is a function of this module, or a dotted path under helpdesk.ai_analysis."""
    method = f"helpdesk.ai_analysis.{kind}" if "." in kind else f"{__name__}.{kind}"
    frappe.enqueue(
        method, queue="long", timeout=360, job_id=job_id, deduplicate=True, enqueue_after_commit=True, **kwargs
    )


def _heartbeat():
    frappe.cache.set_value(HEARTBEAT, str(now_datetime()), expires_in_sec=300)


def _stop(message: str):
    frappe.cache.set_value(STOPPED, message)
    frappe.cache.delete_value(HEARTBEAT)


def _running() -> bool:
    if frappe.cache.get_value(HEARTBEAT, expires=True):
        return True
    since = add_to_date(now_datetime(), minutes=-STALE_MINUTES)
    return bool(frappe.db.exists(CONTACT, {"status": "Tagging", "claimed_at": (">=", since)}))


def start_chain(reason: str, user: str | None = None) -> dict:
    """Enqueue the build, which then starts tagging. Refused while a chain runs."""
    if _running():
        return {"started": False, "run": None}
    run = frappe.generate_hash(length=10)
    frappe.cache.delete_value(STOPPED)
    _heartbeat()  # a second click says "already running" even before the worker picks the job up
    enqueue("build", f"hd-ai::build::{run}", run=run, reason=reason, user=user or frappe.session.user)
    return {"started": True, "run": run}


@safe("build")
def build(run: str, reason: str | None = None, user: str | None = None):
    """Job: rebuild contacts (also with AI off, so the counts stay fresh), then chunk 0.
    reason and user only label the job in the RQ job list."""
    from helpdesk.ai_analysis import cases

    _heartbeat()
    cases.build_contacts()
    frappe.db.commit()
    if not analysis_enabled():
        frappe.cache.delete_value(HEARTBEAT)
        return
    enqueue("chunk", f"hd-ai::tag::{run}::0", run=run, n=0)


@safe("tag")
def chunk(run: str, n: int, _only: list[str] | None = None):
    """Job: one link of the chain. Tags for up to CHUNK_SECONDS, then enqueues chunk n+1 while Pending
    contacts remain. `_only` (tests) limits every claim and release to those contact names."""
    _release_stale(_only)
    if n == 0:
        # Failed contacts get one more try per run; attempts are kept, so another failure fails it again.
        cond, values = _scope(_only)
        frappe.db.sql(f"update `tabHD AI Contact` set status = 'Pending' where status = 'Failed'{cond}", values)
    frappe.db.commit()
    token, skip = f"{run}:{n}", f"skip:{run}"
    try:
        stopped = _tag(token, time.monotonic() + CHUNK_SECONDS, skip, _only)["stopped"]
    except Exception:
        frappe.db.rollback()
        _release(token)  # don't leave this chunk's claims looking like a live chain for 20 minutes
        frappe.db.commit()
        raise
    if stopped:
        _stop(stopped)
    elif _pending(skip, _only):
        enqueue("chunk", f"hd-ai::tag::{run}::{n + 1}", run=run, n=n + 1, **({"_only": _only} if _only else {}))
    else:
        frappe.cache.delete_value(HEARTBEAT)  # the chain is done


def _tag(token: str, deadline: float, skip: str, only=None, limit: int | None = None) -> dict:
    """Claim and tag Pending contacts until the deadline (or `limit` contacts), committing per contact.

    Returns {"tagged", "failed", "cost", "stopped"}, where stopped is the agent-safe reason the chain
    must stop: AI switched off, the monthly budget, or three blocking errors in a row.
    """
    from helpdesk.ai_analysis import cases, tagging
    from helpdesk.api.ticket_ai import TicketAIError

    out = {"tagged": 0, "failed": 0, "cost": 0.0, "stopped": None}
    strikes = 0
    while not out["stopped"] and time.monotonic() < deadline:
        size = BATCH if limit is None else min(BATCH, limit - out["tagged"] - out["failed"])
        if size <= 0:
            break
        if not analysis_enabled():
            out["stopped"] = _("AI Analysis is off.")
            break
        claimed = _claim(token, skip, size, only)
        frappe.db.commit()
        if not claimed:
            break
        lines = cases.lines_for(claimed)
        hashes = dict(
            frappe.db.sql("select name, text_hash from `tabHD AI Contact` where name in %(n)s", {"n": tuple(claimed)})
        )
        for name in claimed:
            if time.monotonic() >= deadline:
                break
            if budget_left() <= 0:
                out["stopped"] = _("Monthly AI budget reached")
                break
            if name not in lines or cases.text_hash(lines[name]) != hashes.get(name):
                # The source changed or vanished since the build, which fixes it next run. The skip mark
                # keeps this run from claiming it again, so the chain can't loop on it.
                values = {"status": "Pending", "claim_token": skip, "claimed_at": None}
                frappe.db.set_value(CONTACT, name, values, update_modified=False)
                frappe.db.commit()
                continue
            failure = None
            try:
                out["cost"] += flt((tagging.tag_contact(name, lines[name]) or {}).get("cost"))
            except Exception as e:
                failure = e
            if failure is None:
                out["tagged"] += 1
                strikes = 0
            else:
                frappe.db.rollback()
                _fail(name, failure)
                out["failed"] += 1
                expected = isinstance(failure, TicketAIError)
                if not expected:
                    _log("tag", failure, name)
                # An unexpected exception is a bug that would hit every contact: it strikes too.
                strikes = strikes + 1 if not expected or failure.http_status in BLOCKING else 0
                if strikes >= 3:
                    out["stopped"] = _message(failure, "tag")
            frappe.db.commit()
            _heartbeat()
            if out["stopped"]:
                break
        _release(token)  # whatever this batch did not reach goes back to Pending
        frappe.db.commit()
    return out


def _scope(only) -> tuple[str, dict]:
    return (" and name in %(only)s", {"only": tuple(only)}) if only else ("", {})


def _claim(token: str, skip: str, size: int, only=None) -> list[str]:
    """One UPDATE claims up to `size` Pending contacts, newest first: two chains never share a contact."""
    cond, values = _scope(only)
    values.update(token=token, skip=skip, now=now_datetime())
    frappe.db.sql(
        f"""update `tabHD AI Contact` set status = 'Tagging', claim_token = %(token)s, claimed_at = %(now)s
        where status = 'Pending' and ifnull(claim_token, '') != %(skip)s{cond}
        order by started_on desc limit {cint(size)}""",
        values,
    )
    return frappe.db.sql_list(
        "select name from `tabHD AI Contact` where status = 'Tagging' and claim_token = %s order by started_on desc",
        token,
    )


def _release(token: str):
    frappe.db.sql(
        """update `tabHD AI Contact` set status = 'Pending', claim_token = null, claimed_at = null
        where status = 'Tagging' and claim_token = %s""",
        token,
    )


def _release_stale(only=None) -> int:
    cond, values = _scope(only)
    values["since"] = add_to_date(now_datetime(), minutes=-STALE_MINUTES)
    where = f"status = 'Tagging' and (claimed_at is null or claimed_at < %(since)s){cond}"
    names = frappe.db.sql_list(f"select name from `tabHD AI Contact` where {where}", values)
    if names:
        frappe.db.sql(
            """update `tabHD AI Contact` set status = 'Pending', claim_token = null, claimed_at = null
            where status = 'Tagging' and name in %(names)s""",
            {"names": tuple(names)},
        )
    return len(names)


def _pending(skip: str, only=None) -> bool:
    cond, values = _scope(only)
    values["skip"] = skip
    sql = f"""select 1 from `tabHD AI Contact`
        where status = 'Pending' and ifnull(claim_token, '') != %(skip)s{cond} limit 1"""
    return bool(frappe.db.sql(sql, values))


def _fail(name: str, e: Exception):
    attempts = cint(frappe.db.get_value(CONTACT, name, "attempts")) + 1
    values = {
        "attempts": attempts,
        "status": "Failed" if attempts >= MAX_ATTEMPTS else "Pending",
        "error": _message(e, "tag"),
        "claim_token": None,
        "claimed_at": None,
    }
    frappe.db.set_value(CONTACT, name, values, update_modified=False)


def spend_month() -> float:
    """AI spend in the current Asia/Qatar month: contacts tagged this month plus insights created this month."""
    # ponytail: cost_usd is cumulative per contact, so a contact re-tagged this month brings its earlier
    # months' cost too: the sum over-counts (stops early, never late). Failed calls and the smoke test
    # are not recorded. A per-call spend ledger would be exact.
    window = {"start": get_first_day(now_datetime())}
    window["end"] = add_months(window["start"], 1)
    sql = "select sum(cost_usd) from `tab{0}` where {1} >= %(start)s and {1} < %(end)s"
    total = flt(frappe.db.sql(sql.format(CONTACT, "tagged_on"), window)[0][0])
    if frappe.db.table_exists("HD AI Insight"):
        total += flt(frappe.db.sql(sql.format("HD AI Insight", "creation"), window)[0][0])
    return total


def budget_left() -> float:
    return flt(conf().budget_usd) - spend_month()


def worker_running() -> bool:
    """Same check as dieture's kds_jobs: any registered RQ worker."""
    if frappe.flags.in_test:
        return False
    try:
        from frappe.utils.background_jobs import get_workers

        return bool(get_workers())
    except Exception:
        return False


def _ai_reason(c) -> str | None:
    """Why AI labelling cannot run now, or None when it can."""
    if not c.enabled:
        return _("AI Analysis is off in HD Settings.")
    if not c.legal_approval:
        return _("Record the legal approval reference in HD Settings to switch AI Analysis on.")
    if not analysis_enabled():
        return _("Set the AI base URL and API key in HD Settings, tab AI.")
    if budget_left() <= 0:
        return _("Monthly AI budget reached")
    return None


def _gold_score() -> dict:
    score = frappe.cache.get_value(GOLD_SCORE)
    if score is None and frappe.db.table_exists("HD AI Insight"):  # the cache was cleared: the score is stored too
        evaluation = {"insight_type": "Evaluation", "status": "Done"}
        stored = frappe.db.get_value("HD AI Insight", evaluation, "output_json", order_by="creation desc")
        score = json.loads(stored) if stored else None
    return score or {}


def status() -> dict:
    """The page's status strip (get_status without can_decide): table counts plus the heartbeat."""
    from helpdesk.ai_analysis import metrics, tagging

    c = conf()
    counts = {s: cint(n) for s, n in frappe.db.sql("select status, count(*) from `tabHD AI Contact` group by status")}
    current = tagging.current_version()
    done, left = (
        cint(v)
        for v in frappe.db.sql(
            """select sum(status = 'Tagged' and tagged_version = %(v)s),
                sum(status in ('Pending', 'Tagging') and ifnull(tagged_version, '') not in ('', %(v)s))
            from `tabHD AI Contact`""",
            {"v": current},
        )[0]
    )
    score = _gold_score()
    # ponytail: coverage is recomputed on every poll (~0.5 s at 2.5k contacts, every 3 s while running);
    # cache it for a minute if the page's polling load ever matters
    cov = metrics.coverage()
    reason = _ai_reason(c)
    return {
        "enabled": c.enabled,
        "ai_ready": reason is None,
        "ai_reason": reason,
        "worker_running": worker_running(),
        "running": _running(),
        "stopped": frappe.cache.get_value(STOPPED),
        "progress": {
            "total": sum(counts.values()),
            "tagged": counts.get("Tagged", 0),
            "pending": counts.get("Pending", 0),
            "tagging": counts.get("Tagging", 0),
            "failed": counts.get("Failed", 0),
            "no_text": counts.get("No text", 0),
            "excluded": counts.get("Excluded", 0),
        },
        "last_labelled": frappe.db.sql("select max(tagged_on) from `tabHD AI Contact`")[0][0],
        "version": {
            "current": current,
            "stale": tagging.stale_count(),
            "relabelling": bool(left),
            "pct": round(100 * done / (done + left)) if left else None,
        },
        "validation": {
            "scored_on": score.get("scored_on"),
            "safety_recall": score.get("safety_recall"),
            "quote_validity": score.get("quote_validity"),
            "ok": bool(score.get("ok")),
        },
        "spend": {"month_usd": round(spend_month(), 4), "budget_usd": c.budget_usd},
        "coverage": {
            "chats_until": (cov.get("chat") or {}).get("until"),
            "deliveries_until": (cov.get("deliveries") or {}).get("until"),
            "calls_until": (cov.get("calls") or {}).get("until"),
            "excluded": cov.get("excluded_contacts"),
        },
        "default_window": metrics.default_window(),
        "web_research": c.web_research,
    }


def nightly():
    """Scheduler (daily): only enqueues. The build runs even with AI off, so the counts stay fresh."""
    start_chain("nightly", "Administrator")
    enqueue("maintenance", f"hd-ai::maintenance::{getdate()}")


@safe("maintenance")
def maintenance(as_of: str | None = None) -> dict:
    """Job (SQL only): stale claims, the retention purge, the vanished-source sweep and (Phase 2) verdicts."""
    as_of = getdate(as_of)
    out = {"released": _release_stale()}
    cutoff = add_months(as_of, -conf().retention_months)
    out["purged"] = _delete(frappe.db.sql_list("select name from `tabHD AI Contact` where started_on < %s", cutoff))
    out["vanished"] = _delete(_vanished())
    # The build deletes vanished and expired contacts without their gold labels.
    orphans = frappe.db.sql_list(
        """select g.name from `tabHD AI Gold Label` g left join `tabHD AI Contact` c on c.name = g.contact
        where c.name is null"""
    )
    if orphans:
        frappe.db.delete("HD AI Gold Label", {"name": ("in", orphans)})
    out["orphan_gold"] = len(orphans)
    frappe.db.commit()  # the SQL maintenance stands even if an advisor step below fails
    from helpdesk.ai_analysis import advisor

    for step, fn in (("verdicts", advisor.update_verdicts), ("insights", advisor.purge_insights)):
        failure = None
        try:
            out[step] = fn(as_of)
        except Exception as e:
            failure = e
        if failure is not None:  # logged outside the except block, as in safe(): type and step only
            frappe.log_error(title="AI Analysis maintenance failed", message=f"{type(failure).__name__} at maintenance:{step}")
    frappe.db.commit()
    return out


def _vanished() -> list[str]:
    """Contacts whose ticket is gone or merged, or whose conversation is gone."""
    names = frappe.db.sql_list(
        """select c.name from `tabHD AI Contact` c left join `tabHD Ticket` t on t.name = c.ticket
        where c.source = 'Ticket' and (t.name is null or t.is_merged = 1)"""
    )
    if frappe.db.table_exists("Messenger Conversation"):  # never sweep every chat because the app is missing
        names += frappe.db.sql_list(
            """select c.name from `tabHD AI Contact` c
            left join `tabMessenger Conversation` m on m.name = c.conversation
            where c.source = 'Chat' and m.name is null"""
        )
    return names


def _delete(names: list[str]) -> int:
    """Delete contacts with their tags and gold labels."""
    for i in range(0, len(names), 500):
        batch = names[i : i + 500]
        frappe.db.delete("HD AI Contact Issue", {"parenttype": CONTACT, "parent": ("in", batch)})
        frappe.db.delete("HD AI Gold Label", {"contact": ("in", batch)})
        frappe.db.delete(CONTACT, {"name": ("in", batch)})
    return len(names)


# --- bench execute ---------------------------------------------------------------------------------

SMOKE_SCHEMA = {
    "type": "object",
    "properties": {"ok": {"type": "boolean"}},
    "required": ["ok"],
    "additionalProperties": False,
}
WEB_SEARCH = {
    "tools": [
        {
            "type": "openrouter:web_search",
            "parameters": {"engine": "exa", "max_results": 5, "search_context_size": "low"},
        }
    ]
}


def run_now(kind: str, **kw):
    """Run a job body synchronously and print JSON: smoke | volumes | build | tag (limit=20) | chain |
    maintenance (as_of=None) | gold_sample (labellers=[...], n=80) | score_gold | suggest (code, from_date,
    to_date, regenerate=0) | research (code, regenerate=0) | brief (week, regenerate=0) | verdicts (as_of=None)."""
    from helpdesk.ai_analysis import advisor, cases, tagging

    if kind == "smoke":
        out = _smoke()
    elif kind == "volumes":
        out = _volumes()
    elif kind == "build":
        out = cases.build_contacts()
    elif kind == "tag":
        _release_stale()
        run = "now-" + frappe.generate_hash(length=6)
        out = _tag(f"{run}:0", float("inf"), f"skip:{run}", limit=cint(kw.get("limit") or 20))
    elif kind == "chain":
        out = start_chain("bench", frappe.session.user)
    elif kind == "maintenance":
        out = maintenance(as_of=kw.get("as_of"))  # None when it failed: see the Error Log
    elif kind == "gold_sample":
        out = {"created": tagging.gold_sample(kw.get("labellers") or [], n=cint(kw.get("n") or 80))}
    elif kind == "score_gold":
        out = tagging.score_gold()
    elif kind == "verdicts":
        out = advisor.update_verdicts(kw.get("as_of"))
    elif kind in ("suggest", "research", "brief"):
        user, again = frappe.session.user, cint(kw.get("regenerate"))
        frappe.flags.hd_ai_sync = True  # the advisor runs each step inline instead of queueing it
        try:
            if kind == "suggest":
                name = advisor.request_suggestions(kw.get("code"), kw.get("from_date"), kw.get("to_date"), user, again)[0]
            elif kind == "research":
                name = advisor.request_research(kw.get("code"), user, again)[0]
            else:
                name = advisor.write_summary(kw.get("week"), user, again)[0]
        finally:
            frappe.flags.hd_ai_sync = False
        out = advisor.insight_projection(name)
    else:
        frappe.throw(
            _(
                "Unknown kind. Use smoke, volumes, build, tag, chain, maintenance, gold_sample, score_gold, suggest, "
                "research, brief or verdicts."
            )
        )
    frappe.db.commit()
    print(json.dumps(out, indent=1, default=str, ensure_ascii=False))


def _smoke() -> dict:
    """One tiny strict-schema call per configured model, plus one web-search call. Reports ok or the
    error type, the HTTP status and whether usage.cost came back; never the reply text."""
    from helpdesk.api import ticket_ai

    if not (ticket_ai.get_config()["base_url"] and ticket_ai._api_key()):
        return {"ok": False, "error": "No AI base URL or API key in HD Settings, tab AI."}
    c = conf()
    provider = ai_provider()
    roles = [("tagging", c.model, 0)]
    roles += [("council", m, None) for m in c.council_models]
    roles += [("chairman", c.chairman_model, None), ("research", c.research_model, 0)]
    models = [
        {"role": role, "model": model, **_probe(model, SMOKE_SCHEMA, temperature, provider)}
        for role, model, temperature in roles
    ]
    web = {"model": c.research_model, **_probe(c.research_model, None, None, provider, WEB_SEARCH)}
    return {"ok": all(r["ok"] for r in [*models, web]), "provider": provider, "models": models, "web_search": web}


def _probe(model: str, schema: dict | None, temperature, provider: dict, extra: dict | None = None) -> dict:
    from helpdesk.api.ticket_ai import TicketAIError, chat_json

    if schema:
        data = {"task": "Reply with ok set to true."}
    else:
        data = "Name one practice that keeps chilled meal deliveries cold in hot weather, and cite a source."
    try:
        _reply, meta = chat_json(
            "You are a connectivity check. Do exactly what the user asks.",
            data,
            schema,
            name="hd_ai_smoke",
            model=model,
            max_tokens=2000,  # reasoning models spend tokens before answering
            temperature=temperature,
            provider=provider,
            extra=extra,
            log_title="AI Analysis smoke test failed",
        )
    except TicketAIError as e:
        return {"ok": False, "error": "TicketAIError", "message": str(e), "http_status": e.http_status}
    except Exception as e:
        return {"ok": False, "error": type(e).__name__, "http_status": None}
    out = {
        "ok": True,
        "routed_model": meta.get("model"),
        "finish_reason": meta.get("finish_reason"),
        "cost_present": "cost" in (meta.get("usage") or {}),
        "cost_usd": meta.get("cost"),
    }
    if extra:
        annotations = meta.get("annotations") or []
        out["url_citations"] = sum(1 for a in annotations if isinstance(a, dict) and a.get("type") == "url_citation")
    return out


def _volumes() -> dict:
    """Phase 0 go/no-go over the last 8 weeks: incoming chats, the outgoing share, normal deliveries per
    day and answered incoming calls. Under 10 incoming chats a week, only the deterministic parts ship."""
    from helpdesk.ai_analysis import stats

    today = getdate()
    start, end = add_days(today, -55), add_days(today, 1)  # 56 days, today included
    days = [add_days(start, i) for i in range(56)]
    weeks = {}

    def week(day):
        return weeks.setdefault(
            stats.week_start(day), {"incoming_chats": 0, "outgoing_chats": 0, "deliveries": 0, "answered_calls": 0}
        )

    for day in days:  # weeks and days without data show as zeros
        week(day)
    per_day = {str(day): 0 for day in days}

    if frappe.db.table_exists("Messenger Message"):
        for day, direction, n in frappe.db.sql(
            """select date(timestamp), message_direction, count(*) from `tabMessenger Message`
            where timestamp >= %s and timestamp < %s and ifnull(is_private, 0) = 0
            group by date(timestamp), message_direction""",
            (start, end),
        ):
            if direction in ("Incoming", "Outgoing"):
                week(day)[f"{direction.lower()}_chats"] += cint(n)

    if frappe.db.table_exists("Delivery Note"):
        normal = (
            "and ifnull(custom_dieture_delivery_type, '') in ('', 'normal')"
            if frappe.db.has_column("Delivery Note", "custom_dieture_delivery_type")
            else ""
        )
        for day, n in frappe.db.sql(
            f"""select posting_date, count(*) from `tabDelivery Note`
            where docstatus = 1 and ifnull(is_return, 0) = 0 {normal} and posting_date >= %s and posting_date < %s
            group by posting_date""",
            (start, end),
        ):
            per_day[str(day)] = cint(n)
            week(day)["deliveries"] += cint(n)

    if frappe.db.table_exists("CRM Call Log"):
        for (started,) in frappe.db.sql(
            """select start_time from `tabCRM Call Log`
            where type = 'Incoming' and status = 'Completed' and char_length(ifnull(`from`, '')) > 4
            and start_time >= %s and start_time < %s""",
            (add_to_date(start, hours=-3), add_to_date(end, hours=-3)),
        ):
            week(started + QATAR)["answered_calls"] += 1

    rows = [{"week": w, **weeks[w]} for w in sorted(weeks)]
    incoming = sum(r["incoming_chats"] for r in rows)
    outgoing = sum(r["outgoing_chats"] for r in rows)
    avg = round(incoming / 8, 1)
    return {
        "from_date": start,
        "to_date": today,
        "weeks": rows,
        "outgoing_share": round(outgoing / (incoming + outgoing), 3) if incoming + outgoing else None,
        "deliveries_per_day": per_day,
        "avg_incoming_chats_per_week": avg,
        "verdict": "ship deterministic parts only" if avg < 10 else "go: enough chats to label",
    }
