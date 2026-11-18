<template>
  <SettingsLayoutBase
    :description="
      __('Tags agents add to a ticket to record what its investigation found.')
    "
  >
    <template #title>
      <h1 class="text-lg font-semibold text-ink-gray-8">
        {{ __("Ticket Tags") }}
      </h1>
    </template>
    <template #content>
      <ErrorMessage
        v-if="tags.error && !tags.data"
        class="mt-6"
        :message="__('Couldn\'t load the tags. Close Settings and open it again.')"
      />
      <div v-else-if="!tags.data" class="mt-12 flex justify-center">
        <LoadingIndicator class="w-4" />
      </div>
      <div v-else class="flex flex-col gap-3 pb-6">
        <p class="text-p-sm text-ink-gray-6">
          {{
            __(
              "Switch a tag off to disable it. Agents can't add a disabled tag, but tickets that have it keep it and reports keep counting it."
            )
          }}
        </p>
        <span class="text-base font-medium text-ink-gray-8">
          {{ __("Tags") }} ({{ tags.data.length }})
        </span>
        <div v-if="tags.data.length" class="flex flex-col gap-1.5">
          <div
            v-for="tag in tags.data"
            :key="tag.name"
            class="rounded border border-outline-gray-2"
          >
            <Switch
              :label="tag.name"
              :icon="LucideTag"
              :model-value="!!tag.enabled"
              :disabled="busy === tag.name"
              :label-classes="tag.enabled ? 'font-normal' : 'font-normal !text-ink-gray-5'"
              @update:model-value="toggle(tag)"
            />
          </div>
        </div>
        <p v-else class="text-p-sm text-ink-gray-5">{{ __("No tags yet.") }}</p>
        <div class="flex items-center gap-2" @keydown.enter.prevent="add">
          <FormControl
            v-model="draft"
            type="text"
            class="flex-1"
            :maxlength="140"
            :placeholder="__('Add a tag and press Enter')"
          >
            <template #prefix>
              <LucidePlus class="size-4 text-ink-gray-5" />
            </template>
          </FormControl>
          <Button
            variant="subtle"
            :label="__('Add')"
            :loading="busy === ADDING"
            @click="add"
          />
        </div>
      </div>
    </template>
  </SettingsLayoutBase>
</template>

<script setup lang="ts">
import SettingsLayoutBase from "@/components/layouts/SettingsLayoutBase.vue";
import { __ } from "@/translation";
import {
  Button,
  call,
  createResource,
  ErrorMessage,
  FormControl,
  LoadingIndicator,
  Switch,
  toast,
} from "frappe-ui";
import { ref } from "vue";
import LucidePlus from "~icons/lucide/plus";
import LucideTag from "~icons/lucide/tag";

// server methods check the same audience as this tab (admins and dashboard managers): some managers,
// e.g. Messenger Managers, have no write permission on HD Ticket Tag itself
const API = "helpdesk.helpdesk.doctype.hd_ticket_tag.hd_ticket_tag";
const ADDING = "__adding__";
const draft = ref("");
const busy = ref("");

const tags = createResource({ url: `${API}.get_tags`, auto: true });

function errorText(e: any) {
  return e?.messages?.join(", ") || e?.message || __("Something went wrong");
}

async function add() {
  if (busy.value) return; // a held or repeated Enter would send the same tag twice
  const name = draft.value.trim();
  if (!name) return;
  const existing = (tags.data || []).find(
    (tag: { name: string }) => tag.name.toLowerCase() === name.toLowerCase()
  );
  if (existing) {
    toast.error(__("{0} is already a tag", existing.name));
    return;
  }
  busy.value = ADDING;
  try {
    await call(`${API}.add_tag`, { tag: name });
    draft.value = "";
    await tags.reload();
  } catch (e) {
    toast.error(errorText(e));
  } finally {
    busy.value = "";
  }
}

async function toggle(tag: { name: string; enabled: number }) {
  busy.value = tag.name;
  try {
    await call(`${API}.set_tag_enabled`, { tag: tag.name, enabled: tag.enabled ? 0 : 1 });
    await tags.reload();
  } catch (e) {
    toast.error(errorText(e));
  } finally {
    busy.value = "";
  }
}
</script>
