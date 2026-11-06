<template>
  <section v-if="data" class="bg-white border border-gray-200 rounded-lg">
    <div
      class="flex flex-wrap items-center gap-x-2 gap-y-1 px-4 py-3 border-b border-gray-100"
    >
      <LucideShieldAlert class="w-4 h-4 text-red-600 shrink-0" />
      <h2 class="text-sm font-semibold text-gray-900">
        {{ __("Food safety") }}
      </h2>
      <span class="text-xs text-gray-400 sm:ml-auto">
        {{
          __("Only the date window applies here; other filters never hide it.")
        }}
      </span>
    </div>

    <div
      v-if="!events.length && !clusters.length && !needsReview.length"
      class="flex items-center gap-2 px-4 py-3 text-sm text-gray-600"
    >
      <LucideShieldCheck class="w-4 h-4 text-green-600 shrink-0" />
      {{ __("No food-safety events in this period") }}
    </div>

    <div v-else class="divide-y divide-gray-100">
      <div class="px-4 py-3 space-y-3">
        <h3 class="text-xs font-medium text-gray-500">
          {{ __("Events") }} ({{ events.length }})
        </h3>
        <p v-if="!events.length" class="text-sm text-gray-500">
          {{ __("No food-safety events in this period") }}
        </p>
        <div
          v-for="e in shown(events)"
          :key="`${e.ref}:${e.code}`"
          class="space-y-1"
        >
          <div
            class="flex flex-wrap items-center gap-1.5 text-xs text-gray-600"
          >
            <span
              :class="[
                CHIP,
                SEVERITY[e.severity] || 'bg-gray-100 text-gray-700',
              ]"
            >
              {{ e.severity || "—" }}
            </span>
            <span class="font-medium text-gray-900">{{
              e.label || e.code
            }}</span>
            <span>{{ day(e.date) }}</span>
            <span>· {{ e.channel ? __(e.channel) : "—" }}</span>
            <span
              v-if="e.has_ticket === false"
              :class="[CHIP, 'bg-amber-100 text-amber-700']"
            >
              {{ __("no ticket yet") }}
            </span>
            <span v-if="e.review" :class="[CHIP, 'bg-gray-100 text-gray-600']">
              {{
                e.review === "Flagged"
                  ? __("Flagged as a wrong label")
                  : __(e.review)
              }}
            </span>
            <button type="button" :class="OPEN" @click="openCase(e.ref)">
              {{ __("Open") }} ↗
            </button>
          </div>
          <blockquote
            class="ps-2 text-sm text-gray-800 break-words border-s-2 border-gray-200 whitespace-pre-line"
            dir="auto"
            :class="getFontFamily(e.quote || '')"
          >
            {{ e.quote }}
          </blockquote>
          <div v-if="hasTranslation(e)" class="ps-2.5 text-xs text-gray-500">
            <span class="font-medium">{{ __("AI translation") }}</span>
            <p
              class="break-words whitespace-pre-line"
              dir="auto"
              :class="getFontFamily(e.quote_en)"
            >
              {{ e.quote_en }}
            </p>
          </div>
        </div>
      </div>

      <div v-if="clusters.length" class="px-4 py-3 space-y-2">
        <h3 class="text-xs font-medium text-gray-500">
          {{ __("Possible clusters") }} ({{ clusters.length }})
        </h3>
        <p class="text-xs text-gray-500">
          {{
            __(
              "2 or more customers with food-safety issues within 4 days. The rule ignores the dish."
            )
          }}
        </p>
        <div
          v-for="(c, i) in clusters"
          :key="`${c.from}:${i}`"
          class="p-2 space-y-1 border border-red-200 rounded bg-red-50"
        >
          <div
            class="flex flex-wrap items-center gap-1.5 text-xs text-gray-700"
          >
            <span class="font-medium text-gray-900">{{
              __("{0} customers", count(c.customers))
            }}</span>
            <span>· {{ day(c.from) }} – {{ day(c.to) }}</span>
            <span v-if="c.labels?.length">· {{ c.labels.join(", ") }}</span>
          </div>
          <div v-if="c.dishes?.length" class="text-xs text-gray-600">
            <span class="font-medium">{{ __("Dish mentioned") }}</span>
            <p
              class="break-words whitespace-pre-line"
              dir="auto"
              :class="getFontFamily(c.dishes.join(', '))"
            >
              {{ c.dishes.join(", ") }}
            </p>
          </div>
          <div v-if="c.refs?.length" class="flex flex-wrap gap-x-3 gap-y-1">
            <button
              v-for="(caseRef, j) in c.refs"
              :key="caseRef"
              type="button"
              :class="OPEN"
              @click="openCase(caseRef)"
            >
              {{ __("Case {0}", String(j + 1)) }} ↗
            </button>
          </div>
        </div>
      </div>

      <div v-if="needsReview.length" class="px-4 py-3 space-y-2">
        <h3 class="text-xs font-medium text-gray-500">
          {{ __("Needs review") }} ({{ needsReview.length }})
        </h3>
        <p class="text-xs text-gray-500">
          {{
            __(
              "Never counted in any number. Check each one: the labels may have missed a food-safety event."
            )
          }}
        </p>
        <div
          v-for="(r, i) in shown(needsReview)"
          :key="`${r.ref}:${i}`"
          class="flex flex-wrap items-center gap-1.5 text-xs text-gray-600"
        >
          <span>{{ day(r.date) }}</span>
          <span>· {{ r.channel ? __(r.channel) : "—" }}</span>
          <span class="text-gray-800">· {{ r.reason }}</span>
          <span v-if="r.rules?.length" class="text-gray-500"
            >({{ r.rules.map(ruleText).join(", ") }})</span
          >
          <span
            v-if="r.has_ticket === false"
            :class="[CHIP, 'bg-amber-100 text-amber-700']"
          >
            {{ __("no ticket yet") }}
          </span>
          <button type="button" :class="OPEN" @click="openCase(r.ref)">
            {{ __("Open") }} ↗
          </button>
        </div>
      </div>

      <div v-if="hidden" class="px-4 py-2">
        <Button
          variant="ghost"
          size="sm"
          :label="__('Show all ({0} more)', String(hidden))"
          @click="expanded = true"
        />
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { dayjs } from "@/dayjs";
import { __ } from "@/translation";
import { getFontFamily } from "@/utils";
import { Button } from "frappe-ui";
import { computed, ref } from "vue";
import LucideShieldAlert from "~icons/lucide/shield-alert";
import LucideShieldCheck from "~icons/lucide/shield-check";

const props = defineProps<{
  data?: Record<string, any> | null;
  canDecide?: boolean;
}>();

const LIMIT = 5;
const CHIP = "inline-flex items-center px-1.5 rounded font-medium";
const OPEN =
  "text-xs font-medium text-gray-700 hover:text-gray-900 hover:underline";
const SEVERITY: Record<string, string> = {
  S1: "bg-red-100 text-red-700",
  S2: "bg-amber-100 text-amber-700",
};

const expanded = ref(false);
const events = computed<Record<string, any>[]>(() => props.data?.events || []);
const clusters = computed<Record<string, any>[]>(
  () => props.data?.clusters || []
);
const needsReview = computed<Record<string, any>[]>(
  () => props.data?.needs_review || []
);
const hidden = computed(() =>
  expanded.value
    ? 0
    : Math.max(0, events.value.length - LIMIT) +
      Math.max(0, needsReview.value.length - LIMIT)
);
const shown = (rows: Record<string, any>[]) =>
  expanded.value ? rows : rows.slice(0, LIMIT);
const day = (d: string | null) => (d ? dayjs(d).format("D MMM YYYY") : "—");
const count = (n: unknown) => (n == null ? "—" : String(n));
const ruleText = (rule: string) => String(rule).replace(/_/g, " ");
const hasTranslation = (e: Record<string, any>) =>
  !!e.quote_en && String(e.quote_en).trim() !== String(e.quote || "").trim();

function openCase(ref: string) {
  window.open(
    "/api/method/helpdesk.api.ai_analysis.open_case?ref=" +
      encodeURIComponent(ref),
    "_blank",
    "noopener"
  );
}
</script>
