<template>
  <Popover v-model:show="open" placement="bottom-start" match-target-width class="w-full">
    <template #target="{ togglePopover }">
      <button
        type="button"
        class="tag-select flex w-full items-center gap-2 text-left text-base"
        :aria-label="triggerLabel"
        :aria-expanded="open"
        @click="togglePopover()"
      >
        <div class="flex min-w-0 flex-1 flex-wrap items-center gap-1">
          <span
            v-for="tag in shown"
            :key="tag"
            class="inline-flex max-w-full items-center gap-1 rounded-full border border-outline-gray-2 bg-surface-white px-2 py-0.5 text-sm text-ink-gray-8"
          >
            <LucideTag class="size-3 shrink-0 text-ink-gray-5" />
            <span class="truncate" dir="auto">{{ tag }}</span>
          </span>
          <span v-if="!shown.length" class="text-ink-gray-4">{{ placeholder }}</span>
        </div>
        <LucideChevronDown class="size-4 shrink-0 text-ink-gray-5" />
      </button>
    </template>
    <template #body>
      <div
        role="group"
        :aria-label="label"
        class="mt-1 max-h-64 overflow-y-auto rounded-lg border border-outline-gray-2 bg-surface-modal p-1.5 shadow-xl"
      >
        <button
          v-for="tag in choices"
          :key="tag.name"
          type="button"
          :aria-pressed="draft.includes(tag.name)"
          class="flex h-8 w-full items-center gap-2 rounded px-2 text-left text-base text-ink-gray-8 hover:bg-surface-gray-2 focus:outline-none focus-visible:bg-surface-gray-2"
          @click="toggle(tag.name)"
        >
          <span
            class="flex size-4 shrink-0 items-center justify-center rounded border"
            :class="
              draft.includes(tag.name)
                ? 'border-outline-gray-5 bg-surface-gray-7 text-ink-white'
                : 'border-outline-gray-3 bg-surface-white'
            "
          >
            <LucideCheck v-if="draft.includes(tag.name)" class="size-3" />
          </span>
          <span class="truncate" dir="auto">{{ tag.name }}</span>
          <span v-if="!tag.enabled" class="ml-auto shrink-0 text-xs text-ink-gray-5">
            {{ __("Disabled") }}
          </span>
        </button>
        <p v-if="!choices.length" class="px-2 py-1.5 text-p-sm text-ink-gray-5">
          {{
            __(
              "No tags to pick. Ask an admin or manager to add or enable tags in Settings > Ticket Tags."
            )
          }}
        </p>
      </div>
    </template>
  </Popover>
</template>

<script setup lang="ts">
import { Popover } from "frappe-ui";
import { computed, ref, watch } from "vue";
import LucideCheck from "~icons/lucide/check";
import LucideChevronDown from "~icons/lucide/chevron-down";
import LucideTag from "~icons/lucide/tag";
import { pickableTags, type TagOption } from "./ticketTags";

const props = withDefaults(
  defineProps<{ modelValue: string[]; options: TagOption[]; label?: string; placeholder?: string }>(),
  { label: "", placeholder: "" }
);
// change: once, when the dropdown closes, so one ticket save however many tags were toggled
// open: so the parent can refresh the options (an admin may have added or disabled tags meanwhile)
const emit = defineEmits<{ (e: "change", tags: string[]): void; (e: "open"): void }>();

const open = ref(false);
const draft = ref<string[]>([]);

const shown = computed(() => (open.value ? draft.value : props.modelValue));
// the field name and its value, as a select would announce them
const triggerLabel = computed(() =>
  props.label ? `${props.label}: ${shown.value.join(", ") || props.placeholder}` : undefined
);

const choices = computed(() => {
  const list = pickableTags(props.options, props.modelValue);
  const known = new Set(list.map((tag) => tag.name));
  // the ticket's own tags stay listed, unmarked, until the options load
  for (const tag of props.modelValue) {
    if (!known.has(tag)) list.push({ name: tag, enabled: 1 });
  }
  return list;
});

watch(open, (isOpen) => {
  if (isOpen) {
    draft.value = [...props.modelValue];
    emit("open");
    return;
  }
  const changed = [...draft.value].sort().join("\n") !== [...props.modelValue].sort().join("\n");
  if (changed) emit("change", [...draft.value]);
});

function toggle(tag: string) {
  draft.value = draft.value.includes(tag)
    ? draft.value.filter((t) => t !== tag)
    : [...draft.value, tag];
}
</script>

<style scoped>
/* same box as the other Details fields (TicketDetailsTab .form-control-core), but it may grow for many tags */
.tag-select {
  min-height: 36px;
  padding: 6px 12px;
  border-radius: 4px;
  border: 1px solid var(--Color-Tokens-Border-Primary, #e4e4e4);
  background: var(--Color-Tokens-Background-Secondary, #f9f9f9);
}
</style>
