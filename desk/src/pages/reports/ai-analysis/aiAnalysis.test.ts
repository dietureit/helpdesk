import {
  badgeMeta,
  chipClass,
  domainOf,
  dueDateFor,
  fillPlaceholders,
  formatQar,
  roleLabel,
  safeUrl,
  sparklinePath,
  trendOptions,
  verdictMeta,
} from "./aiAnalysis";

describe("fillPlaceholders", () => {
  it("splits text and known values", () => {
    expect(
      fillPlaceholders("Cases rose to {{kpi.cases}} this week", {
        "kpi.cases": "7",
      })
    ).toEqual([
      { type: "text", text: "Cases rose to " },
      { type: "value", text: "7" },
      { type: "text", text: " this week" },
    ]);
  });

  it("turns unknown, null and empty values into a dash, never a 0", () => {
    const values = { a: "1", gone: null, blank: "" } as unknown as Record<
      string,
      string
    >;
    expect(
      fillPlaceholders("{{a}}{{missing}} {{ gone }}{{blank}}", values)
    ).toEqual([
      { type: "value", text: "1" },
      { type: "text", text: "—" },
      { type: "text", text: " " },
      { type: "text", text: "—" },
      { type: "text", text: "—" },
    ]);
    expect(fillPlaceholders("{{x}}", null)).toEqual([
      { type: "text", text: "—" },
    ]);
  });

  it("returns [] for empty or null text and keeps plain text whole", () => {
    expect(fillPlaceholders("", { a: "1" })).toEqual([]);
    expect(fillPlaceholders(null, { a: "1" })).toEqual([]);
    expect(fillPlaceholders(undefined, {})).toEqual([]);
    expect(fillPlaceholders("no numbers here {single}", {})).toEqual([
      { type: "text", text: "no numbers here {single}" },
    ]);
  });

  it("stringifies non-string values", () => {
    const values = { n: 3 } as unknown as Record<string, string>;
    expect(fillPlaceholders("{{n}}", values)).toEqual([
      { type: "value", text: "3" },
    ]);
  });
});

describe("sparklinePath", () => {
  it("scales to the max, top = max", () => {
    expect(sparklinePath([0, 5, 10], 100, 20)).toBe("M 0 20 L 50 10 L 100 0");
  });

  it("draws a flat midline when every value is zero", () => {
    expect(sparklinePath([0, 0, 0], 100, 20)).toBe("M 0 10 L 50 10 L 100 10");
  });

  it("leaves gaps at nulls", () => {
    expect(sparklinePath([2, null, 1, 2], 30, 10)).toBe("M 0 0 M 20 5 L 30 0");
    expect(sparklinePath([null, null], 30, 10)).toBe("");
  });

  it("handles empty, single and junk input", () => {
    expect(sparklinePath([], 100, 20)).toBe("");
    expect(sparklinePath(null as unknown as number[], 100, 20)).toBe("");
    expect(sparklinePath([4], 100, 20)).toBe("M 50 0");
    expect(sparklinePath([NaN, -3, 3] as number[], 60, 10)).toBe(
      "M 30 10 L 60 0"
    );
  });

  it("rounds coordinates to 2 decimals", () => {
    expect(sparklinePath([1, 2, 3, 3], 10, 10)).toBe(
      "M 0 6.67 L 3.33 3.33 L 6.67 0 L 10 0"
    );
  });
});

describe("trendOptions", () => {
  const weekly = [
    { week: "2026-02-08", cases: 1, rate: 0.3, covered: true, season: null },
    {
      week: "2026-02-15",
      cases: 2,
      rate: 0.55,
      covered: true,
      season: "Ramadan",
    },
    { week: "2026-02-22", cases: 0, rate: 0, covered: true, season: "Ramadan" },
    { week: "2026-03-01", cases: 0, rate: 0.4, covered: false, season: null },
    { week: "2026-03-08", cases: 0, rate: null, covered: false, season: "Eid" },
  ];

  it("has case bars and a rate line on a second axis, rate only for covered weeks", () => {
    const o = trendOptions(weekly);
    expect(o.animation).toBe(false);
    expect(o.xAxis.data).toEqual(weekly.map((w) => w.week));
    expect(o.yAxis).toHaveLength(2);
    const [bars, line] = o.series;
    expect(bars.type).toBe("bar");
    expect(bars.data).toEqual([1, 2, 0, null, null]); // an uncovered week's 0 is a gap
    expect(line.type).toBe("line");
    expect(line.yAxisIndex).toBe(1);
    expect(line.data).toEqual([0.3, 0.55, 0, null, null]);
    expect(line.connectNulls).toBe(false);
  });

  it("drops the rate axis when no week has a rate", () => {
    const o = trendOptions(weekly.map((w) => ({ ...w, rate: null })));
    expect(o.series).toHaveLength(1);
    expect(o.yAxis).toHaveLength(1);
    expect(o.legend.data).toEqual(["Cases"]);
  });

  it("keeps real cases in an uncovered week", () => {
    const o = trendOptions([
      { week: "2026-03-01", cases: 2, rate: null, covered: false },
    ]);
    expect(o.series[0].data).toEqual([2]);
  });

  it("bands season runs and low-data runs with distinct fills", () => {
    const areas = trendOptions(weekly).series[0].markArea.data;
    const spans = areas.map(([a, b]: any[]) => [a.name, a.xAxis, b.xAxis]);
    expect(spans).toEqual([
      ["Ramadan", "2026-02-15", "2026-02-22"],
      ["Eid", "2026-03-08", "2026-03-08"],
      ["Low data", "2026-03-01", "2026-03-08"],
    ]);
    const fill = (name: string) =>
      areas.find(([a]: any[]) => a.name === name)[0].itemStyle.color;
    expect(fill("Ramadan")).not.toBe(fill("Low data"));
  });

  it("draws a line per action inside the charted weeks and skips the rest", () => {
    const o = trendOptions(weekly, {
      actions: [
        { date: "2026-02-17", label: "Seal check" },
        { date: "2026-02-20", label: "Driver briefing" },
        { date: "2026-03-20", label: "too late" },
        { date: "2026-01-01", label: "too early" },
        { date: "junk", label: "bad date" },
      ],
    });
    const lines = o.series[0].markLine.data;
    expect(lines.map((l: any) => l.xAxis)).toEqual(["2026-02-15"]);
    expect(lines[0].label.formatter()).toBe("Seal check, Driver brie…"); // 24 chars with the ellipsis
  });

  it("escapes the HTML tooltip and shows a dash for missing numbers", () => {
    const o = trendOptions(weekly, {
      actions: [{ date: "2026-03-02", label: "<img src=x onerror=alert(1)>" }],
    });
    const html = o.tooltip.formatter([{ dataIndex: 3 }]);
    expect(html).toContain("Week of 1 Mar 2026");
    expect(html).toContain("No chat data this week");
    expect(html).toContain("Cases: —");
    expect(html).toContain("Per 1,000 deliveries: —");
    expect(html).toContain("&lt;img src=x onerror=alert(1)&gt;");
    expect(html).not.toContain("<img");
    expect(o.tooltip.formatter([{ dataIndex: 99 }])).toBe("");
    expect(o.xAxis.axisLabel.formatter("2026-02-08")).toBe("8 Feb");
  });

  it("is safe on empty or junk input", () => {
    for (const input of [[], null, [{ week: "nope", cases: 3 }]]) {
      const o = trendOptions(input as any);
      expect(o.xAxis.data).toEqual([]);
      expect(o.series[0].data).toEqual([]);
      expect(o.series[0].markArea.data).toEqual([]);
    }
  });
});

describe("chipClass", () => {
  it("maps each exact-test label to its colour family", () => {
    expect(chipClass("Unusual ▲")).toContain("red");
    expect(chipClass("Watch ▲")).toContain("amber");
    expect(chipClass("Usual")).toContain("gray");
    expect(chipClass("Watch ▼")).toContain("teal");
    expect(chipClass("Unusual ▼")).toContain("green");
  });

  it("falls back to quiet gray for no label", () => {
    expect(chipClass(null)).toBe("bg-gray-50 text-gray-500");
    expect(chipClass(undefined)).toBe("bg-gray-50 text-gray-500");
    expect(chipClass("Something else")).toBe("bg-gray-50 text-gray-500");
  });
});

describe("safeUrl / domainOf", () => {
  it("keeps http(s) URLs with a host, normalised", () => {
    expect(safeUrl("https://Example.com/a?b=1")).toBe(
      "https://example.com/a?b=1"
    );
    expect(safeUrl("  http://www.fda.gov  ")).toBe("http://www.fda.gov/");
  });

  it("rejects script, data, relative, hostless and junk URLs", () => {
    for (const bad of [
      "javascript:alert(1)",
      "JavaScript:alert(1)",
      "data:text/html,<script>alert(1)</script>",
      "mailto:a@b.com",
      "ftp://example.com/file",
      "/relative/path",
      "//evil.com/x",
      "https://",
      "http://",
      "not a url",
      "",
      "   ",
      null,
      undefined,
      42 as unknown as string,
    ]) {
      expect(safeUrl(bad)).toBeNull();
    }
  });

  it("gives the hostname without www", () => {
    expect(domainOf("https://www.who.int/news")).toBe("who.int");
    expect(domainOf("https://moph.gov.qa/en")).toBe("moph.gov.qa");
    expect(domainOf("javascript:alert(1)")).toBe("");
    expect(domainOf(null)).toBe("");
  });
});

describe("badgeMeta", () => {
  it("covers every badge with a label, a Badge theme and a plain-words rule", () => {
    const themes = ["red", "orange", "green", "blue", "gray"];
    for (const key of [
      "SAFETY",
      "SURGE",
      "WATCH",
      "IMPROVING",
      "CHRONIC",
      "NEW",
      "RESURFACED",
      "PUBLIC",
    ]) {
      const meta = badgeMeta(key);
      expect(meta.label).toBeTruthy();
      expect(meta.label).not.toBe(key);
      expect(themes).toContain(meta.theme);
      expect(meta.tooltip.length).toBeGreaterThan(20);
    }
    expect(badgeMeta("SAFETY").theme).toBe("red");
    expect(badgeMeta("IMPROVING").theme).toBe("green");
    expect(badgeMeta("SURGE").tooltip).toContain("p < 0.01");
    expect(badgeMeta("CHRONIC").tooltip).toContain("3 of the last 4 weeks");
  });

  it("passes an unknown key through in gray", () => {
    expect(badgeMeta("ODD")).toEqual({
      label: "ODD",
      theme: "gray",
      tooltip: "",
    });
    expect(badgeMeta("")).toEqual({ label: "", theme: "gray", tooltip: "" });
  });
});

describe("verdictMeta", () => {
  it("covers every verdict, always worded association, not proof", () => {
    for (const v of [
      "Not yet",
      "Lower than before",
      "Inconclusive",
      "Higher than before",
      "Not enough data",
    ]) {
      const meta = verdictMeta(v);
      expect(meta.label).toBe(v);
      expect(meta.tooltip.toLowerCase()).toContain("association, not proof");
    }
    expect(verdictMeta("Lower than before").theme).toBe("green");
    expect(verdictMeta("Higher than before").theme).toBe("red");
  });

  it("reads a missing verdict as Not yet and keeps unknown ones", () => {
    expect(verdictMeta(null).label).toBe("Not yet");
    expect(verdictMeta(undefined).label).toBe("Not yet");
    const odd = verdictMeta("Pending review");
    expect(odd.label).toBe("Pending review");
    expect(odd.theme).toBe("gray");
    expect(odd.tooltip.toLowerCase()).toContain("association, not proof");
  });
});

describe("roleLabel", () => {
  it("names each line role", () => {
    expect(roleLabel("customer")).toBe("Customer");
    expect(roleLabel("agent")).toBe("Agent");
    expect(roleLabel("staff")).toBe("Staff note");
    expect(roleLabel("ticket")).toBe("Ticket description");
    expect(roleLabel("bot")).toBe("Bot");
    expect(roleLabel("other")).toBe("other");
    expect(roleLabel("")).toBe("");
  });
});

describe("dueDateFor", () => {
  it("adds 7 / 28 / 90 days", () => {
    expect(dueDateFor("this_week", "2026-11-06")).toBe("2026-11-13");
    expect(dueDateFor("this_month", "2026-11-06")).toBe("2026-12-04");
    expect(dueDateFor("this_quarter", "2026-11-06")).toBe("2027-02-04");
    expect(dueDateFor("this_week", "2026-02-25 10:00:00")).toBe("2026-03-04");
  });

  it("returns blank for an unknown time to effect", () => {
    expect(dueDateFor("someday", "2026-11-06")).toBe("");
    expect(dueDateFor("", "2026-11-06")).toBe("");
  });

  it("counts from today when no valid start is given", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(2026, 11, 30, 23, 30)); // local 30 Dec
    try {
      expect(dueDateFor("this_week")).toBe("2027-01-06");
      expect(dueDateFor("this_week", "junk")).toBe("2027-01-06");
    } finally {
      vi.useRealTimers();
    }
  });
});

describe("formatQar", () => {
  it("formats money with 2 decimals and thousands separators", () => {
    expect(formatQar(1130)).toBe("1,130.00 QAR");
    expect(formatQar(228.524)).toBe("228.52 QAR");
    expect(formatQar(0)).toBe("0.00 QAR");
    expect(formatQar("6333" as unknown as number)).toBe("6,333.00 QAR");
  });

  it("shows a dash for missing values, never 0", () => {
    expect(formatQar(null)).toBe("—");
    expect(formatQar(undefined)).toBe("—");
    expect(formatQar(NaN)).toBe("—");
    expect(formatQar("" as unknown as number)).toBe("—");
  });
});
