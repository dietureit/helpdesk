<template>
  <div
   
    class="my-3 bg-surface-white px-4 py-3"
  >
    <p class="text-xl font-semibold text-ink-gray-9">{{ statusLabel }}</p>
    <div class="mt-2.5">
      <div class="flex items-start gap-2 py-2">
        <span
          class="mt-1 h-2 w-2 rounded-full"
          :class="firstResponseDotClass"
          aria-hidden="true"
        />
        <div class="flex flex-col gap-0.5">
          <span class="text-sm font-medium text-ink-gray-8">
            {{ firstResponseLabel }}
          </span>
          <span class="text-xs text-ink-gray-6">by {{ firstResponseDate }}</span>
        </div>
      </div>
      <div class="flex items-start gap-2 py-2">
        <span
          class="mt-1 h-2 w-2 rounded-full"
          :class="resolutionDotClass"
          aria-hidden="true"
        />
        <div class="flex flex-col gap-0.5">
          <div class="flex items-center gap-2">
            <span class="text-sm font-medium text-ink-gray-8">
              {{ resolutionLabel }}
            </span>
            <span
              v-if="resolutionLabel === 'Resolution Due'"
              class="text-xs font-medium text-ink-gray-6"
            >
              Edit
            </span>
          </div>
          <span class="text-xs text-ink-gray-6">by {{ resolutionDate }}</span>
        </div>
      </div>
      <div v-if="internalSla" class="flex items-start gap-2 py-2">
        <span
          class="mt-1 h-2 w-2 rounded-full"
          :class="internalSla.dotClass"
          aria-hidden="true"
        />
        <div class="flex flex-col gap-0.5">
          <span class="text-sm font-medium text-ink-gray-8">
            Internal SLA · {{ internalSla.tier }}
          </span>
          <span class="text-xs text-ink-gray-6">
            {{ internalSla.status }} · due {{ internalSla.due }}
          </span>
        </div>
      </div>
    </div>
    
  </div>
  <div class="h-[1px] bg-[#EDEDED]  mb-4"/>
</template>

<script setup lang="ts">
import { dayjs } from "@/dayjs";
import { TicketSymbol } from "@/types";
import { dateFormat, dateTooltipFormat } from "@/utils";
import { computed, inject } from "vue";

const ticket = inject(TicketSymbol);

const statusLabel = computed(() => {
  const doc = ticket.value?.doc;
  return doc?.status_category || doc?.status || "-";
});

const firstResponseLabel = computed(() => {
  const doc = ticket.value?.doc;
  if (!doc) return "First Response Due";
  if (doc.first_responded_on) return "First Response";
  return "First Response Due";
});

const resolutionLabel = computed(() => {
  const doc = ticket.value?.doc;
  if (!doc) return "Resolution Due";
  if (doc.resolution_date || doc.agreement_status === "Fulfilled") {
    return "Resolution";
  }
  return "Resolution Due";
});

const firstResponseDotClass = computed(() => {
  const doc = ticket.value?.doc;
  if (doc?.first_responded_on) {
    return "bg-red-500";
  }
  return "bg-red-500";
});

const resolutionDotClass = computed(() => {
  const doc = ticket.value?.doc;
  if (doc?.resolution_date || doc?.agreement_status === "Fulfilled") {
    return "bg-surface-gray-6";
  }
  return "bg-green-500";
});

const firstResponseDate = computed(() => {
  const doc = ticket.value?.doc;
  const responseDate = doc?.first_responded_on || doc?.response_by;
  return responseDate ? dateFormat(responseDate, dateTooltipFormat) : "-";
});

const INTERNAL_SLA_DOT = {
  "On Track": "bg-green-500",
  "At Risk": "bg-orange-500",
  Breached: "bg-red-500",
  Met: "bg-surface-gray-6",
};

const internalSla = computed(() => {
  const doc = ticket.value?.doc;
  if (!doc?.internal_sla_due_by) return null;
  let status = doc.internal_sla_status;
  if (doc.investigation_status !== "Resolved") {
    // the stored status only moves when the scheduler runs, so work it out from the due times
    const now = dayjs();
    if (!now.isBefore(dayjs.tz(doc.internal_sla_due_by))) status = "Breached";
    else if (doc.internal_sla_warning_by && !now.isBefore(dayjs.tz(doc.internal_sla_warning_by)))
      status = "At Risk";
    else status = "On Track";
  }
  return {
    tier: doc.internal_sla_tier,
    status,
    dotClass: INTERNAL_SLA_DOT[status] || "bg-surface-gray-6",
    due: dateFormat(doc.internal_sla_due_by, dateTooltipFormat),
  };
});

const resolutionDate = computed(() => {
  const doc = ticket.value?.doc;
  const resolutionDateValue = doc?.resolution_date || doc?.resolution_by;
  return resolutionDateValue
    ? dateFormat(resolutionDateValue, dateTooltipFormat)
    : "-";
});
</script>

<style scoped></style>
