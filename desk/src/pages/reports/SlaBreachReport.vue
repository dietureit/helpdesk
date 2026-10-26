<template>
  <div class="flex flex-col h-full overflow-y-auto">
    <div class="flex flex-wrap items-center justify-between gap-2 px-5 py-3 border-b">
      <div>
        <h1 class="text-lg font-semibold text-gray-900">SLA Breach Report</h1>
        <p class="text-xs text-gray-500">
          Tickets whose department investigation missed its internal SLA, one row per ticket
        </p>
      </div>
      <div class="flex flex-wrap items-center gap-2">
        <select v-model="state.period" :class="selectClass" aria-label="Period">
          <option v-for="period in PERIODS" :key="period.value" :value="period.value">
            {{ period.label }}
          </option>
        </select>
        <select v-model="state.team" :class="selectClass" aria-label="Team">
          <option value="">All teams</option>
          <option v-for="team in teams.data || []" :key="team.name" :value="team.name">
            {{ team.team_name || team.name }}
          </option>
        </select>
        <select v-model="state.tier" :class="selectClass" aria-label="Tier">
          <option value="">All tiers</option>
          <option v-for="tier in options.data?.tiers || []" :key="tier" :value="tier">
            {{ tier }}
          </option>
        </select>
        <select v-model="state.agent" :class="selectClass" aria-label="Agent">
          <option value="">All agents</option>
          <option v-for="agent in agents.data || []" :key="agent.name" :value="agent.name">
            {{ agent.agent_name || agent.name }}
          </option>
        </select>
        <label class="flex items-center gap-1.5 text-sm text-gray-700">
          <input v-model="state.at_risk" type="checkbox" class="rounded border-gray-300" />
          Include at risk
        </label>
        <Button label="Excel" :disabled="!summary.total" @click="exportExcel" />
      </div>
    </div>

    <div class="p-5 space-y-4">
      <div class="grid grid-cols-2 gap-4 md:grid-cols-5">
        <div
          v-for="tile in tiles"
          :key="tile.label"
          class="p-4 bg-white border border-gray-200 rounded-lg"
        >
          <span class="text-sm font-medium text-gray-500">{{ tile.label }}</span>
          <div class="mt-1 text-2xl font-semibold" :style="{ color: tile.color }">
            {{ tile.value }}
          </div>
          <span class="text-xs text-gray-400">{{ tile.hint }}</span>
        </div>
      </div>

      <div v-if="report.loading && !report.data" class="text-sm text-gray-500">Loading...</div>
      <div
        v-else-if="!rows.length"
        class="flex flex-col items-center justify-center py-10 text-gray-400 bg-white border border-gray-200 rounded-lg"
      >
        <LucideCheckCircle class="w-8 h-8 mb-2" />
        <span class="text-sm">No internal SLA breaches for these filters</span>
      </div>
      <div v-else class="overflow-x-auto bg-white border border-gray-200 rounded-lg">
        <table class="min-w-full text-sm">
          <thead>
            <tr class="text-left text-gray-500 border-b border-gray-200">
              <th
                v-for="column in columns"
                :key="column.key"
                class="px-3 py-2 font-medium whitespace-nowrap"
              >
                {{ column.label }}
              </th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="row in rows"
              :key="row.name"
              class="border-b border-gray-100 last:border-b-0 hover:bg-gray-50"
            >
              <td
                v-for="column in columns"
                :key="column.key"
                class="px-3 py-2 whitespace-nowrap"
                :class="cellClass(column.key, row)"
              >
                <RouterLink
                  v-if="column.key === 'name'"
                  :to="{ name: 'TicketAgent', params: { ticketId: row.name } }"
                  class="font-medium text-gray-900 hover:underline"
                >
                  #{{ row.name }}
                </RouterLink>
                <span
                  v-else-if="column.key === 'subject'"
                  class="block max-w-xs truncate"
                  :title="row.subject"
                >
                  {{ row.subject }}
                </span>
                <span v-else>{{ cellText(column.key, row) }}</span>
              </td>
            </tr>
          </tbody>
        </table>
        <div
          v-if="summary.total > rows.length"
          class="px-3 py-2 text-xs text-gray-500 border-t border-gray-200"
        >
          Showing the first {{ rows.length }} of {{ summary.total }} tickets. The Excel export
          has all of them.
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { dayjs } from "@/dayjs";
import { Button, createResource, usePageMeta } from "frappe-ui";
import { computed, reactive, watch } from "vue";
import { RouterLink, useRoute, useRouter } from "vue-router";
import LucideCheckCircle from "~icons/lucide/check-circle";

// Frappe "timespan" values on the ticket's creation (the start of the SLA clock)
const PERIODS = [
  { label: "Today", value: "today" },
  { label: "This week", value: "this week" },
  { label: "This month", value: "this month" },
  { label: "Last month", value: "last month" },
  { label: "Last 30 days", value: "last 30 days" },
  { label: "Last 90 days", value: "last 90 days" },
  { label: "This year", value: "this year" },
  { label: "All time", value: "all" },
];
const DATE_COLUMNS = new Set(["creation", "internal_sla_due_by", "investigation_resolved_on"]);
const selectClass = "text-sm rounded-lg border-gray-200 py-1.5";

const route = useRoute();
const router = useRouter();

// the filters live in the URL, so the report can be shared and survives a refresh
const fromUrl = (key: string) =>
  typeof route.query[key] === "string" ? (route.query[key] as string) : "";
const state = reactive({
  period: PERIODS.some((p) => p.value === fromUrl("period")) ? fromUrl("period") : "last 30 days",
  team: fromUrl("team"),
  tier: fromUrl("tier"),
  agent: fromUrl("agent"),
  at_risk: fromUrl("at_risk") === "1",
});

function apiFilters() {
  // same shape as the ticket list (helpdesk.api.ticket.build_card_filters)
  const filters: Record<string, any> = {};
  if (state.period !== "all") filters.creation = ["timespan", state.period];
  if (state.team) filters.agent_group = ["=", state.team];
  if (state.tier) filters.internal_sla_tier = ["=", state.tier];
  if (state.agent) filters._assign = ["like", `%"${state.agent}"%`];
  if (state.at_risk) filters.include_at_risk = 1;
  return filters;
}

const report = createResource({
  url: "helpdesk.api.internal_sla.get_breach_report",
  params: { filters: apiFilters() },
  auto: true,
});
const options = createResource({
  url: "helpdesk.api.internal_sla.get_options",
  cache: "InternalSlaOptions",
  auto: true,
});
const teams = createResource({
  url: "frappe.client.get_list",
  params: { doctype: "HD Team", fields: ["name", "team_name"], limit: 100 },
  auto: true,
});
const agents = createResource({
  url: "frappe.client.get_list",
  params: {
    doctype: "HD Agent",
    fields: ["name", "agent_name"],
    filters: { is_active: 1 },
    limit: 100,
  },
  auto: true,
});

watch(state, () => {
  report.update({ params: { filters: apiFilters() } });
  report.reload();
  router.replace({
    query: {
      period: state.period,
      team: state.team || undefined,
      tier: state.tier || undefined,
      agent: state.agent || undefined,
      at_risk: state.at_risk ? "1" : undefined,
    },
  });
});

const EMPTY_SUMMARY = {
  total: 0,
  tracked: 0,
  breached: 0,
  breached_open: 0,
  breached_resolved: 0,
  at_risk: 0,
  met: 0,
  breach_percent: 0,
};
const rows = computed<Record<string, any>[]>(() => report.data?.rows || []);
const columns = computed<{ key: string; label: string }[]>(() => report.data?.columns || []);
const summary = computed(() => report.data?.summary || EMPTY_SUMMARY);

const tiles = computed(() => [
  {
    label: "Breached",
    value: summary.value.breached,
    color: "#F56565",
    hint: `${summary.value.breach_percent}% of ${summary.value.tracked} tracked`,
  },
  {
    label: "Still open",
    value: summary.value.breached_open,
    color: "#F56565",
    hint: "breached, investigation not resolved",
  },
  {
    label: "Resolved late",
    value: summary.value.breached_resolved,
    color: "#ED8936",
    hint: "breached, then resolved",
  },
  {
    label: "At risk",
    value: summary.value.at_risk,
    color: "#F6AD55",
    hint: "open, past the warning point",
  },
  {
    label: "Met",
    value: summary.value.met,
    color: "#48BB78",
    hint: "resolved within the tier",
  },
]);

function cellText(key: string, row: Record<string, any>) {
  const value = row[key];
  if (!value) return "—";
  return DATE_COLUMNS.has(key) ? dayjs.tz(value).format("D MMM YYYY, h:mm A") : value;
}

function cellClass(key: string, row: Record<string, any>) {
  if (key === "internal_sla_status") {
    return row[key] === "Breached" ? "font-medium text-red-600" : "font-medium text-orange-600";
  }
  if (key === "overdue_by" && row[key]) return "text-red-600";
  return "text-gray-700";
}

function exportExcel() {
  const filters = encodeURIComponent(JSON.stringify(apiFilters()));
  window.open(
    `/api/method/helpdesk.api.internal_sla.download_breach_report?filters=${filters}`,
    "_blank"
  );
}

usePageMeta(() => ({ title: "SLA Breach Report" }));
</script>
