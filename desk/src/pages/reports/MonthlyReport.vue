<template>
  <div class="flex flex-col h-full overflow-y-auto">
    <div class="flex items-center justify-between px-5 py-3 border-b">
      <h1 class="text-lg font-semibold text-gray-900">Ticket Report</h1>
      <div class="flex items-center gap-2">
        <select
          v-model="period"
          class="text-sm rounded-lg border-gray-200 py-1.5"
          @change="reload"
        >
          <option value="monthly">Monthly</option>
          <option value="weekly">Weekly</option>
        </select>
        <select
          v-if="period === 'monthly'"
          v-model.number="months"
          class="text-sm rounded-lg border-gray-200 py-1.5"
          @change="reload"
        >
          <option :value="3">Last 3 months</option>
          <option :value="6">Last 6 months</option>
          <option :value="12">Last 12 months</option>
          <option :value="24">Last 24 months</option>
        </select>
        <select
          v-else
          v-model.number="weeks"
          class="text-sm rounded-lg border-gray-200 py-1.5"
          @change="reload"
        >
          <option :value="4">Last 4 weeks</option>
          <option :value="8">Last 8 weeks</option>
          <option :value="12">Last 12 weeks</option>
          <option :value="26">Last 26 weeks</option>
          <option :value="52">Last 52 weeks</option>
        </select>
        <Button label="PDF" @click="exportReport('PDF')" />
        <Button label="Excel" @click="exportReport('Excel')" />
        <Button
          v-if="authStore.isManager"
          label="Schedule Report"
          variant="solid"
          @click="showScheduleDialog = true"
        />
      </div>
    </div>

    <div class="p-5 space-y-6">
      <div v-if="report.loading" class="text-sm text-gray-500">Loading...</div>

      <div v-else-if="!periodGroups.length" class="text-sm text-gray-500">
        No tickets found for this period.
      </div>

      <div
        v-for="group in periodGroups"
        :key="group.period"
        class="bg-white border border-gray-200 rounded-lg"
      >
        <div class="flex justify-between items-center px-4 py-3 border-b">
          <h2 class="text-base font-medium text-gray-900">
            {{ formatPeriod(group.period) }}
          </h2>
          <span class="text-sm text-gray-500">
            {{ group.total }} tickets · {{ group.resolved }} resolved ·
            {{ group.unresolved }} unresolved
          </span>
        </div>
        <div class="px-4 pb-2">
          <div
            class="grid grid-cols-5 gap-2 py-2 text-sm text-gray-500 border-b border-gray-100"
          >
            <span>Type</span>
            <span class="text-right">Incoming</span>
            <span class="text-right">Resolved</span>
            <span class="text-right">Unresolved</span>
            <span class="text-right">Resolution rate</span>
          </div>
          <div
            v-for="row in group.rows"
            :key="row.ticket_type"
            class="grid grid-cols-5 gap-2 py-2 border-b border-gray-100 last:border-b-0"
          >
            <span class="text-sm text-gray-700">{{ row.ticket_type }}</span>
            <span class="text-sm text-gray-900 font-medium text-right">
              {{ row.total }}
            </span>
            <span class="text-sm text-gray-900 font-medium text-right">
              {{ row.resolved }}
            </span>
            <span class="text-sm text-gray-900 font-medium text-right">
              {{ row.unresolved }}
            </span>
            <span class="text-sm font-medium text-right" :class="rateClass(row)">
              {{ rate(row) }}%
            </span>
          </div>
        </div>
      </div>
    </div>

    <ScheduleReportDialog v-model="showScheduleDialog" />
  </div>
</template>

<script setup lang="ts">
import { useAuthStore } from "@/stores/auth";
import { Button, createResource, usePageMeta } from "frappe-ui";
import { computed, ref } from "vue";
import ScheduleReportDialog from "./ScheduleReportDialog.vue";

interface ReportRow {
  month: string; // period key: "2026-07" or "2026-W28"
  ticket_type: string;
  total: number;
  resolved: number;
  unresolved: number;
}

const authStore = useAuthStore();
const months = ref(12);
const period = ref<"monthly" | "weekly">("monthly");
const weeks = ref(12);
const showScheduleDialog = ref(false);

function reportParams() {
  return { months: months.value, period: period.value, weeks: weeks.value };
}

const report = createResource({
  url: "helpdesk.api.dashboard.get_monthly_group_report",
  params: reportParams(),
  auto: true,
});

function reload() {
  report.update({ params: reportParams() });
  report.reload();
}

function exportReport(format: "PDF" | "Excel") {
  const params = new URLSearchParams({
    file_format: format,
    months: String(months.value),
    period: period.value,
    weeks: String(weeks.value),
  });
  window.open(
    `/api/method/helpdesk.api.dashboard.download_group_report?${params}`,
    "_blank"
  );
}

const periodGroups = computed(() => {
  // API returns rows sorted by period desc, incoming desc
  const rows: ReportRow[] = report.data || [];
  const byPeriod = new Map<string, ReportRow[]>();
  for (const row of rows) {
    if (!byPeriod.has(row.month)) byPeriod.set(row.month, []);
    byPeriod.get(row.month)!.push(row);
  }
  return [...byPeriod.entries()].map(([key, periodRows]) => ({
    period: key,
    rows: periodRows,
    total: periodRows.reduce((sum, r) => sum + Number(r.total), 0),
    resolved: periodRows.reduce((sum, r) => sum + Number(r.resolved), 0),
    unresolved: periodRows.reduce((sum, r) => sum + Number(r.unresolved), 0),
  }));
});

function rate(row: ReportRow) {
  return row.total ? Math.round((Number(row.resolved) / Number(row.total)) * 100) : 0;
}

function rateClass(row: ReportRow) {
  const r = rate(row);
  if (r >= 70) return "text-green-600";
  if (r >= 40) return "text-orange-500";
  return "text-red-500";
}

function formatPeriod(key: string) {
  if (key.includes("W")) {
    // "2026-W28" -> "Week 28, 2026 (Jul 6 – Jul 12)"
    const [year, wk] = key.split("-W").map(Number);
    // ISO week: Jan 4 is always in week 1; Monday = day 1
    const jan4 = new Date(year, 0, 4);
    const monday = new Date(jan4);
    monday.setDate(jan4.getDate() - ((jan4.getDay() + 6) % 7) + (wk - 1) * 7);
    const sunday = new Date(monday);
    sunday.setDate(monday.getDate() + 6);
    const fmt = (d: Date) =>
      d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
    return `Week ${wk}, ${year} (${fmt(monday)} – ${fmt(sunday)})`;
  }
  const [year, m] = key.split("-");
  return new Date(Number(year), Number(m) - 1).toLocaleDateString("en-US", {
    month: "long",
    year: "numeric",
  });
}

usePageMeta(() => ({ title: "Ticket Report" }));
</script>
