<template>
  <div class="flex flex-col h-full overflow-y-auto">
    <div class="flex flex-wrap items-center justify-between gap-2 px-5 py-3 border-b">
      <div>
        <h1 class="text-lg font-semibold text-gray-900">Customer Complaints</h1>
        <p class="text-xs text-gray-500">
          Complaint tickets by department (ticket type), with investigation status from comments
        </p>
      </div>
      <div class="flex flex-wrap items-center gap-2">
        <Dropdown :options="periodOptions">
          <Button>
            <template #prefix><LucideCalendar class="w-4 h-4" /></template>
            {{ periodLabel }}
            <template #suffix><LucideChevronDown class="w-4 h-4" /></template>
          </Button>
        </Dropdown>
        <DateRangePicker
          v-if="showDatePicker"
          ref="datePickerRef"
          class="w-0 overflow-hidden"
          v-model="period"
          :formatter="formatRangeLabel"
          @update:model-value="onCustomRange"
        />
        <select v-model="ticketType" :class="selectClass" aria-label="Ticket Type">
          <option value="">All ticket types</option>
          <option v-for="t in ticketTypes.data || []" :key="t.name" :value="t.name">
            {{ t.name }}
          </option>
        </select>
        <select v-model="team" :class="selectClass" aria-label="Team">
          <option value="">All teams</option>
          <option v-for="t in teams.data || []" :key="t.name" :value="t.name">
            {{ t.team_name || t.name }}
          </option>
        </select>
        <Button label="Excel" :disabled="!summary.total" @click="exportFile('Excel')" />
        <Button label="PDF" :disabled="!summary.total" @click="exportFile('PDF')" />
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

      <div class="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <div class="p-4 bg-white border border-gray-200 rounded-lg">
          <h3 class="mb-2 text-sm font-medium text-gray-900">By department</h3>
          <div v-if="report.loading && !report.data" class="text-sm text-gray-500">Loading…</div>
          <div
            v-else-if="!donutConfig"
            class="flex flex-col items-center justify-center py-10 text-gray-400"
          >
            <LucidePieChart class="w-8 h-8 mb-2" />
            <span class="text-sm">No complaints in this range</span>
          </div>
          <div v-else class="h-64">
            <DonutChart :config="donutConfig" class="h-full w-full" />
          </div>
        </div>
        <div class="p-4 bg-white border border-gray-200 rounded-lg">
          <h3 class="mb-2 text-sm font-medium text-gray-900">Resolved vs open</h3>
          <div v-if="report.loading && !report.data" class="text-sm text-gray-500">Loading…</div>
          <div
            v-else-if="!axisConfig"
            class="flex flex-col items-center justify-center py-10 text-gray-400"
          >
            <LucideBarChart2 class="w-8 h-8 mb-2" />
            <span class="text-sm">No complaints in this range</span>
          </div>
          <div v-else class="h-64">
            <AxisChart :config="axisConfig" />
          </div>
        </div>
      </div>

      <div class="overflow-x-auto bg-white border border-gray-200 rounded-lg">
        <table class="min-w-full text-sm">
          <thead>
            <tr class="text-left text-gray-500 border-b border-gray-200">
              <th
                v-for="col in summaryColumns"
                :key="col.key"
                class="px-3 py-2 font-medium whitespace-nowrap"
              >
                {{ col.label }}
              </th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="row in byType"
              :key="row.ticket_type"
              class="border-b border-gray-100 last:border-b-0"
            >
              <td
                v-for="col in summaryColumns"
                :key="col.key"
                class="px-3 py-2 whitespace-nowrap text-gray-700"
              >
                {{ row[col.key] }}
              </td>
            </tr>
            <tr v-if="totals" class="bg-gray-50 font-medium">
              <td
                v-for="col in summaryColumns"
                :key="col.key"
                class="px-3 py-2 whitespace-nowrap text-gray-900"
              >
                {{ totals[col.key] }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div v-for="section in detailSections" :key="section.type" class="space-y-2">
        <h2 class="text-base font-semibold text-gray-900">
          {{ section.type }}
          <span class="text-sm font-normal text-gray-500">({{ section.rows.length }})</span>
        </h2>
        <div class="overflow-x-auto bg-white border border-gray-200 rounded-lg">
          <table class="min-w-full text-sm">
            <thead>
              <tr class="text-left text-gray-500 border-b border-gray-200">
                <th
                  v-for="col in detailColumns"
                  :key="col.key"
                  class="px-3 py-2 font-medium whitespace-nowrap"
                >
                  {{ col.label }}
                </th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="row in section.rows"
                :key="row.name"
                class="border-b border-gray-100 last:border-b-0 align-top hover:bg-gray-50"
              >
                <td
                  v-for="col in detailColumns"
                  :key="col.key"
                  class="px-3 py-2 text-gray-700"
                  :class="detailCellClass(col.key, row)"
                >
                  <RouterLink
                    v-if="col.key === 'name'"
                    :to="{ name: 'TicketAgent', params: { ticketId: row.name } }"
                    class="font-medium text-gray-900 hover:underline whitespace-nowrap"
                  >
                    #{{ row.name }}
                  </RouterLink>
                  <span
                    v-else-if="col.key === 'complaint' || col.key === 'department_reason' || col.key === 'resolution_by_cs'"
                    class="block max-w-xs whitespace-normal"
                    :title="row[col.key]"
                  >
                    {{ row[col.key] || "—" }}
                  </span>
                  <span v-else class="whitespace-nowrap">{{ cellText(col.key, row) }}</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { dayjs } from "@/dayjs";
import {
  AxisChart,
  Button,
  DateRangePicker,
  DonutChart,
  Dropdown,
  createResource,
  usePageMeta,
} from "frappe-ui";
import { computed, nextTick, ref, watch } from "vue";
import { RouterLink, useRoute, useRouter } from "vue-router";
import LucideBarChart2 from "~icons/lucide/bar-chart-2";
import LucideCalendar from "~icons/lucide/calendar";
import LucideChevronDown from "~icons/lucide/chevron-down";
import LucidePieChart from "~icons/lucide/pie-chart";

const selectClass = "text-sm rounded-lg border-gray-200 py-1.5";
const route = useRoute();
const router = useRouter();

function getLastXDays(days: number) {
  const to = dayjs();
  const from = to.subtract(days - 1, "day");
  return `${from.format("YYYY-MM-DD")},${to.format("YYYY-MM-DD")}`;
}

function fromUrl(key: string) {
  return typeof route.query[key] === "string" ? (route.query[key] as string) : "";
}

const defaultPeriod = fromUrl("from_date") && fromUrl("to_date")
  ? `${fromUrl("from_date")},${fromUrl("to_date")}`
  : getLastXDays(30);

const period = ref(defaultPeriod);
const ticketType = ref(fromUrl("ticket_type"));
const team = ref(fromUrl("team"));
const periodLabel = ref("Last 30 Days");
const showDatePicker = ref(false);
const datePickerRef = ref<{ open?: () => void } | null>(null);

function apiFilters() {
  const [from_date, to_date] = (period.value || "").split(",");
  return {
    from_date: from_date || null,
    to_date: to_date || null,
    ticket_type: ticketType.value || null,
    team: team.value || null,
  };
}

const report = createResource({
  url: "helpdesk.api.complaints.get_complaints_report",
  params: { filters: apiFilters() },
  auto: true,
});

const teams = createResource({
  url: "frappe.client.get_list",
  params: { doctype: "HD Team", fields: ["name", "team_name"], limit: 100 },
  auto: true,
});

const ticketTypes = createResource({
  url: "frappe.client.get_list",
  params: {
    doctype: "HD Ticket Type",
    fields: ["name"],
    order_by: "name asc",
    limit: 200,
  },
  auto: true,
});

watch(
  [period, ticketType, team],
  () => {
    report.update({ params: { filters: apiFilters() } });
    report.reload();
    const [from_date, to_date] = (period.value || "").split(",");
    router.replace({
      query: {
        from_date: from_date || undefined,
        to_date: to_date || undefined,
        ticket_type: ticketType.value || undefined,
        team: team.value || undefined,
      },
    });
  }
);

const EMPTY_SUMMARY = {
  total: 0,
  resolved: 0,
  open: 0,
  investigation_submitted: 0,
  investigation_pending: 0,
  prior_total: 0,
};

const summary = computed(() => report.data?.summary || EMPTY_SUMMARY);
const byType = computed(() => report.data?.by_type || []);
const totals = computed(() => report.data?.totals || null);
const summaryColumns = computed(
  () =>
    report.data?.columns?.summary || [
      { key: "ticket_type", label: "Department" },
      { key: "raised", label: "Complaints raised" },
      { key: "prior_raised", label: "Same period prior" },
      { key: "resolved", label: "Resolved" },
      { key: "open", label: "Open" },
      { key: "investigation_submitted", label: "Investigation submitted" },
      { key: "investigation_pending", label: "Investigation pending" },
    ]
);
const detailColumns = computed(
  () =>
    report.data?.columns?.detail || [
      { key: "date", label: "Date" },
      { key: "name", label: "Ticket" },
      { key: "status", label: "Status" },
      { key: "investigation_status", label: "Investigation Status" },
      { key: "contact_number", label: "Contact number" },
      { key: "customer_name", label: "Customer name" },
      { key: "complaint", label: "Complaint" },
      { key: "item_affected", label: "Item affected" },
      { key: "resolution_by_cs", label: "Resolution by CS" },
      { key: "department_reason", label: "Reason given by department" },
      { key: "investigation", label: "Investigation" },
    ]
);

const detailSections = computed(() => {
  const map = report.data?.rows_by_type || {};
  return Object.keys(map)
    .sort((a, b) => a.localeCompare(b))
    .map((type) => ({ type, rows: map[type] || [] }))
    .filter((s) => s.rows.length);
});

const tiles = computed(() => [
  {
    label: "Raised",
    value: summary.value.total,
    color: "#318AD8",
    hint: `prior period ${summary.value.prior_total}`,
  },
  {
    label: "Resolved",
    value: summary.value.resolved,
    color: "#48BB78",
    hint: "status category Resolved",
  },
  {
    label: "Open",
    value: summary.value.open,
    color: "#ED8936",
    hint: "not yet resolved",
  },
  {
    label: "Investigation in",
    value: summary.value.investigation_submitted,
    color: "#48BB78",
    hint: "department comment present",
  },
  {
    label: "Investigation pending",
    value: summary.value.investigation_pending,
    color: "#F56565",
    hint: "no department comment yet",
  },
]);

const DONUT_COLORS = [
  "#318AD8",
  "#48BB78",
  "#ED8936",
  "#F56565",
  "#9F7AEA",
  "#38B2AC",
  "#D69E2E",
  "#718096",
];

const donutConfig = computed(() => {
  const data = report.data?.charts?.donut || [];
  if (!data.length) return null;
  const colored = data.map((d: { label: string; value: number }, i: number) => ({
    ...d,
    color: DONUT_COLORS[i % DONUT_COLORS.length],
  }));
  return {
    title: "",
    subtitle: "",
    data: colored,
    categoryColumn: "label",
    valueColumn: "value",
    colors: colored.map((d) => d.color),
    showInlineLabels: false,
  };
});

const axisConfig = computed(() => {
  const data = report.data?.charts?.axis || [];
  if (!data.length) return null;
  return {
    data,
    xAxis: { key: "type", type: "category", title: "Department" },
    yAxis: { title: "Tickets" },
    series: [
      { name: "Resolved", type: "bar", color: "#48BB78" },
      { name: "Open", type: "bar", color: "#ED8936" },
    ],
    colors: ["#48BB78", "#ED8936"],
  };
});

function cellText(key: string, row: Record<string, any>) {
  const value = row[key];
  if (value === null || value === undefined || value === "") return "—";
  if (key === "date") return dayjs(value).format("D MMM YYYY");
  return value;
}

function detailCellClass(key: string, row: Record<string, any>) {
  if (key === "investigation") {
    return row[key] === "Pending" ? "font-medium text-orange-600" : "font-medium text-green-700";
  }
  if (key === "investigation_status") {
    if (row[key] === "Resolved") return "font-medium text-green-700";
    if (row[key] === "Open") return "font-medium text-orange-600";
  }
  if (key === "status") {
    return "font-medium text-gray-800";
  }
  return "";
}

function setPreset(label: string, days: number) {
  periodLabel.value = label;
  showDatePicker.value = false;
  period.value = getLastXDays(days);
}

function openCustomRange() {
  periodLabel.value = "Custom Range";
  showDatePicker.value = true;
  nextTick(() => datePickerRef.value?.open?.());
}

function formatRangeLabel(range: string) {
  if (!range) return periodLabel.value;
  const [from, to] = range.split(",");
  return `${dayjs(from).format("D MMM YYYY")} – ${dayjs(to).format("D MMM YYYY")}`;
}

function onCustomRange(value: string) {
  if (!value) return;
  period.value = value;
  periodLabel.value = formatRangeLabel(value);
  showDatePicker.value = false;
}

const periodOptions = computed(() => [
  {
    group: "Presets",
    hideLabel: true,
    items: [
      { label: "Last 7 Days", onClick: () => setPreset("Last 7 Days", 7) },
      { label: "Last 30 Days", onClick: () => setPreset("Last 30 Days", 30) },
      { label: "Last 60 Days", onClick: () => setPreset("Last 60 Days", 60) },
      { label: "Last 90 Days", onClick: () => setPreset("Last 90 Days", 90) },
    ],
  },
  {
    label: "Custom Range",
    onClick: openCustomRange,
  },
]);

function exportFile(file_format: "Excel" | "PDF") {
  const filters = encodeURIComponent(JSON.stringify(apiFilters()));
  window.open(
    `/api/method/helpdesk.api.complaints.download_complaints_report?filters=${filters}&file_format=${file_format}`,
    "_blank"
  );
}

usePageMeta(() => ({ title: "Customer Complaints" }));
</script>
