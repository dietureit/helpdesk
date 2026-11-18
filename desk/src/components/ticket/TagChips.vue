<template>
  <div v-if="tags.length" class="flex min-w-0 flex-wrap items-center gap-1">
    <span
      v-for="tag in shown"
      :key="tag"
      class="inline-flex max-w-[12rem] items-center gap-1 rounded-full border border-outline-gray-2 bg-surface-white px-2 py-0.5 text-xs font-medium text-ink-gray-8"
      :title="tag"
    >
      <LucideTag class="size-3 shrink-0 text-ink-gray-5" />
      <span class="truncate" dir="auto">{{ tag }}</span>
    </span>
    <Tooltip v-if="tags.length > max" :text="tags.join(', ')">
      <!-- a button so keyboard users can reach the hidden tags; the tooltip opens on focus too -->
      <button
        type="button"
        class="rounded-full border border-outline-gray-2 bg-surface-gray-1 px-1.5 py-0.5 text-xs font-medium text-ink-gray-6 focus:outline-none focus-visible:ring-2 focus-visible:ring-outline-gray-3"
        :aria-label="tags.join(', ')"
        @click.stop
      >
        +{{ tags.length - max }}
      </button>
    </Tooltip>
  </div>
</template>

<script setup lang="ts">
import { Tooltip } from "frappe-ui";
import { computed } from "vue";
import LucideTag from "~icons/lucide/tag";

const props = withDefaults(defineProps<{ tags: string[]; max?: number }>(), {
  max: 2,
});

const shown = computed(() => props.tags.slice(0, props.max));
</script>
