<template>
  <!-- Teleport to App Header -->
  <teleport to="#app-header">
    <div
      class="flex items-center mx-5 md:mr-0 text-p-sm gap-3 text-[14px] mb-[13px]"
    >
      <!-- Source -->
      <div class="flex items-center gap-1">
        <p
          @click="
            copyToClipboard(
              ticket.doc.name,
              `Ticket #${ticket.doc.name} copied to clipboard`
            )
          "
          class="cursor-copy"
        >
          #{{ ticket.doc.name }}
        </p>
        <!-- Via Email -->
        <div
          v-if="!ticket.doc.via_customer_portal"
          class="text-ink-gray-4 flex items-center"
        >
          <span class="text-ink-gray-4 mr-[6px]">via</span>
          <EmailIcon class="size-4 inline-block mr-1" />
          <span class="">Email</span>
        </div>
        <!-- Via Portal -->
        <div v-else class="text-ink-gray-4 flex items-center">
          <span class="text-ink-gray-4 mr-[6px]">via</span>
          <GlobeIcon class="size-4 inline-block mr-1" />
          <span class="font-medium">Portal</span>
        </div>
      </div>
      <!-- divider -->
      <div class="border-l border-outline-gray-2 h-[13px]" />
      <!-- Resolution by -->
      <div class="flex items-center gap-1">
        <span>Resolution </span>
        <Tooltip
          :text="
            resolutionBy.date
              ? formatInUserTz(resolutionBy.date, dateTooltipFormat)
              : ''
          "
          :hover-delay="0.25"
          :placement="'top'"
        >
          <Badge
            v-if="resolutionBy"
            :label="resolutionBy.label"
            variant="subtle"
            :theme="resolutionBy.color !== 'purple' && resolutionBy.color"
            :class="
              resolutionBy.color === 'purple' && '!text-[#6B46C1] !bg-[#F3E8FF]'
            "
          />
        </Tooltip>
      </div>
      <!-- Assignee (also editable in the sidebar's Details tab) -->
      <template v-if="assignees?.data">
        <div class="border-l border-outline-gray-2 h-[13px]" />
        <div class="flex items-center gap-1.5 min-w-0">
          <span class="shrink-0">{{ __("Assigned to") }}</span>
          <template v-if="assignees.data.length">
            <MultipleAvatar
              :avatars="assignees.data.map((a) => a.name)"
              size="sm"
              hide-name
            />
            <span class="truncate font-medium">{{ assigneeNames }}</span>
          </template>
          <span v-else class="text-ink-gray-4">{{ __("Unassigned") }}</span>
        </div>
      </template>
    </div>
  </teleport>
</template>

<script setup lang="ts">
import { useShortcut } from "@/composables/shortcuts";
import { dayjs, formatInUserTz, inSystemTz } from "@/dayjs";
import { AssigneeSymbol, TicketSymbol } from "@/types";
import { copyToClipboard, dateTooltipFormat, formatTime } from "@/utils";
import { Badge, Tooltip } from "frappe-ui";
import { computed, inject } from "vue";
import { useUserStore } from "@/stores/user";
import MultipleAvatar from "../MultipleAvatar.vue";

const ticket = inject(TicketSymbol);
const assignees = inject(AssigneeSymbol);
const { getUser } = useUserStore();
const assigneeNames = computed(() =>
  (assignees.value?.data || []).map((a) => getUser(a.name).full_name).join(", ")
);

const resolutionBy = computed(() => {
  if (ticket.value?.get?.loading) return { label: "", color: "", date: "" };

  if (
    ticket.value.doc?.status_category === "Paused" &&
    ticket.value.doc?.on_hold_since &&
    inSystemTz(ticket.value.doc?.resolution_by).isAfter(
      inSystemTz(ticket.value.doc?.on_hold_since)
    )
  ) {
    let timeLeft = inSystemTz(ticket.value.doc?.resolution_by).diff(dayjs(), "s");
    return {
      label: `${formatTime(timeLeft)} left (On Hold)`,
      color: "blue",
      date: ticket.value.doc?.on_hold_since,
    };
  } else if (
    !ticket.value.doc?.resolution_date &&
    dayjs().isBefore(inSystemTz(ticket.value.doc?.resolution_by))
  ) {
    let resolutionBy = formatTimeShort(ticket.value.doc?.resolution_by);
    return {
      label: `Due in ${resolutionBy}`,
      color: "purple",
      date: ticket.value.doc?.resolution_by,
    };
  } else if (
    inSystemTz(ticket.value.doc?.resolution_date).isBefore(
      inSystemTz(ticket.value.doc?.resolution_by)
    )
  ) {
    let resolutionBy = formatTimeShort(
      ticket.value.doc?.resolution_date,
      ticket.value.doc?.creation
    );
    return {
      label: `Fulfilled in ${resolutionBy}`,
      color: "green",
      date: ticket.value.doc?.resolution_date,
    };
  } else {
    let resolutionBy = formatTimeShort(ticket.value.doc?.resolution_by);
    return {
      label: `Failed by ${resolutionBy}`,
      color: "red",
      date: ticket.value.doc?.resolution_by,
    };
  }
});

function formatTimeShort(date: string, end?: string): string {
  const start = inSystemTz(date);
  const finish = end ? inSystemTz(end) : dayjs();
  const totalMinutes = Math.abs(start.diff(finish, "minute"));
  const days = Math.floor(totalMinutes / (60 * 24));
  const hours = Math.floor((totalMinutes % (60 * 24)) / 60);
  const minutes = totalMinutes % 60;

  if (days > 0) {
    return `${days}d ${hours}h`;
  }
  if (hours > 0) {
    return `${hours}h ${minutes}m`;
  }
  return `${minutes}m`;
}

useShortcut({ meta: true, shift: true, key: "." }, () => {
  copyToClipboard(window.location.href, `Ticket URL copied to clipboard`);
});

useShortcut({ meta: true, key: "." }, () => {
  copyToClipboard(
    ticket.value.doc.name,
    `Ticket #${ticket.value.doc.name} copied to clipboard`
  );
});
</script>
