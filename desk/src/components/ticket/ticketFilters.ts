// Tickets list filter panel: the filters it offers and how its values map to
// helpdesk.api.ticket.get_tickets_for_card_view filters ({field: [operator, operand]}).
// No imports, so vitest can load it without the app.

export type PanelState = Record<string, string>;
export type FilterOption = { label: string; value: string; group?: string };
export type FilterDef = {
  key: string;
  label: string;
  date?: boolean;
  agentOnly?: boolean;
  options?: FilterOption[];
};

export const UNASSIGNED = "__unassigned__";
export const OVERDUE = "__overdue__";

const toOptions = (values: string[]): FilterOption[] =>
  values.map((value) => ({ label: value, value }));

const SOURCES: Record<string, Record<string, any>> = {
  messenger: { custom_messenger_conversation: ["is", "set"] },
  portal: { via_customer_portal: ["=", 1] },
  email: { email_account: ["is", "set"] },
};

export const FILTERS: FilterDef[] = [
  { key: "custom_category", label: "Category", agentOnly: true },
  { key: "custom_sub_category", label: "Sub Category", agentOnly: true },
  { key: "ticket_type", label: "Ticket Type" },
  { key: "status", label: "Status" },
  {
    key: "investigation_status",
    label: "Investigation Status",
    agentOnly: true,
    options: toOptions(["Open", "Resolved"]),
  },
  { key: "priority", label: "Priority" },
  { key: "agent_group", label: "Team", agentOnly: true },
  { key: "assigned_to", label: "Assigned To", agentOnly: true },
  { key: "owner", label: "Created By", agentOnly: true },
  {
    key: "source",
    label: "Source",
    agentOnly: true,
    options: [
      { label: "Messenger", value: "messenger" },
      { label: "Customer portal", value: "portal" },
      { label: "Email", value: "email" },
    ],
  },
  {
    key: "customer_sla",
    label: "Customer SLA",
    agentOnly: true,
    options: [
      ...toOptions(["First Response Due", "Resolution Due", "Failed", "Fulfilled", "Paused"]),
      { label: "Overdue", value: OVERDUE },
    ],
  },
  {
    key: "internal_sla_status",
    label: "Internal SLA",
    agentOnly: true,
    options: toOptions(["On Track", "At Risk", "Breached", "Met"]),
  },
  { key: "internal_sla_tier", label: "Internal SLA Tier", agentOnly: true },
  { key: "creation", label: "Created At", date: true },
  { key: "resolution_date", label: "Resolved At", date: true },
];

// Frappe "timespan" values, evaluated on the server in the site's timezone.
export const DATE_PRESETS: FilterOption[] = [
  { label: "Today", value: "today" },
  { label: "Yesterday", value: "yesterday" },
  { label: "This week", value: "this week" },
  { label: "Last 7 days", value: "last 7 days" },
  { label: "This month", value: "this month" },
  { label: "Last 30 days", value: "last 30 days" },
  { label: "Last month", value: "last month" },
  { label: "This quarter", value: "this quarter" },
  { label: "This year", value: "this year" },
];

// Filters that don't map 1:1 onto a ticket field.
const DERIVED = new Set(["assigned_to", "source", "customer_sla"]);

/** A custom date range is stored as "YYYY-MM-DD,YYYY-MM-DD"; presets are timespan names. */
export const isDateRange = (value?: string) => Boolean(value?.includes(","));

export function toApiFilters(state: PanelState): Record<string, any> {
  const filters: Record<string, any> = {};
  for (const { key, date } of FILTERS) {
    const value = state[key];
    if (!value) continue;
    if (key === "assigned_to") {
      // _assign holds a JSON list of users: unassigned rows have no quoted value at all
      filters._assign =
        value === UNASSIGNED ? ["not like", '%"%'] : ["like", `%"${value}"%`];
    } else if (key === "source") {
      Object.assign(filters, SOURCES[value]);
    } else if (key === "customer_sla") {
      if (value === OVERDUE) filters.overdue = 1;
      else filters.agreement_status = ["=", value];
    } else if (date) {
      filters[key] = isDateRange(value)
        ? ["between", value.split(",")]
        : ["timespan", value];
    } else {
      filters[key] = ["=", value];
    }
  }
  return filters;
}

/**
 * Dashboard links open the list with ?filters={field: value | [operator, operand]}.
 * Filters a panel control can show become panel state; the rest stay as they are.
 */
export function fromRouteFilters(api: Record<string, any>): {
  state: PanelState;
  leftovers: Record<string, any>;
} {
  const state: PanelState = {};
  const leftovers: Record<string, any> = {};
  for (const [field, raw] of Object.entries(api || {})) {
    const [operator, operand] = Array.isArray(raw)
      ? [String(raw[0]).toLowerCase(), raw[1]]
      : ["=", raw];
    const single =
      operator === "=" ? operand : operator === "in" && operand?.length === 1 ? operand[0] : null;
    const def = FILTERS.find((f) => f.key === field && !DERIVED.has(f.key));
    const assignee = field === "_assign" && operator === "like" && /^%"?([^"%]+)"?%$/.exec(operand);

    if (assignee) {
      state.assigned_to = assignee[1];
    } else if (def?.date && operator === "timespan") {
      state[field] = operand;
    } else if (def?.date && operator === "between" && operand?.length === 2) {
      state[field] = operand.join(",");
    } else if (def && !def.date && typeof single === "string" && single) {
      state[field] = single;
    } else {
      leftovers[field] = raw;
    }
  }
  return { state, leftovers };
}
