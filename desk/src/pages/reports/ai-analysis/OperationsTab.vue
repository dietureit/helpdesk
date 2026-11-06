<template>
  <div class="space-y-4">
    <p v-if="filters?.channel || filters?.dept" class="text-xs text-gray-500">
      {{
        __(
          "Channel and department filters don't apply here: these numbers cover the whole company."
        )
      }}
    </p>

    <div
      v-if="error"
      class="flex flex-wrap items-center gap-3 p-3 text-sm text-red-700 border border-red-200 rounded-lg bg-red-50"
    >
      <span class="flex-1 min-w-0">{{ error }}</span>
      <Button :label="__('Retry')" :loading="loading" @click="load" />
    </div>

    <template v-if="loading && !data">
      <div
        v-for="i in 3"
        :key="i"
        class="p-4 bg-white border border-gray-200 rounded-lg animate-pulse"
      >
        <div class="w-48 h-4 mb-3 bg-gray-200 rounded"></div>
        <div class="h-24 bg-gray-100 rounded"></div>
      </div>
    </template>

    <template v-else-if="data">
      <ul class="space-y-1 text-xs text-gray-500">
        <li
          v-for="caption in captions"
          :key="caption"
          class="flex items-start gap-1.5"
        >
          <LucideInfo class="w-3.5 h-3.5 mt-px shrink-0" />
          <span>{{ caption }}</span>
        </li>
      </ul>

      <section class="p-4 space-y-3 bg-white border border-gray-200 rounded-lg">
        <div>
          <h3 class="text-sm font-medium text-gray-900">
            {{ __("Cost of poor quality") }}
          </h3>
          <p class="text-xs text-gray-500">
            {{
              __(
                "Replacement deliveries at kitchen cost, by month. The selling value is shown underneath as a hint."
              )
            }}
          </p>
        </div>
        <p v-if="!months.length" class="py-6 text-sm text-center text-gray-400">
          {{ __("No delivery data in this period") }}
        </p>
        <template v-else>
          <div v-if="costChart" class="overflow-x-auto">
            <div class="h-80">
              <AxisChart :config="costChart" />
            </div>
          </div>
          <div class="overflow-x-auto border border-gray-200 rounded-lg">
            <table class="min-w-full text-sm">
              <thead>
                <tr class="text-left text-gray-500 border-b border-gray-200">
                  <th class="px-3 py-2 font-medium whitespace-nowrap">
                    {{ __("Month") }}
                  </th>
                  <th class="px-3 py-2 font-medium whitespace-nowrap">
                    {{ __("Replacements") }}
                  </th>
                  <th class="px-3 py-2 font-medium whitespace-nowrap">
                    {{ __("Kitchen cost") }}
                  </th>
                  <th class="px-3 py-2 font-medium whitespace-nowrap">
                    {{ __("Per 1,000 deliveries") }}
                  </th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="m in months"
                  :key="m.month"
                  class="border-b border-gray-100 last:border-b-0"
                >
                  <td class="px-3 py-2 text-gray-700 whitespace-nowrap">
                    {{ day(m.month, "MMM YYYY") }}
                  </td>
                  <td class="px-3 py-2 text-gray-700 whitespace-nowrap">
                    {{ num(m.replacements_n) }}
                  </td>
                  <td class="px-3 py-2 text-gray-700 whitespace-nowrap">
                    {{ formatQar(m.replacements_cost) }}
                    <div class="text-xs text-gray-400">
                      {{
                        __("selling value {0}", formatQar(m.replacements_value))
                      }}
                    </div>
                  </td>
                  <td class="px-3 py-2 text-gray-700 whitespace-nowrap">
                    {{ num(m.per_1000, 2) }}
                  </td>
                </tr>
                <tr class="font-medium bg-gray-50">
                  <td class="px-3 py-2 text-gray-900 whitespace-nowrap">
                    {{ __("Total") }}
                  </td>
                  <td class="px-3 py-2 text-gray-900 whitespace-nowrap">
                    {{ num(totals.replacements_n) }}
                  </td>
                  <td class="px-3 py-2 text-gray-900 whitespace-nowrap">
                    {{ formatQar(totals.replacements_cost) }}
                    <div class="text-xs font-normal text-gray-400">
                      {{
                        __(
                          "selling value {0}",
                          formatQar(totals.replacements_value)
                        )
                      }}
                    </div>
                  </td>
                  <td class="px-3 py-2"></td>
                </tr>
              </tbody>
            </table>
          </div>
        </template>
      </section>

      <section class="p-4 space-y-3 bg-white border border-gray-200 rounded-lg">
        <div>
          <h3 class="text-sm font-medium text-gray-900">
            {{ __("Refunds (all reasons)") }}
          </h3>
          <p class="text-xs text-gray-500">
            {{
              __(
                "Refunds record no reason, so they are listed on their own and never added to the cost of poor quality."
              )
            }}
          </p>
        </div>
        <p v-if="!months.length" class="py-6 text-sm text-center text-gray-400">
          {{ __("No refund data in this period") }}
        </p>
        <div v-else class="overflow-x-auto border border-gray-200 rounded-lg">
          <table class="min-w-full text-sm">
            <thead>
              <tr class="text-left text-gray-500 border-b border-gray-200">
                <th class="px-3 py-2 font-medium whitespace-nowrap">
                  {{ __("Month") }}
                </th>
                <th class="px-3 py-2 font-medium whitespace-nowrap">
                  {{ __("Refunds") }}
                </th>
                <th class="px-3 py-2 font-medium whitespace-nowrap">
                  {{ __("Amount") }}
                </th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="m in months"
                :key="m.month"
                class="border-b border-gray-100 last:border-b-0"
              >
                <td class="px-3 py-2 text-gray-700 whitespace-nowrap">
                  {{ day(m.month, "MMM YYYY") }}
                </td>
                <td class="px-3 py-2 text-gray-700 whitespace-nowrap">
                  {{ num(m.refunds_n) }}
                </td>
                <td class="px-3 py-2 text-gray-700 whitespace-nowrap">
                  {{ formatQar(m.refunds_qar) }}
                </td>
              </tr>
              <tr class="font-medium bg-gray-50">
                <td class="px-3 py-2 text-gray-900 whitespace-nowrap">
                  {{ __("Total") }}
                </td>
                <td class="px-3 py-2 text-gray-900 whitespace-nowrap">
                  {{ num(totals.refunds_n) }}
                </td>
                <td class="px-3 py-2 text-gray-900 whitespace-nowrap">
                  {{ formatQar(totals.refunds_qar) }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section class="p-4 space-y-3 bg-white border border-gray-200 rounded-lg">
        <div>
          <h3 class="text-sm font-medium text-gray-900">
            {{ __("Contact load per 1,000 deliveries") }}
          </h3>
          <p class="text-xs text-gray-500">
            {{
              __(
                "Chat sessions, ticket contacts and answered calls per Sunday–Saturday week, against normal deliveries. “—” means that source has no data for the week."
              )
            }}
          </p>
        </div>
        <p v-if="!weeks.length" class="py-6 text-sm text-center text-gray-400">
          {{ __("No contact data in this period") }}
        </p>
        <div v-else class="overflow-x-auto border border-gray-200 rounded-lg">
          <table class="min-w-full text-sm">
            <thead>
              <tr class="text-left text-gray-500 border-b border-gray-200">
                <th class="px-3 py-2 font-medium whitespace-nowrap">
                  {{ __("Week starting") }}
                </th>
                <th class="px-3 py-2 font-medium whitespace-nowrap">
                  {{ __("Chat sessions") }}
                </th>
                <th class="px-3 py-2 font-medium whitespace-nowrap">
                  {{ __("Ticket contacts") }}
                </th>
                <th class="px-3 py-2 font-medium whitespace-nowrap">
                  {{ __("Answered calls") }}
                </th>
                <th class="px-3 py-2 font-medium whitespace-nowrap">
                  {{ __("Deliveries") }}
                </th>
                <th class="px-3 py-2 font-medium whitespace-nowrap">
                  {{ __("Per 1,000 deliveries") }}
                </th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="w in weeks"
                :key="w.week"
                class="border-b border-gray-100 last:border-b-0"
              >
                <td class="px-3 py-2 text-gray-700 whitespace-nowrap">
                  {{ day(w.week, "D MMM YYYY") }}
                </td>
                <td class="px-3 py-2 text-gray-700 whitespace-nowrap">
                  {{ num(w.chat_sessions) }}
                </td>
                <td class="px-3 py-2 text-gray-700 whitespace-nowrap">
                  {{ num(w.ticket_contacts) }}
                </td>
                <td class="px-3 py-2 text-gray-700 whitespace-nowrap">
                  {{ num(w.answered_calls) }}
                </td>
                <td class="px-3 py-2 text-gray-700 whitespace-nowrap">
                  {{ num(w.deliveries) }}
                </td>
                <td
                  class="px-3 py-2 font-medium text-gray-900 whitespace-nowrap"
                >
                  {{ num(w.per_1000, 2) }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section class="space-y-2">
        <h3 class="text-sm font-medium text-gray-900">
          {{ __("Repeat callers") }}
        </h3>
        <div class="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <div
            v-for="tile in callerTiles"
            :key="tile.label"
            class="p-4 bg-white border border-gray-200 rounded-lg"
          >
            <span class="text-sm font-medium text-gray-500">{{
              tile.label
            }}</span>
            <div
              class="mt-1 text-2xl font-semibold"
              :style="{ color: tile.color }"
            >
              {{ tile.value }}
            </div>
            <span class="text-xs text-gray-400">{{ tile.hint }}</span>
          </div>
        </div>
      </section>
    </template>
  </div>
</template>

<script setup lang="ts">
import { dayjs } from "@/dayjs";
import { __ } from "@/translation";
import { AxisChart, Button, call } from "frappe-ui";
import { computed, ref, watch } from "vue";
import LucideInfo from "~icons/lucide/info";
import { formatQar } from "./aiAnalysis";

const props = defineProps<{
  filters?: Record<string, any>;
  status?: Record<string, any> | null;
  canDecide?: boolean;
}>();
defineEmits<{
  (e: "open-issue", code: string): void;
  (e: "jump", window: { from_date: string; to_date: string }): void;
  (e: "refresh-status"): void;
}>();

// the server sends this caption too; the tab adds it only if the payload lacks it
const CALLS_CAPTION =
  "Answered (recorded) calls only — missed calls are not logged.";

const data = ref<Record<string, any> | null>(null);
const loading = ref(false);
const error = ref("");
let seq = 0; // drops a stale reply when the period changes mid-request

async function load() {
  const mine = ++seq;
  loading.value = true;
  error.value = "";
  try {
    const res = await call("helpdesk.api.ai_analysis.get_operations", {
      from_date: props.filters?.from_date || null,
      to_date: props.filters?.to_date || null,
    });
    if (mine === seq) data.value = res || {};
  } catch (e: any) {
    if (mine === seq)
      error.value = e?.messages?.length
        ? e.messages.join(" ")
        : __("Could not load the operations numbers.");
  } finally {
    if (mine === seq) loading.value = false;
  }
}

// one source per date: a new `filters` object (channel/dept change, a parent re-render) doesn't refetch
watch([() => props.filters?.from_date, () => props.filters?.to_date], load, {
  immediate: true,
});

const months = computed<Record<string, any>[]>(
  () => data.value?.copq?.months || []
);
const weeks = computed<Record<string, any>[]>(
  () => data.value?.contact_load?.weeks || []
);

const captions = computed<string[]>(() => {
  const list: string[] = (data.value?.captions || []).filter(Boolean);
  const calls = __(
    "Answered (recorded) calls only — missed calls are not logged."
  );
  return list.some((c) => c === CALLS_CAPTION || c === calls)
    ? list
    : [calls, ...list];
});

function sum(key: string) {
  const values = months.value
    .map((m) => m[key])
    .filter((v) => v !== null && v !== undefined);
  return values.length ? values.reduce((a, b) => a + Number(b), 0) : null;
}

const totals = computed(() => ({
  replacements_n: sum("replacements_n"),
  replacements_cost: sum("replacements_cost"),
  replacements_value: sum("replacements_value"),
  refunds_n: sum("refunds_n"),
  refunds_qar: sum("refunds_qar"),
}));

const costSeries = __("Kitchen cost");
const costChart = computed(() => {
  if (!months.value.some((m) => m.replacements_cost)) return null;
  return {
    title: "",
    data: months.value.map((m) => ({
      month: day(m.month, "MMM YYYY"),
      [costSeries]: m.replacements_cost ?? null,
    })),
    xAxis: { key: "month", type: "category" as const },
    yAxis: { title: __("QAR") },
    series: [{ name: costSeries, type: "bar" as const, color: "#ED8936" }],
    echartOptions: { animation: false },
  };
});

const callerTiles = computed(() => {
  const rc = data.value?.repeat_callers || {};
  // The share comes from the two counts; `share` (a 0-1 fraction, like every share in these payloads)
  // is used only when a count is missing.
  const share =
    rc.callers && rc.repeat_callers != null
      ? rc.repeat_callers / rc.callers
      : typeof rc.share === "number"
      ? rc.share
      : null;
  return [
    {
      label: __("Callers"),
      value: num(rc.callers),
      color: "#318AD8",
      hint: __("distinct numbers with an answered call"),
    },
    {
      label: __("Repeat callers"),
      value: num(rc.repeat_callers),
      color: "#ED8936",
      hint: __("called more than once"),
    },
    {
      label: __("Share of callers"),
      value: share === null ? "—" : `${Math.round(share * 100)}%`,
      color: "#ED8936",
      hint: __("repeat callers ÷ callers"),
    },
  ];
});

function num(value: unknown, digits = 0) {
  if (value === null || value === undefined || value === "") return "—";
  const n = Number(value);
  if (!Number.isFinite(n)) return String(value);
  return n.toLocaleString("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function day(value: string | null | undefined, format: string) {
  if (!value) return "—";
  const d = dayjs(value);
  return d.isValid() ? d.format(format) : value;
}
</script>
