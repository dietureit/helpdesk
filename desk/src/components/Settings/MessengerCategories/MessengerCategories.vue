<template>
  <SettingsLayoutBase
    :description="
      __(
        'Sub categories agents pick when the category is Enquiry or Assistance.'
      )
    "
  >
    <template #title>
      <div class="flex items-center gap-2">
        <h1 class="text-lg font-semibold text-ink-gray-8">
          {{ __("Messenger Categories") }}
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
        :loading="save.loading"
        :disabled="!isDirty"
        @click="save.submit()"
      />
    </template>
    <template #content>
      <div v-if="!doc.data" class="mt-12 flex justify-center">
        <LoadingIndicator class="w-4" />
      </div>
      <div v-else class="flex flex-col gap-8 pb-6">
        <p class="text-p-sm text-ink-gray-6">
          {{ __("Complaint sub categories come from") }}
          <button
            type="button"
            class="text-ink-gray-8 underline"
            @click="setActiveSettingsTab('Ticket Type Settings')"
          >{{ __("Ticket Type Settings") }}</button>.
        </p>

        <section class="flex flex-col gap-3">
          <div class="flex flex-col gap-1">
            <span class="text-base font-medium text-ink-gray-8">
              {{ __("Enquiry") }} ({{ filledCount(enquiry) }})
            </span>
            <span class="text-p-sm text-ink-gray-6">
              {{
                __(
                  "Shown when the category is Enquiry, in CRM messenger and on tickets."
                )
              }}
            </span>
          </div>
          <Draggable
            v-if="enquiry.length"
            :list="enquiry"
            item-key="key"
            handle=".drag-handle"
            class="flex flex-col gap-1.5"
          >
            <template #item="{ element, index }">
              <div class="flex items-center gap-2">
                <span class="drag-handle cursor-grab text-ink-gray-4">
                  <DragIcon class="h-3.5" />
                </span>
                <FormControl
                  v-model="element.name"
                  type="text"
                  class="flex-1"
                />
                <Button
                  variant="ghost"
                  icon="x"
                  :aria-label="__('Remove')"
                  @click="enquiry.splice(index, 1)"
                />
              </div>
            </template>
          </Draggable>
          <p v-else class="text-p-sm text-ink-gray-5">
            {{ __("No sub categories yet.") }}
          </p>
          <div
            class="flex items-center gap-2"
            @keydown.enter.prevent="add(enquiry, newEnquiry, setNewEnquiry)"
          >
            <FormControl
              v-model="newEnquiry"
              type="text"
              class="flex-1"
              :placeholder="__('Add a sub category and press Enter')"
            >
              <template #prefix>
                <LucidePlus class="size-4 text-ink-gray-5" />
              </template>
            </FormControl>
            <Button
              variant="subtle"
              :label="__('Add')"
              @click="add(enquiry, newEnquiry, setNewEnquiry)"
            />
          </div>
        </section>

        <section class="flex flex-col gap-3">
          <div class="flex flex-col gap-1">
            <span class="text-base font-medium text-ink-gray-8">
              {{ __("Assistance") }} ({{ filledCount(assistance) }})
            </span>
            <span class="text-p-sm text-ink-gray-6">
              {{ __("Shown when the category is Assistance.") }}
            </span>
          </div>
          <Draggable
            v-if="assistance.length"
            :list="assistance"
            item-key="key"
            handle=".drag-handle"
            class="flex flex-col gap-1.5"
          >
            <template #item="{ element, index }">
              <div class="flex items-center gap-2">
                <span class="drag-handle cursor-grab text-ink-gray-4">
                  <DragIcon class="h-3.5" />
                </span>
                <FormControl
                  v-model="element.name"
                  type="text"
                  class="flex-1"
                />
                <Button
                  variant="ghost"
                  icon="x"
                  :aria-label="__('Remove')"
                  @click="assistance.splice(index, 1)"
                />
              </div>
            </template>
          </Draggable>
          <p v-else class="text-p-sm text-ink-gray-5">
            {{ __("No sub categories yet.") }}
          </p>
          <div
            class="flex items-center gap-2"
            @keydown.enter.prevent="
              add(assistance, newAssistance, setNewAssistance)
            "
          >
            <FormControl
              v-model="newAssistance"
              type="text"
              class="flex-1"
              :placeholder="__('Add a sub category and press Enter')"
            >
              <template #prefix>
                <LucidePlus class="size-4 text-ink-gray-5" />
              </template>
            </FormControl>
            <Button
              variant="subtle"
              :label="__('Add')"
              @click="add(assistance, newAssistance, setNewAssistance)"
            />
          </div>
        </section>
      </div>
    </template>
  </SettingsLayoutBase>
</template>

<script setup lang="ts">
import { DragIcon } from "@/components/icons";
import SettingsLayoutBase from "@/components/layouts/SettingsLayoutBase.vue";
import { __ } from "@/translation";
import {
  Badge,
  Button,
  createResource,
  FormControl,
  LoadingIndicator,
  toast,
} from "frappe-ui";
import { computed, onUnmounted, ref, watch } from "vue";
import Draggable from "vuedraggable";
import LucidePlus from "~icons/lucide/plus";
import {
  disableSettingModalOutsideClick,
  setActiveSettingsTab,
} from "../settingsModal";

type Row = { key: number; name: string };

let lastKey = 0;
const row = (name: string): Row => ({ key: ++lastKey, name });

const enquiry = ref<Row[]>([]);
const assistance = ref<Row[]>([]);
const newEnquiry = ref("");
const newAssistance = ref("");
const saved = ref("");

function parseList(raw: string | null | undefined): Row[] {
  return (raw || "")
    .split(",")
    .map((name) => name.trim())
    .filter(Boolean)
    .map(row);
}

function namesOf(rows: Row[]) {
  return rows.map((item) => item.name.trim()).filter(Boolean);
}

function snapshot() {
  return JSON.stringify({
    enquiry: namesOf(enquiry.value),
    assistance: namesOf(assistance.value),
  });
}

function filledCount(rows: Row[]) {
  return namesOf(rows).length;
}

function setNewEnquiry(value: string) {
  newEnquiry.value = value;
}

function setNewAssistance(value: string) {
  newAssistance.value = value;
}

function add(list: Row[], draft: string, clear: (value: string) => void) {
  const name = draft.trim();
  if (!name) return;
  if (name.includes(",")) {
    toast.error(__("{0} cannot contain a comma", name));
    return;
  }
  const exists = namesOf(list).some(
    (current) => current.toLowerCase() === name.toLowerCase()
  );
  if (exists) {
    toast.error(__("{0} is already a sub category", name));
    return;
  }
  list.push(row(name));
  clear("");
}

function invalidNames(rows: Row[], label: string) {
  const seen = new Set<string>();
  for (const name of namesOf(rows)) {
    if (name.includes(",")) return __("{0} cannot contain a comma", name);
    const key = name.toLowerCase();
    if (seen.has(key)) return __("{0} is already in {1}", name, label);
    seen.add(key);
  }
}

function load(data: Record<string, any>) {
  enquiry.value = parseList(data.enquiry_sub_categories);
  assistance.value = parseList(data.assistance_sub_categories);
  saved.value = snapshot();
}

const doc = createResource({
  url: "frappe.client.get",
  params: { doctype: "HD Settings", name: "HD Settings" },
  auto: true,
  onSuccess: load,
});

const save = createResource({
  url: "frappe.client.set_value",
  makeParams() {
    return {
      doctype: "HD Settings",
      name: "HD Settings",
      fieldname: {
        enquiry_sub_categories: namesOf(enquiry.value).join(", "),
        assistance_sub_categories: namesOf(assistance.value).join(", "),
      },
    };
  },
  validate() {
    return (
      invalidNames(enquiry.value, __("Enquiry")) ||
      invalidNames(assistance.value, __("Assistance"))
    );
  },
  onSuccess(data) {
    load(data);
    toast.success(__("Messenger categories saved"));
  },
});

const isDirty = computed(() => Boolean(doc.data) && snapshot() !== saved.value);

watch(isDirty, (dirty) => {
  disableSettingModalOutsideClick.value = dirty;
});

onUnmounted(() => {
  disableSettingModalOutsideClick.value = false;
});
</script>
