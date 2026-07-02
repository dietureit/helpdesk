<template>
  <div class="flex flex-col h-full overflow-y-auto">
    <div class="flex items-center justify-between px-5 py-3 border-b">
      <h1 class="text-lg font-semibold text-gray-900">Monthly Ticket Report</h1>
      <select
        v-model.number="months"
        class="text-sm rounded-lg border-gray-200 py-1.5"
        @change="reload"
      >
        <option :value="3">Last 3 months</option>
        <option :value="6">Last 6 months</option>
        <option :value="12">Last 12 months</option>
        <option :value="24">Last 24 months</option>
      </select>
    </div>

    <div class="p-5 space-y-6">
      <div v-if="report.loading" class="text-sm text-gray-500">Loading...</div>

      <div v-else-if="!monthGroups.length" class="text-sm text-gray-500">
        No tickets found for this period.
      </div>

      <div
        v-for="monthGroup in monthGroups"
        :key="monthGroup.month"
        class="bg-white border border-gray-200 rounded-lg"
      >
        <div class="flex justify-between items-center px-4 py-3 border-b">
          <h2 class="text-base font-medium text-gray-900">
            {{ formatMonth(monthGroup.month) }}
          </h2>
          <span class="text-sm text-gray-500">
            {{ monthGroup.total }} tickets · {{ monthGroup.resolved }} resolved ·
            {{ monthGroup.unresolved }} unresolved
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
            v-for="row in monthGroup.rows"
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
  </div>
</template>

<script setup lang="ts">
import { createResource, usePageMeta } from "frappe-ui";
import { computed, ref } from "vue";

interface ReportRow {
  month: string;
  ticket_type: string;
  total: number;
  resolved: number;
  unresolved: number;
}

const months = ref(12);

const report = createResource({
  url: "helpdesk.api.dashboard.get_monthly_group_report",
  params: { months: months.value },
  auto: true,
});

function reload() {
  report.update({ params: { months: months.value } });
  report.reload();
}

const monthGroups = computed(() => {
  // API returns rows sorted by month desc, incoming desc
  const rows: ReportRow[] = report.data || [];
  const byMonth = new Map<string, ReportRow[]>();
  for (const row of rows) {
    if (!byMonth.has(row.month)) byMonth.set(row.month, []);
    byMonth.get(row.month)!.push(row);
  }
  return [...byMonth.entries()].map(([month, monthRows]) => ({
    month,
    rows: monthRows,
    total: monthRows.reduce((sum, r) => sum + Number(r.total), 0),
    resolved: monthRows.reduce((sum, r) => sum + Number(r.resolved), 0),
    unresolved: monthRows.reduce((sum, r) => sum + Number(r.unresolved), 0),
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

function formatMonth(month: string) {
  const [year, m] = month.split("-");
  return new Date(Number(year), Number(m) - 1).toLocaleDateString("en-US", {
    month: "long",
    year: "numeric",
  });
}

usePageMeta(() => ({ title: "Monthly Report" }));
</script>
