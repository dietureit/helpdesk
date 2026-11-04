<template>
  <SettingsLayoutBase>
    <template #title>
      <div class="flex items-center gap-2">
        <Button
          variant="ghost"
          icon-left="chevron-left"
          :label="name"
          size="md"
          @click="goBack"
          class="cursor-pointer -ml-4 hover:bg-transparent focus:bg-transparent focus:outline-none focus:ring-0 focus:ring-offset-0 focus-visible:none active:bg-transparent active:outline-none active:ring-0 active:ring-offset-0 active:text-ink-gray-5 font-semibold text-ink-gray-7 text-lg hover:opacity-70 !pr-0"
        />
        <Badge
          v-if="doc.data?.is_system"
          variant="subtle"
          theme="gray"
          size="sm"
          :label="__('System')"
        />
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
      <div class="flex items-center gap-2">
        <Dropdown
          v-if="doc.data && !doc.data.is_system"
          placement="right"
          :options="menu"
        >
          <Button
            icon="more-horizontal"
            variant="ghost"
            :loading="remove.loading"
            @click="isConfirmingDelete = false"
          />
        </Dropdown>
        <Button
          :label="__('Save')"
          variant="solid"
          :loading="save.loading"
          :disabled="!isDirty"
          @click="save.submit()"
        />
      </div>
    </template>
    <template #content>
      <div v-if="!form" class="mt-12 flex justify-center">
        <LoadingIndicator class="w-4" />
      </div>
      <div v-else class="flex flex-col gap-8 pb-6">
        <div class="grid grid-cols-2 gap-4">
          <Link
            v-model="form.priority"
            doctype="HD Ticket Priority"
            :label="__('Default priority')"
            :placeholder="__('Helpdesk default')"
          />
          <FormControl
            v-model="form.description"
            type="text"
            :label="__('Description')"
            :placeholder="__('Optional')"
          />
        </div>

        <section class="flex flex-col gap-3">
          <div class="flex flex-col gap-1">
            <span class="text-base font-medium text-ink-gray-8">
              {{ __("Sub types") }} ({{ form.sub_types.length }})
            </span>
            <span class="text-p-sm text-ink-gray-6">
              {{ __("Agents pick one of these after choosing {0}.", name) }}
            </span>
          </div>
          <Draggable
            v-if="form.sub_types.length"
            :list="form.sub_types"
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
                  v-model="element.sub_type"
                  type="text"
                  class="flex-1"
                />
                <Button
                  variant="ghost"
                  icon="x"
                  :aria-label="__('Remove')"
                  @click="form.sub_types.splice(index, 1)"
                />
              </div>
            </template>
          </Draggable>
          <p v-else class="text-p-sm text-ink-gray-5">
            {{ __("No sub types yet, so agents won't be asked for one.") }}
          </p>
          <FormControl
            v-model="newSubType"
            type="text"
            :placeholder="__('Add a sub type and press Enter')"
            @keydown.enter.prevent="addSubType"
          >
            <template #prefix>
              <LucidePlus class="size-4 text-ink-gray-5" />
            </template>
          </FormControl>
        </section>

        <section class="flex flex-col gap-3">
          <div class="flex flex-col gap-1">
            <span class="text-base font-medium text-ink-gray-8">
              {{ __("Fields to fill in") }} ({{ form.fields.length }})
            </span>
            <span class="text-p-sm text-ink-gray-6">
              {{
                __(
                  "Agents fill these in when logging {0} tickets, in the messenger ticket form and on the ticket's Details tab.",
                  name
                )
              }}
            </span>
          </div>
          <Draggable
            v-if="form.fields.length"
            :list="form.fields"
            item-key="key"
            handle=".drag-handle"
            class="flex flex-col"
          >
            <template #item="{ element, index }">
              <div
                class="flex items-center gap-3 border-b border-outline-gray-1 py-1.5"
              >
                <span class="drag-handle cursor-grab text-ink-gray-4">
                  <DragIcon class="h-3.5" />
                </span>
                <div class="flex min-w-0 flex-1 items-baseline gap-2">
                  <span class="truncate text-base font-medium text-ink-gray-8">
                    {{ element.label || element.fieldname }}
                  </span>
                  <span class="shrink-0 text-p-sm text-ink-gray-5">
                    {{ element.fieldtype }}
                  </span>
                </div>
                <FormControl
                  v-model="element.placeholder"
                  type="text"
                  size="sm"
                  class="w-48"
                  :placeholder="__('Placeholder (optional)')"
                />
                <Checkbox v-model="element.required" :label="__('Required')" />
                <Button
                  variant="ghost"
                  icon="x"
                  :aria-label="__('Remove')"
                  @click="form.fields.splice(index, 1)"
                />
              </div>
            </template>
          </Draggable>
          <p v-else class="text-p-sm text-ink-gray-5">
            {{ __("No fields yet, so agents only pick the sub type.") }}
          </p>
          <Autocomplete
            value=""
            :options="availableFields"
            class="self-start"
            @change="addField"
          >
            <template #target="{ togglePopover }">
              <Button
                variant="subtle"
                icon-left="plus"
                :label="__('Add field')"
                @click="togglePopover()"
              />
            </template>
            <template #item-label="{ option }">
              <div class="flex min-w-60 flex-1 items-center justify-between gap-4">
                <span>{{ option.label }}</span>
                <span class="text-p-sm text-ink-gray-5">
                  {{ option.fieldtype }}
                </span>
              </div>
            </template>
          </Autocomplete>
        </section>
      </div>
    </template>
  </SettingsLayoutBase>
  <ConfirmDialog
    v-model="showDiscard"
    :title="__('Unsaved changes')"
    :message="
      __('Are you sure you want to go back? Unsaved changes will be lost.')
    "
    :onConfirm="leave"
    :onCancel="() => (showDiscard = false)"
  />
</template>

<script setup lang="ts">
import { Link } from "@/components";
import ConfirmDialog from "@/components/ConfirmDialog.vue";
import Autocomplete from "@/components/frappe-ui/Autocomplete.vue";
import { DragIcon } from "@/components/icons";
import SettingsLayoutBase from "@/components/layouts/SettingsLayoutBase.vue";
import { __ } from "@/translation";
import { ConfirmDelete } from "@/utils";
import {
  Badge,
  Button,
  Checkbox,
  createResource,
  Dropdown,
  FormControl,
  LoadingIndicator,
  toast,
} from "frappe-ui";
import { computed, onUnmounted, ref, watch } from "vue";
import Draggable from "vuedraggable";
import LucidePlus from "~icons/lucide/plus";
import { disableSettingModalOutsideClick } from "../settingsModal";

const props = defineProps<{ name: string }>();
const emit = defineEmits<{ back: []; changed: [] }>();

type FieldOption = { label: string; value: string; fieldtype: string };
type Form = {
  priority: string;
  description: string;
  sub_types: { key: number; sub_type: string }[];
  fields: {
    key: number;
    fieldname: string;
    label: string;
    fieldtype: string;
    required: boolean;
    placeholder: string;
  }[];
};

// Stable row keys, so dragging or typing into a row keeps its input (and focus)
let lastKey = 0;
const withKey = <T extends object>(row: T) => ({ key: ++lastKey, ...row });

const form = ref<Form | null>(null);
const saved = ref("");

function load(doc: Record<string, any>) {
  form.value = {
    priority: doc.priority || "",
    description: doc.description || "",
    sub_types: (doc.sub_types || []).map((row) =>
      withKey({ sub_type: row.sub_type })
    ),
    fields: (doc.first_contact_fields || []).map((row) =>
      withKey({
        fieldname: row.fieldname,
        label: row.label,
        fieldtype: row.fieldtype,
        required: Boolean(row.required),
        placeholder: row.placeholder || "",
      })
    ),
  };
  saved.value = JSON.stringify(payload());
}

// Rows go without name/idx: Frappe replaces both tables, so the saved order is the order on screen
function payload() {
  const value = form.value!;
  return {
    priority: value.priority || "",
    description: value.description,
    sub_types: value.sub_types
      .map((row) => row.sub_type.trim())
      .filter(Boolean)
      .map((sub_type) => ({ sub_type })),
    first_contact_fields: value.fields.map((row) => ({
      fieldname: row.fieldname,
      required: row.required ? 1 : 0,
      placeholder: row.placeholder,
    })),
  };
}

// Not createDocumentResource: it is cached per document and keeps the first mount's onSuccess
const doc = createResource({
  url: "frappe.client.get",
  params: { doctype: "HD Ticket Type", name: props.name },
  auto: true,
  onSuccess: load,
});

// Errors (e.g. a repeated sub type) are toasted once by the global fallbackErrorHandler
const save = createResource({
  url: "frappe.client.set_value",
  makeParams: () => ({
    doctype: "HD Ticket Type",
    name: props.name,
    fieldname: payload(),
  }),
  onSuccess: (data) => {
    load(data);
    emit("changed");
    toast.success(__("Ticket type saved"));
  },
});

const isDirty = computed(
  () => Boolean(form.value) && JSON.stringify(payload()) !== saved.value
);
watch(isDirty, (dirty) => {
  disableSettingModalOutsideClick.value = dirty;
});
onUnmounted(() => {
  disableSettingModalOutsideClick.value = false;
});

const showDiscard = ref(false);
function goBack() {
  if (isDirty.value) showDiscard.value = true;
  else emit("back");
}
function leave() {
  showDiscard.value = false;
  // Workaround (as in HolidayView): leaving while the dialog closes stops the settings modal from closing
  setTimeout(() => emit("back"), 250);
}

const newSubType = ref("");
function addSubType() {
  const subType = newSubType.value.trim();
  if (!subType) return;
  const exists = form.value!.sub_types.some(
    (row) => row.sub_type.trim().toLowerCase() === subType.toLowerCase()
  );
  if (exists) {
    toast.error(__("{0} is already a sub type", subType));
    return;
  }
  form.value!.sub_types.push(withKey({ sub_type: subType }));
  newSubType.value = "";
}

const fieldOptions = createResource({
  url: "helpdesk.helpdesk.doctype.hd_ticket_type.hd_ticket_type.get_form_field_options",
  cache: "TicketTypeFieldOptions",
  auto: true,
});
const availableFields = computed(() => {
  const added = new Set(form.value?.fields.map((row) => row.fieldname));
  return ((fieldOptions.data || []) as FieldOption[]).filter(
    (option) => !added.has(option.value)
  );
});
function addField(option: FieldOption | null) {
  if (!option) return;
  form.value!.fields.push(
    withKey({
      fieldname: option.value,
      label: option.label,
      fieldtype: option.fieldtype,
      required: false,
      placeholder: "",
    })
  );
}

const isConfirmingDelete = ref(false);
const remove = createResource({
  url: "frappe.client.delete",
  params: { doctype: "HD Ticket Type", name: props.name },
  onSuccess: () => {
    toast.success(__("Ticket type deleted"));
    emit("changed");
    emit("back");
  },
});
const menu = ConfirmDelete({
  isConfirmingDelete,
  onConfirmDelete: () => remove.submit(),
});
</script>
