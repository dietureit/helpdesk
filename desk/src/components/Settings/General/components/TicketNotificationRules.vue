<template>
  <div>
    <div class="flex items-center justify-between">
      <div class="flex flex-col gap-1">
        <span class="text-base font-medium text-ink-gray-8">{{
          __("Ticket notification automation")
        }}</span>
        <span class="text-p-sm text-ink-gray-6">{{
          __("Create notification rules using select-based conditions.")
        }}</span>
      </div>
      <Button
        variant="subtle"
        theme="gray"
        :label="__('Add Rule')"
        @click="addRule"
      />
    </div>

    <div class="mt-3 flex flex-col gap-3" v-if="rules.length">
      <div
        v-for="(rule, index) in rules"
        :key="rule._id"
        class="rounded-lg border border-gray-300 p-3"
      >
        <div class="grid grid-cols-1 md:grid-cols-3 gap-3">
          <FormControl
            type="text"
            :label="__('Description')"
            v-model="rule.description"
          />
          <FormControl
            type="select"
            :label="__('Notification Type')"
            v-model="rule.notification_type"
            :options="notificationTypeOptions"
          />
          <FormControl
            type="select"
            :label="__('Notify To')"
            v-model="rule.notify_to"
            :options="notifyToOptions"
          />
        </div>

        <div class="grid grid-cols-1 md:grid-cols-3 gap-3 mt-3">
          <FormControl
            v-if="rule.notify_to === 'Specific User'"
            type="select"
            :label="__('Specific User')"
            v-model="rule.notify_user"
            :options="userOptions"
          />
          <div class="flex items-end justify-between gap-2">
            <Checkbox v-model="rule.is_enabled" :label="__('Enabled')" />
            <Button
              variant="ghost"
              icon="trash-2"
              theme="red"
              @click="removeRule(index)"
            />
          </div>
        </div>

        <div class="mt-3 rounded-md border border-gray-200 p-3 bg-surface-gray-1">
          <div class="text-sm font-medium text-ink-gray-8">
            {{ __("Notification Message Template") }}
          </div>
          <div class="text-xs text-ink-gray-6 mt-1 flex flex-wrap gap-1">
            <span>{{ __("Use dynamic variables like") }}</span>
            <code v-pre>{{ recipient_name }}</code>
            <span>{{ __("and") }}</span>
            <code v-pre>{{ ticket_subject }}</code>
          </div>
          <FormControl
            class="mt-3"
            type="textarea"
            :label="__('Notification Message')"
            v-model="rule.notification_message"
            :rows="4"
          />
        </div>

        <div class="mt-3">
          <Checkbox v-model="rule.send_email" :label="__('Send Email')" />
          <div
            class="mt-2 rounded-md border border-gray-200 p-3 bg-surface-gray-1"
            v-if="rule.send_email"
          >
            <div class="text-sm font-medium text-ink-gray-8">
              {{ __("Email Template") }}
            </div>
            <div class="text-xs text-ink-gray-6 mt-1">
              <span>{{ __("Available variables:") }}</span>
              <div class="mt-1 flex flex-wrap gap-1.5">
                <code v-pre>{{ ticket_name }}</code>
                <code v-pre>{{ ticket_subject }}</code>
                <code v-pre>{{ ticket_status }}</code>
                <code v-pre>{{ ticket_type }}</code>
                <code v-pre>{{ ticket_priority }}</code>
                <code v-pre>{{ ticket_team }}</code>
                <code v-pre>{{ ticket_owner }}</code>
                <code v-pre>{{ recipient }}</code>
                <code v-pre>{{ recipient_name }}</code>
              </div>
            </div>
            <div class="grid grid-cols-1 gap-3 mt-3">
              <FormControl
                type="text"
                :label="__('Email Subject')"
                v-model="rule.email_subject"
              />
              <FormControl
                type="textarea"
                :label="__('Email Message')"
                v-model="rule.email_message"
                :rows="8"
              />
            </div>
          </div>
        </div>

        <div class="mt-3">
          <span class="text-p-sm text-ink-gray-7 font-medium">{{
            __("Condition")
          }}</span>
          <div class="mt-2">
            <CFConditions
              v-if="Array.isArray(rule._conditions) && rule._conditions.length > 0"
              :conditions="rule._conditions"
              :level="0"
            />
            <div
              v-else
              class="flex p-3 items-center cursor-pointer justify-center gap-2 text-sm border border-gray-300 text-gray-600 rounded-md"
              @click="rule._conditions = [['', '', '']]"
            >
              <FeatherIcon name="plus" class="h-4" />
              {{ __("Add condition") }}
            </div>
          </div>
        </div>
        <div class="mt-3 grid grid-cols-1 md:grid-cols-3 gap-3">
          <FormControl
            type="select"
            :label="__('Test with Ticket')"
            v-model="testTicketByRule[rule._id]"
            :options="ticketOptions"
          />
          <div class="flex items-end">
            <Button
              variant="outline"
              :label="__('Test Rule')"
              :loading="Boolean(testingByRule[rule._id])"
              @click="testRule(rule)"
            />
          </div>
          <div class="flex items-end text-sm text-ink-gray-7">
            <span v-if="rule._testResult">
              {{
                rule._testResult.matched
                  ? `${__("Matched. Recipients")}: ${(rule._testResult.recipients || []).length}`
                  : __("Not matched for selected ticket.")
              }}
            </span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import CFConditions from "@/components/conditions-filter/CFConditions.vue";
import { __ } from "@/translation";
import { HDSettingsSymbol } from "@/types";
import { parseApiOptions } from "@/utils";
import { Button, call, Checkbox, createListResource, FeatherIcon, FormControl, toast } from "frappe-ui";
import { computed, inject, ref } from "vue";

const settingsData = inject(HDSettingsSymbol);

const userList = createListResource({
  doctype: "User",
  auto: true,
  fields: ["name"],
  filters: { enabled: 1, user_type: "System User" },
});
const ticketList = createListResource({
  doctype: "HD Ticket",
  auto: true,
  fields: ["name"],
  limit: 100,
  orderBy: "modified desc",
});

const rules = computed(() => settingsData.value.ticketNotificationRules || []);
const testTicketByRule = ref<Record<string, string>>({});
const testingByRule = ref<Record<string, boolean>>({});

const notificationTypeOptions = [
  { label: "Assignment", value: "Assignment" },
  { label: "Mention", value: "Mention" },
  { label: "Reaction", value: "Reaction" },
  { label: "Team Assignment", value: "Team Assignment" },
];

const notifyToOptions = [
  { label: "Assigned Agents", value: "Assigned Agents" },
  { label: "Team Members", value: "Team Members" },
  { label: "Ticket Owner", value: "Ticket Owner" },
  { label: "Specific User", value: "Specific User" },
];

const userOptions = computed(() =>
  parseApiOptions((userList.data || []).map((d: any) => d.name))
);
const ticketOptions = computed(() =>
  parseApiOptions((ticketList.data || []).map((d: any) => d.name))
);

const addRule = () => {
  settingsData.value.ticketNotificationRules.push({
    _id: Math.random().toString(36).slice(2),
    is_enabled: true,
    description: "",
    condition_json: "[]",
    _conditions: [],
    notification_message: "",
    notification_type: "Team Assignment",
    notify_to: "Assigned Agents",
    notify_user: "",
    send_email: false,
    email_subject: "",
    email_message: "",
  });
};

const removeRule = (index: number) => {
  settingsData.value.ticketNotificationRules.splice(index, 1);
};

const testRule = async (rule: any) => {
  const ticketName = testTicketByRule.value[rule._id];
  if (!ticketName) {
    toast.error(__("Select a ticket to test this rule."));
    return;
  }
  try {
    testingByRule.value[rule._id] = true;
    const result: any = await call(
      "helpdesk.helpdesk.doctype.hd_ticket.hd_ticket.evaluate_hd_ticket_rule_preview",
      {
        ticket_name: ticketName,
        rule_kind: "notification",
        rule: {
          notify_to: rule.notify_to,
          notify_user: rule.notify_user,
          condition_json: JSON.stringify(rule._conditions || []),
        },
      }
    );
    rule._testResult = result;
    if (result?.matched) {
      toast.success(`${__("Rule matched. Recipients")}: ${(result.recipients || []).length}`);
    } else {
      toast.error(__("Rule did not match selected ticket."));
    }
  } catch (e: any) {
    toast.error(e?.message || __("Failed to test rule."));
  } finally {
    testingByRule.value[rule._id] = false;
  }
};
</script>
