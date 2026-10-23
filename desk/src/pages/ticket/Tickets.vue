<template>
  <div>
    <!-- <LayoutHeader>
      <template #left-header>
        <ViewBreadcrumbs
          label="Tickets"
          :route-name="isCustomerPortal ? 'TicketsCustomer' : 'TicketsAgent'"
          :options="dropdownOptions"
          :dropdown-actions="viewActions"
          :current-view="currentView"
        />
      </template>
      <template #right-header>
        <div class="flex items-center gap-2"> -->
          <!--
          <div
            class="flex items-center gap-1 rounded-lg border border-outline-gray-2 bg-surface-white p-1"
          >
            <Button
              variant="ghost"
              theme="gray"
              class="h-9 w-9"
              :class="
                isTableView
                  ? 'bg-surface-gray-2 border border-outline-gray-3'
                  : ''
              "
              :aria-pressed="isTableView"
              @click="viewMode = 'table'"
            >
              <LucideLayoutList class="h-4 w-4" />
            </Button>
            <Button
              variant="ghost"
              theme="gray"
              class="h-9 w-9"
              :class="
                !isTableView
                  ? 'bg-surface-gray-2 border border-outline-gray-3'
                  : ''
              "
              :aria-pressed="!isTableView"
              @click="viewMode = 'card'"
            >
              <LucideLayoutGrid class="h-4 w-4" />
            </Button>
          </div>
          -->
          <!-- <RouterLink
            :to="{ name: isCustomerPortal ? 'TicketNew' : 'TicketAgentNew' }"
          >
            <Button label="Create" theme="gray" variant="solid">
              <template #prefix>
                <LucidePlus class="h-4 w-4" />
              </template>
            </Button>
          </RouterLink>
        </div>
      </template>
    </LayoutHeader> -->
    <!--
    <div v-show="isTableView">
      <TicketListViewSection
        ref="listViewSectionRef"
        :options="options"
        @empty-action="handleEmptyStateAction"
        @row-click="handleTableRowClick"
      />
    </div>
    -->
    <TicketCardViewSection
      v-if="!isTableView"
      :rows="cardRows"
      :loading="listLoading"
      :total-count="totalCount"
      :current-count="currentCount"
      :page-length-count="pageLengthCount"
      :status-options="statusOptionList"
      :priority-options="priorityOptionList"
      :filter-state="panelFilters"
      :filter-options="filterOptions"
      :leftovers="routeLeftovers"
      :offset="cardViewOffset"
      :search="cardSearch"
      @empty-action="handleEmptyStateAction"
      @row-click="handleCardClick"
      @update-status="handleCardStatus"
      @update-priority="handleCardPriority"
      @next-page="handleCardNextPage"
      @prev-page="handleCardPrevPage"
      @load-more="handleCardLoadMore"
      @update:search="handleCardSearchUpdate"
      @update-filter="updatePanelFilter"
      @clear-filters="clearCardFilters"
      @remove-leftovers="routeLeftovers = {}"
      @export="exportCardTickets"
      @update-limit="handleUpdateLimit"
    />
    <ExportModal
      v-model="showExportModal"
      :rowCount="exportRowCount"
      @update="
        ({ export_type, export_all }) => exportRows(export_type, export_all)
      "
    />
    <ViewModal
      v-if="viewDialog.show"
      v-model="viewDialog"
      @update="(view, action) => handleView(view, action)"
    />
  </div>
</template>

<script setup lang="ts">
import { LayoutHeader } from "@/components";
import {
  EditIcon,
  IndicatorIcon,
  PinIcon,
  TicketIcon,
  UnpinIcon,
} from "@/components/icons";
import ExportModal from "@/components/ticket/ExportModal.vue";
import TicketRowActions from "@/components/ticket/TicketRowActions.vue";
import TicketCardViewSection from "@/components/ticket/TicketCardViewSection.vue";
import {
  PanelState,
  UNASSIGNED,
  fromRouteFilters,
  toApiFilters,
} from "@/components/ticket/ticketFilters";
// import TicketListViewSection from "@/components/ticket/TicketListViewSection.vue";
import ViewBreadcrumbs from "@/components/ViewBreadcrumbs.vue";
import ViewModal from "@/components/ViewModal.vue";
import { currentView, useView } from "@/composables/useView";
import { dayjs } from "@/dayjs";
import { useAuthStore } from "@/stores/auth";
import { globalStore } from "@/stores/globalStore";
import { useTicketStatusStore } from "@/stores/ticketStatus";
import { View } from "@/types";
import { getIcon, isCustomerPortal } from "@/utils";
import { Badge, FeatherIcon, toast, Tooltip, usePageMeta, Dropdown, call, createResource } from "frappe-ui";
import { useDebounceFn } from "@vueuse/core";
import { computed, h, nextTick, onMounted, onUnmounted, provide, reactive, ref, watch } from "vue";
// import { useStorage } from "@vueuse/core";
import { useRoute, useRouter } from "vue-router";
import LucidePencil from "~icons/lucide/pencil";
// import LucideLayoutList from "~icons/lucide/layout-list";
// import LucideLayoutGrid from "~icons/lucide/layout-grid";
import LucideAlignJustify from "~icons/lucide/align-justify";
import LucidePlus from "~icons/lucide/plus";

const router = useRouter();
const route = useRoute();

const {
  getCurrentUserViews,
  createView,
  publicViews,
  pinnedViews,
  findView,
  updateView,
  deleteView,
} = useView("HD Ticket");

const { $dialog, $socket } = globalStore();
const { isManager } = useAuthStore();

const listViewSectionRef = ref<any>(null);
const listViewRef = computed(() => listViewSectionRef.value?.listViewRef);
// const viewMode = useStorage<"table" | "card">("tickets_view_mode", "table");
const viewMode = ref<"table" | "card">("card"); // lock to card view only
const isTableView = computed(() => viewMode.value === "table");

// Separate resource for card view
const cardViewLimit = ref(20);
const cardViewOffset = ref(0);
const cardViewResource = createResource({
  url: "helpdesk.api.ticket.get_tickets_for_card_view",
  params: {
    filters: {},
    limit: cardViewLimit.value,
    offset: cardViewOffset.value,
    order_by: "modified desc"
  },
  auto: false,
});

const ticketRows = computed(() => listViewRef.value?.list?.data?.data || []);
const cardRows = computed(() => {
  if (viewMode.value === "card") {
    // Backend already sorts by category when "All" filter is applied
    // No need to sort again on frontend
    const rows = cardViewResource.data?.data || [];
    return rows;
  }
  const rows = ticketRows.value || [];
  return [...rows].sort((a, b) => statusRank(a) - statusRank(b));
});
const listLoading = computed(() => {
  if (viewMode.value === "card") {
    return cardViewResource.loading;
  }
  return listViewRef.value?.list?.loading;
});
const totalCount = computed(() => {
  if (viewMode.value === "card") {
    return cardViewResource.data?.total_count || 0;
  }
  return listViewRef.value?.list?.data?.total_count || 0;
});
const currentCount = computed(() => {
  if (viewMode.value === "card") {
    return cardViewOffset.value + (cardViewResource.data?.data?.length || 0);
  }
  return cardRows.value.length;
});
const exportRowCount = computed(
  () => listViewRef.value?.list?.data?.total_count ?? 0
);
const showExportModal = ref(false);
const { getStatus, statuses } = useTicketStatusStore();

// Priority options
const priorities = createResource({
  url: "frappe.client.get_list",
  params: {
    doctype: "HD Ticket Priority",
    fields: ["name"],
    orderBy: "`tabHD Ticket Priority`.order",
    limit: 100,
  },
  auto: true,
});

const listSelections = ref(new Set());
const selectBannerActions = [
  {
    label: "Export",
    icon: "download",
    onClick: (selections: Set<string>) => {
      listSelections.value = new Set(selections);
      showExportModal.value = true;
    },
  },
];

function handleEmptyStateAction() {
  router.push({
    name: isCustomerPortal.value ? "TicketNew" : "TicketAgentNew",
  });
}

function handleTableRowClick(row: string) {
  router.push({
    name: isCustomerPortal.value ? "TicketCustomer" : "TicketAgent",
    params: { ticketId: row },
  });
}

// Update ticket field function
async function updateTicketField(ticketId: string, field: string, value: string) {
  try {
    await call("frappe.client.set_value", {
      doctype: "HD Ticket",
      name: ticketId,
      fieldname: field,
      value: value,
    });
    toast.success("Updated successfully");
    
    if (viewMode.value === "card") {
      await cardViewResource.reload();
    } else {
      await listViewRef.value?.reload(false);
    }
  } catch (error: any) {
    toast.error(error.message || "Failed to update");
  }
}

const defaultFilters = reactive<Record<string, any>>({});

// Initialize defaultFilters from route query if present
if (route.query.filters) {
  try {
    const queryFilters = typeof route.query.filters === 'string' 
      ? JSON.parse(route.query.filters) 
      : route.query.filters;
    if (queryFilters && Object.keys(queryFilters).length > 0) {
      // Normalize filter operators (convert LIKE to like, etc.)
      const normalizedFilters = { ...queryFilters };
      Object.keys(normalizedFilters).forEach(key => {
        const filterValue = normalizedFilters[key];
        if (Array.isArray(filterValue) && filterValue.length === 2) {
          const operator = filterValue[0];
          if (typeof operator === 'string') {
            // Normalize operator to lowercase
            normalizedFilters[key] = [operator.toLowerCase(), filterValue[1]];
          }
        }
      });
      Object.assign(defaultFilters, normalizedFilters);
      console.log("Initialized defaultFilters from route:", defaultFilters);
    }
  } catch (error) {
    console.error("Error parsing filters from route on init:", error);
  }
}

const options = {
  doctype: "HD Ticket",
  columnConfig: {
    status: {
      custom: ({ item, row }) => {
        const status = getStatus(item);
        const label = isCustomerPortal.value
          ? status?.["label_customer"]
          : status?.["label_agent"];
        
        const statusOptions = (statuses.data || []).map((s) => ({
          label: s.label_agent,
          icon: () => h(IndicatorIcon, { class: s.parsed_color }),
          onClick: () => updateTicketField(row.name, "status", s.label_agent),
        }));
        
        return h("div", { class: "group relative" }, [
          h(
            Dropdown,
            {
              options: statusOptions,
              placement: "right",
            },
            {
              default: () =>
                h(
                  "div",
                  { class: "flex items-center space-x-2 justify-start w-full px-2 py-1 rounded hover:bg-surface-gray-2 cursor-pointer" },
                  [
                    h(IndicatorIcon, { class: status?.["parsed_color"] }),
                    h("span", { class: "truncate flex-1" }, label),
                    h(LucidePencil, { class: "size-3 text-ink-gray-5 opacity-0 group-hover:opacity-100 transition-opacity" }),
                  ]
                ),
            }
          ),
        ]);
      },
    },
    priority: {
      custom: ({ item, row }) => {
        const priorityOptions = (priorities.data || []).map((p) => ({
          label: p.name,
          onClick: () => updateTicketField(row.name, "priority", p.name),
        }));
        
        return h("div", { class: "group relative" }, [
          h(
            Dropdown,
            {
              options: priorityOptions,
              placement: "right",
            },
            {
              default: () =>
                h(
                  "div",
                  { class: "flex items-center space-x-2 justify-start w-full px-2 py-1 rounded hover:bg-surface-gray-2 cursor-pointer" },
                  [
                    h("span", { class: "truncate flex-1" }, item || "None"),
                    h(LucidePencil, { class: "size-3 text-ink-gray-5 opacity-0 group-hover:opacity-100 transition-opacity" }),
                  ]
                ),
            }
          ),
        ]);
      },
    },
    agreement_status: {
      custom: ({ item }) => {
        return h(Badge, {
          label: item,
          theme: slaStatusColorMap[item],
          variant: "outline",
        });
      },
    },
    response_by: {
      custom: ({ row, item }) => handle_response_by_field(row, item),
    },
    resolution_by: {
      custom: ({ row, item }) => handle_resolution_by_field(row, item),
    },
    actions: {
      custom: ({ row }) => {
        if (isCustomerPortal.value) return null;
        return h(TicketRowActions, {
          ticket: row,
          onUpdate: () => listViewRef.value?.reload(false),
        });
      },
    },
  },
  isCustomerPortal: isCustomerPortal.value,
  selectable: true,
  showSelectBanner: true,
  selectBannerActions,
  emptyState: {
    title: "No Tickets Found",
    icon: h(TicketIcon, {
      class: "h-10 w-10",
    }),
  },
  rowRoute: {
    name: isCustomerPortal.value ? "TicketCustomer" : "TicketAgent",
    prop: "ticketId",
  },
  hideColumnSetting: false,
  default_page_length: 25,
  defaultFilters,
};

const statusOptionList = computed(() =>
  (statuses.data || [])
    .filter((s) => s.label_agent !== "Overdue")
    .map((s) => ({
      label: isCustomerPortal.value ? s.label_customer : s.label_agent,
      value: s.label_agent,
      indicatorClass: s.parsed_color,
      category: s.category,
    }))
);

const priorityOptionList = computed(() =>
  (priorities.data || []).map((p) => p.name)
);

const agentOptions = createResource({
  url: "frappe.client.get_list",
  params: {
    doctype: "HD Agent",
    fields: ["name", "agent_name"],
    limit: 100,
  },
  auto: true,
});

const teamOptions = createResource({
  url: "frappe.client.get_list",
  params: {
    doctype: "HD Team",
    fields: ["name", "team_name"],
    limit: 100,
  },
  auto: true,
});

const ticketTypeOptions = createResource({
  url: "frappe.client.get_list",
  params: {
    doctype: "HD Ticket Type",
    fields: ["name"],
    limit: 100,
  },
  auto: true,
});

function setDefaultFilters(filters: Record<string, any> = {}) {
  Object.keys(defaultFilters).forEach((key) => delete defaultFilters[key]);
  Object.assign(defaultFilters, filters || {});
}

watch(
  () => route.query.view,
  () => {
    setDefaultFilters({});
  }
);

// Watch for list view to be ready and apply route filters if needed
watch(
  () => listViewRef.value?.list,
  (list) => {
    if (list && route.query.filters && viewMode.value === "table") {
      try {
        const queryFilters = typeof route.query.filters === 'string' 
          ? JSON.parse(route.query.filters) 
          : route.query.filters;
        
        if (queryFilters && Object.keys(queryFilters).length > 0) {
          // Normalize filter operators (convert LIKE to like, etc.)
          const normalizedFilters = { ...queryFilters };
          Object.keys(normalizedFilters).forEach(key => {
            const filterValue = normalizedFilters[key];
            if (Array.isArray(filterValue) && filterValue.length === 2) {
              const operator = filterValue[0];
              if (typeof operator === 'string') {
                // Normalize operator to lowercase
                normalizedFilters[key] = [operator.toLowerCase(), filterValue[1]];
              }
            }
          });
          
          // Check if filters need to be applied
          const currentFilters = list.params?.filters || {};
          const filtersMatch = Object.keys(normalizedFilters).every(key => {
            const routeValue = JSON.stringify(normalizedFilters[key]);
            const currentValue = JSON.stringify(currentFilters[key]);
            return routeValue === currentValue;
          });
          
          // Only apply if filters don't match
          if (!filtersMatch) {
            // Merge with existing filters to preserve any that might have been set
            const mergedFilters = { ...currentFilters, ...normalizedFilters };
            console.log("Applying route filters to list view:", mergedFilters);
            list.params = {
              ...list.params,
              filters: mergedFilters,
              default_filters: mergedFilters,
            };
            list.submit(list.params);
          }
        }
      } catch (error) {
        console.error("Error applying route filters to list view:", error);
      }
    }
  },
  { immediate: true }
);

function handle_response_by_field(row: any, item: string) {
  if (!row.first_responded_on && dayjs(item).isBefore(new Date())) {
    return h(Badge, {
      label: "Failed",
      theme: "red",
      variant: "outline",
    });
  }
  if (row.first_responded_on && dayjs(row.first_responded_on).isBefore(item)) {
    return h(Badge, {
      label: "Fulfilled",
      theme: "green",
      variant: "outline",
    });
  } else if (dayjs(row.first_responded_on).isAfter(item)) {
    return h(Badge, {
      label: "Failed",
      theme: "red",
      variant: "outline",
    });
  } else {
    return h(
      Tooltip,
      {
        text: dayjs(item).long(),
      },
      () => dayjs.tz(item).fromNow()
    );
  }
}

function handle_resolution_by_field(row: any, item: string) {
  const status = getStatus(row.status) || {};
  if (status.category === "Paused") {
    return h(Badge, {
      label: "Paused",
      theme: "blue",
      variant: "outline",
    });
  } else if (row.resolution_date && dayjs(row.resolution_date).isBefore(item)) {
    return h(Badge, {
      label: "Fulfilled",
      theme: "green",
      variant: "outline",
    });
  } else if (dayjs(row.resolution_date).isAfter(item)) {
    return h(Badge, {
      label: "Failed",
      theme: "red",
      variant: "outline",
    });
  } else {
    return h(
      Tooltip,
      {
        text: dayjs(item).long(),
      },
      () => dayjs.tz(item).fromNow()
    );
  }
}

async function exportRows(
  export_type: "CSV" | "Excel" = "Excel",
  export_all: boolean = false
) {
  const list = listViewRef.value?.list;
  if (!list) return;

  const fields = JSON.stringify(list.data.columns.map((f) => f.key));
  const order_by = list.params.order_by;

  let filters = { ...list.params.filters };
  let pageLength: number;

  if (export_all) {
    filters = JSON.stringify(filters);
    pageLength = list.data.total_count;
  } else {
    pageLength = listSelections.value.size;
    filters["name"] = ["in", Array.from(listSelections.value)];
    filters = JSON.stringify(filters);
  }

  window.location.href = `/api/method/frappe.desk.reportview.export_query?file_format_type=${export_type}&title=HD Ticket&doctype=HD Ticket&fields=${fields}&filters=${filters}&order_by=${order_by}&page_length=${pageLength}&start=0&view=Report&with_comment_count=1`;
  reset();
  showExportModal.value = false;
}

function reset(reload = false) {
  listViewRef.value?.unselectAll();
  listSelections.value?.clear();
  if (reload) listViewRef.value.reload();
}

const pageLengthCount = computed(() => {
  if (viewMode.value === "card") {
    return cardViewLimit.value;
  }
  return (
    listViewRef.value?.list?.params?.page_length_count ||
    options.default_page_length ||
    20
  );
});

function handleCardLoadMore() {
  if (viewMode.value === "card") {
    cardViewOffset.value += cardViewLimit.value;
    loadCardViewTickets();
  } else {
    const count = pageLengthCount.value;
    listViewRef.value?.handlePageLength?.(count, true);
  }
}

function handleCardNextPage() {
  if (viewMode.value === "card") {
    if (currentCount.value < totalCount.value) {
      cardViewOffset.value += cardViewLimit.value;
      loadCardViewTickets();
    }
  } else {
    const count = pageLengthCount.value;
    listViewRef.value?.handlePageLength?.(count, true);
  }
}

function handleCardPrevPage() {
  if (viewMode.value === "card") {
    cardViewOffset.value = Math.max(0, cardViewOffset.value - cardViewLimit.value);
    loadCardViewTickets();
  } else {
    const count = pageLengthCount.value;
    const currentLength = listViewRef.value?.list?.params?.page_length || count;
    const newLength = Math.max(count, currentLength - count);
    listViewRef.value?.handlePageLength?.(newLength, false);
  }
}

function handleUpdateLimit(newLimit: number) {
  cardViewLimit.value = newLimit;
  cardViewOffset.value = 0;
  loadCardViewTickets();
}

function statusRank(row: any) {
  const meta = getStatus(row?.status) || {};
  const category = meta.category || "";
  // Open/New tickets first (0)
  if (category === "Open" || row?.status === "Open" || row?.status === "New") return 0;
  // Pending/Paused tickets second (1)
  if (category === "Paused" || row?.status === "Pending") return 1;
  // Resolved/Closed tickets last (2)
  if (category === "Resolved" || row?.status === "Closed" || row?.status === "Resolved") return 2;
  return 0;
}

function handleCardClick(ticketId: string) {
  console.log("Navigating to ticket:", ticketId);
  if (!ticketId) {
    console.error("No ticket ID provided");
    return;
  }
  router.push({
    name: isCustomerPortal.value ? "TicketCustomer" : "TicketAgent",
    params: { ticketId },
  });
}

function handleCardStatus(ticketId: string, value: string) {
  updateTicketField(ticketId, "status", value);
}

function handleCardPriority(ticketId: string, value: string) {
  updateTicketField(ticketId, "priority", value);
}

// Filter panel state (keys from components/ticket/ticketFilters.ts)
const panelFilters = reactive<PanelState>({});
// Dashboard-link filters the panel can't show (e.g. several statuses); sent as they are
const routeLeftovers = ref<Record<string, any>>({});
// "More filters" popover (view-controls/Filter.vue) on any ticket field
const advancedList = reactive({ params: { filters: {} as Record<string, any> } });
const filterableFields = createResource({
  url: "helpdesk.api.doc.get_filterable_fields",
  cache: ["DocField", "HD Ticket"],
  params: { doctype: "HD Ticket" },
  auto: !isCustomerPortal.value,
  transform: (data) =>
    data.map((field) => ({ label: field.label, value: field.fieldname, ...field })),
});
provide("listViewData", reactive({ list: advancedList, filterableFields }));
provide("listViewActions", {
  applyFilters: (filters: Record<string, any>) => {
    advancedList.params.filters = { ...filters };
  },
});

const cardSearch = ref("");
const searchText = ref("");
const setSearchText = useDebounceFn((value: string) => {
  searchText.value = value.trim();
}, 400);

const requestFilters = computed(() => {
  // the panel wins over "More filters", which win over what a dashboard link brought along
  const filters: Record<string, any> = {
    ...routeLeftovers.value,
    ...advancedList.params.filters,
    ...toApiFilters(panelFilters),
  };
  if (searchText.value) filters.search = searchText.value;
  return filters;
});

// Categories and internal SLA tiers for the panel
const filterMeta = createResource({
  url: "helpdesk.api.internal_sla.get_options",
  auto: !isCustomerPortal.value,
});

const filterOptions = computed(() => {
  // resource.data is null until the first fetch
  const names = (rows: any[] | null, key = "name") =>
    (rows || []).map((row) => ({ label: row[key], value: row[key] }));
  const categories: Record<string, string[]> = filterMeta.data?.categories || {};
  const agents = (agentOptions.data || []).map((agent) => ({
    label: agent.agent_name || agent.name,
    value: agent.name,
  }));
  return {
    custom_category: Object.keys(categories).map((c) => ({ label: c, value: c })),
    custom_sub_category: Object.entries(categories).flatMap(([group, subs]) =>
      subs.map((sub) => ({ label: sub, value: sub, group }))
    ),
    ticket_type: names(ticketTypeOptions.data),
    status: (statuses.data || [])
      .filter((s) => s.enabled)
      .map((s) => ({
        label: isCustomerPortal.value ? s.label_customer : s.label_agent,
        value: s.label_agent,
      })),
    priority: names(priorities.data),
    agent_group: names(teamOptions.data),
    assigned_to: [{ label: "Unassigned", value: UNASSIGNED }, ...agents],
    owner: [{ label: "Administrator", value: "Administrator" }, ...agents],
    internal_sla_tier: (filterMeta.data?.tiers || []).map((t: string) => ({ label: t, value: t })),
  };
});

function updatePanelFilter(key: string, value: string) {
  if (value) panelFilters[key] = value;
  else delete panelFilters[key];
  // sub-categories belong to one category
  if (key === "custom_category") delete panelFilters.custom_sub_category;
}

function clearCardFilters() {
  Object.keys(panelFilters).forEach((key) => delete panelFilters[key]);
  routeLeftovers.value = {};
  advancedList.params.filters = {};
  cardSearch.value = "";
  searchText.value = "";
}

function handleCardSearchUpdate(value: string) {
  cardSearch.value = value;
  setSearchText(value);
}

// Excel of every ticket matching the current filters and search, across all pages
function exportCardTickets() {
  const filters = encodeURIComponent(JSON.stringify(requestFilters.value));
  window.location.href = `/api/method/helpdesk.api.ticket.export_tickets?filters=${filters}`;
}

function loadCardViewTickets() {
  cardViewResource.update({
    params: {
      filters: JSON.stringify(requestFilters.value),
      limit: cardViewLimit.value,
      offset: cardViewOffset.value,
      order_by: "modified desc",
    },
  });
  cardViewResource.reload();
}

// ?filters=... is the filter state: dashboard links open the list with it, and the list writes its
// own filters back so refresh, Back and shared links keep them.
let urlFilters = ""; // the last ?filters value read from or written to the URL

watch(
  () => route.query.filters,
  (raw) => {
    const value = raw ? String(raw) : "";
    if (value === urlFilters) return; // our own router.replace
    urlFilters = value;
    let parsed = {};
    try {
      parsed = value ? JSON.parse(value) : {};
    } catch {
      parsed = {};
    }
    const { state, leftovers } = fromRouteFilters(parsed);
    clearCardFilters();
    Object.assign(panelFilters, state);
    routeLeftovers.value = leftovers;
  },
  { immediate: true }
);

watch(
  () => JSON.stringify(requestFilters.value),
  () => {
    cardViewOffset.value = 0;
    loadCardViewTickets();
    const { search: _search, ...filters } = requestFilters.value;
    const value = Object.keys(filters).length ? JSON.stringify(filters) : "";
    if (value === urlFilters) return;
    urlFilters = value;
    const query = { ...route.query };
    if (value) query.filters = value;
    else delete query.filters;
    router.replace({ query });
  },
  { immediate: true }
);

const slaStatusColorMap = {
  Fulfilled: "green",
  Failed: "red",
  "Resolution Due": "orange",
  "First Response Due": "orange",
  Paused: "blue",
};

let viewDialog = reactive({
  show: false,
  view: {
    label: "",
    icon: "",
    name: "",
  },
  mode: "create",
});

const dropdownOptions = computed(() => {
  const items = [
    {
      group: "Default Views",
      items: [
        {
          label: "List View",
          icon: "align-justify",
          onClick: () =>
            router.push({
              name: isCustomerPortal.value ? "TicketsCustomer" : "TicketsAgent",
            }),
        },
      ],
    },
  ];

  // Saved Views
  if (getCurrentUserViews.value?.length !== 0) {
    items.push({
      group: "Saved Views",
      items: parseViews(getCurrentUserViews.value),
    });
  }
  if (pinnedViews.value?.length !== 0) {
    items.push({
      group: "Private Views",
      items: parseViews(pinnedViews.value),
    });
  }
  if (publicViews.value?.length !== 0) {
    items.push({
      group: "Public Views",
      items: parseViews(publicViews.value),
    });
  }

  items.push({
    group: "Create View",
    hideLabel: true,
    items: [
      {
        label: "Create View",
        icon: "plus",
        onClick: () => {
          resetState();
          viewDialog.show = true;
        },
      },
    ],
  });

  return items;
});

let selectedView: View | null = null;

const viewActions = (view) => {
  const _view = findView(view.name).value;

  let actions = [
    {
      group: "Default Views",
      hideLabel: true,
      items: [
        {
          label: "Duplicate",
          icon: h(FeatherIcon, { name: "copy" }),
          onClick: () => {
            viewDialog.view.label = _view.label + " (New)";
            viewDialog.view.icon = _view.icon;
            viewDialog.view.name = _view.name;
            viewDialog.mode = "duplicate";
            selectedView = _view;
            viewDialog.show = true;
          },
        },
      ],
    },
  ];
  if (!_view.public || isManager) {
    actions[0].items.push({
      label: "Edit",
      icon: h(EditIcon, { class: "h-4 w-4" }),
      onClick: () => {
        viewDialog.view.label = _view.label;
        viewDialog.view.icon = _view.icon;
        viewDialog.view.name = _view.name;
        viewDialog.mode = "edit";
        viewDialog.show = true;
      },
    });
    if (!_view.public) {
      actions[0].items.push({
        label: _view?.pinned ? "Unpin View" : "Pin View",
        icon: h(_view?.pinned ? UnpinIcon : PinIcon, { class: "h-4 w-4" }),
        onClick: () => {
          const newView = {
            name: _view.name,
          };
          newView["pinned"] = !_view.pinned;
          updateView(newView);
        },
      });
    }
    if (isManager && !isCustomerPortal.value) {
      actions[0].items.push({
        label: _view?.public ? "Make Private" : "Make Public",
        icon: h(FeatherIcon, {
          name: _view?.public ? "lock" : "unlock",
          class: "h-4 w-4",
        }),
        onClick: () => {
          const newView = {
            name: _view.name,
            public: !_view.public,
          };

          if (_view.public) {
            $dialog({
              title: `Make ${_view.label} private?`,
              message:
                "This view is currently public. Changing it to private will hide it for all the users.",
              actions: [
                {
                  label: "Confirm",
                  variant: "solid",
                  onClick({ close }) {
                    close();
                    updateView(newView);
                  },
                },
              ],
            });
          } else {
            updateView(newView);
          }
        },
      });
    }
    actions.push({
      group: "Delete View",
      hideLabel: true,
      items: [
        {
          label: "Delete",
          icon: "trash-2",
          onClick: () => {
            $dialog({
              title: `Delete ${_view.label}?`,
              message: `Are you sure you want to delete this view?
              ${
                _view.public
                  ? "This view is public, and will be removed for all users."
                  : ""
              }`,
              actions: [
                {
                  label: "Confirm",
                  variant: "solid",
                  onClick({ close }) {
                    if (route.query.view === _view.name) {
                      router.push({
                        name: isCustomerPortal.value
                          ? "TicketsCustomer"
                          : "TicketsAgent",
                      });
                    }
                    deleteView(_view.name);
                    handleSuccess("deleted");
                    close();
                  },
                },
              ],
            });
          },
        },
      ],
    });
  }

  return actions;
};

function parseViews(views: View[]) {
  return views?.map((view) => {
    return {
      ...view,
      onClick: () => {
        currentView.value = {
          label: view.label,
          icon: view.icon,
        };
        router.push({
          name: view.route_name,
          query: {
            view: view.name,
          },
        });
      },
    };
  });
}

function handleView(viewInfo, action) {
  let view: View;
  if (action === "update") {
    updateView(viewInfo);
    handleSuccess("updated");
    currentView.value = {
      label: viewInfo.label,
      icon: getIcon(viewInfo.icon),
    };
    return;
  } else if (action === "duplicate") {
    view = {
      ...selectedView,
      filters: JSON.stringify(selectedView.filters),
      columns: JSON.stringify(selectedView.columns),
      rows: JSON.stringify(selectedView.rows),
      label: viewInfo.label,
      icon: viewInfo.icon,
      public: false,
      pinned: false,
    };
  } else {
    view = {
      dt: "HD Ticket",
      type: "list",
      label: viewInfo.label ?? "List",
      icon: viewInfo.icon ?? "",
      route_name: router.currentRoute.value.name as string,
      order_by: listViewRef.value?.list?.params.order_by,
      filters: JSON.stringify(listViewRef.value?.list?.params.filters),
      columns: JSON.stringify(listViewRef.value?.list?.data.columns),
      rows: JSON.stringify(listViewRef.value?.list?.data?.rows),
      is_customer_portal: isCustomerPortal.value,
    };
  }

  // createView
  createView(view, (d) => {
    currentView.value = {
      label: d.label || "List",
      icon: getIcon(d.icon),
    };
    router.push({
      name: isCustomerPortal.value ? "TicketsCustomer" : "TicketsAgent",
      query: {
        view: d.name,
      },
    });

    handleSuccess();
  });
}

function handleSuccess(msg = "created") {
  toast.success(`View ${msg}`);
  resetState();
}
function resetState() {
  viewDialog.show = false;
  viewDialog.view.label = "";
  viewDialog.view.icon = "";
  viewDialog.view.name = "";
  viewDialog.mode = null;
  selectedView = null;
}

onMounted(() => {
  if (!route.query.view) {
    currentView.value = {
      label: "List",
      icon: LucideAlignJustify,
    };
  }
  if (!isCustomerPortal.value) {
    $socket.on("helpdesk:new-ticket", () => {
      if (viewMode.value === "card") {
        cardViewResource.reload();
      } else {
        listViewRef.value?.reload();
      }
    });
  }
});

onUnmounted(() => {
  if (!isCustomerPortal.value) {
    $socket.off("helpdesk:new-ticket");
  }
});

usePageMeta(() => {
  return {
    title: "Tickets",
  };
});
</script>
