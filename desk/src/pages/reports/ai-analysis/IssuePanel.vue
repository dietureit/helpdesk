<template>
  <Dialog v-model="open" :options="{ size: '5xl' }" @close="emit('close')">
    <template #body-title>
      <div class="flex flex-wrap items-center gap-2 pr-2">
        <h3 class="text-lg font-semibold text-gray-900 sm:text-xl">{{ issue?.label || code }}</h3>
        <Badge :label="issue?.code || code" size="sm" />
      </div>
    </template>

    <template #body-content>
      <div class="space-y-6 text-sm ai-issue-panel">
        <div
          v-if="error"
          class="flex flex-wrap items-center justify-between gap-2 p-3 text-red-700 border border-red-200 rounded-lg bg-red-50"
        >
          <span>{{ error }}</span>
          <Button :label="__('Retry')" :loading="loading" @click="loadIssue" />
        </div>

        <div v-if="!issue && !error" class="space-y-3 animate-pulse">
          <div class="w-2/3 h-4 bg-gray-200 rounded"></div>
          <div class="w-full h-4 bg-gray-200 rounded"></div>
          <div class="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <div v-for="i in 8" :key="i" class="h-16 bg-gray-200 rounded-lg"></div>
          </div>
          <div class="h-64 bg-gray-200 rounded-lg"></div>
        </div>

        <template v-if="issue">
          <!-- Summary -->
          <section class="space-y-3" :class="{ 'opacity-60': loading }">
            <div class="flex flex-wrap items-center text-gray-600 gap-x-3 gap-y-1">
              <span>{{ __("Owner: {0}", issue.owner_department || "—") }}</span>
              <span>{{ __("Kind: {0}", __(issue.kind || "Other")) }}</span>
              <span v-if="issue.family">{{ __("Family: {0}", issue.family) }}</span>
              <Badge v-if="issue.is_food_safety" theme="red" :label="__('Food safety')" size="sm" />
            </div>
            <p v-if="issue.definition" class="text-gray-700 whitespace-pre-line" dir="auto">
              {{ issue.definition }}
            </p>
            <dl class="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <div
                v-for="n in numbers"
                :key="n.label"
                class="min-w-0 p-3 border border-gray-200 rounded-lg"
              >
                <dt class="text-xs text-gray-500">{{ __(n.label) }}</dt>
                <dd class="mt-0.5 text-lg font-semibold text-gray-900">{{ n.value }}</dd>
                <dd v-if="n.note" class="text-xs text-gray-500">{{ n.note }}</dd>
              </div>
            </dl>
            <ul v-if="issue.badges?.length" class="space-y-1">
              <li v-for="b in issue.badges" :key="b.key" class="flex items-start gap-2">
                <Badge
                  :label="badgeMeta(b.key).label"
                  :theme="badgeMeta(b.key).theme"
                  size="sm"
                  class="shrink-0"
                />
                <span class="text-gray-700">{{ b.text || badgeMeta(b.key).tooltip }}</span>
              </li>
            </ul>
            <p v-if="issue.season" class="text-gray-600">
              {{ __("This period overlaps {0}: season weeks are shaded on the chart and left out of baselines.", issue.season) }}
            </p>
            <div v-if="issue.co_occurring?.length" class="flex flex-wrap items-center gap-1.5">
              <span class="text-gray-500">{{ __("Raised together with") }}</span>
              <Badge
                v-for="c in issue.co_occurring"
                :key="c.code"
                :label="`${c.label} (${num(c.n)})`"
                size="sm"
              />
            </div>
            <div v-if="issue.offered?.length" class="flex flex-wrap items-center gap-1.5">
              <span class="text-gray-500">{{ __("What was offered") }}</span>
              <Badge
                v-for="o in issue.offered"
                :key="o.key"
                :label="`${__(o.label)} ${pct(o.share)} (${num(o.n)})`"
                size="sm"
              />
            </div>
          </section>

          <!-- Trend -->
          <section class="space-y-2">
            <h4 :class="H">{{ __("Trend") }}</h4>
            <div v-if="issue.weekly?.length" class="overflow-x-auto">
              <div class="h-[300px] min-w-[300px]">
                <ECharts :options="chartOptions" />
              </div>
            </div>
            <p v-else class="text-gray-500">{{ __("No weekly data for this issue.") }}</p>
            <p class="text-xs text-gray-500">
              {{ __("Shaded weeks fall in a season or have too little chat data; they are left out of baselines.") }}
            </p>
          </section>

          <!-- Where -->
          <section class="space-y-3">
            <h4 :class="H">{{ __("Where") }}</h4>
            <div class="grid gap-4 md:grid-cols-2">
              <div class="overflow-x-auto border border-gray-200 rounded-lg">
                <table class="min-w-full text-sm">
                  <thead>
                    <tr class="text-left text-gray-500 border-b border-gray-200">
                      <th class="px-3 py-2 font-medium">{{ __("Channel") }}</th>
                      <th class="px-3 py-2 font-medium text-right">{{ __("Cases") }}</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr
                      v-for="c in where.channels"
                      :key="c.channel"
                      class="border-b border-gray-100 last:border-b-0"
                    >
                      <td class="px-3 py-2 text-gray-700">{{ c.channel }}</td>
                      <td class="px-3 py-2 text-right text-gray-900">{{ num(c.cases) }}</td>
                    </tr>
                    <tr v-if="!where.channels.length">
                      <td colspan="2" class="px-3 py-2 text-gray-400">
                        {{ __("No cases in this period.") }}
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
              <div class="overflow-x-auto border border-gray-200 rounded-lg">
                <table class="min-w-full text-sm">
                  <thead>
                    <tr class="text-left text-gray-500 border-b border-gray-200">
                      <th class="px-3 py-2 font-medium">{{ __("Weekday") }}</th>
                      <th class="px-3 py-2 font-medium text-right">{{ __("Cases") }}</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr
                      v-for="w in where.weekdays"
                      :key="w.weekday"
                      class="border-b border-gray-100 last:border-b-0"
                    >
                      <td class="px-3 py-2 text-gray-700">{{ __(w.weekday) }}</td>
                      <td class="px-3 py-2 text-right text-gray-900">{{ num(w.cases) }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>
            <div class="overflow-x-auto border border-gray-200 rounded-lg">
              <table class="min-w-full text-sm">
                <thead>
                  <tr class="text-left text-gray-500 border-b border-gray-200">
                    <th class="px-3 py-2 font-medium">{{ __("Dish") }}</th>
                    <th class="px-3 py-2 font-medium text-right whitespace-nowrap">{{ __("Cases") }}</th>
                    <th class="px-3 py-2 font-medium text-right whitespace-nowrap">
                      {{ __("Meals delivered") }}
                    </th>
                    <th class="px-3 py-2 font-medium text-right whitespace-nowrap">
                      {{ __("Expected cases") }}
                    </th>
                    <th class="px-3 py-2 font-medium">{{ __("Flag") }}</th>
                  </tr>
                </thead>
                <tbody>
                  <tr
                    v-for="d in where.dishes"
                    :key="d.dish"
                    class="border-b border-gray-100 last:border-b-0"
                  >
                    <td class="px-3 py-2 text-gray-700">{{ d.dish }}</td>
                    <td class="px-3 py-2 text-right text-gray-900">{{ num(d.cases) }}</td>
                    <td class="px-3 py-2 text-right text-gray-700">{{ num(d.meals) }}</td>
                    <td class="px-3 py-2 text-right text-gray-700">
                      {{ d.expected == null ? "—" : Number(d.expected).toFixed(2) }}
                    </td>
                    <td class="px-3 py-2">
                      <Tooltip v-if="d.flag" :text="pText(d.p)">
                        <span><Badge theme="red" :label="__('Flagged')" size="sm" /></span>
                      </Tooltip>
                      <span v-else class="text-gray-400">—</span>
                    </td>
                  </tr>
                  <tr v-if="!where.dishes.length">
                    <td colspan="5" class="px-3 py-2 text-gray-400">
                      {{ __("No case was matched to a dish on the menu.") }}
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
            <p class="text-xs text-gray-500">
              {{ __("A dish is flagged only when it has more cases than its share of meals delivered predicts (p < 0.01, at least 300 meals and 3 cases).") }}
            </p>
          </section>

          <!-- Evidence -->
          <section class="space-y-2">
            <div>
              <h4 :class="H">
                {{ __("Evidence") }}
                <span v-if="ev.loaded" class="text-sm font-normal text-gray-500">({{ num(ev.total) }})</span>
              </h4>
              <p class="text-xs text-gray-500">
                {{ __("Verified quotes, one per contact, worst severity first.") }}
              </p>
            </div>
            <div
              v-if="ev.error"
              class="flex flex-wrap items-center justify-between gap-2 p-3 text-red-700 border border-red-200 rounded-lg bg-red-50"
            >
              <span>{{ ev.error }}</span>
              <Button
                :label="__('Retry')"
                :loading="ev.loading"
                @click="loadEvidence(!ev.rows.length)"
              />
            </div>
            <div v-if="!ev.loaded && !ev.error" class="space-y-2 animate-pulse">
              <div v-for="i in 3" :key="i" class="h-16 bg-gray-200 rounded-lg"></div>
            </div>
            <p v-else-if="ev.loaded && !ev.rows.length" class="text-gray-500">
              {{ __("No verified quotes in this period.") }}
            </p>
            <ul
              v-if="ev.rows.length"
              class="border border-gray-200 divide-y divide-gray-100 rounded-lg"
            >
              <li
                v-for="row in ev.rows"
                :key="row.ref"
                class="p-3 space-y-2"
                :class="{ 'bg-gray-50': row.review === 'Rejected' }"
              >
                <div class="flex flex-wrap items-center gap-1.5 text-xs text-gray-500">
                  <Badge :label="roleLabel(row.role)" size="sm" />
                  <span>{{ fmtDate(row.date) }}</span>
                  <span>·</span>
                  <span>{{ row.channel || "—" }}</span>
                  <Badge
                    v-if="row.severity"
                    :label="row.severity"
                    :theme="SEV_THEME[row.severity] || 'gray'"
                    size="sm"
                  />
                  <Tooltip :text="quoteStatusTip(row.quote_status)">
                    <span>
                      <Badge
                        :label="__(row.quote_status || 'Unverified')"
                        :theme="row.quote_status === 'Verified' ? 'green' : 'blue'"
                        variant="outline"
                        size="sm"
                      />
                    </span>
                  </Tooltip>
                  <span v-if="row.ticket">{{ __("Ticket #{0}", String(row.ticket)) }}</span>
                </div>
                <p
                  class="text-gray-900 break-words whitespace-pre-line"
                  dir="auto"
                  :class="getFontFamily(row.quote || '')"
                >
                  {{ row.quote }}
                </p>
                <div v-if="showTranslation(row)">
                  <span class="text-xs font-medium text-gray-500">{{ __("AI translation") }}</span>
                  <p
                    class="text-gray-600 break-words whitespace-pre-line"
                    dir="auto"
                    :class="getFontFamily(row.quote_en || '')"
                  >
                    {{ row.quote_en }}
                  </p>
                </div>
                <div class="flex flex-wrap items-center gap-2">
                  <Button size="sm" @click="openCase(row.ref)">{{ __("Open") }} ↗</Button>
                  <Badge
                    v-if="row.review"
                    :label="REVIEW_LABEL[row.review] ? __(REVIEW_LABEL[row.review]) : row.review"
                    :theme="REVIEW_THEME[row.review] || 'gray'"
                    size="sm"
                  />
                  <Button
                    v-if="!row.review"
                    size="sm"
                    variant="ghost"
                    :label="__('Wrong label?')"
                    :loading="busy[row.ref]"
                    @click="flag(row)"
                  />
                  <template v-if="canDecide">
                    <template v-if="row.review !== 'Confirmed' && row.review !== 'Rejected'">
                      <Button
                        size="sm"
                        theme="green"
                        variant="subtle"
                        :label="__('Confirm')"
                        :disabled="busy[row.ref]"
                        @click="review(row, 'Confirmed')"
                      />
                      <Button
                        size="sm"
                        theme="red"
                        variant="subtle"
                        :label="__('Reject')"
                        :disabled="busy[row.ref]"
                        @click="review(row, 'Rejected')"
                      />
                    </template>
                    <Button
                      v-else
                      size="sm"
                      variant="ghost"
                      :label="__('Undo')"
                      :loading="busy[row.ref]"
                      @click="review(row, '')"
                    />
                  </template>
                  <span v-if="rowError[row.ref]" class="text-xs text-red-600">{{ rowError[row.ref] }}</span>
                </div>
              </li>
            </ul>
            <div
              v-if="hasMore"
              class="flex flex-wrap items-center justify-between gap-2 text-xs text-gray-500"
            >
              <span>{{ __("Showing the first {0} of {1}.", String(kept), String(ev.total)) }}</span>
              <Button
                size="sm"
                :label="__('Show {0} more', String(Math.min(PAGE, ev.total - kept)))"
                :loading="ev.loading"
                @click="loadEvidence(false)"
              />
            </div>
          </section>

          <!-- Tickets -->
          <section v-if="ticketIds.length" class="space-y-1">
            <RouterLink :to="ticketsRoute" class="font-medium text-gray-900 hover:underline">
              {{
                ticketIds.length === 1
                  ? __("Open this ticket →")
                  : __("Open these {0} tickets →", String(ticketIds.length))
              }}
            </RouterLink>
            <p class="text-xs text-gray-500">
              {{ __("The ticket list applies your team restrictions, so it may show fewer.") }}
            </p>
          </section>

          <!-- Suggestions (Phase 2) -->
          <section>
            <SuggestionsSection
              v-if="showSuggestions"
              :code="code"
              :kind="issue.kind"
              :filters="filters"
              :can-decide="canDecide"
              :status="status"
              :suggestions="issue.suggestions"
              :research="issue.research"
              @refresh-status="emit('refresh-status')"
            />
            <div v-else class="flex flex-wrap items-center gap-2">
              <Button :label="__('Get suggestions')" :disabled="!!aiBlocked" @click="revealed = true">
                <template #prefix><LucideSparkles class="w-4 h-4" /></template>
              </Button>
              <span class="text-xs text-gray-500">
                {{ aiBlocked || __("Optional for demand and feedback: AI proposes fixes grounded in these quotes.") }}
              </span>
            </div>
          </section>
        </template>
      </div>
    </template>
  </Dialog>
</template>

<script setup lang="ts">
import { dayjs } from "@/dayjs";
import { __ } from "@/translation";
import { getFontFamily } from "@/utils";
import { Badge, Button, Dialog, ECharts, Tooltip, call } from "frappe-ui";
import { computed, reactive, ref, watch } from "vue";
import { RouterLink } from "vue-router";
import LucideSparkles from "~icons/lucide/sparkles";
import SuggestionsSection from "./SuggestionsSection.vue";
import { badgeMeta, roleLabel, trendOptions } from "./aiAnalysis";

const props = defineProps<{
  code: string;
  filters?: Record<string, any>;
  canDecide?: boolean;
  status?: Record<string, any> | null;
}>();
const emit = defineEmits<{
  (e: "close"): void;
  (e: "refresh-status"): void;
}>();

const H = "text-base font-semibold text-gray-900";
const PAGE = 30;
const SEV_THEME: Record<string, string> = { S1: "red", S2: "orange", S3: "blue", S4: "gray" };
const REVIEW_LABEL: Record<string, string> = {
  Flagged: "Flagged for review",
  Confirmed: "Confirmed",
  Rejected: "Rejected: not counted",
};
const REVIEW_THEME: Record<string, string> = { Flagged: "orange", Confirmed: "green", Rejected: "red" };

const open = ref(true); // the shell mounts the panel while ?issue= is set
const params = computed(() => ({
  from_date: props.filters?.from_date || undefined,
  to_date: props.filters?.to_date || undefined,
  channel: props.filters?.channel || undefined,
  dept: props.filters?.dept || undefined,
}));

const issue = ref<Record<string, any> | null>(null);
const loading = ref(false);
const error = ref("");
let seq = 0; // only the latest request may land

async function loadIssue() {
  const mine = ++seq;
  loading.value = true;
  error.value = "";
  try {
    const res = await call("helpdesk.api.ai_analysis.get_issue", { ...params.value, code: props.code });
    if (mine === seq) issue.value = res;
  } catch (e: any) {
    if (mine === seq) error.value = errorText(e);
  } finally {
    if (mine === seq) loading.value = false;
  }
}

const ev = reactive({ rows: [] as Record<string, any>[], total: 0, loading: false, loaded: false, error: "" });
let evSeq = 0;
// Rejected rows stay on screen (for Undo) but leave the server's list, so the next page starts after
// the rows still counted, and the total drops by one per rejection.
const kept = computed(() => ev.rows.filter((r) => r.review !== "Rejected").length);
const hasMore = computed(() => ev.loaded && kept.value < ev.total);

async function loadEvidence(reset: boolean) {
  const mine = ++evSeq;
  ev.loading = true;
  ev.error = "";
  try {
    const res = await call("helpdesk.api.ai_analysis.get_evidence", {
      ...params.value,
      code: props.code,
      start: reset ? 0 : kept.value,
      limit: PAGE,
    });
    if (mine !== evSeq) return;
    const fresh: Record<string, any>[] = res?.rows || [];
    if (reset) {
      ev.rows = fresh;
    } else {
      const seen = new Set(ev.rows.map((r) => r.ref));
      ev.rows.push(...fresh.filter((r) => !seen.has(r.ref)));
    }
    ev.total = res?.total ?? ev.rows.length;
    ev.loaded = true;
  } catch (e: any) {
    if (mine === evSeq) ev.error = errorText(e);
  } finally {
    if (mine === evSeq) ev.loading = false;
  }
}

const revealed = ref(false);
watch(
  () => [props.code, JSON.stringify(params.value)],
  (now, before) => {
    if (!before || before[0] !== now[0]) {
      // another issue: never show the previous one's numbers or quotes while loading
      issue.value = null;
      Object.assign(ev, { rows: [], total: 0, loaded: false });
      revealed.value = false;
    }
    loadIssue();
    loadEvidence(true);
  },
  { immediate: true }
);

const nf = new Intl.NumberFormat("en", { maximumFractionDigits: 2 });
function num(v: any) {
  return v == null || v === "" || Number.isNaN(Number(v)) ? "—" : nf.format(Number(v));
}
function fmtDate(d?: string | null) {
  return d ? dayjs(d).format("D MMM YYYY") : "—";
}
function pct(share: any) {
  return share == null ? "—" : `${Math.round(Number(share) * 100)}%`;
}
function pText(p: any) {
  if (p == null) return __("Funnel test");
  return __("Funnel test p {0}", p < 0.001 ? "< 0.001" : Number(p).toFixed(3));
}

const numbers = computed(() => {
  const n = issue.value?.numbers || {};
  const complaint = issue.value?.kind === "Complaint";
  let rateNote = complaint
    ? __("No rate without delivery coverage")
    : __("No rate without chat coverage");
  if (n.rate != null) {
    rateNote =
      n.exposure_kind === "Deliveries"
        ? __("per 1,000 deliveries")
        : __("cases per covered chat week");
  }
  return [
    { label: "Cases", value: num(n.cases) },
    { label: "Customers", value: num(n.customers) },
    { label: "Contacts", value: num(n.contacts) },
    { label: "Repeat contacts", value: num(n.repeat_contacts) },
    {
      label: "Weeks active",
      value: n.weeks_active == null ? "—" : __("{0} of 8", String(n.weeks_active)),
    },
    { label: "First seen", value: fmtDate(n.first_seen) },
    { label: "Last seen", value: fmtDate(n.last_seen) },
    { label: "Rate", value: n.rate == null ? "—" : Number(n.rate).toFixed(2), note: rateNote },
  ];
});

// get_issue's action is {name, status, overdue, verdict}: it gets a marker on the chart only once the
// server also sends its done_on (or due_date); trendOptions skips an action without a date.
const chartOptions = computed(() => {
  const a = issue.value?.action;
  const date = a?.done_on || a?.due_date;
  const actions = date ? [{ date, label: a.title || a.name || __("Action") }] : [];
  return trendOptions(issue.value?.weekly || [], { actions });
});
const where = computed(() => ({
  channels: issue.value?.where?.channels || [],
  weekdays: issue.value?.where?.weekdays || [],
  dishes: issue.value?.where?.dishes || [],
}));

const ticketIds = computed<string[]>(() => (issue.value?.ticket_ids || []).map(String));
// ponytail: every id rides in the URL; past a few hundred tickets, link a saved filter instead
const ticketsRoute = computed(() => ({
  name: "TicketsAgent",
  query: { filters: JSON.stringify({ name: ["in", ticketIds.value] }) },
}));

const showSuggestions = computed(
  () =>
    issue.value?.kind === "Complaint" ||
    revealed.value ||
    Boolean(issue.value?.suggestions || issue.value?.research)
);
const aiBlocked = computed(() => {
  const s = props.status;
  if (!s) return __("Checking whether AI is available…");
  if (!s.ai_ready) return s.ai_reason || __("AI is not available.");
  if (!s.worker_running) return __("Background worker not running.");
  return "";
});

function showTranslation(row: Record<string, any>) {
  return Boolean(row.quote_en) && String(row.quote_en).trim() !== String(row.quote || "").trim();
}
function quoteStatusTip(status?: string | null) {
  if (status === "Verified") return __("Found word for word in the source.");
  if (status === "Repaired") {
    return __("Found in the source with small differences; the quote shown is the exact source text.");
  }
  return __("Not found in the source.");
}
function openCase(ref: string) {
  window.open(
    "/api/method/helpdesk.api.ai_analysis.open_case?ref=" + encodeURIComponent(ref),
    "_blank",
    "noopener"
  );
}

const busy = reactive<Record<string, boolean>>({});
const rowError = reactive<Record<string, string>>({});

async function act(row: Record<string, any>, method: string, args: Record<string, any>) {
  busy[row.ref] = true;
  rowError[row.ref] = "";
  try {
    // row.code: the label's own code, should the server ever send it (a code merged into this one)
    const code = row.code || issue.value?.code || props.code;
    return await call(`helpdesk.api.ai_analysis.${method}`, { ref: row.ref, code, ...args });
  } catch (e: any) {
    rowError[row.ref] = errorText(e);
    return null;
  } finally {
    busy[row.ref] = false;
  }
}

async function flag(row: Record<string, any>) {
  const res = await act(row, "flag_label", {});
  if (!res) return;
  if (res.flagged) row.review = "Flagged";
  else rowError[row.ref] = __("Already reviewed. Refresh to see the review.");
}

async function review(row: Record<string, any>, value: "Confirmed" | "Rejected" | "") {
  const before = row.review;
  if (!(await act(row, "set_review", { review: value }))) return;
  row.review = value || null;
  if (value === "Rejected" || before === "Rejected") {
    ev.total += value === "Rejected" ? -1 : 1;
    // a rejected label leaves every count: refresh this panel's numbers
    // ponytail: the Issues table behind the panel catches up on its next load, not right away
    loadIssue();
  }
}

function errorText(e: any) {
  return (e?.messages?.length ? e.messages.join(" ") : e?.message) || __("Something went wrong.");
}
</script>

<style>
/* frappe-ui Dialog has no full-screen mode: below 640 px the issue panel takes the whole width */
@media (max-width: 639px) {
  .dialog-overlay > div:has(.ai-issue-panel) {
    padding: 0;
  }
  .dialog-content:has(.ai-issue-panel) {
    max-width: none;
    min-height: 100vh;
    margin: 0;
    border-radius: 0;
  }
}
</style>
