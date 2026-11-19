<template>
  <SettingsLayoutBase
    :description="
      __('Tags agents add to a ticket to record what its investigation found.')
    "
  >
    <template #title>
      <div class="flex items-center gap-2">
        <h1 class="text-lg font-semibold text-ink-gray-8">
          {{ __("Ticket Tags") }}
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
        :loading="saving"
        :disabled="!isDirty"
        @click="save"
      />
    </template>
    <template #content>
      <ErrorMessage
        v-if="tags.error && !tags.data"
        class="mt-6"
        :message="__('Couldn\'t load the tags. Close Settings and open it again.')"
      />
      <div v-else-if="!form" class="mt-12 flex justify-center">
        <LoadingIndicator class="w-4" />
      </div>
      <section v-else class="flex flex-col gap-4 pb-6">
        <div class="flex items-start justify-between gap-4">
          <div>
            <h2 class="text-base font-semibold text-ink-gray-8">
              {{ __("Tags") }} ({{ form.length }})
            </h2>
            <p class="mt-1 text-p-sm text-ink-gray-6">
              {{
                __(
                  "A tag is offered only on tickets of its ticket types, so every tag needs at least one. Switch a tag off to disable it: agents can't add it, but tickets that have it keep it and reports keep counting it."
                )
              }}
            </p>
          </div>
          <Button :label="__('Add tag')" @click="addRow">
            <template #prefix><LucidePlus class="size-4" /></template>
          </Button>
        </div>
        <div
          v-if="form.length"
          class="grid grid-cols-[minmax(0,1fr)_minmax(0,1.6fr)_auto_1.75rem] items-center gap-x-3 gap-y-2"
        >
          <span class="text-sm text-ink-gray-5">{{ __("Tag") }}</span>
          <span class="text-sm text-ink-gray-5">{{ __("Ticket types") }}</span>
          <span class="text-sm text-ink-gray-5">{{ __("Enabled") }}</span>
          <span />
          <template v-for="row in form" :key="row.key">
            <FormControl
              v-if="row.is_new"
              v-model="row.name"
              :maxlength="140"
              :placeholder="__('New tag')"
              :aria-label="__('Tag')"
            />
            <div
              v-else
              class="flex min-w-0 items-center gap-2 text-base"
              :class="row.enabled ? 'text-ink-gray-8' : 'text-ink-gray-5'"
            >
              <LucideTag class="size-4 shrink-0 text-ink-gray-5" />
              <span class="truncate" dir="auto">{{ row.name }}</span>
            </div>
            <!-- searchable; saved with the form -->
            <MultiSelect
              v-model="row.ticket_types"
              class="w-full"
              :options="typeOptions(row)"
              :placeholder="
                row.is_new
                  ? __('Pick ticket types')
                  : __('No ticket types: offered on no ticket')
              "
              :aria-label="__('Ticket types for {0}', row.name || __('the new tag'))"
            >
              <template #option="{ item }">
                <span class="truncate">{{ item.label }}</span>
                <span v-if="isDisabledType(item.value)" class="ml-2 text-xs text-ink-gray-5">
                  {{ __("Disabled") }}
                </span>
              </template>
            </MultiSelect>
            <Switch v-model="row.enabled" :aria-label="__('Enabled')" />
            <Button
              v-if="row.is_new"
              variant="ghost"
              icon="x"
              :aria-label="__('Remove')"
              @click="removeRow(row)"
            />
            <span v-else />
          </template>
        </div>
        <p v-else class="text-p-sm text-ink-gray-5">{{ __("No tags yet.") }}</p>
        <ErrorMessage v-if="attempted" :message="problem" />
      </section>
    </template>
  </SettingsLayoutBase>
</template>

<script setup lang="ts">
import SettingsLayoutBase from "@/components/layouts/SettingsLayoutBase.vue";
import { __ } from "@/translation";
import {
  Badge,
  Button,
  call,
  createListResource,
  createResource,
  ErrorMessage,
  FormControl,
  LoadingIndicator,
  MultiSelect,
  Switch,
  toast,
} from "frappe-ui";
import { computed, onUnmounted, ref, watch } from "vue";
import LucidePlus from "~icons/lucide/plus";
import LucideTag from "~icons/lucide/tag";
import { disableSettingModalOutsideClick } from "../settingsModal";

// server methods check the same audience as this tab (admins and dashboard managers): some managers,
// e.g. Messenger Managers, have no write permission on HD Ticket Tag itself
const API = "helpdesk.helpdesk.doctype.hd_ticket_tag.hd_ticket_tag";

type Tag = { name: string; enabled: number; ticket_types: string[] };
type Row = { key: string; name: string; enabled: boolean; ticket_types: string[]; is_new?: boolean };

const tags = createResource({ url: `${API}.get_tags`, auto: true });
// no cache key: a shared key would stop other auto-loading ticket type lists from fetching
const ticketTypes = createListResource({
  doctype: "HD Ticket Type",
  filters: { enabled: 1 },
  fields: ["name"],
  orderBy: "name asc",
  pageLength: 999,
  auto: true,
});

const form = ref<Row[] | null>(null);
const saving = ref(false);
const attempted = ref(false); // show what blocks the save only after a try
let newRows = 0;

const original = computed<Map<string, Tag>>(
  () => new Map((tags.data || []).map((tag: Tag) => [tag.name, tag]))
);

// every load (and the reload after a save) starts the form from what is saved
watch(
  () => tags.data,
  (data: Tag[] | null) => {
    if (!data) return;
    form.value = data.map((tag) => ({
      key: tag.name,
      name: tag.name,
      enabled: !!tag.enabled,
      ticket_types: [...tag.ticket_types],
    }));
  },
  { immediate: true }
);

function typesChanged(row: Row) {
  const saved = original.value.get(row.key)?.ticket_types || [];
  return saved.join("\n") !== row.ticket_types.join("\n");
}

function changed(row: Row) {
  return (
    row.is_new || typesChanged(row) || !!original.value.get(row.key)?.enabled !== row.enabled
  );
}

const isDirty = computed(() => !!form.value?.some(changed));
// like Internal SLA: while there are unsaved edits, an outside click doesn't close Settings and switching tabs asks
watch(isDirty, (dirty) => {
  disableSettingModalOutsideClick.value = dirty;
});
onUnmounted(() => {
  disableSettingModalOutsideClick.value = false;
});

/** What would stop the save, or "": names for new tags, no duplicates, and at least one ticket type on every new
 * tag or tag whose types changed. An older tag without types may stay as it is. */
const problem = computed(() => {
  const seen = new Set<string>();
  for (const row of form.value || []) {
    const name = row.name.trim();
    if (!name) return __("Give every new tag a name.");
    if (seen.has(name.toLowerCase())) return __("{0} is already a tag", name);
    seen.add(name.toLowerCase());
    if (!row.ticket_types.length && (row.is_new || typesChanged(row))) {
      return __("Pick at least one ticket type for {0}.", name);
    }
  }
  return "";
});

/** Enabled ticket types, plus the row's disabled ones so they can be removed. */
function typeOptions(row: Row) {
  const enabled: string[] = (ticketTypes.data || []).map((type: { name: string }) => type.name);
  return [...new Set([...enabled, ...row.ticket_types])].map((name) => ({ label: name, value: name }));
}

function isDisabledType(name: string) {
  return !!ticketTypes.data && !ticketTypes.data.some((type: { name: string }) => type.name === name);
}

function addRow() {
  form.value?.push({ key: `new-${++newRows}`, name: "", enabled: true, ticket_types: [], is_new: true });
}

function removeRow(row: Row) {
  form.value = (form.value || []).filter((other) => other !== row);
}

async function save() {
  if (problem.value) {
    attempted.value = true;
    return;
  }
  saving.value = true;
  try {
    // only the rows and fields that changed: another admin's edit to anything else survives
    await call(`${API}.save_tags`, {
      tags: (form.value || []).filter(changed).map((row) => {
        if (row.is_new) {
          return { name: row.name.trim(), is_new: 1, enabled: row.enabled ? 1 : 0, ticket_types: row.ticket_types };
        }
        const out: Record<string, unknown> = { name: row.name };
        if (!!original.value.get(row.key)?.enabled !== row.enabled) out.enabled = row.enabled ? 1 : 0;
        if (typesChanged(row)) out.ticket_types = row.ticket_types;
        return out;
      }),
    });
    attempted.value = false;
    toast.success(__("Ticket tags saved"));
    await tags.reload();
  } catch (e: any) {
    toast.error(e?.messages?.join(", ") || e?.message || __("Couldn't save the tags"));
  } finally {
    saving.value = false;
  }
}
</script>
