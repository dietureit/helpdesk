<template>
  <div class="space-y-4">
    <section class="p-4 space-y-3 bg-white border border-gray-200 rounded-lg">
      <div>
        <h3 class="text-sm font-medium text-gray-900">
          {{ __("Ask your tickets") }}
        </h3>
        <p class="text-xs text-gray-500">
          {{
            __(
              "Ask in English or Arabic. Each question stands alone: the AI does not see your earlier questions or answers. Please leave out customer names and phone numbers."
            )
          }}
        </p>
      </div>
      <Textarea
        v-model="question"
        variant="outline"
        :rows="3"
        :maxlength="MAX_LENGTH"
        dir="auto"
        :class="getFontFamily(question)"
        :placeholder="__('Ask about complaints, requests or enquiries…')"
        :aria-label="__('Your question')"
      />
      <div class="flex flex-wrap items-center gap-2">
        <span class="text-xs text-gray-500">{{ __("Try:") }}</span>
        <button
          v-for="example in EXAMPLES"
          :key="example"
          type="button"
          class="px-2 py-1 text-xs text-gray-700 bg-gray-100 rounded-full hover:bg-gray-200"
          dir="auto"
          :class="getFontFamily(example)"
          @click="question = example"
        >
          {{ example }}
        </button>
      </div>
      <div class="flex flex-wrap items-center gap-3">
        <Button
          variant="solid"
          :label="__('Ask')"
          :loading="asking"
          :disabled="!canAsk"
          @click="ask()"
        >
          <template #prefix><LucideSend class="w-4 h-4" /></template>
        </Button>
        <span class="text-xs text-gray-400"
          >{{ question.length }}/{{ MAX_LENGTH }}</span
        >
        <span v-if="blockedReason" class="text-xs text-orange-700">{{
          blockedReason
        }}</span>
      </div>
      <p
        v-if="askError"
        class="p-3 text-sm text-red-700 border border-red-200 rounded-lg bg-red-50"
      >
        {{ askError }}
      </p>
    </section>

    <div class="grid grid-cols-1 gap-4 lg:grid-cols-3">
      <div class="min-w-0 lg:col-span-2">
        <div
          v-if="
            current ? insightLoading && !insight : historyLoading && !history
          "
          class="p-4 space-y-3 bg-white border border-gray-200 rounded-lg animate-pulse"
        >
          <div class="w-2/3 h-4 bg-gray-200 rounded"></div>
          <div class="h-16 bg-gray-100 rounded"></div>
          <div class="h-24 bg-gray-100 rounded"></div>
        </div>

        <div
          v-else-if="!current"
          class="flex flex-col items-center justify-center py-10 text-gray-400 bg-white border border-gray-200 rounded-lg"
        >
          <LucideMessageSquareText class="w-8 h-8 mb-2" />
          <span class="text-sm">{{
            __("Ask a question, or open one from your recent questions.")
          }}</span>
        </div>

        <div
          v-else-if="insightError && !insight"
          class="flex flex-wrap items-center gap-3 p-3 text-sm text-red-700 border border-red-200 rounded-lg bg-red-50"
        >
          <span class="flex-1 min-w-0">{{ insightError }}</span>
          <Button :label="__('Retry')" @click="loadInsight(current)" />
        </div>

        <article
          v-else-if="insight"
          class="p-4 space-y-4 bg-white border border-gray-200 rounded-lg"
        >
          <div class="flex flex-wrap items-start justify-between gap-2">
            <div class="min-w-0">
              <p class="text-xs text-gray-500">{{ when(insight.creation) }}</p>
              <p
                class="font-medium text-gray-900 whitespace-pre-line"
                dir="auto"
                :class="getFontFamily(questionText)"
              >
                {{ questionText }}
              </p>
            </div>
            <Badge
              variant="subtle"
              :theme="validation.ok ? 'green' : 'orange'"
              :label="validation.text"
            />
          </div>

          <div
            v-if="insightError"
            class="flex flex-wrap items-center gap-3 p-3 text-sm text-red-700 border border-red-200 rounded-lg bg-red-50"
          >
            <span class="flex-1 min-w-0">{{ insightError }}</span>
            <Button :label="__('Retry')" @click="loadInsight(current)" />
          </div>

          <div
            v-if="running"
            class="flex items-center gap-2 text-sm text-gray-600"
          >
            <LoadingIndicator class="w-4 h-4" />
            <span>
              {{
                insight.progress_label ||
                (insight.status === "Queued"
                  ? __("Waiting for the background worker…")
                  : __("Working on the answer…"))
              }}
            </span>
          </div>
          <p
            v-if="running && status?.worker_running === false"
            class="text-xs text-orange-700"
          >
            {{
              __("Background worker not running, so this question is waiting.")
            }}
          </p>

          <div
            v-if="insight.status === 'Failed'"
            class="flex flex-wrap items-center gap-3 p-3 text-sm text-red-700 border border-red-200 rounded-lg bg-red-50"
          >
            <span class="flex-1 min-w-0">
              {{ insight.error || __("The answer could not be written.") }}
            </span>
            <Button
              v-if="questionText"
              :label="__('Ask again')"
              :disabled="!!blockedReason || asking"
              @click="ask(questionText)"
            />
            <span
              v-if="questionText && blockedReason"
              class="text-xs text-orange-700"
            >
              {{ blockedReason }}
            </span>
          </div>

          <div
            v-if="output.declined"
            class="flex items-start gap-2 p-3 text-sm text-orange-800 border border-orange-200 rounded-lg bg-orange-50"
          >
            <LucideTriangleAlert class="w-4 h-4 mt-0.5 shrink-0" />
            <span
              class="whitespace-pre-line"
              dir="auto"
              :class="getFontFamily(output.declined)"
            >
              {{ output.declined }}
            </span>
          </div>

          <p
            v-if="segments.length"
            class="leading-relaxed text-gray-900 whitespace-pre-line"
            dir="auto"
            :class="getFontFamily(answerText)"
          >
            <template v-for="(segment, i) in segments" :key="i">
              <span v-if="segment.type === 'value'" class="font-semibold">{{
                segment.text
              }}</span>
              <template v-else>{{ segment.text }}</template>
            </template>
          </p>

          <div
            v-if="planChips.length || filtersText || nCases !== null"
            class="space-y-2"
          >
            <h4 class="text-xs font-medium text-gray-500">
              {{ __("How this was computed") }}
            </h4>
            <div class="flex flex-wrap gap-1.5">
              <span
                v-for="chip in planChips"
                :key="chip.label"
                class="px-2 py-0.5 text-xs text-gray-700 bg-gray-100 rounded-full"
                dir="auto"
              >
                <span class="text-gray-500">{{ chip.label }}:</span>
                {{ chip.text }}
              </span>
            </div>
            <p
              v-if="filtersText"
              class="text-xs text-gray-500 whitespace-pre-line"
              dir="auto"
            >
              {{ filtersText }}
            </p>
            <p v-if="nCases !== null" class="text-xs text-gray-500">
              {{
                __(
                  "Based on {0} cases, counted the same way as the rest of this page.",
                  cell(nCases)
                )
              }}
            </p>
          </div>

          <div v-if="tableColumns.length" class="space-y-2">
            <h4 class="text-xs font-medium text-gray-500">
              {{ __("Result") }}
            </h4>
            <div class="overflow-x-auto border border-gray-200 rounded-lg">
              <table class="min-w-full text-sm">
                <thead>
                  <tr class="text-left text-gray-500 border-b border-gray-200">
                    <th
                      v-for="(column, c) in tableColumns"
                      :key="c"
                      class="px-3 py-2 font-medium whitespace-nowrap"
                      dir="auto"
                    >
                      {{ column }}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  <tr
                    v-for="(row, r) in tableRows"
                    :key="r"
                    class="border-b border-gray-100 last:border-b-0"
                  >
                    <td
                      v-for="(value, c) in row"
                      :key="c"
                      class="px-3 py-2 text-gray-700 whitespace-nowrap"
                      dir="auto"
                    >
                      {{ cell(value) }}
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
            <p v-if="!tableRows.length" class="text-xs text-gray-400">
              {{ __("No matching rows.") }}
            </p>
          </div>

          <div v-if="evidence.length" class="space-y-2">
            <h4 class="text-xs font-medium text-gray-500">
              {{ __("Cited quotes") }}
            </h4>
            <ul
              class="border border-gray-200 divide-y divide-gray-100 rounded-lg"
            >
              <li
                v-for="(quote, q) in evidence"
                :key="quote.id || quote.ref || q"
                class="flex items-start gap-3 p-3"
              >
                <span
                  v-if="quote.id"
                  class="px-1.5 py-0.5 text-xs font-medium text-gray-600 bg-gray-100 rounded shrink-0"
                >
                  {{ quote.id }}
                </span>
                <div class="flex-1 min-w-0 space-y-1">
                  <p
                    class="text-sm text-gray-900 whitespace-pre-line"
                    dir="auto"
                    :class="getFontFamily(quote.quote || '')"
                  >
                    {{ quote.quote }}
                  </p>
                  <p
                    v-if="quote.quote_en && quote.quote_en !== quote.quote"
                    class="text-xs text-gray-600 whitespace-pre-line"
                    dir="auto"
                    :class="getFontFamily(quote.quote_en)"
                  >
                    <span class="font-medium text-gray-500"
                      >{{ __("AI translation") }}:</span
                    >
                    {{ quote.quote_en }}
                  </p>
                  <p class="text-xs text-gray-400">{{ quoteMeta(quote) }}</p>
                </div>
                <Button
                  v-if="quote.ref"
                  size="sm"
                  variant="ghost"
                  :label="__('Open ↗')"
                  @click="openCase(quote.ref)"
                />
              </li>
            </ul>
          </div>
        </article>
      </div>

      <aside
        class="self-start p-4 space-y-3 bg-white border border-gray-200 rounded-lg"
      >
        <h3 class="flex items-center gap-1.5 text-sm font-medium text-gray-900">
          <LucideHistory class="w-4 h-4" />
          {{ __("Your recent questions") }}
        </h3>
        <div
          v-if="historyError"
          class="flex flex-wrap items-center gap-2 p-2 text-xs text-red-700 border border-red-200 rounded bg-red-50"
        >
          <span class="flex-1 min-w-0">{{ historyError }}</span>
          <Button size="sm" :label="__('Retry')" @click="loadHistory()" />
        </div>
        <div v-if="historyLoading && !history" class="space-y-2 animate-pulse">
          <div v-for="i in 3" :key="i" class="h-10 bg-gray-100 rounded"></div>
        </div>
        <p v-else-if="history && !history.length" class="text-sm text-gray-400">
          {{ __("No questions yet.") }}
        </p>
        <ul v-else-if="history" class="-mx-2 space-y-0.5">
          <li v-for="row in history" :key="row.insight">
            <button
              type="button"
              class="w-full px-2 py-2 rounded text-start hover:bg-gray-50"
              :class="row.insight === current ? 'bg-gray-100' : ''"
              @click="open(row.insight, row.question)"
            >
              <span
                class="text-sm text-gray-900 whitespace-pre-line line-clamp-2"
                dir="auto"
                :class="getFontFamily(row.question || '')"
              >
                {{ row.question }}
              </span>
              <span class="flex items-center gap-2 mt-1">
                <Badge
                  size="sm"
                  variant="subtle"
                  :theme="statusMeta(row).theme"
                  :label="statusMeta(row).label"
                />
                <span class="text-xs text-gray-400">{{
                  when(row.creation)
                }}</span>
              </span>
            </button>
          </li>
        </ul>
      </aside>
    </div>
  </div>
</template>

<script setup lang="ts">
import { dayjs } from "@/dayjs";
import { __ } from "@/translation";
import { getFontFamily } from "@/utils";
import { Badge, Button, LoadingIndicator, Textarea, call } from "frappe-ui";
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import LucideHistory from "~icons/lucide/history";
import LucideMessageSquareText from "~icons/lucide/message-square-text";
import LucideSend from "~icons/lucide/send";
import LucideTriangleAlert from "~icons/lucide/triangle-alert";
import { fillPlaceholders, roleLabel } from "./aiAnalysis";

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

const MAX_LENGTH = 500;
const POLL_MS = 3000;
const RUNNING = ["Queued", "Running"];
const EXAMPLES = [
  __("Which delivery problems rose this month?"),
  __("ما هي أكثر الشكاوى تكراراً؟"),
];
const GROUP_BY: Record<string, string> = {
  week: __("week"),
  code: __("issue"),
  channel: __("channel"),
  dish: __("dish"),
  weekday: __("weekday"),
};
const METRIC: Record<string, string> = {
  cases: __("cases"),
  customers: __("customers"),
  rate: __("rate per 1,000 deliveries"),
};
const STATUS: Record<string, { label: string; theme: string }> = {
  Queued: { label: __("Queued"), theme: "gray" },
  Running: { label: __("Running"), theme: "blue" },
  Done: { label: __("Answered"), theme: "green" },
  Failed: { label: __("Failed"), theme: "red" },
  "No synthesis": { label: __("No answer"), theme: "orange" },
};

const question = ref("");
const asking = ref(false);
const askError = ref("");

const current = ref("");
const currentQuestion = ref("");
const insight = ref<Record<string, any> | null>(null);
const insightLoading = ref(false);
const insightError = ref("");

const history = ref<Record<string, any>[] | null>(null);
const historyLoading = ref(true); // onMounted loads it straight away
const historyError = ref("");

const blockedReason = computed(() => {
  const s = props.status;
  if (!s) return __("Checking whether AI is available…");
  if (!s.ai_ready)
    return s.ai_reason || __("AI is off, so questions can't be answered.");
  if (!s.worker_running)
    return __("Background worker not running, so questions can't be answered.");
  return "";
});
const canAsk = computed(
  () =>
    !!question.value.trim() &&
    question.value.length <= MAX_LENGTH &&
    !blockedReason.value &&
    !asking.value
);

const validation = computed(() => {
  const v = props.status?.validation;
  if (!v?.ok)
    return { ok: false, text: __("not yet validated — treat as directional") };
  return {
    ok: true,
    text: v.scored_on
      ? __("Validated: gold set scored {0}", day(v.scored_on))
      : __("Validated against the gold set"),
  };
});

const running = computed(() => RUNNING.includes(insight.value?.status));
const output = computed<Record<string, any>>(() => insight.value?.output || {});
const questionText = computed<string>(
  () =>
    output.value.question ||
    insight.value?.question ||
    currentQuestion.value ||
    ""
);
const segments = computed(() =>
  output.value.answer
    ? fillPlaceholders(output.value.answer, output.value.values || {})
    : []
);
const answerText = computed(() => segments.value.map((s) => s.text).join(""));
const table = computed<Record<string, any>>(() => output.value.table || {});
const tableColumns = computed<string[]>(() => table.value.columns || []);
const tableRows = computed<unknown[][]>(() =>
  (table.value.rows || []).map((row: any) =>
    Array.isArray(row) ? row : tableColumns.value.map((c) => row?.[c])
  )
);
const filtersText = computed<string>(
  () => table.value.filters_text || output.value.filters_text || ""
);
const nCases = computed(
  () => output.value.n_cases ?? table.value.n_cases ?? null
);
const evidence = computed<Record<string, any>[]>(
  () => output.value.evidence || []
);

const planChips = computed(() => {
  const plan = output.value.plan || {};
  const list = (v: unknown) =>
    Array.isArray(v) ? v.filter(Boolean).join(", ") : "";
  return [
    { label: __("Issues"), text: list(plan.codes) },
    { label: __("Kinds"), text: list(plan.kinds) },
    { label: __("Channels"), text: list(plan.channels) },
    {
      label: __("Period"),
      text: plan.from || plan.to ? `${day(plan.from)} – ${day(plan.to)}` : "",
    },
    {
      label: __("Grouped by"),
      text: GROUP_BY[plan.group_by] || plan.group_by || "",
    },
    { label: __("Metric"), text: METRIC[plan.metric] || plan.metric || "" },
  ].filter((chip) => chip.text);
});

let timer: ReturnType<typeof setTimeout> | undefined;
let seq = 0; // the newest get_insight call wins; older replies are dropped

async function loadInsight(name: string) {
  const mine = ++seq;
  clearTimeout(timer);
  insightLoading.value = true;
  insightError.value = "";
  try {
    const res = await call("helpdesk.api.ai_analysis.get_insight", { name });
    if (mine !== seq) return;
    const finished = running.value && !RUNNING.includes(res?.status);
    insight.value = res || null;
    if (RUNNING.includes(res?.status)) {
      timer = setTimeout(() => loadInsight(name), POLL_MS);
    } else if (finished) {
      loadHistory();
      emit("refresh-status");
    }
  } catch (e: any) {
    if (mine === seq)
      insightError.value = errorText(e, __("Could not load this answer."));
  } finally {
    if (mine === seq) insightLoading.value = false;
  }
}

function open(name: string, text?: string) {
  if (name !== current.value) {
    current.value = name;
    currentQuestion.value = text || "";
    insight.value = null;
  }
  loadInsight(name);
}

async function ask(text?: string) {
  const q = (text ?? question.value).trim();
  if (!q || q.length > MAX_LENGTH || blockedReason.value || asking.value)
    return;
  asking.value = true;
  askError.value = "";
  try {
    const res = await call("helpdesk.api.ai_analysis.ask", { question: q });
    if (res?.insight) {
      if (text === undefined) question.value = "";
      open(res.insight, q);
      loadHistory();
    } else {
      askError.value = res?.message || __("The question could not be started.");
    }
  } catch (e: any) {
    askError.value = errorText(e, __("The question could not be started."));
  } finally {
    asking.value = false;
  }
}

async function loadHistory(openLatest = false) {
  historyLoading.value = true;
  historyError.value = "";
  try {
    const rows = (await call("helpdesk.api.ai_analysis.get_questions")) || [];
    history.value = rows;
    if (openLatest && !current.value && rows.length)
      open(rows[0].insight, rows[0].question);
  } catch (e: any) {
    historyError.value = errorText(e, __("Could not load your questions."));
  } finally {
    historyLoading.value = false;
  }
}

onMounted(() => loadHistory(true));
onBeforeUnmount(() => {
  seq++;
  clearTimeout(timer);
});

function statusMeta(row: Record<string, any>) {
  if (row.declined) return { label: __("Declined"), theme: "orange" };
  return STATUS[row.status] || { label: row.status || "—", theme: "gray" };
}

function quoteMeta(quote: Record<string, any>) {
  return [
    day(quote.date),
    quote.channel,
    quote.severity,
    quote.role ? roleLabel(quote.role) : "",
  ]
    .filter((part) => part && part !== "—")
    .join(" · ");
}

function openCase(ref: string) {
  window.open(
    "/api/method/helpdesk.api.ai_analysis.open_case?ref=" +
      encodeURIComponent(ref),
    "_blank",
    "noopener"
  );
}

function cell(value: unknown) {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "number")
    return value.toLocaleString("en-US", { maximumFractionDigits: 2 });
  if (typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value))
    return day(value);
  return String(value);
}

function day(value: string | null | undefined) {
  if (!value) return "—";
  const d = dayjs(value);
  return d.isValid() ? d.format("D MMM YYYY") : value;
}

function when(value: string | null | undefined) {
  return value && dayjs(value).isValid()
    ? dayjs(value).format("D MMM YYYY, h:mm A")
    : "";
}

function errorText(e: any, fallback: string) {
  return e?.messages?.length ? e.messages.join(" ") : fallback;
}
</script>
