<template>
  <div class="p-4 mb-4 bg-white border border-gray-200 rounded-lg">
    <div class="mb-4">
      <h3 class="text-base font-medium text-gray-900">Internal SLA</h3>
      <p class="text-xs text-gray-500">
        Department investigations against their tier, for tickets created in the period
      </p>
    </div>

    <div class="grid grid-cols-2 gap-4 mb-4 md:grid-cols-4">
      <StatusCard
        v-for="card in CARDS"
        :key="card.status"
        :label="card.status"
        :count="counts[card.status] || 0"
        :color="card.color"
        :filters="{ internal_sla_status: ['in', [card.status]] }"
        :team="team"
        :agent="agent"
        :owner="owner"
        :from-date="fromDate"
        :to-date="toDate"
      />
    </div>

    <div v-if="tickets.length">
      <div
        class="grid grid-cols-[4rem_minmax(0,1fr)_9rem_9rem_9rem] gap-2 mb-2 text-sm text-gray-500"
      >
        <span>Ticket</span>
        <span>Subject</span>
        <span>Team</span>
        <span>Tier</span>
        <span class="text-right">Due</span>
      </div>
      <RouterLink
        v-for="ticket in tickets"
        :key="ticket.name"
        :to="{ name: 'TicketAgent', params: { ticketId: ticket.name } }"
        class="grid grid-cols-[4rem_minmax(0,1fr)_9rem_9rem_9rem] gap-2 py-2 text-sm border-t border-gray-100 hover:bg-gray-50"
      >
        <span class="font-medium text-gray-900">#{{ ticket.name }}</span>
        <span class="text-gray-700 truncate">{{ ticket.subject }}</span>
        <span class="text-gray-700 truncate">{{ ticket.agent_group || "—" }}</span>
        <span class="text-gray-700 truncate">{{ ticket.internal_sla_tier }}</span>
        <span
          class="text-right"
          :class="ticket.internal_sla_status === 'Breached' ? 'text-red-600' : 'text-orange-600'"
          :title="dayjs.tz(ticket.internal_sla_due_by).long()"
        >
          {{ dueText(ticket.internal_sla_due_by) }}
        </span>
      </RouterLink>
    </div>
    <div v-else class="flex flex-col items-center justify-center py-6 text-gray-400">
      <LucideCheckCircle class="w-8 h-8 mb-2" />
      <span class="text-sm">No open investigations at risk or past their internal SLA</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { dayjs } from "@/dayjs";
import LucideCheckCircle from "~icons/lucide/check-circle";
import StatusCard from "./StatusCard.vue";

interface SlaTicket {
  name: string;
  subject: string;
  agent_group: string | null;
  internal_sla_tier: string;
  internal_sla_status: string;
  internal_sla_due_by: string;
}

defineProps<{
  counts: Record<string, number>;
  tickets: SlaTicket[];
  team?: string | null;
  agent?: string | null;
  owner?: string | null;
  fromDate?: string | null;
  toDate?: string | null;
}>();

const CARDS = [
  { status: "On Track", color: "#48BB78" },
  { status: "At Risk", color: "#F6AD55" },
  { status: "Breached", color: "#F56565" },
  { status: "Met", color: "#318AD8" },
];

function dueText(due: string) {
  const dueAt = dayjs.tz(due);
  return dueAt.isBefore(dayjs()) ? `${dueAt.fromNow(true)} overdue` : `due ${dueAt.fromNow()}`;
}
</script>
