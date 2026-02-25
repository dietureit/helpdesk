<template>
  <SettingsLayoutBase :description="__('Configure Helpdesk automations.')">
    <template #title>
      <div class="flex items-center gap-2">
        <h1 class="text-lg font-semibold text-ink-gray-8">
          {{ __("Automations") }}
        </h1>
        <Badge
          variant="subtle"
          theme="orange"
          size="sm"
          :label="__('Unsaved')"
          v-if="isDirty"
        />
      </div>
    </template>
    <template #header-actions>
      <Button
        :label="__('Save')"
        variant="solid"
        @click="saveSettings"
        :loading="saveSettingsResource.loading"
        :disabled="!isDirty"
      />
    </template>
    <template #content>
      <div
        v-if="settingsDataResource.loading && !settingsDataResource.data"
        class="flex items-center justify-center mt-12"
      >
        <LoadingIndicator class="w-4" />
      </div>
      <div v-else class="flex flex-col gap-6">
        <div class="rounded-lg border border-gray-200 p-4 bg-surface-gray-1">
          <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
            <FormControl
              type="select"
              :label="__('Notification Sender Email Account')"
              :options="emailAccountOptions"
              v-model="settingsData.ticketNotificationSenderEmailAccount"
            />
          </div>
          <div class="mt-2 text-xs text-ink-gray-6">
            {{
              __(
                "Emails from ticket notification automation rules will use this outgoing account."
              )
            }}
          </div>
        </div>

        <div class="flex items-end gap-10 border-b border-gray-200">
          <button
            type="button"
            class="pb-3 text-base transition-colors border-b-2 -mb-px"
            :class="
              activeTab === 'ticket_type'
                ? 'text-ink-gray-9 border-black font-medium'
                : 'text-ink-gray-6 border-transparent hover:text-ink-gray-8'
            "
            @click="activeTab = 'ticket_type'"
          >
            {{ __("Ticket Type Assignment") }}
          </button>
          <button
            type="button"
            class="pb-3 text-base transition-colors border-b-2 -mb-px"
            :class="
              activeTab === 'notification'
                ? 'text-ink-gray-9 border-black font-medium'
                : 'text-ink-gray-6 border-transparent hover:text-ink-gray-8'
            "
            @click="activeTab = 'notification'"
          >
            {{ __("Notification Automation") }}
          </button>
        </div>

        <div v-if="activeTab === 'ticket_type'" class="pt-2">
          <TicketTypeTeamAssignmentRules />
        </div>
        <div v-else class="pt-2 flex flex-col gap-6">
          <TicketNotificationRules />
        </div>
      </div>
    </template>
  </SettingsLayoutBase>
</template>

<script setup lang="ts">
import TicketNotificationRules from "@/components/Settings/General/components/TicketNotificationRules.vue";
import TicketTypeTeamAssignmentRules from "@/components/Settings/General/components/TicketTypeTeamAssignmentRules.vue";
import SettingsLayoutBase from "@/components/layouts/SettingsLayoutBase.vue";
import { disableSettingModalOutsideClick } from "@/components/Settings/settingsModal";
import { __ } from "@/translation";
import { HDSettingsSymbol } from "@/types";
import { convertToConditions } from "@/utils";
import {
  Badge,
  Button,
  createListResource,
  createResource,
  FormControl,
  LoadingIndicator,
  toast,
} from "frappe-ui";
import { computed, onUnmounted, provide, ref, watch } from "vue";

const isDirty = ref(false);
const initialData = ref<string | null>(null);
const activeTab = ref<"ticket_type" | "notification">("ticket_type");
const settingsData = ref({
  ticketNotificationSenderEmailAccount: "",
  ticketTypeTeamAssignmentRules: [] as any[],
  ticketNotificationRules: [] as any[],
});

provide(HDSettingsSymbol as any, settingsData as any);

const getComparableState = () => {
  const teamRules = (settingsData.value.ticketTypeTeamAssignmentRules || []).map(
    (row: any) => ({
      enabled: Boolean(row.enabled),
      ticket_type: row.ticket_type || "",
      team: row.team || "",
      condition_json: JSON.stringify(row._conditions || []),
    })
  );

  const notificationRules = (settingsData.value.ticketNotificationRules || []).map(
    (row: any) => ({
      is_enabled: Boolean(row.is_enabled),
      description: row.description || "",
      condition_json: JSON.stringify(row._conditions || []),
      notification_message: row.notification_message || "",
      notification_type: row.notification_type || "Team Assignment",
      notify_to: row.notify_to || "Assigned Agents",
      notify_user: row.notify_user || "",
      send_email: Boolean(row.send_email),
      email_subject: row.email_subject || "",
      email_message: row.email_message || "",
    })
  );

  return {
    ticketNotificationSenderEmailAccount:
      settingsData.value.ticketNotificationSenderEmailAccount || "",
    ticketTypeTeamAssignmentRules: teamRules,
    ticketNotificationRules: notificationRules,
  };
};

const emailAccountList = createListResource({
  doctype: "Email Account",
  auto: true,
  fields: ["name", "email_id"],
  filters: { enable_outgoing: 1 },
  orderBy: "name asc",
  limit: 100,
});

const emailAccountOptions = computed(() => {
  const rows = (emailAccountList.data || []) as Array<{ name: string; email_id?: string }>;
  const options = rows.map((row) => ({
    label: row.email_id ? `${row.name} (${row.email_id})` : row.name,
    value: row.name,
  }));
  return [{ label: __("Select"), value: "" }, ...options];
});

const settingsDataResource = createResource({
  url: "frappe.client.get",
  params: {
    doctype: "HD Settings",
    name: "HD Settings",
  },
  auto: true,
  onSuccess(data: any) {
    settingsData.value = {
      ticketNotificationSenderEmailAccount:
        data.ticket_notification_sender_email_account || "",
      ticketTypeTeamAssignmentRules: (data.ticket_type_team_assignment_rules || []).map(
        (row: any) => ({
          _id: Math.random().toString(36).slice(2),
          enabled: Boolean(row.enabled),
          ticket_type: row.ticket_type || "",
          team: row.team || "",
          condition_json: row.condition_json || "[]",
          _conditions: (() => {
            try {
              return JSON.parse(row.condition_json || "[]");
            } catch {
              return [];
            }
          })(),
        })
      ),
      ticketNotificationRules: (data.ticket_notification_rules || []).map(
        (row: any) => ({
          _id: Math.random().toString(36).slice(2),
          is_enabled: Boolean(row.is_enabled),
          description: row.description || "",
          condition_json: row.condition_json || "[]",
          _conditions: (() => {
            try {
              return JSON.parse(row.condition_json || "[]");
            } catch {
              return [];
            }
          })(),
          notification_message: row.notification_message || "",
          notification_type: row.notification_type || "Team Assignment",
          notify_to: row.notify_to || "Assigned Agents",
          notify_user: row.notify_user || "",
          send_email: Boolean(row.send_email),
          email_subject: row.email_subject || "",
          email_message: row.email_message || "",
        })
      ),
    };
    initialData.value = JSON.stringify(getComparableState());
  },
});

const saveSettingsResource = createResource({
  url: "frappe.client.set_value",
  makeParams() {
    return {
      doctype: "HD Settings",
      name: "HD Settings",
      fieldname: {
        ticket_notification_sender_email_account:
          settingsData.value.ticketNotificationSenderEmailAccount || "",
        ticket_type_team_assignment_rules: (
          settingsData.value.ticketTypeTeamAssignmentRules || []
        ).map((row: any) => ({
          enabled: row.enabled ? 1 : 0,
          ticket_type: row.ticket_type,
          team: row.team,
          condition_json: JSON.stringify(row._conditions || []),
          condition: convertToConditions({
            conditions: row._conditions || [],
            fieldPrefix: "doc",
          }),
        })),
        ticket_notification_rules: (
          settingsData.value.ticketNotificationRules || []
        ).map((row: any) => ({
          is_enabled: row.is_enabled ? 1 : 0,
          description: row.description,
          condition_json: JSON.stringify(row._conditions || []),
          condition: convertToConditions({
            conditions: row._conditions || [],
            fieldPrefix: "doc",
          }),
          notification_message: row.notification_message,
          notification_type: row.notification_type,
          notify_to: row.notify_to,
          notify_user: row.notify_user,
          send_email: row.send_email ? 1 : 0,
          email_subject: row.email_subject,
          email_message: row.email_message,
        })),
      },
    };
  },
  onSuccess() {
    initialData.value = JSON.stringify(getComparableState());
    isDirty.value = false;
    disableSettingModalOutsideClick.value = false;
    toast.success(__("Automation settings updated"));
  },
});

const saveSettings = async () => {
  await saveSettingsResource.submit();
};

watch(
  settingsData,
  () => {
    if (!initialData.value) return;
    isDirty.value = JSON.stringify(getComparableState()) !== initialData.value;
    disableSettingModalOutsideClick.value = isDirty.value;
  },
  { deep: true }
);

onUnmounted(() => {
  disableSettingModalOutsideClick.value = false;
});
</script>
