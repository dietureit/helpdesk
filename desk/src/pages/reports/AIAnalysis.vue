<template>
  <div class="flex flex-col h-full overflow-y-auto">
    <div
      class="flex flex-wrap items-center justify-between gap-2 px-4 py-3 border-b sm:px-5"
    >
      <div class="min-w-0">
        <h1 class="text-lg font-semibold text-gray-900">
          {{ __("AI Analysis") }}
        </h1>
        <p class="text-xs text-gray-500">
          {{
            __(
              "Numbers are computed from data; AI only labels, quotes and suggests."
            )
          }}
        </p>
      </div>
      <div class="flex flex-wrap items-center gap-2">
        <Dropdown v-if="!showDatePicker" :options="periodOptions">
          <Button>
            <template #prefix><LucideCalendar class="w-4 h-4" /></template>
            {{ periodLabel }}
            <template #suffix><LucideChevronDown class="w-4 h-4" /></template>
          </Button>
        </Dropdown>
        <!-- Replaces the Dropdown (as on Customer Complaints): next to a still-mounted Dropdown, its closing
             menu takes focus back and the calendar closes on that "click outside" -->
        <DateRangePicker
          v-else
          ref="datePickerRef"
          :model-value="rangeValue"
          class="w-56"
          @update:model-value="onCustomRange"
        />
        <select
          :value="filters.channel || ''"
          :class="selectClass"
          :aria-label="__('Channel')"
          @change="onSelect('channel', $event)"
        >
          <option value="">{{ __("All channels") }}</option>
          <option v-for="c in CHANNELS" :key="c" :value="c">{{ __(c) }}</option>
        </select>
        <select
          :value="filters.dept || ''"
          :class="selectClass"
          :aria-label="__('Department')"
          @change="onSelect('dept', $event)"
        >
          <option value="">{{ __("All departments") }}</option>
          <option v-for="d in DEPARTMENTS" :key="d" :value="d">
            {{ __(d) }}
          </option>
        </select>
        <Tooltip :text="runBlocked">
          <span class="inline-flex">
            <Button
              variant="solid"
              :label="__('Run analysis')"
              :loading="starting"
              :disabled="!!runBlocked"
              @click="runAnalysis"
            >
              <template #prefix><LucidePlay class="w-4 h-4" /></template>
            </Button>
          </span>
        </Tooltip>
      </div>
    </div>

    <div class="px-4 py-4 space-y-4 sm:p-5">
      <div
        v-if="!status && !statusError"
        class="flex flex-wrap gap-1.5 animate-pulse"
      >
        <div v-for="i in 7" :key="i" class="w-32 h-5 bg-gray-200 rounded" />
      </div>
      <div v-else-if="!status" :class="ERROR_BOX">
        <LucideCircleAlert class="w-4 h-4 shrink-0" />
        <span class="flex-1 min-w-0">{{ statusError }}</span>
        <Button
          size="sm"
          :label="__('Retry')"
          :loading="statusLoading"
          @click="loadStatus"
        />
      </div>
      <div v-else class="space-y-2">
        <div class="flex flex-wrap items-center gap-1.5 text-xs">
          <span
            v-for="item in statusItems"
            :key="item.key"
            class="inline-flex items-center px-2 py-0.5 rounded"
            :class="TONES[item.tone]"
          >
            {{ item.text }}
          </span>
        </div>
        <div class="flex flex-wrap items-center gap-1.5 text-xs">
          <span
            v-for="chip in coverageChips"
            :key="chip"
            class="inline-flex items-center px-2 py-0.5 text-gray-600 border border-gray-200 rounded"
          >
            {{ chip }}
          </span>
        </div>
        <div
          v-if="statusError"
          class="flex flex-wrap items-center gap-2 text-xs text-red-700"
        >
          <span>{{ __("Status could not refresh: {0}", statusError) }}</span>
          <Button
            size="sm"
            variant="ghost"
            :label="__('Retry')"
            @click="loadStatus"
          />
        </div>
      </div>

      <div
        v-if="runMessage"
        class="flex items-start gap-2 text-sm text-gray-700"
      >
        <span class="flex-1 min-w-0">{{ runMessage }}</span>
        <Button
          size="sm"
          variant="ghost"
          :label="__('Dismiss')"
          @click="runMessage = ''"
        />
      </div>

      <div v-if="windowNotice" :class="NOTICE_BOX">
        <LucideTriangleAlert class="w-4 h-4 shrink-0" />
        <span class="flex-1 min-w-0">{{ windowNotice }}</span>
        <Button
          v-if="canJump"
          size="sm"
          :label="__('Jump to latest covered period')"
          @click="useDefaultWindow"
        />
      </div>

      <div v-if="safety.error" :class="ERROR_BOX">
        <LucideCircleAlert class="w-4 h-4 shrink-0" />
        <span class="flex-1 min-w-0">{{
          __("Food-safety box could not load: {0}", safety.error)
        }}</span>
        <Button
          size="sm"
          :label="__('Retry')"
          :loading="safety.loading"
          @click="loadSafety"
        />
      </div>
      <template v-if="tab !== 'brief'">
        <SafetyBox
          v-if="safety.data"
          :data="safety.data.safety"
          :can-decide="canDecide"
        />
        <div
          v-else-if="!safety.error"
          class="h-24 bg-white border border-gray-200 rounded-lg animate-pulse"
        />
      </template>

      <div class="overflow-x-auto">
        <TabButtons
          class="w-max"
          :buttons="tabButtons"
          :model-value="tab"
          @update:model-value="setTab"
        />
      </div>
      <component
        :is="TAB_COMPONENTS[tab]"
        v-if="filters.from_date"
        :filters="filters"
        :status="status"
        :can-decide="canDecide"
        @open-issue="openIssue"
        @jump="onJump"
        @refresh-status="loadStatus"
      />
      <div
        v-else-if="!statusError"
        class="h-40 bg-white border border-gray-200 rounded-lg animate-pulse"
      />
    </div>

    <IssuePanel
      v-if="issueCode && filters.from_date"
      :code="issueCode"
      :filters="filters"
      :can-decide="canDecide"
      :status="status"
      @close="closeIssue"
    />
  </div>
</template>

<script setup lang="ts">
import { dayjs } from "@/dayjs";
import { __ } from "@/translation";
import {
  Button,
  DateRangePicker,
  Dropdown,
  TabButtons,
  Tooltip,
  call,
  usePageMeta,
} from "frappe-ui";
import {
  computed,
  defineAsyncComponent,
  onBeforeUnmount,
  onMounted,
  reactive,
  ref,
  watch,
  type Component,
} from "vue";
import { useRoute, useRouter } from "vue-router";
import LucideCalendar from "~icons/lucide/calendar";
import LucideChevronDown from "~icons/lucide/chevron-down";
import LucideCircleAlert from "~icons/lucide/circle-alert";
import LucidePlay from "~icons/lucide/play";
import LucideTriangleAlert from "~icons/lucide/triangle-alert";
import { CHANNELS, DEPARTMENTS } from "./ai-analysis/aiAnalysis";
import SafetyBox from "./ai-analysis/SafetyBox.vue";

type Filters = {
  from_date: string | null;
  to_date: string | null;
  channel: string | null;
  dept: string | null;
  kind: string;
};

const TAB_COMPONENTS: Record<string, Component> = {
  brief: defineAsyncComponent(() => import("./ai-analysis/BriefTab.vue")),
  issues: defineAsyncComponent(() => import("./ai-analysis/IssuesTab.vue")),
  actions: defineAsyncComponent(() => import("./ai-analysis/ActionsTab.vue")),
  ask: defineAsyncComponent(() => import("./ai-analysis/AskTab.vue")),
  operations: defineAsyncComponent(
    () => import("./ai-analysis/OperationsTab.vue")
  ),
  health: defineAsyncComponent(() => import("./ai-analysis/DataHealthTab.vue")),
};
const IssuePanel = defineAsyncComponent(
  () => import("./ai-analysis/IssuePanel.vue")
);

const API = "helpdesk.api.ai_analysis.";
const TABS = Object.keys(TAB_COMPONENTS);
const KINDS = ["problems", "demand", "feedback", "all"];
const PRESETS = [7, 28, 90];
const DAY = /^\d{4}-\d{2}-\d{2}$/;
const CODE = /^[A-Z][A-Z0-9_]{1,63}$/;
const POLL_MS = 3000;
const selectClass = "text-sm rounded-lg border-gray-200 py-1.5";
const ERROR_BOX =
  "flex flex-wrap items-center gap-2 p-3 text-sm text-red-700 bg-red-50 border border-red-200 rounded-lg";
const NOTICE_BOX =
  "flex flex-wrap items-center gap-2 p-3 text-sm text-amber-800 bg-amber-50 border border-amber-200 rounded-lg";
const TONES: Record<string, string> = {
  ok: "bg-green-100 text-green-700",
  warn: "bg-amber-100 text-amber-700",
  bad: "bg-red-100 text-red-700",
  info: "bg-blue-100 text-blue-700",
  neutral: "bg-gray-100 text-gray-700",
};

const route = useRoute();
const router = useRouter();

// --- URL state: every filter comes from route.query; writes merge into it --------------------------
const q = (key: string) =>
  typeof route.query[key] === "string" ? (route.query[key] as string) : "";
const oneOf = (value: string, options: string[]) =>
  options.includes(value) ? value : null;

function setQuery(patch: Record<string, string | undefined>) {
  router.replace({ query: { ...route.query, ...patch } });
}

const tab = computed(() => oneOf(q("tab"), TABS) || "brief");
const issueCode = computed(() => (CODE.test(q("issue")) ? q("issue") : ""));
const urlWindow = computed(() => {
  const from_date = q("from_date");
  const to_date = q("to_date");
  return DAY.test(from_date) && DAY.test(to_date) && from_date <= to_date
    ? { from_date, to_date }
    : null;
});

// --- status ------------------------------------------------------------------------------------------
const status = ref<Record<string, any> | null>(null);
const statusError = ref("");
const statusLoading = ref(false);
let statusSeq = 0;
let pollTimer: ReturnType<typeof setTimeout> | undefined;
let alive = true;

function errorText(e: any): string {
  return (
    (e?.messages?.length ? e.messages.join(" ") : e?.message) ||
    __("Something went wrong.")
  );
}

async function loadStatus() {
  const seq = ++statusSeq; // only the newest load may schedule the next poll
  clearTimeout(pollTimer);
  statusLoading.value = true;
  try {
    const data = await call(API + "get_status");
    if (seq !== statusSeq || !alive) return;
    status.value = data;
    statusError.value = "";
    if (data?.running) pollTimer = setTimeout(loadStatus, POLL_MS);
  } catch (e) {
    if (seq === statusSeq) statusError.value = errorText(e); // stops polling until Retry
  } finally {
    if (seq === statusSeq) statusLoading.value = false;
  }
}

onMounted(loadStatus);
onBeforeUnmount(() => {
  alive = false;
  clearTimeout(pollTimer);
});

const canDecide = computed(() => !!status.value?.can_decide);
const defaultWindow = computed(() => {
  const w = status.value?.default_window;
  return w?.from_date && w?.to_date
    ? { from_date: String(w.from_date), to_date: String(w.to_date) }
    : null;
});
const period = computed(() => urlWindow.value || defaultWindow.value);
const isDefault = computed(
  () =>
    !!period.value &&
    !!defaultWindow.value &&
    period.value.from_date === defaultWindow.value.from_date &&
    period.value.to_date === defaultWindow.value.to_date
);

// Same values → the same object, so a tab does not refetch when only ?tab=, ?issue= or the polled
// status changes.
const filters = computed<Filters>((prev) => {
  const next: Filters = {
    from_date: period.value?.from_date || null,
    to_date: period.value?.to_date || null,
    channel: oneOf(q("channel"), CHANNELS),
    dept: oneOf(q("dept"), DEPARTMENTS),
    kind: oneOf(q("kind"), KINDS) || "problems",
  };
  return prev && JSON.stringify(prev) === JSON.stringify(next) ? prev : next;
});

const fmtDay = (d: string | null | undefined) =>
  d ? dayjs(d).format("D MMM YYYY") : "—";
const num = (n: unknown) =>
  n == null || n === "" || !Number.isFinite(Number(n))
    ? "—"
    : Number(n).toLocaleString("en-US");
const usd = (n: unknown) =>
  n == null || n === "" || !Number.isFinite(Number(n))
    ? "—"
    : Number(n).toLocaleString("en-US", { style: "currency", currency: "USD" });

const statusItems = computed(() => {
  const s = status.value;
  if (!s) return [];
  const p = s.progress || {};
  const v = s.version || {};
  const gold = s.validation || {};
  const items: { key: string; tone: string; text: string }[] = [
    s.ai_ready
      ? { key: "ai", tone: "ok", text: __("AI on") }
      : {
          key: "ai",
          tone: "warn",
          text: s.ai_reason ? __("AI off: {0}", s.ai_reason) : __("AI off"),
        },
    {
      key: "contacts",
      tone: "neutral",
      text: __(
        "{0} contacts · {1} labelled · {2} pending",
        num(p.total),
        num(p.tagged),
        num(p.pending)
      ),
    },
    {
      key: "last",
      tone: "neutral",
      text: s.last_labelled
        ? __(
            "Last labelled {0}",
            dayjs.tz(s.last_labelled).format("D MMM YYYY, h:mm A")
          )
        : __("Not labelled yet"),
    },
    v.relabelling
      ? {
          key: "version",
          tone: "warn",
          text: __("Re-labelling {0}% — numbers are settling", num(v.pct)),
        }
      : {
          key: "version",
          tone: "neutral",
          text: __("Label version {0}", v.current || "—"),
        },
    gold.ok
      ? {
          key: "gold",
          tone: "ok",
          text: __("Gold set scored {0}", fmtDay(gold.scored_on)),
        }
      : {
          key: "gold",
          tone: "warn",
          text: gold.scored_on
            ? __(
                "Gold set scored {0}, not yet validated — treat trends as directional",
                fmtDay(gold.scored_on)
              )
            : __("Not yet validated — treat trends as directional"),
        },
    s.worker_running
      ? { key: "worker", tone: "ok", text: __("Worker running") }
      : {
          key: "worker",
          tone: "bad",
          text: __("Worker down — the analysis cannot run"),
        },
    {
      key: "spend",
      tone: "neutral",
      text: __(
        "AI spend {0} of {1} this month",
        usd(s.spend?.month_usd),
        usd(s.spend?.budget_usd)
      ),
    },
  ];
  if (s.running)
    items.unshift({
      key: "running",
      tone: "info",
      text: __("Analysis running…"),
    });
  if (s.stopped)
    items.push({ key: "stopped", tone: "bad", text: String(s.stopped) });
  return items;
});

const coverageChips = computed(() => {
  const c = status.value?.coverage || {};
  return [
    c.chats_until
      ? __("Chats until {0}", fmtDay(c.chats_until))
      : __("No chat data yet"),
    c.deliveries_until
      ? __("Deliveries until {0}", fmtDay(c.deliveries_until))
      : __("No delivery data yet"),
    c.calls_until
      ? __("Answered calls until {0}", fmtDay(c.calls_until))
      : __("No answered-call data yet"),
    __("{0} contacts excluded", num(c.excluded)),
  ];
});

// --- run analysis (any agent) ------------------------------------------------------------------------
const starting = ref(false);
const runMessage = ref("");
const runBlocked = computed(() => {
  if (!status.value) return __("Loading the status…");
  if (!status.value.worker_running)
    return __("Background worker not running, so the analysis cannot start.");
  if (status.value.running) return __("The analysis is already running.");
  return "";
});

async function runAnalysis() {
  starting.value = true;
  try {
    const res = await call(API + "run_analysis");
    runMessage.value = res?.message || "";
  } catch (e) {
    runMessage.value = errorText(e);
  } finally {
    starting.value = false;
  }
  loadStatus();
}

// --- period, channel and department --------------------------------------------------------------
const showDatePicker = ref(false);
const datePickerRef = ref<{ open?: () => void } | null>(null);
const rangeValue = computed(() =>
  period.value ? `${period.value.from_date},${period.value.to_date}` : ""
);

function lastDays(days: number) {
  const to = dayjs();
  return {
    from_date: to.subtract(days - 1, "day").format("YYYY-MM-DD"),
    to_date: to.format("YYYY-MM-DD"),
  };
}

function useDefaultWindow() {
  showDatePicker.value = false;
  setQuery({ from_date: undefined, to_date: undefined });
}

function onJump(w: { from_date?: string; to_date?: string } | null) {
  const [from_date, to_date] = [w?.from_date || "", w?.to_date || ""].sort();
  if (DAY.test(from_date) && DAY.test(to_date))
    setQuery({ from_date, to_date });
}

function setPreset(days: number) {
  showDatePicker.value = false;
  setQuery(lastDays(days));
}

function openCustomRange() {
  showDatePicker.value = true;
  // after the Dropdown has unmounted, so its menu's focus trap is gone
  setTimeout(() => datePickerRef.value?.open?.(), 0);
}

function onCustomRange(value: string) {
  showDatePicker.value = false;
  if (!value) return useDefaultWindow(); // the calendar's Clear emits ""
  const [from_date, to_date] = value.split(",");
  onJump({ from_date, to_date });
}

const periodLabel = computed(() => {
  const p = period.value;
  if (!p) return __("Period");
  if (isDefault.value) {
    return status.value?.default_window?.latest
      ? __("Latest period with data")
      : __("Last {0} days", "28");
  }
  const preset = PRESETS.find((n) => {
    const w = lastDays(n);
    return w.from_date === p.from_date && w.to_date === p.to_date;
  });
  return preset
    ? __("Last {0} days", String(preset))
    : `${fmtDay(p.from_date)} – ${fmtDay(p.to_date)}`;
});

const periodOptions = computed(() => [
  {
    group: "Presets",
    hideLabel: true,
    items: [
      { label: __("Latest period with data"), onClick: useDefaultWindow },
      ...PRESETS.map((n) => ({
        label: __("Last {0} days", String(n)),
        onClick: () => setPreset(n),
      })),
    ],
  },
  { label: __("Custom range"), onClick: openCustomRange },
]);

function onSelect(key: "channel" | "dept", event: Event) {
  setQuery({ [key]: (event.target as HTMLSelectElement).value || undefined });
}

// --- food-safety box and the window notice (date window only) ------------------------------------
const safety = reactive<{
  data: Record<string, any> | null;
  loading: boolean;
  error: string;
}>({
  data: null,
  loading: false,
  error: "",
});
let safetySeq = 0;

async function loadSafety() {
  const { from_date, to_date } = filters.value;
  if (!from_date || !to_date) return;
  const seq = ++safetySeq; // a slower answer for an older window never overwrites a newer one
  safety.loading = true;
  safety.error = "";
  try {
    const data = await call(API + "get_safety", { from_date, to_date });
    if (seq === safetySeq) safety.data = data;
  } catch (e) {
    if (seq === safetySeq) safety.error = errorText(e);
  } finally {
    if (seq === safetySeq) safety.loading = false;
  }
}

watch(
  [() => filters.value.from_date, () => filters.value.to_date],
  loadSafety,
  { immediate: true }
);
// fresh labels can add safety events: reload once a run finishes
watch(
  () => !!status.value?.running,
  (running, wasRunning) => {
    if (wasRunning && !running) loadSafety();
  }
);

const windowState = computed(() => safety.data?.state || null);
const windowNotice = computed(() =>
  windowState.value?.covered === false
    ? windowState.value.notice || __("No chat data in this period")
    : ""
);
const canJump = computed(
  () => !!windowState.value?.jump && !!defaultWindow.value && !isDefault.value
);

// --- tabs and the issue panel ----------------------------------------------------------------------
const tabButtons = computed(() => [
  { label: __("Brief"), value: "brief" },
  { label: __("Issues"), value: "issues" },
  { label: __("Actions"), value: "actions" },
  { label: __("Ask"), value: "ask" },
  { label: __("Operations"), value: "operations" },
  { label: __("Data health"), value: "health" },
]);

function setTab(value: string) {
  setQuery({ tab: value === "brief" ? undefined : value });
}

function openIssue(code: string) {
  if (CODE.test(code || "")) setQuery({ issue: code });
}

function closeIssue() {
  setQuery({ issue: undefined });
}

usePageMeta(() => ({ title: __("AI Analysis") }));
</script>
