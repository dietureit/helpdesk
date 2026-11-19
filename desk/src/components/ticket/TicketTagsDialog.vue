<template>
  <Dialog
    :model-value="tagPrompt.show"
    :options="{
      title: __('What did the investigation on #{0} find?', tagPrompt.ticket),
      size: 'md',
    }"
    @update:model-value="setShow"
  >
    <template #body-content>
      <p class="mb-4 text-p-sm text-ink-gray-6">
        {{
          __(
            "Optional. Pick the tags that describe the result; they show on the ticket and in reports."
          )
        }}
      </p>
      <!-- askForTags opens this only with the ticket type's tags in hand, so there is no loading or empty state -->
      <div class="flex flex-wrap gap-2">
        <button
          v-for="tag in tagPrompt.choices"
          :key="tag.name"
          type="button"
          :aria-pressed="selected.includes(tag.name)"
          class="inline-flex max-w-full items-center gap-1.5 rounded-full border px-3 py-1 text-sm transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-outline-gray-3"
          :class="
            selected.includes(tag.name)
              ? 'border-outline-gray-5 bg-surface-gray-7 text-ink-white'
              : 'border-outline-gray-2 bg-surface-white text-ink-gray-8 hover:bg-surface-gray-2'
          "
          @click="toggle(tag.name)"
        >
          <LucideCheck v-if="selected.includes(tag.name)" class="size-3.5 shrink-0" />
          <LucideTag v-else class="size-3.5 shrink-0 text-ink-gray-5" />
          <span class="truncate" dir="auto">{{ tag.name }}</span>
          <span v-if="!tag.enabled" class="shrink-0 opacity-70">({{ __("Disabled") }})</span>
        </button>
      </div>
      <ErrorMessage class="mt-3" :message="error" />
    </template>
    <template #actions>
      <div class="flex justify-end gap-2">
        <Button :label="__('Skip')" :disabled="saving" @click="tagPrompt.show = false" />
        <Button
          variant="solid"
          :label="__('Save tags')"
          :loading="saving"
          :disabled="!changed"
          @click="save"
        />
      </div>
    </template>
  </Dialog>
</template>

<script setup lang="ts">
import { __ } from "@/translation";
import { Button, call, Dialog, ErrorMessage, toast } from "frappe-ui";
import { computed, ref, watch } from "vue";
import LucideCheck from "~icons/lucide/check";
import LucideTag from "~icons/lucide/tag";
import { tagPrompt } from "./ticketTags";

const selected = ref<string[]>([]);
const saving = ref(false);
const error = ref("");

const changed = computed(
  () => [...selected.value].sort().join("\n") !== [...tagPrompt.tags].sort().join("\n")
);

// every ask, including one that arrives while the dialog is still open for another ticket
watch(
  () => tagPrompt.seq,
  () => {
    selected.value = [...tagPrompt.tags];
    error.value = "";
  }
);

function setShow(show: boolean) {
  if (!show && saving.value) return; // Esc or an outside click mid-save: the save closes it when done
  tagPrompt.show = show;
}

function toggle(tag: string) {
  selected.value = selected.value.includes(tag)
    ? selected.value.filter((t) => t !== tag)
    : [...selected.value, tag];
}

async function save() {
  // this save belongs to the ask that is open now; a later ask may own the dialog by the time it finishes
  const { seq, ticket, onSaved } = tagPrompt;
  saving.value = true;
  error.value = "";
  try {
    await call("frappe.client.set_value", {
      doctype: "HD Ticket",
      name: ticket,
      fieldname: { investigation_tags: selected.value.map((tag) => ({ tag })) },
    });
    if (tagPrompt.seq === seq) tagPrompt.show = false;
    toast.success(__("Tags saved"));
    onSaved?.();
  } catch (e: any) {
    const message = e?.messages?.join(", ") || e?.message || __("Couldn't save the tags");
    // stay open with the server's reason, e.g. a tag disabled meanwhile
    if (tagPrompt.seq === seq) error.value = message;
    else toast.error(message);
  } finally {
    saving.value = false;
  }
}
</script>
