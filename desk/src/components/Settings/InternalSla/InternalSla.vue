<template>
  <SettingsLayoutBase
    :description="
      __(
        'Tracks how long the concerned department takes to finish its investigation. The clock starts when a ticket is created and stops when its Investigation Status is Resolved.'
      )
    "
  >
    <template #title>
      <div class="flex items-center gap-2">
        <h1 class="text-lg font-semibold text-ink-gray-8">
          {{ __("Internal SLA") }}
        </h1>
        <Badge
          v-if="isDirty"
          variant="subtle"
          theme="orange"
          size="sm"
          :label="__('Unsaved')"
        />
      </div>
    </template>
    <template #header-actions>
      <Button
        :label="__('Save')"
        variant="solid"
        :loading="saveResource.loading"
        :disabled="!isDirty"
        @click="save"
      />
    </template>
    <template #content>
      <div v-if="!form" class="mt-12 flex items-center justify-center">
        <LoadingIndicator class="w-4" />
      </div>
      <div v-else class="flex flex-col gap-8 pb-6">
        <section class="flex flex-col gap-4">
          <div class="flex items-center justify-between gap-4">
            <div class="flex flex-col gap-1">
              <span class="text-base font-medium text-ink-gray-8">
                {{ __("Enable internal SLA") }}
              </span>
              <span class="text-p-sm text-ink-gray-6">
                {{
                  __(
                    "New tickets get a tier from the rules below; agents can change it on the ticket."
                  )
                }}
              </span>
            </div>
            <Switch v-model="form.enabled" />
          </div>
          <FormControl
            v-model="form.warning_percent"
            class="w-56"
            type="number"
            :label="__('Warn at (% of the target elapsed)')"
          />
        </section>

        <hr />
        <section class="flex flex-col gap-3">
          <div>
            <h2 class="text-base font-semibold text-ink-gray-8">
              {{ __("Business days") }}
            </h2>
            <p class="mt-1 text-p-sm text-ink-gray-6">
              {{
                __(
                  "Targets in days count only these days and skip the holiday list. Minutes and hours run around the clock."
                )
              }}
            </p>
          </div>
          <div class="flex flex-wrap gap-2">
            <Button
              v-for="day in WEEKDAYS"
              :key="day"
              :label="__(day.charAt(0).toUpperCase() + day.slice(1, 3))"
              :variant="form[day] ? 'solid' : 'outline'"
              :aria-pressed="form[day]"
              @click="form[day] = !form[day]"
            />
          </div>
          <Link
            v-model="form.holiday_list"
            class="w-64"
            doctype="HD Service Holiday List"
            :label="__('Holiday list')"
            :placeholder="__('No holidays')"
          />
        </section>

        <hr />
        <section class="flex flex-col gap-3">
          <div class="flex items-center justify-between">
            <h2 class="text-base font-semibold text-ink-gray-8">
              {{ __("Tiers") }}
            </h2>
            <Button :label="__('Add tier')" @click="addTier">
              <template #prefix><LucidePlus class="size-4" /></template>
            </Button>
          </div>
          <div
            v-for="(tier, index) in form.tiers"
            :key="index"
            class="grid grid-cols-[minmax(0,1.2fr)_5rem_7rem_minmax(0,1.5fr)_auto] items-center gap-2"
          >
            <FormControl v-model="tier.tier" :placeholder="__('Tier name')" />
            <FormControl v-model="tier.target" type="number" :aria-label="__('Target')" />
            <FormControl
              v-model="tier.unit"
              type="select"
              :options="['Minutes', 'Hours', 'Days']"
              :aria-label="__('Unit')"
            />
            <FormControl v-model="tier.description" :placeholder="__('Description (optional)')" />
            <Button
              variant="ghost"
              icon="x"
              :aria-label="__('Remove tier')"
              @click="form.tiers.splice(index, 1)"
            />
          </div>
        </section>

        <hr />
        <section class="flex flex-col gap-3">
          <div class="flex items-center justify-between gap-4">
            <div>
              <h2 class="text-base font-semibold text-ink-gray-8">
                {{ __("Rules") }}
              </h2>
              <p class="mt-1 text-p-sm text-ink-gray-6">
                {{
                  __(
                    "Checked top to bottom; the first matching rule sets a new ticket's tier. Empty columns match anything."
                  )
                }}
              </p>
            </div>
            <Button :label="__('Add rule')" @click="addRule">
              <template #prefix><LucidePlus class="size-4" /></template>
            </Button>
          </div>
          <div
            class="grid grid-cols-[repeat(6,minmax(0,1fr))_auto] gap-2 text-xs text-ink-gray-6"
          >
            <span>{{ __("Category") }}</span>
            <span>{{ __("Sub category") }}</span>
            <span>{{ __("Ticket type") }}</span>
            <span>{{ __("Sub type") }}</span>
            <span>{{ __("Team") }}</span>
            <span>{{ __("Tier") }}</span>
            <span class="w-24" />
          </div>
          <div
            v-for="(rule, index) in form.rules"
            :key="index"
            class="grid grid-cols-[repeat(6,minmax(0,1fr))_auto] items-center gap-2"
          >
            <FormControl
              type="select"
              :options="categoryOptions"
              :aria-label="__('Category')"
              :model-value="rule.category || ANY"
              @update:model-value="
                (value: string) => {
                  rule.category = fromOption(value);
                  rule.sub_category = '';
                }
              "
            />
            <FormControl
              type="select"
              :options="subCategoryOptions(rule.category)"
              :aria-label="__('Sub category')"
              :model-value="rule.sub_category || ANY"
              @update:model-value="(value: string) => (rule.sub_category = fromOption(value))"
            />
            <Link
              doctype="HD Ticket Type"
              :placeholder="__('Any')"
              :model-value="rule.ticket_type"
              @update:model-value="
                (value: string) => {
                  if (value !== rule.ticket_type) rule.sub_type = ''; // a sub type belongs to one type
                  rule.ticket_type = value;
                }
              "
            />
            <FormControl
              type="select"
              :options="subTypeOptions(rule.ticket_type)"
              :aria-label="__('Sub type')"
              :model-value="rule.sub_type || ANY"
              @update:model-value="(value: string) => (rule.sub_type = fromOption(value))"
            />
            <Link v-model="rule.team" doctype="HD Team" :placeholder="__('Any')" />
            <FormControl
              type="select"
              :options="tierOptions"
              :aria-label="__('Tier')"
              :model-value="rule.tier || ANY"
              @update:model-value="(value: string) => (rule.tier = fromOption(value))"
            />
            <div class="flex w-24 items-center">
              <Button
                variant="ghost"
                :aria-label="__('Move up')"
                :disabled="index === 0"
                @click="moveRule(index, -1)"
              >
                <LucideArrowUp class="size-4" />
              </Button>
              <Button
                variant="ghost"
                :aria-label="__('Move down')"
                :disabled="index === form.rules.length - 1"
                @click="moveRule(index, 1)"
              >
                <LucideArrowDown class="size-4" />
              </Button>
              <Button
                variant="ghost"
                icon="x"
                :aria-label="__('Remove rule')"
                @click="form.rules.splice(index, 1)"
              />
            </div>
          </div>
        </section>

        <hr />
        <section class="flex flex-col gap-3">
          <div>
            <h2 class="text-base font-semibold text-ink-gray-8">
              {{ __("Alerts") }}
            </h2>
            <p class="mt-1 text-p-sm text-ink-gray-6">
              {{
                __(
                  "Assigned agents are alerted when a ticket reaches the warning point and when it breaches. Changes here apply to tickets that get a tier from now on."
                )
              }}
            </p>
          </div>
          <div class="flex flex-col gap-1.5">
            <span class="text-xs text-ink-gray-5">
              {{ __("Also alert on breach (e.g. the CX Manager)") }}
            </span>
            <div class="flex flex-wrap items-center gap-1.5">
              <span
                v-for="user in form.breach_recipients"
                :key="user"
                class="inline-flex items-center gap-1 rounded bg-surface-gray-2 py-0.5 pl-2 pr-1 text-sm text-ink-gray-8"
              >
                {{ user }}
                <button
                  type="button"
                  class="rounded p-0.5 hover:bg-surface-gray-3"
                  :aria-label="__('Remove {0}', user)"
                  @click="form.breach_recipients = form.breach_recipients.filter((u) => u !== user)"
                >
                  <LucideX class="size-3" />
                </button>
              </span>
              <Link
                class="w-56"
                doctype="User"
                :filters="{ enabled: 1, user_type: 'System User' }"
                :model-value="''"
                :placeholder="__('Add a person')"
                @update:model-value="addRecipient"
              />
            </div>
          </div>
          <div class="flex items-center justify-between">
            <span class="text-base font-medium text-ink-gray-8">
              {{ __("Also send alerts by email") }}
            </span>
            <Switch v-model="form.send_email" />
          </div>
        </section>
      </div>
    </template>
  </SettingsLayoutBase>
</template>

<script setup lang="ts">
import { Link } from "@/components";
import SettingsLayoutBase from "@/components/layouts/SettingsLayoutBase.vue";
import { __ } from "@/translation";
import {
  Badge,
  Button,
  createResource,
  FormControl,
  LoadingIndicator,
  Switch,
  toast,
} from "frappe-ui";
import { computed, onUnmounted, ref, watch } from "vue";
import LucideArrowDown from "~icons/lucide/arrow-down";
import LucideArrowUp from "~icons/lucide/arrow-up";
import LucidePlus from "~icons/lucide/plus";
import LucideX from "~icons/lucide/x";
import { disableSettingModalOutsideClick } from "../settingsModal";

type Option = { label: string; value: string };

const WEEKDAYS = [
  "monday",
  "tuesday",
  "wednesday",
  "thursday",
  "friday",
  "saturday",
  "sunday",
];

// frappe-ui's select drops options with an empty value, so "Any" / "No internal SLA" use this one
const ANY = "__any__";
const fromOption = (value: string) => (value === ANY ? "" : value);

const form = ref<Record<string, any> | null>(null);
const savedForm = ref("");
const categories = ref<Record<string, string[]>>({});

// ticket type -> { sub_types } (the same forms the ticket dialog and Details tab use)
const typeForms = ref<Record<string, { sub_types?: string[] }>>({});
createResource({
  url: "helpdesk.helpdesk.doctype.hd_ticket_type.hd_ticket_type.get_ticket_type_forms",
  auto: true,
  onSuccess: (data) => (typeForms.value = data || {}),
});

function subTypeOptions(ticketType: string): Option[] {
  const subTypes = ticketType
    ? typeForms.value[ticketType]?.sub_types || []
    : [...new Set(Object.values(typeForms.value).flatMap((form) => form.sub_types || []))];
  return [{ label: __("Any"), value: ANY }, ...subTypes.map((sub) => ({ label: sub, value: sub }))];
}

function toForm(doc: Record<string, any>) {
  return {
    enabled: Boolean(doc.enabled),
    warning_percent: doc.warning_percent,
    ...Object.fromEntries(WEEKDAYS.map((day) => [day, Boolean(doc[day])])),
    holiday_list: doc.holiday_list || "",
    tiers: (doc.tiers || []).map((row) => ({
      tier: row.tier,
      target: row.target,
      unit: row.unit,
      description: row.description || "",
    })),
    rules: (doc.rules || []).map((row) => ({
      category: row.category || "",
      sub_category: row.sub_category || "",
      ticket_type: row.ticket_type || "",
      sub_type: row.sub_type || "",
      team: row.team || "",
      tier: row.tier || "",
    })),
    breach_recipients: (doc.breach_recipients || []).map((row) => row.user),
    send_email: Boolean(doc.send_email),
  };
}

function load(data: { settings: Record<string, any>; categories: Record<string, string[]> }) {
  form.value = toForm(data.settings);
  categories.value = data.categories || {};
  savedForm.value = JSON.stringify(form.value);
}

createResource({
  url: "helpdesk.api.internal_sla.get_settings",
  auto: true,
  onSuccess: load,
});

const saveResource = createResource({
  url: "helpdesk.api.internal_sla.save_settings",
  makeParams: () => {
    const value = form.value!;
    const checks = ["enabled", "send_email", ...WEEKDAYS];
    return {
      settings: {
        ...value,
        ...Object.fromEntries(checks.map((field) => [field, value[field] ? 1 : 0])),
        breach_recipients: value.breach_recipients.map((user: string) => ({ user })),
      },
    };
  },
  onSuccess: (data) => {
    load(data);
    toast.success(__("Internal SLA settings saved"));
  },
  // frappe-ui calls onError up to three times per failed request; save() shows the error once
  onError: () => {},
});

async function save() {
  try {
    await saveResource.submit();
  } catch (error) {
    toast.error(error?.messages?.[0] || error?.message || __("Could not save the settings"));
  }
}

const isDirty = computed(
  () => Boolean(form.value) && JSON.stringify(form.value) !== savedForm.value
);
watch(isDirty, (dirty) => {
  disableSettingModalOutsideClick.value = dirty;
});
onUnmounted(() => {
  disableSettingModalOutsideClick.value = false;
});

const categoryOptions = computed(() => [
  { label: __("Any"), value: ANY },
  ...Object.keys(categories.value).map((category) => ({ label: category, value: category })),
]);

function subCategoryOptions(category: string) {
  const subCategories = category
    ? categories.value[category] || []
    : Object.values(categories.value).flat();
  return [
    { label: __("Any"), value: ANY },
    ...subCategories.map((sub) => ({ label: sub, value: sub })),
  ];
}

const tierOptions = computed(() => [
  { label: __("No internal SLA"), value: ANY },
  ...form
    .value!.tiers.filter((tier) => tier.tier)
    .map((tier) => ({ label: tier.tier, value: tier.tier })),
]);

function addTier() {
  form.value!.tiers.push({ tier: "", target: 1, unit: "Days", description: "" });
}

function addRule() {
  form.value!.rules.push({
    category: "",
    sub_category: "",
    ticket_type: "",
    sub_type: "",
    team: "",
    tier: "",
  });
}

function moveRule(index: number, step: number) {
  const rules = form.value!.rules;
  [rules[index], rules[index + step]] = [rules[index + step], rules[index]];
}

function addRecipient(user: string) {
  if (user && !form.value!.breach_recipients.includes(user)) {
    form.value!.breach_recipients.push(user);
  }
}
</script>
