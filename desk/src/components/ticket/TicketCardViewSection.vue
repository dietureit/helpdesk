<template>
  <div class="flex flex-col gap-4 px-5 pb-6 pt-3 lg:flex-row lg:gap-0">
    <div class="flex-1">
      <div class="rounded-xl bg-surface-white p-4">
        <div
          v-if="!loading"
          class="sticky top-0 z-30 mb-4 flex flex-wrap items-center justify-between gap-4 rounded-sm border border-outline-gray-2 bg-surface-white px-5 py-3 shadow-[0_8px_18px_rgba(0,0,0,0.05)]"
        >
          <div class="flex flex-wrap items-center gap-3">
            <div
              class="flex h-9 w-9 items-center justify-center rounded-lg border border-outline-gray-3 bg-surface-gray-1"
            >
              <LucideFilter class="h-4 w-4 text-ink-gray-7" />
            </div>
            <span class="text-base font-semibold text-ink-gray-9">
              {{ listLabel }}
            </span>
            <span
              class="rounded-full bg-surface-gray-9 px-2.5 py-1 text-xs font-semibold leading-none text-ink-white"
            >
              {{ totalCount }}
            </span>
            <div
              v-if="totalCount > 0"
              class="flex items-center gap-2 text-sm text-ink-gray-8"
            >
              <span class="font-semibold text-ink-gray-9">{{ pageStart }}</span>
              <span class="text-ink-gray-4">-</span>
              <span class="font-semibold text-ink-gray-9">{{ pageEnd }}</span>
              <span class="text-ink-gray-6">of</span>
              <span class="font-semibold text-ink-gray-9">{{ totalCount }}</span>
            </div>
          </div>

          <div class="flex items-center gap-4">
            <Button
              class="lg:hidden"
              :label="showFilters ? 'Hide filters' : 'Filters'"
              @click="showFilters = !showFilters"
            >
              <template #prefix>
                <LucideFilter class="h-4 w-4" />
              </template>
            </Button>
            <RouterLink :to="{ name: createTicketRoute }">
              <Button label="Create" theme="gray" variant="solid">
                <template #prefix>
                  <LucidePlus class="h-4 w-4" />
                </template>
              </Button>
            </RouterLink>
            <Button
              v-if="!isCustomerPortal"
              label="Export"
              :disabled="!totalCount"
              :title="`Download the ${totalCount} matching tickets as Excel`"
              @click="emit('export')"
            >
              <template #prefix>
                <LucideDownload class="h-4 w-4" />
              </template>
            </Button>
            <template v-if="totalCount > 0">
              <div class="flex items-center gap-2.5">
                <span class="text-sm font-semibold text-ink-gray-7">Show</span>
                <Dropdown :options="pageLengthOptions" placement="bottom-end">
                  <template #default="{ open }">
                    <button
                      type="button"
                      class="flex h-9 items-center gap-2 rounded-lg border border-outline-gray-3 bg-surface-white px-3 text-sm font-semibold text-ink-gray-9 transition-all hover:-translate-y-0.5 hover:border-outline-gray-4 hover:bg-surface-gray-1 focus:-translate-y-0.5 focus:border-outline-gray-4 focus:outline-none focus:ring-2 focus:ring-outline-gray-3"
                      aria-label="Select results per page"
                    >
                      <span>{{ pageLengthCount }}</span>
                      <LucideChevronDown
                        class="h-4 w-4 text-ink-gray-5 transition-transform"
                        :class="open ? 'rotate-180' : ''"
                      />
                    </button>
                  </template>
                </Dropdown>
              </div>
              <div class="flex items-center gap-2">
                <Button
                  size="sm"
                  variant="ghost"
                  theme="gray"
                  class="h-9 w-9 rounded-lg border border-outline-gray-3 bg-surface-white transition-transform hover:-translate-y-0.5 hover:bg-surface-gray-1"
                  :disabled="pageStart <= 1 || loading"
                  @click="emit('prev-page')"
                  aria-label="Previous page"
                >
                  <LucideChevronLeft class="h-4 w-4" />
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  theme="gray"
                  class="h-9 w-9 rounded-lg border border-outline-gray-3 bg-surface-white transition-transform hover:-translate-y-0.5 hover:bg-surface-gray-1"
                  :disabled="currentCount >= totalCount || loading"
                  @click="emit('next-page')"
                  aria-label="Next page"
                >
                  <LucideChevronRight class="h-4 w-4" />
                </Button>
              </div>
            </template>
          </div>
        </div>
        <TicketCardView
          :rows="rows"
          :loading="loading"
          :status-options="statusOptions"
      :priority-options="priorityOptions"
      @row-click="emit('row-click', $event)"
      @update-status="(ticketId, value) => emit('update-status', ticketId, value)"
      @update-priority="
        (ticketId, value) => emit('update-priority', ticketId, value)
      "
      @empty-state-action="emit('empty-action')"
    />
  </div>
    </div>

    <div
      class="hidden lg:block w-4 shrink-0 self-stretch -mt-3"
      style="background-color: #EBEEF3"
      aria-hidden="true"
    ></div>


    <div
      :class="showFilters ? 'flex' : 'hidden lg:flex'"
      class="order-first w-full shrink-0 flex-col gap-4 bg-surface-white p-4 h-fit lg:order-none lg:w-72 lg:sticky lg:top-4 lg:max-h-[calc(100vh-6rem)] lg:overflow-y-auto"
    >
      <div class="flex items-center justify-between">
        <span class="font-['Poppins'] text-[14px] font-normal leading-[21px] text-ink-gray-9">
          FILTERS
        </span>
        <button
          type="button"
          class="font-['Poppins'] text-[12px] font-medium leading-[18px] text-ink-gray-9 transition-colors hover:text-ink-gray-8"
          :aria-expanded="showApplied"
          @click="showApplied = !showApplied"
        >
          {{ showApplied ? "Hide Applied Filters" : "Show Applied Filters" }}
          <span v-if="appliedCount">({{ appliedCount }})</span>
        </button>
      </div>

      <div v-if="showApplied" class="flex flex-wrap items-center gap-1.5">
        <span
          v-for="chip in appliedChips"
          :key="chip.key"
          class="inline-flex items-center gap-1 rounded bg-surface-gray-2 py-0.5 pl-2 pr-1 text-[12px] leading-[18px] text-ink-gray-8"
        >
          {{ chip.label }}: {{ chip.value }}
          <button
            type="button"
            class="rounded p-0.5 hover:bg-surface-gray-3"
            :aria-label="`Remove ${chip.label} filter`"
            @click="emit('update-filter', chip.key, '')"
          >
            <LucideX class="h-3 w-3" />
          </button>
        </span>
        <span
          v-if="hasLeftovers"
          class="inline-flex items-center gap-1 rounded bg-surface-gray-2 py-0.5 pl-2 pr-1 text-[12px] leading-[18px] text-ink-gray-8"
          :title="JSON.stringify(leftovers)"
        >
          Other filters
          <button
            type="button"
            class="rounded p-0.5 hover:bg-surface-gray-3"
            aria-label="Remove other filters"
            @click="emit('remove-leftovers')"
          >
            <LucideX class="h-3 w-3" />
          </button>
        </span>
        <span v-if="!appliedCount" class="text-[12px] text-ink-gray-5">
          No filters applied
        </span>
        <button
          v-else
          type="button"
          class="text-[12px] font-medium text-ink-gray-7 underline hover:text-ink-gray-9"
          @click="clearAll"
        >
          Clear all
        </button>
      </div>

      <div class="relative">
        <label class="sr-only" for="ticket-filter-search">Search</label>
        <svg
          xmlns="http://www.w3.org/2000/svg"
          width="12"
          height="12"
          viewBox="0 0 12 12"
          fill="none"
          class="pointer-events-none absolute left-3 top-1/2 h-3 w-3 -translate-y-1/2"
          aria-hidden="true"
        >
          <g clip-path="url(#clip0_7898_1623)">
            <path
              fill-rule="evenodd"
              clip-rule="evenodd"
              d="M5.0475 9.16873C2.68875 9.16873 0.77663 7.29 0.77663 4.96875C0.77663 2.6475 2.68875 0.765015 5.0475 0.765015C7.40625 0.765015 9.31875 2.6475 9.31875 4.96875C9.31875 7.29 7.40625 9.16873 5.0475 9.16873ZM11.883 11.3438L8.78587 8.295C9.59662 7.41375 10.095 6.25125 10.095 4.96875C10.095 2.22375 7.83525 0 5.0475 0C2.25975 0 0 2.22375 0 4.96875C0 7.71 2.25975 9.93375 5.0475 9.93375C6.252 9.93375 7.35675 9.51751 8.2245 8.82376L11.334 11.8837C11.4859 12.0337 11.7315 12.0337 11.883 11.8837C12.0349 11.7375 12.0349 11.4938 11.883 11.3438Z"
              fill="black"
            />
          </g>
          <defs>
            <clipPath id="clip0_7898_1623">
              <rect width="12" height="12" fill="white" />
            </clipPath>
          </defs>
        </svg>
        <input
          id="ticket-filter-search"
          v-model="searchQuery"
          type="text"
          placeholder="Search ticket, subject, customer or phone"
          class="h-[35px] w-full rounded border border-[#E4E4E4] bg-surface-white pl-8 pr-3 text-[12px] leading-[18px] text-ink-gray-9 placeholder-ink-gray-4 focus:border-outline-gray-3 focus:outline-none focus:ring-2 focus:ring-outline-gray-2"
        />
      </div>

      <div class="space-y-3">
        <div v-for="filter in visibleFilters" :key="filter.key" class="space-y-1.5">
          <label
            :for="`ticket-filter-${filter.key}`"
            class="text-[12px] font-normal leading-[18px] text-ink-gray-7"
          >
            {{ filter.label }}
          </label>
          <template v-if="filter.date">
            <select
              :id="`ticket-filter-${filter.key}`"
              :class="selectClass"
              :value="dateChoice(filter.key)"
              @change="setDate(filter.key, ($event.target as HTMLSelectElement).value)"
            >
              <option value="">--</option>
              <option v-for="preset in DATE_PRESETS" :key="preset.value" :value="preset.value">
                {{ preset.label }}
              </option>
              <option :value="CUSTOM">Custom range…</option>
            </select>
            <DateRangePicker
              v-if="dateChoice(filter.key) === CUSTOM"
              class="mt-1.5"
              variant="outline"
              placeholder="Pick a date range"
              :model-value="isDateRange(filterState[filter.key]) ? filterState[filter.key] : ''"
              @update:model-value="(value: string) => emit('update-filter', filter.key, value || '')"
            />
          </template>
          <select
            v-else
            :id="`ticket-filter-${filter.key}`"
            :class="selectClass"
            :value="filterState[filter.key] || ''"
            @change="emit('update-filter', filter.key, ($event.target as HTMLSelectElement).value)"
          >
            <option value="">--</option>
            <template v-if="filter.key === 'custom_sub_category'">
              <optgroup
                v-for="(options, group) in subCategoryGroups"
                :key="group"
                :label="String(group)"
              >
                <option v-for="option in options" :key="option.value" :value="option.value">
                  {{ option.label }}
                </option>
              </optgroup>
            </template>
            <template v-else>
              <option v-for="option in optionsFor(filter)" :key="option.value" :value="option.value">
                {{ option.label }}
              </option>
            </template>
          </select>
        </div>

        <div v-if="!isCustomerPortal" class="space-y-1.5">
          <span class="text-[12px] font-normal leading-[18px] text-ink-gray-7">
            More filters (any field)
          </span>
          <Filter />
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import TicketCardView from "@/components/ticket/TicketCardView.vue";
import {
  DATE_PRESETS,
  FILTERS,
  FilterDef,
  FilterOption,
  PanelState,
  isDateRange,
} from "@/components/ticket/ticketFilters";
import Filter from "@/components/view-controls/Filter.vue";
import { isCustomerPortal } from "@/utils";
import { Button, DateRangePicker, Dropdown } from "frappe-ui";
import { computed, reactive, ref, watch } from "vue";
import { RouterLink } from "vue-router";
import LucideFilter from "~icons/lucide/filter";
import LucideChevronDown from "~icons/lucide/chevron-down";
import LucideChevronLeft from "~icons/lucide/chevron-left";
import LucideChevronRight from "~icons/lucide/chevron-right";
import LucideDownload from "~icons/lucide/download";
import LucidePlus from "~icons/lucide/plus";
import LucideX from "~icons/lucide/x";

const props = withDefaults(
  defineProps<{
    rows: any[];
    loading?: boolean;
    totalCount?: number;
    currentCount?: number;
    pageLengthCount?: number;
    statusOptions?: Array<{
      label: string;
      value: string;
      indicatorClass?: string;
      category?: string;
    }>;
    priorityOptions?: string[];
    filterState?: PanelState;
    filterOptions?: Record<string, FilterOption[]>;
    leftovers?: Record<string, any>;
    offset?: number;
    search?: string;
  }>(),
  {
    rows: () => [],
    loading: false,
    totalCount: 0,
    currentCount: 0,
    pageLengthCount: 20,
    statusOptions: () => [],
    priorityOptions: () => [],
    filterState: () => ({}),
    filterOptions: () => ({}),
    leftovers: () => ({}),
    offset: 0,
    search: "",
  }
);

const emit = defineEmits<{
  (e: "row-click", ticketId: string): void;
  (e: "update-status", ticketId: string, value: string): void;
  (e: "update-priority", ticketId: string, value: string): void;
  (e: "load-more"): void;
  (e: "next-page"): void;
  (e: "prev-page"): void;
  (e: "update-limit", value: number): void;
  (e: "empty-action"): void;
  (e: "update:search", value: string): void;
  (e: "update-filter", key: string, value: string): void;
  (e: "clear-filters"): void;
  (e: "remove-leftovers"): void;
  (e: "export"): void;
}>();

const selectClass =
  "h-[35px] w-full appearance-none rounded border border-[#E4E4E4] bg-surface-white px-3 pr-8 text-[12px] leading-[18px] text-ink-gray-9 focus:border-outline-gray-3 focus:outline-none focus:ring-2 focus:ring-outline-gray-2";
const CUSTOM = "custom";

const showFilters = ref(false); // below lg the panel sits behind the "Filters" button
const showApplied = ref(false);
const customDate = reactive<Record<string, boolean>>({});

const searchQuery = ref(props.search || "");
const syncingSearch = ref(false);

watch(
  () => props.search,
  (value) => {
    const nextValue = value ?? "";
    if (nextValue !== searchQuery.value) {
      syncingSearch.value = true;
      searchQuery.value = nextValue;
    }
  }
);

watch(searchQuery, (value) => {
  if (syncingSearch.value) {
    syncingSearch.value = false;
    return;
  }
  emit("update:search", value);
});

const visibleFilters = computed(() =>
  FILTERS.filter((filter) => !(filter.agentOnly && isCustomerPortal.value))
);

function optionsFor(filter: FilterDef): FilterOption[] {
  return filter.options || props.filterOptions[filter.key] || [];
}

// Sub-categories grouped by category; only the chosen category's when one is set
const subCategoryGroups = computed(() => {
  const groups: Record<string, FilterOption[]> = {};
  const category = props.filterState.custom_category;
  for (const option of props.filterOptions.custom_sub_category || []) {
    if (category && option.group !== category) continue;
    (groups[option.group || ""] ||= []).push(option);
  }
  return groups;
});

function dateChoice(key: string) {
  const value = props.filterState[key];
  return customDate[key] || isDateRange(value) ? CUSTOM : value || "";
}

function setDate(key: string, value: string) {
  customDate[key] = value === CUSTOM;
  // a custom range is applied once both dates are picked
  if (value !== CUSTOM) emit("update-filter", key, value);
}

function chipValue(filter: FilterDef) {
  const value = props.filterState[filter.key];
  if (filter.date) {
    return isDateRange(value)
      ? value.replace(",", " → ")
      : DATE_PRESETS.find((preset) => preset.value === value)?.label || value;
  }
  return optionsFor(filter).find((option) => option.value === value)?.label || value;
}

const appliedChips = computed(() =>
  visibleFilters.value
    .filter((filter) => props.filterState[filter.key])
    .map((filter) => ({ key: filter.key, label: filter.label, value: chipValue(filter) }))
);
const hasLeftovers = computed(() => Object.keys(props.leftovers).length > 0);
const appliedCount = computed(
  () => appliedChips.value.length + (hasLeftovers.value ? 1 : 0)
);

function clearAll() {
  Object.keys(customDate).forEach((key) => delete customDate[key]);
  emit("clear-filters");
}

const pageEnd = computed(() => Math.min(props.currentCount || 0, props.totalCount || 0));
const pageStart = computed(() => (pageEnd.value ? props.offset + 1 : 0));

const pageLengthOptions = computed(() =>
  [10, 20, 50, 100].map((value) => ({
    label: `${value} per page`,
    onClick: () => emit("update-limit", value),
  }))
);

const listLabel = computed(() =>
  props.filterState.status ? `${props.filterState.status} tickets` : "All tickets"
);

const createTicketRoute = computed(() =>
  isCustomerPortal.value ? "TicketNew" : "TicketAgentNew"
);
</script>
