import {
  OVERDUE,
  UNASSIGNED,
  fromRouteFilters,
  toApiFilters,
} from "./ticketFilters";

describe("toApiFilters", () => {
  it("maps plain fields to equality filters and skips empty ones", () => {
    expect(
      toApiFilters({ status: "Open", custom_category: "Complaint", priority: "" })
    ).toEqual({ custom_category: ["=", "Complaint"], status: ["=", "Open"] });
  });

  it("maps assignee, unassigned, source and customer SLA", () => {
    expect(toApiFilters({ assigned_to: "a@x.com" })).toEqual({
      _assign: ["like", '%"a@x.com"%'],
    });
    expect(toApiFilters({ assigned_to: UNASSIGNED })).toEqual({
      _assign: ["not like", '%"%'],
    });
    expect(toApiFilters({ source: "messenger" })).toEqual({
      custom_messenger_conversation: ["is", "set"],
    });
    expect(toApiFilters({ customer_sla: OVERDUE })).toEqual({ overdue: 1 });
    expect(toApiFilters({ customer_sla: "Failed" })).toEqual({
      agreement_status: ["=", "Failed"],
    });
  });

  it("maps date presets to timespans and custom ranges to between", () => {
    expect(
      toApiFilters({ creation: "last 7 days", resolution_date: "2026-10-01,2026-10-22" })
    ).toEqual({
      creation: ["timespan", "last 7 days"],
      resolution_date: ["between", ["2026-10-01", "2026-10-22"]],
    });
  });
});

describe("fromRouteFilters", () => {
  it("shows dashboard card filters in the panel", () => {
    expect(
      fromRouteFilters({
        status: ["in", ["Open"]],
        agent_group: "Delivery Issues",
        _assign: ["LIKE", '%"a@x.com"%'],
        owner: "b@x.com",
        creation: ["between", ["2026-01-01", "2026-10-22"]],
        internal_sla_status: ["in", ["Breached"]],
      })
    ).toEqual({
      state: {
        status: "Open",
        agent_group: "Delivery Issues",
        assigned_to: "a@x.com",
        owner: "b@x.com",
        creation: "2026-01-01,2026-10-22",
        internal_sla_status: "Breached",
      },
      leftovers: {},
    });
    expect(fromRouteFilters({ creation: ["timespan", "today"] }).state).toEqual({
      creation: "today",
    });
  });

  it("keeps filters the panel cannot show", () => {
    const overdueCard = {
      status: ["in", ["Open", "Replied"]],
      resolution_by: ["<", "2026-10-22 00:00:00"],
    };
    expect(fromRouteFilters(overdueCard)).toEqual({ state: {}, leftovers: overdueCard });
  });
});
