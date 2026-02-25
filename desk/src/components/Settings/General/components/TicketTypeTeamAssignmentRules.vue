<template>
  <div>
    <div class="flex items-center justify-between">
      <div class="flex flex-col gap-1">
        <span class="text-base font-medium text-ink-gray-8">{{
          __("Ticket type to team assignment")
        }}</span>
        <span class="text-p-sm text-ink-gray-6">{{
          __("Map ticket types to teams with optional UI conditions.")
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
            type="select"
            :label="__('Ticket Type')"
            v-model="rule.ticket_type"
            :options="ticketTypeOptions"
          />
          <FormControl
            type="select"
            :label="__('Team')"
            v-model="rule.team"
            :options="teamOptions"
          />
          <div class="flex items-end justify-between gap-2">
            <Checkbox v-model="rule.enabled" :label="__('Enabled')" />
            <Button
              variant="ghost"
              icon="trash-2"
              theme="red"
              @click="removeRule(index)"
            />
          </div>
        </div>
        <div class="mt-3">
          <span class="text-p-sm text-ink-gray-7 font-medium">{{
            __("Condition (optional)")
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
                  ? __("Matched. Team will be assigned.")
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

const ticketTypeList = createListResource({
  doctype: "HD Ticket Type",
  auto: true,
  fields: ["name"],
});

const teamList = createListResource({
  doctype: "HD Team",
  auto: true,
  fields: ["name"],
});
const ticketList = createListResource({
  doctype: "HD Ticket",
  auto: true,
  fields: ["name"],
  limit: 100,
  orderBy: "modified desc",
});

const ticketTypeOptions = computed(() =>
  parseApiOptions((ticketTypeList.data || []).map((d: any) => d.name))
);
const teamOptions = computed(() =>
  parseApiOptions((teamList.data || []).map((d: any) => d.name))
);
const ticketOptions = computed(() =>
  parseApiOptions((ticketList.data || []).map((d: any) => d.name))
);

const rules = computed(() => settingsData.value.ticketTypeTeamAssignmentRules || []);
const testTicketByRule = ref<Record<string, string>>({});
const testingByRule = ref<Record<string, boolean>>({});

const addRule = () => {
  settingsData.value.ticketTypeTeamAssignmentRules.push({
    _id: Math.random().toString(36).slice(2),
    enabled: true,
    ticket_type: "",
    team: "",
    condition_json: "[]",
    _conditions: [],
  });
};

const removeRule = (index: number) => {
  settingsData.value.ticketTypeTeamAssignmentRules.splice(index, 1);
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
        rule_kind: "team_assignment",
        rule: {
          team: rule.team,
          condition_json: JSON.stringify(rule._conditions || []),
        },
      }
    );
    rule._testResult = result;
    if (result?.matched) {
      toast.success(__("Rule matched."));
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
