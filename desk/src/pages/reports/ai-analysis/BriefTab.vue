<template>
  <div class="space-y-4">
    <div class="flex flex-wrap items-center gap-2">
      <select
        v-if="weekOptions.length"
        :value="brief?.week"
        :class="selectClass"
        class="max-w-full"
        :aria-label="__('Week')"
        @change="onWeekChange"
      >
        <option v-for="w in weekOptions" :key="w" :value="w">
          {{ __("Week of {0}", fmtDate(w)) }}
        </option>
      </select>
      <Button
        :label="isAi ? __('Rewrite summary') : __('Write summary')"
        :loading="summary.busy"
        :disabled="!brief || !!aiBlocked || summary.busy"
        @click="writeSummary"
      >
        <template #prefix><LucideSparkles class="size-4" /></template>
      </Button>
      <Tooltip :text="__('A one-page PDF of this week, without customer quotes.')">
        <Button :label="__('Download PDF')" :disabled="!brief" @click="downloadPdf">
          <template #prefix><LucideDownload class="size-4" /></template>
        </Button>
      </Tooltip>
      <span v-if="aiBlocked" class="text-xs text-gray-500">{{ aiBlocked }}</span>
      <span v-else-if="summary.busy" class="text-xs text-gray-500">
        {{ summary.label || __("Writing the summary…") }}
      </span>
      <span v-if="loading && brief" class="text-xs text-gray-400">{{ __("Refreshing…") }}</span>
    </div>

    <div
      v-if="error"
      class="flex flex-wrap items-center gap-2 p-3 text-sm text-red-700 border border-red-200 rounded-lg bg-red-50"
    >
      <span class="flex-1 min-w-0">{{ error }}</span>
      <Button size="sm" :label="__('Retry')" @click="load" />
    </div>

    <div v-if="!brief && loading" class="space-y-4 animate-pulse">
      <div class="h-20 bg-gray-100 rounded-lg" />
      <div class="grid grid-cols-2 gap-4 md:grid-cols-3 xl:grid-cols-6">
        <div v-for="i in 6" :key="i" class="h-24 bg-gray-100 rounded-lg" />
      </div>
      <div class="grid gap-4 lg:grid-cols-3">
        <div v-for="i in 3" :key="i" class="h-56 bg-gray-100 rounded-lg" />
      </div>
    </div>

    <template v-if="brief">
      <div
        v-if="brief.state?.notice"
        class="flex flex-wrap items-center gap-2 p-3 text-sm border rounded-lg border-amber-200 bg-amber-50 text-amber-800"
      >
        <LucideTriangleAlert class="size-4 shrink-0" />
        <span class="flex-1 min-w-0">{{ brief.state.notice }}</span>
        <Button
          v-if="brief.weeks?.length && brief.weeks[0] !== brief.week"
          size="sm"
          :label="__('Jump to latest covered week')"
          @click="setWeek(brief.weeks[0])"
        />
      </div>

      <!-- 1. Headline -->
      <section class="p-4 bg-white border border-gray-200 rounded-lg">
        <!-- the AI text holds {{key}} placeholders; code fills the numbers, shown bold -->
        <template v-if="isAi">
          <p
            class="text-base text-gray-900 whitespace-pre-line"
            dir="auto"
            :class="getFontFamily(brief.headline.text || '')"
          >
            <template v-for="(seg, i) in segments" :key="i">
              <strong v-if="seg.type === 'value'" class="font-semibold">{{ seg.text }}</strong>
              <span v-else>{{ seg.text }}</span>
            </template>
          </p>
          <ul v-if="bullets.length" class="mt-2 space-y-1 text-sm text-gray-800 list-disc list-inside">
            <li
              v-for="(b, i) in bullets"
              :key="i"
              class="whitespace-pre-line"
              dir="auto"
              :class="getFontFamily(b.text)"
            >
              <template v-for="(seg, j) in b.segments" :key="j">
                <strong v-if="seg.type === 'value'" class="font-semibold">{{ seg.text }}</strong>
                <span v-else>{{ seg.text }}</span>
              </template>
            </li>
          </ul>
        </template>
        <p
          v-else
          class="text-base text-gray-900 whitespace-pre-line"
          dir="auto"
          :class="getFontFamily(brief.headline?.text || '')"
        >
          {{ brief.headline?.text }}
        </p>
        <p class="mt-1 text-xs text-gray-500">
          <template v-if="isAi">
            {{ __("AI summary · {0}", brief.headline.model || "—") }}
            <template v-if="brief.headline.at">· {{ fmtDateTime(brief.headline.at) }}</template>
            · {{ __("numbers filled in from code") }}
          </template>
          <template v-else>{{ __("Code-built from the numbers") }}</template>
        </p>
        <p v-if="summary.error" class="mt-2 text-sm text-red-600">{{ summary.error }}</p>
      </section>

      <!-- 2. KPI strip -->
      <div class="grid grid-cols-2 gap-4 md:grid-cols-3 xl:grid-cols-6">
        <div
          v-for="tile in brief.kpis || []"
          :key="tile.key"
          class="p-4 bg-white border border-gray-200 rounded-lg"
        >
          <span class="text-sm font-medium text-gray-500">{{ __(tile.label) }}</span>
          <div class="mt-1 text-2xl font-semibold text-gray-900">{{ tile.display ?? "—" }}</div>
          <div v-if="tile.chip" class="flex flex-wrap items-center gap-1 mt-1 text-xs">
            <span v-if="tile.chip.label" class="px-1.5 rounded-full" :class="chipClass(tile.chip.label)">
              {{ __(tile.chip.label) }}
            </span>
            <span class="text-gray-600">{{ tile.chip.text }}</span>
          </div>
          <span v-if="tile.hint" class="block mt-1 text-xs text-gray-400">{{ tile.hint }}</span>
        </div>
      </div>

      <SafetyBox :data="brief.safety" :can-decide="canDecide" />

      <!-- 3. Top 3 problems -->
      <section class="space-y-2">
        <h2 class="text-base font-semibold text-gray-900">{{ __("Top problems") }}</h2>
        <p
          v-if="!brief.top?.length"
          class="p-4 text-sm text-gray-500 bg-white border border-gray-200 rounded-lg"
        >
          {{ __("No complaint cases in the 4 weeks up to this week.") }}
        </p>
        <div v-else class="grid gap-4 lg:grid-cols-3">
          <div
            v-for="card in brief.top"
            :key="card.code"
            role="button"
            tabindex="0"
            class="flex flex-col min-w-0 gap-3 p-4 bg-white border border-gray-200 rounded-lg cursor-pointer hover:border-gray-400"
            @click="emit('open-issue', card.code)"
            @keydown.enter.self="emit('open-issue', card.code)"
          >
            <div class="flex items-start justify-between gap-2">
              <div class="min-w-0">
                <div class="font-medium text-gray-900">{{ card.label }}</div>
                <div class="text-xs text-gray-500">{{ card.owner_department || "—" }}</div>
              </div>
              <svg
                class="w-20 h-6 text-gray-500 shrink-0"
                viewBox="0 0 80 24"
                fill="none"
                role="img"
                :aria-label="__('Cases over the last 8 weeks')"
              >
                <path
                  :d="sparklinePath(card.sparkline || [], 80, 24)"
                  stroke="currentColor"
                  stroke-width="1.5"
                  stroke-linecap="round"
                  stroke-linejoin="round"
                />
              </svg>
            </div>
            <div v-if="card.badges?.length" class="flex flex-wrap gap-1">
              <Tooltip
                v-for="meta in card.badges.map((b) => badgeMeta(b))"
                :key="meta.label"
                :text="meta.tooltip"
              >
                <Badge :theme="meta.theme" :label="meta.label" />
              </Tooltip>
            </div>
            <dl class="grid grid-cols-2 gap-2 text-sm">
              <div>
                <dt class="text-xs text-gray-500">{{ __("This week") }}</dt>
                <dd class="text-gray-900">
                  {{ __("{0} cases · {1} customers", num(card.week_cases), num(card.week_customers)) }}
                </dd>
              </div>
              <div>
                <dt class="text-xs text-gray-500">{{ __("4 weeks") }}</dt>
                <dd class="text-gray-900">
                  {{ __("{0} cases · {1} customers", num(card.cases), num(card.customers)) }}
                </dd>
              </div>
            </dl>
            <p class="text-xs text-gray-500">
              {{ __("Mostly via {0}", card.top_channel || "—") }}
              <template v-if="card.dish">· {{ __("Dish: {0}", card.dish) }}</template>
            </p>
            <p v-if="!card.quotes?.length" class="text-xs text-gray-400">
              {{ __("No verified quotes in these 4 weeks.") }}
            </p>
            <div
              v-for="q in card.quotes || []"
              :key="q.ref"
              class="p-2 space-y-1 rounded bg-gray-50"
            >
              <p
                class="text-sm text-gray-800 whitespace-pre-line"
                dir="auto"
                :class="getFontFamily(q.quote || '')"
              >
                {{ q.quote }}
              </p>
              <p v-if="q.quote_en && q.quote_en !== q.quote" class="text-xs text-gray-500">
                <span>{{ __("AI translation:") }}</span>
                <span class="whitespace-pre-line" dir="auto" :class="getFontFamily(q.quote_en)">
                  {{ q.quote_en }}
                </span>
              </p>
              <div class="flex flex-wrap items-center gap-x-2 text-xs text-gray-500">
                <span>{{ roleLabel(q.role) }}</span>
                <span>{{ fmtDate(q.date) }}</span>
                <span>{{ q.channel }}</span>
                <span v-if="!q.has_ticket" class="text-amber-700">{{ __("no ticket yet") }}</span>
                <button
                  type="button"
                  class="ml-auto font-medium text-gray-700 hover:underline"
                  @click.stop="openCase(q.ref)"
                >
                  {{ __("Open ↗") }}
                </button>
              </div>
            </div>
            <div v-if="card.action" class="flex flex-wrap items-center gap-1 text-xs">
              <Badge
                :theme="card.action.overdue ? 'red' : 'blue'"
                :label="
                  card.action.overdue
                    ? __('Action overdue')
                    : __('Action: {0}', __(card.action.status || 'Open'))
                "
              />
              <template v-if="card.action.verdict">
                <Badge
                  :theme="verdictMeta(card.action.verdict).theme"
                  :label="verdictMeta(card.action.verdict).label"
                />
                <span class="text-gray-500">{{ __("association, not proof") }}</span>
              </template>
            </div>
          </div>
        </div>
      </section>

      <div class="grid gap-4 lg:grid-cols-2">
        <!-- 4. What changed -->
        <section class="p-4 bg-white border border-gray-200 rounded-lg">
          <h2 class="mb-2 text-sm font-medium text-gray-900">{{ __("What changed") }}</h2>
          <p v-if="!brief.changed?.length" class="text-sm text-gray-500">
            {{ __("No problem changed enough to flag.") }}
          </p>
          <ul v-else class="divide-y divide-gray-100">
            <li v-for="c in brief.changed" :key="c.code" class="py-2 space-y-0.5">
              <button
                type="button"
                class="flex flex-wrap items-center gap-2 text-left"
                @click="emit('open-issue', c.code)"
              >
                <Badge :theme="badgeMeta(c.badge).theme" :label="badgeMeta(c.badge).label" />
                <span class="text-sm font-medium text-gray-900 hover:underline">{{ c.label }}</span>
                <span class="text-sm text-gray-700">{{ c.text }}</span>
              </button>
              <p v-if="badgeMeta(c.badge).tooltip" class="text-xs text-gray-500">
                {{ badgeMeta(c.badge).tooltip }}
              </p>
            </li>
          </ul>
        </section>

        <!-- 5. Demand & requests -->
        <section class="p-4 space-y-3 bg-white border border-gray-200 rounded-lg">
          <h2 class="text-sm font-medium text-gray-900">{{ __("Demand & requests") }}</h2>
          <p v-if="!demand.top?.length" class="text-sm text-gray-500">
            {{ __("No enquiries or requests this week.") }}
          </p>
          <div v-else class="overflow-x-auto">
            <table class="min-w-full text-sm">
              <thead>
                <tr class="text-left text-gray-500 border-b border-gray-200">
                  <th class="px-3 py-2 font-medium whitespace-nowrap">{{ __("Topic") }}</th>
                  <th class="px-3 py-2 font-medium text-right whitespace-nowrap">{{ __("Cases") }}</th>
                  <th class="px-3 py-2 font-medium whitespace-nowrap">{{ __("vs 4-week average") }}</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="d in demand.top"
                  :key="d.code"
                  class="border-b border-gray-100 last:border-b-0 hover:bg-gray-50"
                >
                  <td class="px-3 py-2">
                    <button
                      type="button"
                      class="text-left text-gray-900 hover:underline"
                      @click="emit('open-issue', d.code)"
                    >
                      {{ d.label }}
                    </button>
                  </td>
                  <td class="px-3 py-2 text-right text-gray-700">{{ num(d.cases) }}</td>
                  <td class="px-3 py-2 text-xs whitespace-nowrap">
                    <template v-if="d.chip">
                      <span
                        v-if="d.chip.label"
                        class="px-1.5 mr-1 rounded-full"
                        :class="chipClass(d.chip.label)"
                      >
                        {{ __(d.chip.label) }}
                      </span>
                      <span class="text-gray-600">{{ d.chip.text }}</span>
                    </template>
                    <span v-else class="text-gray-400">—</span>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <dl class="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
            <div>
              <dt class="text-xs text-gray-500">{{ __("In Arabic") }}</dt>
              <dd class="text-gray-900">{{ pct(demand.arabic_share) }}</dd>
            </div>
            <div>
              <dt class="text-xs text-gray-500">{{ __("Public comments") }}</dt>
              <dd class="text-gray-900">{{ num(demand.public_comments) }}</dd>
            </div>
            <div>
              <dt class="text-xs text-gray-500">{{ __("Praise") }}</dt>
              <dd class="text-gray-900">{{ num(demand.praise) }}</dd>
            </div>
            <div>
              <dt class="text-xs text-gray-500">{{ __("Suggestions") }}</dt>
              <dd class="text-gray-900">{{ num(demand.suggestions) }}</dd>
            </div>
          </dl>
        </section>
      </div>

      <!-- 6. Phase 2: actions and decisions -->
      <section v-if="brief.actions" class="p-4 space-y-3 bg-white border border-gray-200 rounded-lg">
        <div class="flex flex-wrap items-center justify-between gap-2">
          <h2 class="text-sm font-medium text-gray-900">{{ __("Actions & follow-through") }}</h2>
          <Button size="sm" variant="ghost" :label="__('Open actions')" @click="goTab('actions')" />
        </div>
        <div class="grid gap-4 md:grid-cols-2">
          <div v-for="group in actionGroups" :key="group.key" class="min-w-0">
            <h3 class="mb-1 text-xs font-medium text-gray-500">
              {{ group.title }} ({{ group.rows.length }})
            </h3>
            <p v-if="!group.rows.length" class="text-sm text-gray-400">{{ __("None") }}</p>
            <ul v-else class="space-y-2">
              <li v-for="a in group.rows" :key="a.name" class="space-y-0.5">
                <button type="button" class="block w-full text-left" @click="goTab('actions')">
                  <span
                    class="text-sm text-gray-900 whitespace-pre-line hover:underline"
                    dir="auto"
                    :class="getFontFamily(a.title || '')"
                  >
                    {{ a.title }}
                  </span>
                  <span class="block text-xs text-gray-500" :class="{ 'text-red-600': a.overdue }">
                    {{ actionLine(a) }}
                  </span>
                </button>
                <div v-if="a.verdict" class="flex flex-wrap items-center gap-1 text-xs">
                  <Badge :theme="verdictMeta(a.verdict).theme" :label="verdictMeta(a.verdict).label" />
                  <span class="text-gray-500">{{ __("association, not proof") }}</span>
                </div>
              </li>
            </ul>
          </div>
        </div>
      </section>

      <section v-if="brief.decisions" class="p-4 bg-white border border-gray-200 rounded-lg">
        <h2 class="mb-2 text-sm font-medium text-gray-900">{{ __("Decisions needed") }}</h2>
        <p v-if="!brief.decisions.length" class="text-sm text-gray-500">
          {{ __("Nothing is waiting on a decision.") }}
        </p>
        <ul v-else class="divide-y divide-gray-100">
          <li v-for="(d, i) in brief.decisions" :key="i">
            <button
              type="button"
              class="flex items-center w-full gap-2 py-2 text-sm text-left hover:bg-gray-50"
              @click="decide(d)"
            >
              <Badge v-if="d.kind" :label="kindLabel(d.kind)" />
              <span class="flex-1 min-w-0 text-gray-800" dir="auto">{{ d.text }}</span>
              <LucideChevronRight class="text-gray-400 size-4 shrink-0" />
            </button>
            <!-- the call-back list (customers who want to cancel): contact refs only -->
            <div v-if="d.refs?.length" class="flex flex-wrap pb-2 text-xs gap-x-3 gap-y-1">
              <button
                v-for="(ref, j) in d.refs.slice(0, 10)"
                :key="ref"
                type="button"
                class="text-gray-600 hover:underline"
                @click="openCase(ref)"
              >
                {{ __("Case {0} ↗", String(j + 1)) }}
              </button>
              <span v-if="d.refs.length > 10" class="text-gray-400">
                {{ __("and {0} more", num(d.refs.length - 10)) }}
              </span>
            </div>
          </li>
        </ul>
      </section>

      <!-- Footer -->
      <footer class="flex flex-wrap pt-2 text-xs text-gray-500 border-t border-gray-200 gap-x-4 gap-y-1">
        <span v-if="footer.season">{{ __("Season: {0}", footer.season) }}</span>
        <span>{{ excludedText }}</span>
        <span>{{ addedText }}</span>
        <span>{{ __("Label version {0}", status?.version?.current || "—") }}</span>
        <span>
          {{
            footer.validated
              ? __("Validated against the gold set")
              : __("Not yet validated — treat trends as directional")
          }}
        </span>
        <span v-if="footer.model">{{ __("Labelling model {0}", footer.model) }}</span>
      </footer>
    </template>
  </div>
</template>

<script setup lang="ts">
import { dayjs } from "@/dayjs";
import { __ } from "@/translation";
import { getFontFamily } from "@/utils";
import { Badge, Button, Tooltip, call } from "frappe-ui";
import { computed, onBeforeUnmount, reactive, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import LucideChevronRight from "~icons/lucide/chevron-right";
import LucideDownload from "~icons/lucide/download";
import LucideSparkles from "~icons/lucide/sparkles";
import LucideTriangleAlert from "~icons/lucide/triangle-alert";
import SafetyBox from "./SafetyBox.vue";
import {
  badgeMeta,
  chipClass,
  fillPlaceholders,
  roleLabel,
  sparklinePath,
  verdictMeta,
} from "./aiAnalysis";

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

const API = "helpdesk.api.ai_analysis.";
const selectClass = "text-sm rounded-lg border-gray-200 py-1.5";
const route = useRoute();
const router = useRouter();

const brief = ref<Record<string, any> | null>(null);
const loading = ref(false);
const error = ref("");
let loadSeq = 0;

// the Brief owns ?week= (company-wide, so the page filters do not apply); blank = last complete covered week
const routeWeek = computed(() => {
  const w = route.query.week;
  return typeof w === "string" && /^\d{4}-\d{2}-\d{2}$/.test(w) ? w : "";
});

async function load() {
  const seq = ++loadSeq;
  loading.value = true;
  error.value = "";
  try {
    const data = await call(API + "get_brief", routeWeek.value ? { week: routeWeek.value } : {});
    if (seq === loadSeq) brief.value = data;
  } catch (e) {
    if (seq === loadSeq) error.value = errText(e);
  } finally {
    if (seq === loadSeq) loading.value = false;
  }
}

function setWeek(week: string) {
  if (week && week !== brief.value?.week) router.replace({ query: { ...route.query, week } });
}
function onWeekChange(e: Event) {
  setWeek((e.target as HTMLSelectElement).value);
}

const weekOptions = computed<string[]>(() => {
  const weeks = [...(brief.value?.weeks || [])];
  const current = brief.value?.week;
  if (current && !weeks.includes(current)) weeks.push(current); // an uncovered week opened from a link
  return weeks.sort().reverse();
});

const isAi = computed(() => brief.value?.headline?.source === "ai");
const segments = computed(() =>
  isAi.value ? fillPlaceholders(brief.value!.headline.text || "", brief.value!.headline.values || {}) : []
);
// the weekly summary's bullets ({code, kind, text, cites}) share the headline's values
const bullets = computed(() => {
  const h = brief.value?.headline;
  if (!isAi.value || !Array.isArray(h?.bullets)) return [];
  return h.bullets
    .filter((b: any) => b?.text)
    .map((b: any) => ({ text: String(b.text), segments: fillPlaceholders(b.text, h.values || {}) }));
});
const demand = computed(() => brief.value?.demand || {});
const footer = computed(() => brief.value?.footer || {});

const aiBlocked = computed(() => {
  const s = props.status;
  if (!s) return __("Checking whether AI is available…");
  if (!s.ai_ready) return s.ai_reason || __("AI is off.");
  if (!s.worker_running) return __("Background worker not running.");
  return "";
});

// --- Write summary: queue the job, poll the insight every 3 s, then reload the brief ---------------
const summary = reactive({ busy: false, label: "", error: "" });
let pollTimer: ReturnType<typeof setTimeout> | undefined;
let pollSeq = 0;

function stopPoll() {
  clearTimeout(pollTimer);
  pollSeq++;
  Object.assign(summary, { busy: false, label: "" });
}

async function writeSummary() {
  if (!brief.value) return;
  stopPoll();
  const seq = pollSeq;
  Object.assign(summary, { busy: true, error: "" });
  try {
    const res = await call(API + "write_summary", {
      week: brief.value.week,
      regenerate: isAi.value ? 1 : 0,
    });
    if (seq === pollSeq) poll(res.insight, seq);
  } catch (e) {
    if (seq === pollSeq) Object.assign(summary, { busy: false, error: errText(e) });
  }
}

async function poll(name: string, seq: number) {
  let insight: Record<string, any>;
  try {
    insight = await call(API + "get_insight", { name });
  } catch (e) {
    if (seq === pollSeq) Object.assign(summary, { busy: false, error: errText(e) });
    return;
  }
  if (seq !== pollSeq) return;
  if (insight.status === "Queued" || insight.status === "Running") {
    summary.label = insight.progress_label || __(insight.status);
    pollTimer = setTimeout(() => poll(name, seq), 3000);
    return;
  }
  Object.assign(summary, { busy: false, label: "" });
  if (insight.status !== "Done") {
    summary.error =
      insight.error || __("The summary did not pass the checks, so the code-built headline stays.");
  }
  emit("refresh-status");
  load();
}

// --- small helpers ------------------------------------------------------------------------------
const actionGroups = computed(() => {
  const a = brief.value?.actions || {};
  return [
    { key: "due", title: __("Due this week"), rows: a.due || [] },
    { key: "overdue", title: __("Overdue"), rows: a.overdue || [] },
    { key: "verdicts", title: __("Verdicts"), rows: a.verdicts || [] },
    { key: "recurred", title: __("Fixes that recurred"), rows: a.recurred || [] },
  ];
});

function actionLine(a: Record<string, any>) {
  return [
    a.label || a.issue_code,
    a.assigned_to_name || a.owner_department,
    a.due_date ? __("due {0}", fmtDate(a.due_date)) : "",
    a.status ? __(a.status) : "",
  ]
    .filter(Boolean)
    .join(" · ");
}

// an action item also names its issue: the Actions tab is where it is resolved
function decide(d: Record<string, any>) {
  if (d.action) goTab("actions");
  else if (d.issue) emit("open-issue", d.issue);
  else if (d.tab) goTab(d.tab);
}

function goTab(tab: string) {
  router.replace({ query: { ...route.query, tab } });
}

function kindLabel(kind: string) {
  const text = String(kind).replace(/_/g, " ");
  return __(text.charAt(0).toUpperCase() + text.slice(1));
}

const excludedText = computed(() => {
  const by = Object.entries(footer.value.exclusions_by_reason || {})
    .map(([reason, n]) => `${reason}: ${num(n as number)}`)
    .join(", ");
  return __("{0} contacts excluded", num(footer.value.excluded)) + (by ? ` (${by})` : "");
});

const addedText = computed(() => {
  const added: Record<string, any>[] = footer.value.exclusions_added || [];
  if (!added.length) return __("No exclusions added this week");
  const who = added.map((a) => __("{0} by {1}", num(a.n), a.by || __("unknown"))).join(", ");
  return __("Exclusions added this week: {0}", who);
});

function openCase(ref: string) {
  window.open(
    "/api/method/helpdesk.api.ai_analysis.open_case?ref=" + encodeURIComponent(ref),
    "_blank",
    "noopener"
  );
}

function downloadPdf() {
  if (!brief.value) return;
  const week = encodeURIComponent(brief.value.week);
  window.open(`/api/method/${API}download_brief?week=${week}`, "_blank", "noopener");
}

function errText(e: any): string {
  return (e?.messages?.length ? e.messages.join(" ") : e?.message) || __("Something went wrong.");
}

function fmtDate(d?: string | null) {
  return d ? dayjs(d).format("D MMM YYYY") : "—";
}
function fmtDateTime(d?: string | null) {
  return d ? dayjs(d).format("D MMM YYYY, h:mm A") : "—";
}
function num(n?: number | null) {
  return n == null ? "—" : Number(n).toLocaleString("en");
}
function pct(x?: number | null) {
  return x == null ? "—" : `${Math.round(x * 100)}%`;
}

watch(routeWeek, () => {
  stopPoll();
  summary.error = "";
  load();
});
// a finished analysis run changes the numbers
watch(
  () => props.status?.running,
  (now, was) => {
    if (was && !now) load();
  }
);
onBeforeUnmount(stopPoll);
load();
</script>
