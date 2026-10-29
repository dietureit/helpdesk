<template>
  <div class="flex flex-col gap-3 border-b px-6 py-3">
    <div
      v-for="s in sections"
      :key="s.label"
      class="flex items-center text-base leading-5"
    >
      <Tooltip :text="s.label">
        <div class="w-[126px] text-sm text-gray-600">{{ s.label }}</div>
      </Tooltip>
      <div class="flex items-center justify-between">
        <div v-if="s.value">{{ s.value }}</div>
        <Tooltip :text="s.tooltipValue">
          <Badge
            v-if="s.badgeText"
            class="-ml-1"
            :label="s.badgeText"
            variant="subtle"
            :theme="s.badgeColor"
          />
        </Tooltip>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { dayjs } from "@/dayjs";
import {
  dateFormat,
  dateTooltipFormat,
  formatTime,
  getTimeInSeconds,
} from "@/utils";
import { Badge, Tooltip } from "frappe-ui";
import { computed, onUnmounted, ref, watch } from "vue";

const props = defineProps({
  ticket: {
    type: Object,
    required: true,
  },
});

let resolutionInterval = null;

const resolutionSeconds = ref(0);

const resolutionBadge = computed(() => {
  let resolution = null;
  if (resolutionInterval) {
    clearInterval(resolutionInterval);
  }
  if (
    props.ticket.status_category === "Paused" &&
    props.ticket.on_hold_since &&
    dayjs(props.ticket.resolution_by).isAfter(dayjs(props.ticket.on_hold_since))
  ) {
    let timeLeft = dayjs(props.ticket.resolution_by).diff(dayjs(), "s");
    resolution = {
      label: `${formatTime(timeLeft)} left (On Hold)`,
      color: "blue",
      date: props.ticket.on_hold_since,
    };
  } else if (
    !props.ticket.resolution_date &&
    dayjs().isBefore(props.ticket.resolution_by)
  ) {
    let resolutionBy = formatTime(
      dayjs(props.ticket.resolution_by).diff(dayjs(), "s")
    );
    handleResolutionInterval(resolutionBy);

    resolution = {
      label: `Due in ${formatTime(resolutionSeconds.value)}`,
      color: "orange",
      date: props.ticket.resolution_by,
    };
  } else if (props.ticket.agreement_status === "Fulfilled") {
    resolution = {
      label: `Fulfilled in ${formatTime(
        dayjs(props.ticket.resolution_time, "s")
      )}`,
      color: "green",
      date: props.ticket.resolution_date,
    };
  } else {
    resolution = {
      label: "Failed",
      color: "red",
      date: props.ticket.resolution_by,
    };
  }
  return resolution;
});

function getCalculatedResolution() {
  let resolution = dayjs(props.ticket.resolution_by).add(
    props.ticket.total_hold_time,
    "s"
  );
  // let now = new Date()
  resolution = dayjs(resolution).diff(dayjs(), "s");
  return formatTime(resolution);
}

const sections = computed(() => [
  {
    label: "Resolution",
    tooltipValue: dateFormat(resolutionBadge.value.date, dateTooltipFormat),
    badgeText: resolutionBadge.value.label,
    badgeColor: resolutionBadge.value.color,
  },
  {
    label: "Source",
    value: props.ticket.via_customer_portal ? "Portal" : "Mail",
  },
]);

// Watch for status changes and clear intervals
watch(
  () => props.ticket,
  (ticket: any) => {
    if (ticket.status_category !== "Open") {
      if (resolutionInterval) {
        clearInterval(resolutionInterval);
        resolutionInterval = null;
      }
    }
  },
  { deep: true, immediate: true }
);

function handleResolutionInterval(time: string) {
  if (!time) return;
  if (props.ticket.status_category !== "Open") {
    return;
  }

  resolutionSeconds.value = getTimeInSeconds(time);
  resolutionInterval = setInterval(() => {
    if (resolutionSeconds.value <= 0) {
      clearInterval(resolutionInterval);
      return;
    }
    resolutionSeconds.value--;
  }, 1000);
}

onUnmounted(() => {
  if (resolutionInterval) {
    clearInterval(resolutionInterval);
  }
  resolutionInterval = null;
});
</script>
