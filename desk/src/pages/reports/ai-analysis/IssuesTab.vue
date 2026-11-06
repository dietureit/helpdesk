<template>
  <div class="space-y-4">
    <div class="flex flex-wrap items-center justify-between gap-2">
      <!-- the kind buttons don't wrap: on a phone they scroll, not the page (w-max stops them shrinking) -->
      <div class="max-w-full overflow-x-auto">
        <div class="w-max">
          <TabButtons :buttons="kindButtons" :model-value="kind" @update:model-value="setKind" />
        </div>
      </div>
      <div class="flex flex-wrap items-center gap-2">
        <label class="flex items-center gap-1.5 text-sm text-gray-600">
          {{ __("Sort") }}
          <select v-model="sortKey" :class="selectClass" :aria-label="__('Sort issues')">
            <option v-for="o in SORTS" :key="o.value" :value="o.value">{{ __(o.label) }}</option>
          </select>
        </label>
        <Tooltip :text="__(PRIORITY_FORMULA)">
          <span class="text-gray-400" tabindex="0" :aria-label="__(PRIORITY_FORMULA)">
            <LucideInfo class="w-4 h-4" />
          </span>
        </Tooltip>
        <Popover placement="bottom-end">
          <template #target="{ togglePopover }">
            <Button :label="__('How we count')" @click="togglePopover" />
          </template>
          <template #body-main>
            <ul
              class="w-80 max-w-[calc(100vw-2rem)] py-3 pr-3 space-y-1.5 text-sm list-disc pl-7 text-gray-700"
            >
              <li v-for="line in data?.how_we_count || []" :key="line">{{ line }}</li>
              <li>{{ __(MULTI_ISSUE_NOTE) }}</li>
            </ul>
          </template>
        </Popover>
      </div>
    </div>

    <div
      v-if="error"
      class="flex flex-wrap items-center justify-between gap-2 p-3 text-sm text-red-700 border border-red-200 rounded-lg bg-red-50"
    >
      <span>{{ error }}</span>
      <Button :label="__('Retry')" :loading="loading" @click="load" />
    </div>

    <template v-if="data || !error">
      <div class="grid grid-cols-2 gap-4 md:grid-cols-3 xl:grid-cols-6">
        <template v-if="!data">
          <div
            v-for="i in 6"
            :key="i"
            class="p-4 bg-white border border-gray-200 rounded-lg animate-pulse"
          >
            <div class="w-20 h-4 mb-2 bg-gray-200 rounded"></div>
            <div class="w-12 h-8 bg-gray-200 rounded"></div>
          </div>
        </template>
        <template v-else>
          <div
            v-for="tile in data.kpis || []"
            :key="tile.key"
            class="min-w-0 p-4 bg-white border border-gray-200 rounded-lg"
          >
            <span class="text-sm font-medium text-gray-500">{{ __(tile.label) }}</span>
            <div class="flex flex-wrap items-baseline mt-1 gap-x-2 gap-y-1">
              <span class="text-2xl font-semibold text-gray-900">
                {{ tile.value == null ? "—" : tile.display ?? num(tile.value) }}
              </span>
              <Tooltip v-if="tile.chip" :text="chipTip(tile.chip)">
                <span :class="[CHIP, chipClass(tile.chip.label)]">{{ chipText(tile.chip) }}</span>
              </Tooltip>
            </div>
            <Tooltip :text="tile.hint || ''" :disabled="!tile.hint">
              <span class="block mt-1 text-xs text-gray-400 line-clamp-2">{{ tile.hint }}</span>
            </Tooltip>
          </div>
        </template>
      </div>

      <div
        class="overflow-hidden bg-white border border-gray-200 rounded-lg"
        :class="{ 'opacity-60': loading && data }"
      >
        <div v-if="!data" class="p-4 space-y-3 animate-pulse">
          <div v-for="i in 5" :key="i" class="h-6 bg-gray-200 rounded"></div>
        </div>
        <div
          v-else-if="!rows.length"
          class="flex flex-col items-center justify-center px-4 py-10 text-center text-gray-400"
        >
          <LucideListChecks class="w-8 h-8 mb-2" />
          <span class="text-sm">{{ emptyText }}</span>
          <Button
            v-if="data.state?.jump"
            class="mt-3"
            :label="__('Jump to latest covered period')"
            @click="emit('jump', data.state.jump)"
          />
        </div>
        <div v-else class="overflow-x-auto">
          <table class="min-w-full text-sm">
            <thead>
              <tr class="text-left text-gray-500 border-b border-gray-200">
                <th
                  v-for="col in columns"
                  :key="col.key"
                  class="px-3 py-2 font-medium whitespace-nowrap"
                >
                  {{ __(col.label) }}
                </th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="row in rows"
                :key="row.code"
                class="align-top border-b border-gray-100 cursor-pointer last:border-b-0 hover:bg-gray-50"
                @click="emit('open-issue', row.code)"
              >
                <td class="px-3 py-2 min-w-[12rem]">
                  <button
                    type="button"
                    class="font-medium text-left text-gray-900 hover:underline"
                    @click.stop="emit('open-issue', row.code)"
                  >
                    {{ row.label || row.code }}
                  </button>
                  <div class="flex items-center gap-1.5 mt-0.5 text-xs text-gray-500 whitespace-nowrap">
                    <Badge v-if="row.family" :label="row.family" size="sm" />
                    <span>{{ row.owner_department || "—" }}</span>
                  </div>
                </td>
                <td class="px-3 py-2 whitespace-nowrap">
                  <span class="font-medium text-gray-900">{{ num(row.cases) }}</span>
                  <Tooltip v-if="row.chip" :text="chipTip(row.chip)">
                    <span class="ml-1.5" :class="[CHIP, chipClass(row.chip.label)]">
                      {{ chipText(row.chip) }}
                    </span>
                  </Tooltip>
                </td>
                <td class="px-3 py-2 text-gray-700 whitespace-nowrap">{{ num(row.customers) }}</td>
                <td class="px-3 py-2">
                  <Tooltip :text="trendText(row.trend)">
                    <svg
                      :width="SPARK_W"
                      :height="SPARK_H"
                      :viewBox="`0 0 ${SPARK_W} ${SPARK_H}`"
                      class="overflow-visible text-gray-500"
                      role="img"
                      :aria-label="trendText(row.trend)"
                    >
                      <path
                        :d="sparklinePath(row.trend || [], SPARK_W, SPARK_H)"
                        fill="none"
                        stroke="currentColor"
                        stroke-width="1.5"
                        stroke-linecap="round"
                        stroke-linejoin="round"
                      />
                    </svg>
                  </Tooltip>
                </td>
                <td class="px-3 py-2 text-gray-700 whitespace-nowrap">
                  {{ row.weeks_active == null ? "—" : __("{0} of 8", String(row.weeks_active)) }}
                </td>
                <td class="px-3 py-2 whitespace-nowrap">
                  <span v-for="s in sevMix(row.severity)" :key="s.key" class="mr-1">
                    <Badge :label="`${s.key} ${s.n}`" :theme="SEV_THEME[s.key]" size="sm" />
                  </span>
                  <span v-if="!sevMix(row.severity).length" class="text-gray-400">—</span>
                </td>
                <td class="px-3 py-2">
                  <div class="text-gray-700 whitespace-nowrap">{{ row.top_channel || "—" }}</div>
                  <Tooltip v-if="row.dish" :text="__(DISH_FLAG)">
                    <div class="max-w-[14rem] text-xs text-red-600 truncate">
                      {{ __("Dish: {0}", row.dish) }}
                    </div>
                  </Tooltip>
                </td>
                <td class="px-3 py-2">
                  <div v-if="row.badges?.length" class="flex flex-wrap gap-1">
                    <Tooltip v-for="b in row.badges" :key="b" :text="badgeMeta(b).tooltip">
                      <span>
                        <Badge :label="badgeMeta(b).label" :theme="badgeMeta(b).theme" size="sm" />
                      </span>
                    </Tooltip>
                  </div>
                  <span v-else class="text-gray-400">—</span>
                </td>
                <td v-if="showAction" class="px-3 py-2 whitespace-nowrap">
                  <div v-if="row.action" class="flex flex-wrap items-center gap-1">
                    <Badge
                      :label="__(row.action.status || 'Open')"
                      :theme="row.action.overdue ? 'red' : 'blue'"
                      size="sm"
                    />
                    <span v-if="row.action.overdue" class="text-xs text-red-600">
                      {{ __("Overdue") }}
                    </span>
                    <Tooltip
                      v-if="row.action.verdict && row.action.verdict !== 'Not yet'"
                      :text="verdictMeta(row.action.verdict).tooltip"
                    >
                      <span>
                        <Badge
                          :label="verdictMeta(row.action.verdict).label"
                          :theme="verdictMeta(row.action.verdict).theme"
                          size="sm"
                        />
                      </span>
                    </Tooltip>
                  </div>
                  <span v-else-if="row.suggestions" class="text-xs text-gray-600">
                    {{ suggestionText(row.suggestions) }}
                  </span>
                  <span v-else class="text-gray-400">—</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <button
          v-if="data?.unclassified"
          type="button"
          class="flex flex-wrap items-baseline w-full px-3 py-2 text-sm text-left border-t border-gray-200 gap-x-2 bg-gray-50 hover:bg-gray-100"
          @click="toNewQueue"
        >
          <span class="font-medium text-gray-900">
            {{ __("Unclassified ({0})", String(data.unclassified)) }}
          </span>
          <span class="text-xs text-gray-500">
            {{ __("Labels that fit no issue code yet: review them in the NEW queue on Data health →") }}
          </span>
        </button>
      </div>
      <p v-if="rows.length" class="text-xs text-gray-500">{{ __(MULTI_ISSUE_NOTE) }}</p>
    </template>
  </div>
</template>

<script setup lang="ts">
import { dayjs } from "@/dayjs";
import { __ } from "@/translation";
import { Badge, Button, Popover, TabButtons, Tooltip, call } from "frappe-ui";
import { computed, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import LucideInfo from "~icons/lucide/info";
import LucideListChecks from "~icons/lucide/list-checks";
import { badgeMeta, chipClass, sparklinePath, verdictMeta } from "./aiAnalysis";

const props = defineProps<{
  filters?: Record<string, any>;
  status?: Record<string, any> | null;
  canDecide?: boolean;
}>();
const emit = defineEmits<{
  (e: "open-issue", code: string): void;
  (e: "jump", window: { from_date: string; to_date: string }): void;
  (e: "refresh-status"): void;
}>();

const route = useRoute();
const router = useRouter();

const selectClass = "text-sm rounded-lg border-gray-200 py-1.5";
const CHIP = "inline-flex items-center rounded px-1.5 py-0.5 text-xs font-medium whitespace-nowrap";
const SPARK_W = 96;
const SPARK_H = 24;
const KINDS = ["problems", "demand", "feedback", "all"];
const SORTS = [
  { value: "priority", label: "Priority" },
  { value: "cases", label: "Cases" },
  { value: "customers", label: "Customers" },
  { value: "change", label: "Change" },
];
const SEV_THEME: Record<string, string> = { S1: "red", S2: "orange", S3: "blue", S4: "gray" };
const PRIORITY_FORMULA =
  "Priority: each affected customer is weighted by their worst case: S1 = 10, S2 = 5, S3 = 2, S4 = 1.";
const MULTI_ISSUE_NOTE = "A contact can carry up to 4 issues, so rows add up to more than the total.";
const DISH_FLAG = "Flagged dish: more cases than its share of meals delivered predicts (p < 0.01).";

const kindButtons = computed(() => [
  { label: __("Problems"), value: "problems" },
  { label: __("Demand & requests"), value: "demand" },
  { label: __("Feedback"), value: "feedback" },
  { label: __("All"), value: "all" },
]);
// The shell derives filters from the URL; read the query as well in case it doesn't pass kind.
const kind = computed(() => {
  const k = props.filters?.kind || route.query.kind;
  return typeof k === "string" && KINDS.includes(k) ? k : "problems";
});
function setKind(value: string) {
  if (value !== kind.value) router.replace({ query: { ...route.query, kind: value } });
}

const params = computed(() => ({
  from_date: props.filters?.from_date || undefined,
  to_date: props.filters?.to_date || undefined,
  channel: props.filters?.channel || undefined,
  dept: props.filters?.dept || undefined,
  kind: kind.value,
}));

const data = ref<Record<string, any> | null>(null);
const loading = ref(false);
const error = ref("");
let seq = 0; // only the latest request may land

async function load() {
  const mine = ++seq;
  loading.value = true;
  error.value = "";
  try {
    const res = await call("helpdesk.api.ai_analysis.get_overview", params.value);
    if (mine === seq) data.value = res;
  } catch (e: any) {
    if (mine === seq) error.value = errorText(e);
  } finally {
    if (mine === seq) loading.value = false;
  }
}
watch(() => JSON.stringify(params.value), load, { immediate: true });

const sortKey = ref("priority");
const rows = computed<Record<string, any>[]>(() => {
  const by: Record<string, (r: Record<string, any>) => number> = {
    priority: (r) => r.priority ?? 0,
    cases: (r) => r.cases ?? 0,
    customers: (r) => r.customers ?? 0,
    change: (r) => (r.cases ?? 0) - (r.prior_cases ?? 0),
  };
  const key = by[sortKey.value] || by.priority;
  // a stable sort: ties keep the server's order (priority, then cases)
  return [...(data.value?.issues || [])].sort((a, b) => key(b) - key(a));
});
// Phase 2 adds row.action / row.suggestions (each may be null); the column appears once the keys exist.
const showAction = computed(() =>
  (data.value?.issues || []).some((r: Record<string, any>) => "action" in r || "suggestions" in r)
);
const columns = computed(() => [
  { key: "issue", label: "Issue" },
  { key: "cases", label: "Cases" },
  { key: "customers", label: "Customers" },
  { key: "trend", label: "Last 12 weeks" },
  { key: "weeks_active", label: "Weeks active" },
  { key: "severity", label: "Severity mix" },
  { key: "where", label: "Where" },
  { key: "badges", label: "Badges" },
  ...(showAction.value ? [{ key: "action", label: "Action status" }] : []),
]);

const emptyText = computed(() => {
  if (data.value?.state?.covered === false) {
    return data.value.state.notice || __("No data in this period.");
  }
  return __("No issues of this kind in this period.");
});

function toNewQueue() {
  router.replace({ query: { ...route.query, tab: "health" } });
}

const nf = new Intl.NumberFormat("en", { maximumFractionDigits: 2 });
function num(v: any) {
  return v == null || v === "" || Number.isNaN(Number(v)) ? "—" : nf.format(Number(v));
}
function fmtDate(d?: string | null) {
  return d ? dayjs(d).format("D MMM YYYY") : "—";
}
function chipText(chip: Record<string, any>) {
  return [chip.label, chip.text].filter(Boolean).join(" · ");
}
function chipTip(chip: Record<string, any>) {
  const w = data.value?.window;
  const parts = [];
  if (w?.prior_from) {
    parts.push(__("Compared with {0} – {1}", fmtDate(w.prior_from), fmtDate(w.prior_to)));
  }
  if (chip.p != null) {
    parts.push(__("exact test p {0}", chip.p < 0.001 ? "< 0.001" : Number(chip.p).toFixed(3)));
  }
  return parts.join(" · ");
}
function trendText(trend?: number[] | null) {
  return __("Cases in the last 12 weeks, oldest first: {0}", (trend || []).join(", ") || "—");
}
function sevMix(sev?: Record<string, number> | null) {
  return ["S1", "S2", "S3", "S4"].filter((s) => sev?.[s]).map((s) => ({ key: s, n: sev![s] }));
}
function suggestionText(s: Record<string, any>) {
  if (s.status === "Queued" || s.status === "Running") return __("Suggestions running");
  if (s.status === "Failed") return __("Suggestions failed");
  if (s.decision === "Adopted") return __("Plan adopted");
  if (s.decision === "Rejected") return __("Plan rejected");
  return __("Plan awaiting decision");
}
function errorText(e: any) {
  return (e?.messages?.length ? e.messages.join(" ") : e?.message) || __("Something went wrong.");
}
</script>
