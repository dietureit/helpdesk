<template>
  <div class="space-y-4">
    <div class="flex flex-wrap items-center justify-between gap-2">
      <TabButtons v-model="filter" :buttons="filterButtons" />
      <p class="text-xs text-gray-500">
        {{ __("Verdicts compare cases before and after a fix: an association, not proof.") }}
      </p>
    </div>

    <div
      v-if="recurred"
      class="flex items-start gap-2 p-3 text-sm text-red-800 border border-red-200 rounded-lg bg-red-50"
    >
      <LucideRepeat class="w-4 h-4 mt-0.5 shrink-0" />
      <span>
        {{
          recurred === 1
            ? __("1 fix recurred: the problem came back after the fix was judged lower than before.")
            : __("{0} fixes recurred: the problem came back after the fixes were judged lower than before.", String(recurred))
        }}
      </span>
    </div>

    <div v-if="actions.s.error" :class="errorClass">
      <span class="flex-1 min-w-0">{{ actions.s.error }}</span>
      <Button :label="__('Retry')" :loading="actions.s.loading" @click="actions.load" />
    </div>

    <div v-if="actions.s.loading && !actions.s.data" class="p-4 space-y-2 bg-white border border-gray-200 rounded-lg animate-pulse">
      <div v-for="i in 4" :key="i" class="h-8 bg-gray-100 rounded"></div>
    </div>
    <div
      v-else-if="actions.s.data && !rows.length"
      class="flex flex-col items-center justify-center py-10 text-gray-400 bg-white border border-gray-200 rounded-lg"
    >
      <LucideListChecks class="w-8 h-8 mb-2" />
      <span class="px-4 text-sm text-center">{{ emptyText }}</span>
    </div>
    <div
      v-else-if="rows.length"
      class="overflow-x-auto bg-white border border-gray-200 rounded-lg"
      :class="{ 'opacity-60': actions.s.loading }"
    >
      <table class="min-w-full text-sm">
        <thead>
          <tr class="text-left text-gray-500 border-b border-gray-200">
            <th v-for="c in columns" :key="c" class="px-3 py-2 font-medium whitespace-nowrap">{{ c }}</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="row in rows"
            :key="row.name"
            class="align-top border-b border-gray-100 cursor-pointer last:border-b-0 hover:bg-gray-50"
            tabindex="0"
            @click="openRow(row)"
            @keydown.enter="openRow(row)"
          >
            <td class="px-3 py-2">
              <span
                class="block text-gray-900 max-w-xs whitespace-pre-line min-w-[10rem]"
                dir="auto"
                :class="font(row.title)"
              >{{ row.title || row.name }}</span>
            </td>
            <td class="px-3 py-2">
              <button
                type="button"
                class="text-left text-gray-900 hover:underline"
                @click.stop="emit('open-issue', row.issue_code)"
              >
                {{ row.label || row.issue_code || "—" }}
              </button>
            </td>
            <td class="px-3 py-2 whitespace-nowrap">
              <div class="text-gray-700">{{ row.owner_department || "—" }}</div>
              <div class="text-xs text-gray-500">{{ row.assigned_to_name || row.assigned_to || "—" }}</div>
            </td>
            <td class="px-3 py-2 whitespace-nowrap">
              <Badge
                :label="__(row.status || 'Open')"
                :theme="STATUS_THEME[row.status] || 'gray'"
                :variant="row.status === 'Dropped' ? 'outline' : 'subtle'"
              />
            </td>
            <td class="px-3 py-2 whitespace-nowrap" :class="row.overdue ? 'font-medium text-red-600' : 'text-gray-700'">
              {{ fmtDate(row.due_date) }}
              <div v-if="row.overdue" class="text-xs">{{ __("Overdue") }}</div>
            </td>
            <td class="px-3 py-2 whitespace-nowrap">
              <div class="text-gray-700">{{ fmtNum(row.baseline_value) }} → {{ fmtNum(row.target_value) }}</div>
              <div v-if="unitOf(row)" class="text-xs text-gray-400">{{ unitOf(row) }}</div>
              <div v-if="row.recent_value != null" class="text-xs text-gray-500">
                {{ __("Last 4 weeks before adoption: {0}", fmtNum(row.recent_value)) }}
              </div>
              <div v-if="row.target_met" class="text-xs text-green-700">{{ __("Target met") }}</div>
            </td>
            <td class="px-3 py-2 whitespace-nowrap">
              <Tooltip :text="verdictMeta(row.verdict).tooltip">
                <Badge :label="verdictMeta(row.verdict).label || __('Not yet')" :theme="verdictMeta(row.verdict).theme" />
              </Tooltip>
              <div class="text-xs text-gray-400">
                {{ __("association, not proof") }}
                <template v-if="TESTED.includes(row.verdict) && row.verdict_p != null">
                  · {{ __("p = {0}", fmtP(row.verdict_p)) }}
                </template>
              </div>
            </td>
            <td class="px-3 py-2 text-gray-700 whitespace-nowrap">{{ fmtDate(row.next_check) }}</td>
            <td class="px-3 py-2 whitespace-nowrap">
              <Badge v-if="row.recurred" theme="red" :label="__('Recurred')" />
              <span v-else class="text-gray-400">—</span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <section class="space-y-2">
      <div>
        <h2 class="text-base font-semibold text-gray-900">{{ __("Decisions log") }}</h2>
        <p class="text-xs text-gray-500">{{ __("Adopted and rejected plans, newest first. Click a row to open the issue.") }}</p>
      </div>
      <div v-if="decisions.s.error" :class="errorClass">
        <span class="flex-1 min-w-0">{{ decisions.s.error }}</span>
        <Button :label="__('Retry')" :loading="decisions.s.loading" @click="decisions.load" />
      </div>
      <div v-if="decisions.s.loading && !decisions.s.data" class="h-24 bg-white border border-gray-200 rounded-lg animate-pulse"></div>
      <p
        v-else-if="decisions.s.data && !decisionRows.length"
        class="py-6 text-sm text-center text-gray-400 bg-white border border-gray-200 rounded-lg"
      >
        {{ __("No plans adopted or rejected yet.") }}
      </p>
      <div v-else-if="decisionRows.length" class="overflow-x-auto bg-white border border-gray-200 rounded-lg">
        <table class="min-w-full text-sm">
          <thead>
            <tr class="text-left text-gray-500 border-b border-gray-200">
              <th v-for="c in decisionColumns" :key="c" class="px-3 py-2 font-medium whitespace-nowrap">{{ c }}</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="d in decisionRows"
              :key="d.insight"
              class="align-top border-b border-gray-100 cursor-pointer last:border-b-0 hover:bg-gray-50"
              tabindex="0"
              @click="emit('open-issue', d.issue_code)"
              @keydown.enter="emit('open-issue', d.issue_code)"
            >
              <td class="px-3 py-2 whitespace-nowrap">
                <Badge
                  :label="d.decision ? __(d.decision) : '—'"
                  :theme="d.decision === 'Adopted' ? 'green' : d.decision === 'Rejected' ? 'red' : 'gray'"
                />
              </td>
              <td class="px-3 py-2 text-gray-900">{{ d.label || d.issue_code || "—" }}</td>
              <td class="px-3 py-2 text-gray-700 whitespace-nowrap">{{ d.decision_reason ? __(d.decision_reason) : "—" }}</td>
              <td class="px-3 py-2 text-gray-700">
                <span class="block max-w-xs whitespace-pre-line" dir="auto" :class="font(d.decision_note)">{{ d.decision_note || "—" }}</span>
              </td>
              <td class="px-3 py-2 text-gray-700 whitespace-nowrap">{{ d.decided_by_name || "—" }}</td>
              <td class="px-3 py-2 text-gray-700 whitespace-nowrap">{{ fmtDateTime(d.decided_on) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <Dialog v-model="dlg.open" :options="{ size: 'xl' }">
      <template #body-title>
        <h3
          class="text-xl font-semibold text-gray-900 whitespace-pre-line"
          dir="auto"
          :class="font(dlg.row?.title)"
        >{{ dlg.row?.title || dlg.row?.name }}</h3>
      </template>
      <template #body-content>
        <div v-if="dlg.row" class="space-y-4 break-words">
          <dl class="grid grid-cols-1 gap-3 text-sm sm:grid-cols-2">
            <div>
              <dt class="text-xs text-gray-500">{{ __("Issue") }}</dt>
              <dd class="text-gray-900">{{ dlg.row.label || dlg.row.issue_code || "—" }}</dd>
            </div>
            <div>
              <dt class="text-xs text-gray-500">{{ __("Owner") }}</dt>
              <dd class="text-gray-900">
                {{ dlg.row.owner_department || "—" }} · {{ dlg.row.assigned_to_name || dlg.row.assigned_to || "—" }}
              </dd>
            </div>
            <div>
              <dt class="text-xs text-gray-500">{{ __("Due") }}</dt>
              <dd :class="dlg.row.overdue ? 'font-medium text-red-600' : 'text-gray-900'">
                {{ fmtDate(dlg.row.due_date) }}<template v-if="dlg.row.overdue"> · {{ __("Overdue") }}</template>
              </dd>
            </div>
            <div>
              <dt class="text-xs text-gray-500">{{ __("Verdict") }}</dt>
              <dd class="text-gray-900">
                {{ verdictMeta(dlg.row.verdict).label || __("Not yet") }}
                <span class="text-xs text-gray-500">· {{ __("association, not proof") }}</span>
              </dd>
            </div>
          </dl>
          <div v-if="dlg.row.plan">
            <div class="text-xs font-medium text-gray-500">{{ __("Plan") }}</div>
            <p
              class="text-sm text-gray-700 whitespace-pre-line"
              dir="auto"
              :class="font(dlg.row.plan)"
            >{{ dlg.row.plan }}</p>
          </div>
          <div v-if="verdictHistory(dlg.row).length">
            <div class="text-xs font-medium text-gray-500">{{ __("Verdict history") }}</div>
            <ul class="space-y-1 text-sm text-gray-700">
              <li v-for="(h, i) in verdictHistory(dlg.row)" :key="i">
                {{ fmtDate(h.checked_on) }}
                <template v-if="h.weeks"> · {{ __("{0} weeks after the fix", String(h.weeks)) }}</template>
                · {{ verdictMeta(h.verdict).label || h.verdict || "—" }}
                <template v-if="h.p != null"> · {{ __("p = {0}", fmtP(h.p)) }}</template>
              </li>
            </ul>
          </div>
          <template v-if="canEdit(dlg.row)">
            <FormControl v-model="dlg.status" type="select" :label="__('Status')" :options="statusOptions" />
            <FormControl v-if="dlg.status === 'Done'" v-model="dlg.done_on" type="date" :label="__('Done on')" />
            <FormControl
              v-model="dlg.note"
              type="textarea"
              :label="__('Note (optional)')"
              :placeholder="__('What was done, or why it was dropped')"
            />
            <p v-if="dlg.error" class="text-sm text-red-700">{{ dlg.error }}</p>
          </template>
          <p v-else class="text-xs text-gray-500">
            {{ __("Only the assignee or a manager can update this action.") }}
          </p>
        </div>
      </template>
      <template #actions>
        <div class="flex flex-wrap justify-end gap-2">
          <Button :label="__('Close')" @click="dlg.open = false" />
          <Button
            v-if="canEdit(dlg.row)"
            variant="solid"
            :label="__('Save')"
            :loading="dlg.saving"
            @click="save"
          />
        </div>
      </template>
    </Dialog>
  </div>
</template>

<script setup lang="ts">
import { dayjs } from "@/dayjs";
import { useAuthStore } from "@/stores/auth";
import { __ } from "@/translation";
import { getFontFamily } from "@/utils";
import { Badge, Button, call, Dialog, FormControl, TabButtons, Tooltip } from "frappe-ui";
import { computed, onMounted, reactive, ref, watch } from "vue";
import LucideListChecks from "~icons/lucide/list-checks";
import LucideRepeat from "~icons/lucide/repeat";
import { verdictMeta } from "./aiAnalysis";

type Row = Record<string, any>;

const props = defineProps<{ filters?: Row; status?: Row | null; canDecide?: boolean }>();
const emit = defineEmits<{
  (e: "open-issue", code: string): void;
  (e: "jump", window: { from_date: string; to_date: string }): void;
  (e: "refresh-status"): void;
}>();

const API = "helpdesk.api.ai_analysis.";
const errorClass =
  "flex flex-wrap items-center gap-3 p-3 text-sm text-red-700 border border-red-200 rounded-lg bg-red-50";
const STATUS_THEME: Row = { Open: "gray", "In progress": "blue", Done: "green", Dropped: "gray" };
// verdict_p is only meaningful for a tested verdict (the action stores 0 when there was no test)
const TESTED = ["Lower than before", "Inconclusive", "Higher than before"];

const filterButtons = [
  { label: __("Open"), value: "open" },
  { label: __("Overdue"), value: "overdue" },
  { label: __("Verifying"), value: "verifying" },
  { label: __("All"), value: "all" },
];
const columns = [
  __("Action"),
  __("Issue"),
  __("Owner"),
  __("Status"),
  __("Due"),
  __("Baseline → target"),
  __("Verdict"),
  __("Next check"),
  __("Recurred"),
];
const decisionColumns = [__("Decision"), __("Issue"), __("Reason"), __("Note"), __("By"), __("When")];
const statusOptions = ["Open", "In progress", "Done", "Dropped"].map((s) => ({ label: __(s), value: s }));

const auth = useAuthStore();

// getFontFamily returns a Tailwind class (Arabic → system-ui), so it is bound as a class
const font = (t: unknown) => getFontFamily(typeof t === "string" ? t : "");
const errText = (e: any) =>
  (e?.messages?.length ? e.messages.join(" ") : "") || __("Something went wrong. Try again.");
const fmtDate = (d: unknown) => (d ? dayjs(d as string).format("D MMM YYYY") : "—");
const fmtDateTime = (d: unknown) => (d ? dayjs.tz(d as string).format("D MMM YYYY, h:mm A") : "—");
const fmtNum = (n: unknown) =>
  n == null || n === "" ? "—" : Number(n).toLocaleString("en", { maximumFractionDigits: 2 });
const fmtP = (p: number) => (p < 0.001 ? "< 0.001" : Number(p).toFixed(3));

// The values are in the action's success_metric. Without it, only Days exposure is unambiguous (always
// per week); a Deliveries action can be per week or per 1,000 deliveries, so no unit beats a wrong one.
function unitOf(row: Row) {
  const unit: Row = {
    cases_per_week: __("cases per week"),
    customers_per_week: __("customers per week"),
    rate_per_1000_deliveries: __("cases per 1,000 deliveries"),
  };
  return unit[row.success_metric] || (row.exposure_kind === "Days" ? __("per week") : "");
}

// A list endpoint with its own loading/error; `seq` drops a reply that a newer request overtook.
function loader(method: string, params: () => Row = () => ({})) {
  const s = reactive({ data: null as Row[] | null, loading: false, error: "" });
  let seq = 0;
  async function load() {
    const my = ++seq;
    s.loading = true;
    try {
      const data = await call(API + method, params());
      if (my !== seq) return;
      s.data = Array.isArray(data) ? data : [];
      s.error = "";
    } catch (e) {
      if (my === seq) s.error = errText(e);
    } finally {
      if (my === seq) s.loading = false;
    }
  }
  return { s, load };
}

const filter = ref("open");
const actions = loader("get_actions", () => ({ filter: filter.value }));
const decisions = loader("get_decisions");
const rows = computed<Row[]>(() => actions.s.data || []);
const decisionRows = computed<Row[]>(() => decisions.s.data || []);
const recurred = computed(() => rows.value.filter((r) => r.recurred).length);
const emptyText = computed(
  () =>
    ({
      open: __("No open actions. Adopt a plan from an issue's suggestions to track it here."),
      overdue: __("No overdue actions."),
      verifying: __("No finished actions waiting for a verdict."),
      all: __("No actions yet. Adopt a plan from an issue's suggestions to track it here."),
    })[filter.value]
);

watch(filter, () => actions.load());
onMounted(() => {
  actions.load();
  decisions.load();
});

function verdictHistory(row: Row | null): Row[] {
  let h = row?.verdict_history;
  if (typeof h === "string") {
    try {
      h = JSON.parse(h);
    } catch {
      h = null;
    }
  }
  return Array.isArray(h) ? h.filter((x) => x && typeof x === "object") : [];
}

// Update dialog: deciders and the assignee can edit (the server re-checks)
const canEdit = (row: Row | null) =>
  !!row && (!!props.canDecide || (!!row.assigned_to && row.assigned_to === auth.userId));
const dlg = reactive({
  open: false,
  row: null as Row | null,
  status: "Open",
  done_on: "",
  note: "",
  saving: false,
  error: "",
});
function openRow(row: Row) {
  Object.assign(dlg, {
    open: true,
    row,
    status: row.status || "Open",
    done_on: row.done_on || "",
    note: "",
    error: "",
  });
}
watch(
  () => dlg.status,
  (s) => {
    if (s === "Done" && !dlg.done_on) dlg.done_on = dayjs().format("YYYY-MM-DD");
  }
);
async function save() {
  if (!dlg.row) return;
  dlg.saving = true;
  dlg.error = "";
  try {
    await call(API + "update_action", {
      name: dlg.row.name,
      status: dlg.status,
      done_on: dlg.status === "Done" ? dlg.done_on || undefined : undefined,
      note: dlg.note.trim() || undefined,
    });
    dlg.open = false;
    actions.load(); // the row may leave this filter (e.g. Done leaves Open)
  } catch (e) {
    dlg.error = errText(e);
  } finally {
    dlg.saving = false;
  }
}
</script>
