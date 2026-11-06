// Pure helpers for the AI Analysis page (CONTRACT.md section 14). No Vue imports, so vitest runs them
// directly. Names and signatures are the contract: add exports, never rename or remove one.
export type Segment = { type: "text" | "value"; text: string };
export type Theme = "red" | "orange" | "green" | "blue" | "gray";
export type Meta = { label: string; theme: Theme; tooltip: string };

// desk's translationPlugin puts __ on window; this shim keeps the module import-free (and the strings
// visible to the __("...") extractor). Outside the app (tests) it returns the English text. The maps
// below are functions so each call translates with whatever translations have loaded by then.
const __ = (message: string): string =>
  (globalThis as any).__?.(message) ?? message;

// The server's enums (helpdesk/api/ai_analysis.py CHANNELS, helpdesk/ai_analysis DEPARTMENTS).
export const CHANNELS = [
  "Ticket",
  "WhatsApp",
  "Instagram DM",
  "Instagram comment",
  "Facebook comment",
  "Messenger",
];
export const DEPARTMENTS = [
  "Kitchen & QA",
  "Operations & Packing",
  "Delivery",
  "Customer Service",
  "Tech",
  "Marketing & Sales",
  "Finance",
];

const ISO_DAY = /^\d{4}-\d{2}-\d{2}/;
const MONTHS = [
  "Jan",
  "Feb",
  "Mar",
  "Apr",
  "May",
  "Jun",
  "Jul",
  "Aug",
  "Sep",
  "Oct",
  "Nov",
  "Dec",
];

function addDays(iso: string, days: number): string {
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d + days)).toISOString().slice(0, 10);
}

function dayText(iso: string, withYear = false): string {
  if (!ISO_DAY.test(iso || "")) return String(iso ?? "");
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  return `${d} ${MONTHS[m - 1]}${withYear ? ` ${y}` : ""}`;
}

function toNumber(v: unknown): number | null {
  if (v == null || v === "") return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

const round2 = (n: number) => Math.round(n * 100) / 100;

/** "{{key}}" placeholders → segments; a missing or empty value becomes the text "—", never a 0. */
export function fillPlaceholders(
  text: string | null | undefined,
  values: Record<string, string> | null | undefined
): Segment[] {
  if (!text) return [];
  const out: Segment[] = [];
  let last = 0;
  for (const m of text.matchAll(/\{\{\s*([^{}\s]+)\s*\}\}/g)) {
    const at = m.index ?? 0;
    if (at > last) out.push({ type: "text", text: text.slice(last, at) });
    const value = values?.[m[1]];
    out.push(
      value == null || value === ""
        ? { type: "text", text: "—" }
        : { type: "value", text: String(value) }
    );
    last = at + m[0].length;
  }
  if (last < text.length) out.push({ type: "text", text: text.slice(last) });
  return out;
}

/** SVG path for a w×h sparkline: max at the top, a flat midline when every value is 0, gaps at nulls. */
export function sparklinePath(
  values: (number | null)[],
  w: number,
  h: number
): string {
  const vals = (Array.isArray(values) ? values : []).map((v) => {
    const n = toNumber(v);
    return n == null ? null : Math.max(0, n);
  });
  const max = Math.max(0, ...vals.filter((v): v is number => v != null));
  const step = vals.length > 1 ? w / (vals.length - 1) : 0;
  const x0 = vals.length > 1 ? 0 : w / 2;
  const parts: string[] = [];
  let penDown = false;
  vals.forEach((v, i) => {
    if (v == null) {
      penDown = false;
      return;
    }
    const y = max > 0 ? h - (v / max) * h : h / 2;
    parts.push(`${penDown ? "L" : "M"} ${round2(x0 + i * step)} ${round2(y)}`);
    penDown = true;
  });
  return parts.join(" ");
}

const BAR_COLOR = "#318AD8";
const RATE_COLOR = "#9F7AEA";
const ACTION_COLOR = "#48BB78";
const SEASON_FILL = "rgba(214, 158, 46, 0.12)";
const LOW_DATA_FILL = "rgba(113, 128, 150, 0.16)";

const escapeHtml = (s: unknown) =>
  String(s ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[
        c
      ] as string)
  );

/** Consecutive rows sharing a non-null key → [firstWeek, lastWeek, key]. */
function runs(
  rows: Record<string, any>[],
  keyOf: (row: Record<string, any>) => string | null
) {
  const out: [string, string, string][] = [];
  rows.forEach((row, i) => {
    const key = keyOf(row);
    if (key && i > 0 && key === keyOf(rows[i - 1]))
      out[out.length - 1][1] = row.week;
    else if (key) out.push([row.week, row.week, key]);
  });
  return out;
}

/**
 * ECharts option for an issue's weekly trend: case bars, a rate line on a second axis for covered weeks
 * only, light bands for season and low-data (uncovered) weeks, a vertical line per action, a tooltip.
 * weekly: [{week: "YYYY-MM-DD" (Sunday), cases, rate, covered, season}] oldest first.
 * opts.actions: [{date: "YYYY-MM-DD", label}]; dates outside the charted weeks are skipped.
 */
export function trendOptions(
  weekly: Record<string, any>[],
  opts: { actions?: { date: string; label: string }[] } & Record<
    string,
    any
  > = {}
): Record<string, any> {
  const rows = (Array.isArray(weekly) ? weekly : [])
    .filter((w) => ISO_DAY.test(w?.week || ""))
    .map((w) => ({ ...w, week: String(w.week).slice(0, 10) }));
  const weeks = rows.map((w) => w.week);
  // an uncovered week's 0 is missing data, not a real zero: leave a gap unless cases were found anyway
  const cases = rows.map((w) =>
    w.covered === false && !toNumber(w.cases) ? null : toNumber(w.cases)
  );
  const rates = rows.map((w) =>
    w.covered === false ? null : toNumber(w.rate)
  );
  const hasRate = rates.some((r) => r != null);
  const casesName = __("Cases");
  const rateName = __("Per 1,000 deliveries");

  const actionsByWeek: Record<string, string[]> = {};
  for (const a of Array.isArray(opts?.actions) ? opts.actions : []) {
    const day = String(a?.date ?? "").slice(0, 10);
    if (!ISO_DAY.test(day)) continue;
    const week = [...weeks].reverse().find((w) => w <= day);
    if (week && day < addDays(week, 7)) {
      actionsByWeek[week] = [
        ...(actionsByWeek[week] || []),
        String(a.label ?? ""),
      ];
    }
  }

  const band = (from: string, to: string, name: string, color: string) => [
    {
      name,
      xAxis: from,
      itemStyle: { color },
      label: {
        show: true,
        position: "insideTop",
        color: "#718096",
        fontSize: 10,
      },
    },
    { xAxis: to },
  ];
  const lowData = __("Low data");
  const areas = [
    ...runs(rows, (w) => (w.season ? String(w.season) : null)).map(
      ([a, b, n]) => band(a, b, n, SEASON_FILL)
    ),
    ...runs(rows, (w) => (w.covered === false ? lowData : null)).map(
      ([a, b, n]) => band(a, b, n, LOW_DATA_FILL)
    ),
  ];
  const lines = Object.entries(actionsByWeek).map(([week, labels]) => {
    const text = labels.join(", ");
    return {
      xAxis: week,
      label: {
        formatter: () => (text.length > 24 ? `${text.slice(0, 23)}…` : text),
      },
    };
  });

  return {
    animation: false,
    grid: { left: 8, right: 8, top: 36, bottom: 32, containLabel: true },
    legend: { bottom: 0, data: hasRate ? [casesName, rateName] : [casesName] },
    tooltip: {
      trigger: "axis",
      axisPointer: { type: "shadow" },
      formatter: (params: any) => {
        const i = (Array.isArray(params) ? params[0] : params)?.dataIndex;
        const w = rows[i];
        if (!w) return "";
        const out = [`${__("Week of")} ${dayText(w.week, true)}`];
        if (w.covered === false) out.push(__("No chat data this week"));
        out.push(`${casesName}: ${cases[i] ?? "—"}`);
        if (hasRate) out.push(`${rateName}: ${rates[i] ?? "—"}`);
        if (w.season) out.push(String(w.season));
        for (const label of actionsByWeek[w.week] || [])
          out.push(`${__("Action")}: ${label}`);
        return out.map(escapeHtml).join("<br>"); // tooltips render as HTML: escape every piece
      },
    },
    xAxis: {
      type: "category",
      data: weeks,
      axisTick: { interval: 0 }, // a tick per week, so a one-week band spans its whole slot
      axisLabel: { formatter: (v: string) => dayText(v) },
    },
    yAxis: [
      { type: "value", name: casesName, minInterval: 1 },
      ...(hasRate
        ? [{ type: "value", name: rateName, splitLine: { show: false } }]
        : []),
    ],
    series: [
      {
        name: casesName,
        type: "bar",
        data: cases,
        itemStyle: { color: BAR_COLOR },
        // on the bar series: bar marker positioning makes a category band cover whole weeks
        markArea: { silent: true, data: areas },
        markLine: {
          silent: true,
          symbol: "none",
          lineStyle: { color: ACTION_COLOR, type: "dashed" },
          label: { position: "end", color: ACTION_COLOR, fontSize: 10 },
          data: lines,
        },
      },
      ...(hasRate
        ? [
            {
              name: rateName,
              type: "line",
              yAxisIndex: 1,
              data: rates,
              connectNulls: false,
              symbolSize: 5,
              itemStyle: { color: RATE_COLOR },
            },
          ]
        : []),
    ],
  };
}

const CHIP_CLASSES: Record<string, string> = {
  "Unusual ▲": "bg-red-100 text-red-700",
  "Watch ▲": "bg-amber-100 text-amber-700",
  Usual: "bg-gray-100 text-gray-700",
  "Watch ▼": "bg-teal-100 text-teal-700",
  "Unusual ▼": "bg-green-100 text-green-700",
};

/** Tailwind classes for an exact-test chip label; no label (no test was possible) is a quiet gray. */
export function chipClass(label: string | null | undefined): string {
  return CHIP_CLASSES[label ?? ""] || "bg-gray-50 text-gray-500";
}

/** The normalised href of an http(s) URL with a host, else null (javascript:, data:, relative, junk). */
export function safeUrl(url: string | null | undefined): string | null {
  if (typeof url !== "string" || !url.trim()) return null;
  try {
    const u = new URL(url.trim());
    return (u.protocol === "http:" || u.protocol === "https:") && u.hostname
      ? u.href
      : null;
  } catch {
    return null;
  }
}

/** "https://www.example.com/x" → "example.com"; "" for anything safeUrl rejects. */
export function domainOf(url: string | null | undefined): string {
  const href = safeUrl(url);
  return href ? new URL(href).hostname.replace(/^www\./i, "") : "";
}

const badges = (): Record<string, Meta> => ({
  SAFETY: {
    label: __("Safety"),
    theme: "red",
    tooltip: __(
      "At least one counted food-safety case (S1 or S2) in this period."
    ),
  },
  SURGE: {
    label: __("Surge"),
    theme: "red",
    tooltip: __(
      "The last 4 weeks run at least double the usual rate, with 3+ cases from 2+ customers (exact test, p < 0.01). Usual = up to 12 earlier weeks without seasons or data gaps."
    ),
  },
  WATCH: {
    label: __("Watch"),
    theme: "orange",
    tooltip: __(
      "The last 4 weeks run at least double the usual rate, with 3+ cases from 2+ customers, but the evidence is weaker than a surge (exact test, p < 0.05)."
    ),
  },
  IMPROVING: {
    label: __("Improving"),
    theme: "green",
    tooltip: __(
      "The last 4 weeks run below the usual rate (exact test, p < 0.01), from a baseline of 3+ cases."
    ),
  },
  CHRONIC: {
    label: __("Chronic"),
    theme: "orange",
    tooltip: __(
      "Cases started in at least 3 of the last 4 weeks, from 2 or more customers."
    ),
  },
  NEW: {
    label: __("New"),
    theme: "blue",
    tooltip: __(
      "First case in the last 14 days, with 2+ cases from 2+ customers. Not shown during the first 8 weeks of history."
    ),
  },
  RESURFACED: {
    label: __("Resurfaced"),
    theme: "orange",
    tooltip: __(
      "Seen before, then no cases for 8 weeks (weeks 5–12 back), and now 2+ cases from 2+ customers in the last 4 weeks."
    ),
  },
  PUBLIC: {
    label: __("Public"),
    theme: "gray",
    tooltip: __("Raised in a public Instagram or Facebook comment."),
  },
});

export function badgeMeta(key: string): Meta {
  return badges()[key] || { label: key || "", theme: "gray", tooltip: "" };
}

const verdicts = (): Record<string, Meta> => {
  const notProof = __("Association, not proof.");
  return {
    "Not yet": {
      label: __("Not yet"),
      theme: "gray",
      tooltip: `${__(
        "Not checked yet: checks run 4 and 8 weeks after the action is done, plus a week for it to take effect."
      )} ${notProof}`,
    },
    "Lower than before": {
      label: __("Lower than before"),
      theme: "green",
      tooltip: `${__(
        "Fewer cases than in the clean weeks before the action (exact test, p < 0.05)."
      )} ${notProof}`,
    },
    Inconclusive: {
      label: __("Inconclusive"),
      theme: "blue",
      tooltip: `${__(
        "No clear change from the clean weeks before the action."
      )} ${notProof}`,
    },
    "Higher than before": {
      label: __("Higher than before"),
      theme: "red",
      tooltip: `${__(
        "More cases than in the clean weeks before the action (exact test, p < 0.05)."
      )} ${notProof}`,
    },
    "Not enough data": {
      label: __("Not enough data"),
      theme: "gray",
      tooltip: `${__(
        "No test: fewer than 5 cases, a low-data week in the window, or nothing to compare against."
      )} ${notProof}`,
    },
  };
};

/** Badge meta for an action verdict; no verdict yet reads as "Not yet". */
export function verdictMeta(verdict: string | null | undefined): Meta {
  return (
    verdicts()[verdict || "Not yet"] || {
      label: verdict || "",
      theme: "gray",
      tooltip: __("Association, not proof."),
    }
  );
}

export function roleLabel(role: string): string {
  const roles: Record<string, string> = {
    customer: __("Customer"),
    agent: __("Agent"),
    staff: __("Staff note"),
    ticket: __("Ticket description"),
    bot: __("Bot"),
  };
  return roles[role] || role || "";
}

const DUE_DAYS: Record<string, number> = {
  this_week: 7,
  this_month: 28,
  this_quarter: 90,
};

/** Due date for an option's time_to_effect: +7 / +28 / +90 days from `from` (default today); "" if unknown. */
export function dueDateFor(timeToEffect: string, from?: string): string {
  const days = DUE_DAYS[timeToEffect];
  if (!days) return "";
  let base =
    typeof from === "string" && ISO_DAY.test(from) ? from.slice(0, 10) : "";
  if (!base) {
    const t = new Date(); // the viewer's local calendar day
    base = new Date(Date.UTC(t.getFullYear(), t.getMonth(), t.getDate()))
      .toISOString()
      .slice(0, 10);
  }
  return addDays(base, days);
}

/** 1130 → "1,130.00 QAR"; null, blank or not a number → "—". */
export function formatQar(n: number | null | undefined): string {
  const v = toNumber(n);
  return v == null
    ? "—"
    : `${v.toLocaleString("en-US", {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      })} QAR`;
}
