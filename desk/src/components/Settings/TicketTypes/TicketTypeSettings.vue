<template>
  <TicketTypeEdit
    v-if="current"
    :name="current"
    @back="current = ''"
    @changed="forms.reload()"
  />
  <SettingsLayoutBase
    v-else
    :title="__('Ticket Type Settings')"
    :description="
      __('Set the sub types and fields agents fill in for each ticket type.')
    "
  >
    <template #header-actions>
      <Button
        :label="__('New')"
        theme="gray"
        variant="solid"
        icon-left="plus"
        @click="showNew = true"
      />
    </template>
    <template v-if="types.length > 9 || query" #header-bottom>
      <div class="relative">
        <Input
          :model-value="query"
          @input="query = $event"
          :placeholder="__('Search')"
          type="text"
          class="bg-white hover:bg-white focus:ring-0 border-outline-gray-2"
          icon-left="search"
          inputClass="p-4 pr-12"
        />
        <Button
          v-if="query"
          icon="x"
          variant="ghost"
          @click="query = ''"
          class="absolute right-1 top-1/2 -translate-y-1/2"
        />
      </div>
    </template>
    <template #content>
      <div v-if="!forms.data" class="mt-12 flex justify-center">
        <LoadingIndicator class="w-4" />
      </div>
      <div v-else-if="rows.length" class="w-full -ml-2">
        <div class="ml-2 text-sm text-gray-600">{{ __("Ticket type") }}</div>
        <hr class="mx-2 mt-2" />
        <div v-for="(row, index) in rows" :key="row.name">
          <button
            type="button"
            class="flex h-12.5 w-full items-center justify-between gap-4 rounded px-2 text-left hover:bg-gray-50"
            @click="current = row.name"
          >
            <span class="text-base font-medium text-ink-gray-7">
              {{ row.name }}
            </span>
            <span class="flex items-center gap-2 text-p-sm text-ink-gray-5">
              {{ row.summary }}
              <LucideChevronRight class="size-4" />
            </span>
          </button>
          <hr v-if="index !== rows.length - 1" class="mx-2" />
        </div>
      </div>
      <div
        v-else
        class="flex h-full flex-col items-center justify-center gap-1"
      >
        <div class="text-base font-medium text-ink-gray-6">
          {{ __("No ticket type found") }}
        </div>
        <div class="text-p-sm text-ink-gray-5">
          {{
            query
              ? __("Change your search terms to find ticket types.")
              : __("Add one to get started.")
          }}
        </div>
      </div>
    </template>
  </SettingsLayoutBase>
  <Dialog
    v-model="showNew"
    :options="{
      title: __('New ticket type'),
      actions: [
        {
          label: __('Create'),
          variant: 'solid',
          loading: create.loading,
          onClick: () => create.submit(),
        },
      ],
    }"
  >
    <template #body-content>
      <form @submit.prevent="create.submit()">
        <FormControl
          v-model="newName"
          type="text"
          :label="__('Name')"
          :placeholder="__('e.g. Allergy')"
        />
      </form>
    </template>
  </Dialog>
</template>

<script setup lang="ts">
import SettingsLayoutBase from "@/components/layouts/SettingsLayoutBase.vue";
import { __ } from "@/translation";
import {
  Button,
  createResource,
  Dialog,
  FormControl,
  Input,
  LoadingIndicator,
  toast,
} from "frappe-ui";
import { computed, ref } from "vue";
import LucideChevronRight from "~icons/lucide/chevron-right";
import TicketTypeEdit from "./TicketTypeEdit.vue";

type TypeForm = { sub_types: string[]; fields: unknown[] };

// Same cache key as the ticket Details tab, so reloading here also refreshes a ticket open behind the modal
const forms = createResource({
  url: "helpdesk.helpdesk.doctype.hd_ticket_type.hd_ticket_type.get_ticket_type_forms",
  cache: "TicketTypeForms",
  auto: true,
});

const current = ref("");
const query = ref("");

function summary({ sub_types, fields }: TypeForm) {
  const parts: string[] = [];
  if (sub_types.length)
    parts.push(
      sub_types.length === 1
        ? __("1 sub type")
        : __("{0} sub types", String(sub_types.length))
    );
  if (fields.length)
    parts.push(
      fields.length === 1
        ? __("1 field")
        : __("{0} fields", String(fields.length))
    );
  return parts.join(" · ") || __("Not set up");
}

const types = computed(() =>
  Object.entries((forms.data || {}) as Record<string, TypeForm>)
    .map(([name, form]) => ({ name, summary: summary(form) }))
    .sort((a, b) => a.name.localeCompare(b.name))
);
const rows = computed(() => {
  const search = query.value.trim().toLowerCase();
  return types.value.filter((row) => row.name.toLowerCase().includes(search));
});

const showNew = ref(false);
const newName = ref("");
const create = createResource({
  url: "frappe.client.insert",
  makeParams: () => ({
    doc: { doctype: "HD Ticket Type", name: newName.value.trim() },
  }),
  validate: (params) => {
    if (!params.doc.name) return __("Name is required");
  },
  onSuccess: (doc) => {
    toast.success(__("Ticket type created"));
    showNew.value = false;
    newName.value = "";
    query.value = ""; // so the new type is in the list on the way back
    forms.reload();
    current.value = doc.name;
  },
});
</script>
