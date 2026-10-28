<template>
  <div class="flex flex-col">
    <div class="px-5 pb-4 flex flex-col">
      <!-- User avatar with buttons -->
      <TicketContact />
      <!-- Core Fields -->
      <div>
        <div
          v-for="(section, index) in coreFields"
          :key="index"
          :class="
            section.group ? 'flex flex-col gap-2 w-full mb-3' : 'mb-3'
          "
        >
          <template v-for="field in section.fields">
            <Link
              v-if="field.visible"
              :key="field.fieldname"
              :ref="(el) => setFieldRef(field.fieldname, el)"
              class="form-control-core form-control-link w-full"
              :id="field.fieldname"
              :page-length="10"
              :label="field.label"
              :placeholder="field.placeholder"
              :doctype="field.doctype"
              :modelValue="field.value"
              :required="field.required"
              :disabled="isTicketResolved || field.disabled"
              @update:model-value="
              (val:string) => handleFieldUpdate(field.fieldname, val,true)
            "
            />
            <FormControl
              v-if="field.fieldname === 'ticket_type' && subTypeOptions.length > 1"
              type="select"
              class="form-control-core mt-3"
              :label="__('Sub Type')"
              :options="subTypeOptions"
              :model-value="ticket.doc.sub_type || NONE"
              :disabled="isTicketResolved"
              @update:model-value="
                (val: string) => handleFieldUpdate('sub_type', val === NONE ? '' : val, true)
              "
            />
            <FormControl
              v-if="field.fieldname === 'ticket_type' && categoryOptions.length > 1"
              type="select"
              class="form-control-core mt-3"
              :label="__('Category')"
              :options="categoryOptions"
              :model-value="ticket.doc.custom_category || NONE"
              :disabled="isTicketResolved"
              @update:model-value="
                (val: string) => handleFieldUpdate('custom_category', val === NONE ? '' : val, true)
              "
            />
            <FormControl
              v-if="field.fieldname === 'ticket_type' && ticket.doc.custom_category"
              type="select"
              class="form-control-core mt-3"
              :label="__('Sub Category')"
              :options="subCategoryOptions"
              :model-value="ticket.doc.custom_sub_category || NONE"
              :disabled="isTicketResolved"
              @update:model-value="
                (val: string) => handleFieldUpdate('custom_sub_category', val === NONE ? '' : val, true)
              "
            />
            <!-- not locked by isTicketResolved: departments investigate after the agent resolves -->
            <FormControl
              v-if="field.fieldname === 'status'"
              type="select"
              class="form-control-core mt-3"
              :label="__('Investigation Status')"
              placeholder="—"
              :options="['Open', 'Resolved']"
              :model-value="ticket.doc.investigation_status || ''"
              @update:model-value="
                (val: string) => handleFieldUpdate('investigation_status', val, true)
              "
            />
            <FormControl
              v-if="field.fieldname === 'agent_group' && showTierPicker"
              type="select"
              class="form-control-core mt-3"
              :label="__('Internal SLA Tier')"
              :options="tierOptions"
              :model-value="ticket.doc.internal_sla_tier || NONE"
              @update:model-value="
                (val: string) =>
                  handleFieldUpdate('internal_sla_tier', val === NONE ? '' : val, true)
              "
            />
          </template>
        </div>

        <!-- Assignee component -->
        <AssignTo :readonly="isTicketResolved" />
        <div class="flex flex-col gap-1.5 mt-2">
          <span class="form-control-label text-xs">Owner</span>
          <FormControl
            type="select"
            :options="ownerOptions"
            :model-value="ownerDisplay"
            disabled
            class="form-control-core"
          />
        </div>
      </div>
    </div>

    <!-- Additional / complaint fields (grouped like Dieture Update Complaint) -->
    <div class="border-t flex flex-col pb-4">
      <div
        v-for="(section, index) in customFieldSections"
        :key="section.label"
        :class="index > 0 ? 'border-t border-gray-100 mt-1' : ''"
      >
        <div
          class="px-5 pt-3.5 pb-1.5 text-[11px] font-semibold uppercase tracking-wider text-gray-500"
        >
          {{ section.label }}
        </div>
        <TicketField
          v-for="field in section.fields"
          :key="field.fieldname"
          :field="field"
          :value="field.value"
          @change="({ fieldname, value }) => handleFieldUpdate(fieldname, value)"
        />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { Link } from "@/components";
import { parseField } from "@/composables/formCustomisation";
import { useNotifyTicketUpdate } from "@/composables/realtime";
import { useShortcut } from "@/composables/shortcuts";
import { getMeta } from "@/stores/meta";
import { __ } from "@/translation";
import {
  ActivitiesSymbol,
  AssigneeSymbol,
  CustomizationSymbol,
  FieldValue,
  TicketSymbol,
} from "@/types";
import { computed, inject, ref, watch } from "vue";
import { createResource, FormControl } from "frappe-ui";
import TicketField from "../TicketField.vue";
import AssignTo from "./AssignTo.vue";
import TicketContact from "./TicketContact.vue";

const ticket = inject(TicketSymbol);
const assignees = inject(AssigneeSymbol);
const customizations = inject(CustomizationSymbol);
const activities = inject(ActivitiesSymbol);
const { getFields, getField } = getMeta("HD Ticket");
const { notifyTicketUpdate } = useNotifyTicketUpdate(ticket.value?.name);

// Check if ticket is resolved to make fields readonly
const isTicketResolved = computed(() => {
  return ticket.value?.doc?.status_category === "Resolved";
});

const ownerDisplay = ref("");
const ownerOptions = computed(() => [
  {
    label: ownerDisplay.value || "—",
    value: ownerDisplay.value,
  },
]);

watch(
  () => ticket.value?.doc,
  (doc) => {
    if (doc) {
      console.log("Ticket doc (TicketDetailsTab):", doc);
    }
  },
  { immediate: true }
);

watch(
  () => ticket.value?.doc?.owner,
  (owner) => {
    ownerDisplay.value =
      owner ||
      ticket.value?.data?.owner ||
      ticket.value?.doc?.modified_by ||
      "";
  },
  { immediate: true }
);

const internalSlaOptions = createResource({
  url: "helpdesk.api.internal_sla.get_options",
  cache: "InternalSlaOptions",
  auto: true,
});

const showTierPicker = computed(
  () =>
    Boolean(internalSlaOptions.data?.enabled) &&
    Boolean(ticket.value.doc.investigation_status)
);

// frappe-ui's select drops options with an empty value
const NONE = "__none__";

const tierOptions = computed(() => {
  const tiers: string[] = [...(internalSlaOptions.data?.tiers || [])];
  const current = ticket.value.doc.internal_sla_tier;
  if (current && !tiers.includes(current)) tiers.push(current); // renamed or removed in settings
  return [
    { label: "No internal SLA", value: NONE },
    ...tiers.map((tier) => ({ label: tier, value: tier })),
  ];
});

// Sub types and first contact fields configured on the HD Ticket Type
const ticketTypeForms = createResource({
  url: "helpdesk.helpdesk.doctype.hd_ticket_type.hd_ticket_type.get_ticket_type_forms",
  cache: "TicketTypeForms",
  auto: true,
});
const typeForm = computed(
  () =>
    ticketTypeForms.data?.[ticket.value.doc.ticket_type] || {
      sub_types: [],
      fields: [],
    }
);
const subTypeOptions = computed(() => {
  const subs: string[] = [...typeForm.value.sub_types];
  const current = ticket.value.doc.sub_type;
  if (current && !subs.includes(current)) subs.push(current); // renamed or removed on the ticket type
  return [{ label: "—", value: NONE }, ...subs.map((s) => ({ label: s, value: s }))];
});

const categories = computed<Record<string, string[]>>(
  () => internalSlaOptions.data?.categories || {}
);
const categoryOptions = computed(() => [
  { label: "—", value: NONE },
  ...Object.keys(categories.value).map((c) => ({ label: c, value: c })),
]);
const subCategoryOptions = computed(() => {
  const subs = [...(categories.value[ticket.value.doc.custom_category] || [])];
  const current = ticket.value.doc.custom_sub_category;
  if (current && !subs.includes(current)) subs.push(current); // renamed or removed in crm
  return [
    { label: "—", value: NONE },
    ...subs.map((sub) => ({ label: sub, value: sub })),
  ];
});

// ticket_type, priority, status, customer, agent_group
const coreFields = computed(() => {
  // TODO: to confirm whether customizations should apply to core fields as well
  const fieldsMeta = getFields();
  if (!fieldsMeta || fieldsMeta.length === 0) {
    return [];
  }
  const _coreFields = [
    { group: false, fields: [getField("ticket_type")] },
    { group: false, fields: [getField("priority")] },
    { group: false, fields: [getField("status")] },
    { group: false, fields: [getField("agent_group")] },
  ];

  _coreFields.forEach((section) => {
    section.fields = section.fields.map((f) => {
      f = parseField(f, ticket.value.doc);

      // cant handle required depends on as we directly set the value in DB on change
      f["required"] = f.reqd;
      f["ref"] = f.fieldname;

      f = getFieldInFormat(f, f);
      f["visible"] = true;
      return f;
    });
  });
  return _coreFields;
});

/** Dieture complaint form order — section labels shown above matching template fields. */
const COMPLAINT_FIELD_SECTIONS: { label: string; fieldnames: string[] }[] = [
  {
    label: __("Complaints Overview"),
    fieldnames: [
      "custom_select_source",
      "custom_select_channel",
      "custom_select_type",
      "custom_ticket_number",
    ],
  },
  {
    label: __("Customer Information"),
    fieldnames: [
      "custom_customer_type",
      "custom_customer_phone",
      "custom_customer_name",
      "custom_customer_email",
      "custom_account_status",
      "custom_age",
      "custom_gender",
    ],
  },
  {
    label: __("Complaints Classification"),
    fieldnames: [
      "custom_proof",
      "custom_complaints_description",
      "custom_department",
      "custom_dish",
      "custom_dish_complaint",
      "custom_ingredients",
      "custom_date_of_dish",
    ],
  },
  {
    label: __("Complaints Tracking"),
    fieldnames: [
      "custom_customer_request",
      "custom_assigned_agent",
      "custom_assigned_manager",
      "custom_complaint_status",
      "custom_solution",
    ],
  },
];

const CORE_SKIP = new Set([
  "ticket_type",
  "priority",
  "customer",
  "agent_group",
  "subject",
  "status",
  "investigation_status",
  "internal_sla_tier",
  "sub_type",
  "custom_category",
  "custom_sub_category",
]);

const customFields = computed(() => {
  const fieldsMeta = getFields();
  if (!fieldsMeta || fieldsMeta.length === 0) {
    return [];
  }

  if (!customizations.value.data || customizations.value.loading) return [];
  let customFields = customizations.value.data?.custom_fields || [];
  const firstContact = new Set(typeForm.value.fields.map((f) => f.fieldname));
  customFields = customFields.filter(
    (f) => !CORE_SKIP.has(f.fieldname) && !firstContact.has(f.fieldname)
  );
  let _customFields = customFields.map((f) => {
    let fieldMeta = getField(f.fieldname);
    if (!fieldMeta) {
      return null;
    }

    fieldMeta = parseField(fieldMeta, ticket.value.doc);
    // cant handle required depends on as we directly set the value in DB
    fieldMeta["required"] = fieldMeta.reqd || f.required;

    return getFieldInFormat(f, fieldMeta);
  });
  return _customFields.filter((f) => f && f.visible);
});

/** Fields CS captures at first contact for this ticket type (HD Ticket Type → First Contact Fields). */
const firstContactFields = computed(() => {
  if (!getFields()?.length) return [];
  return typeForm.value.fields
    .map((f) => {
      const fieldMeta = getField(f.fieldname);
      if (!fieldMeta) return null;
      return getFieldInFormat(f, parseField(fieldMeta, ticket.value.doc));
    })
    .filter((f) => f && f.visible);
});

const customFieldSections = computed(() => {
  const fields = customFields.value || [];
  const byName = new Map(fields.map((f) => [f.fieldname, f]));
  const used = new Set<string>();
  const sections: { label: string; fields: typeof fields }[] = [];
  if (firstContactFields.value.length) {
    sections.push({
      label: __("First Contact (CS)"),
      fields: firstContactFields.value,
    });
  }

  for (const section of COMPLAINT_FIELD_SECTIONS) {
    const sectionFields = section.fieldnames
      .map((name) => byName.get(name))
      .filter(Boolean);
    if (!sectionFields.length) continue;
    sectionFields.forEach((f) => used.add(f.fieldname));
    sections.push({ label: section.label, fields: sectionFields });
  }

  const other = fields.filter((f) => !used.has(f.fieldname));
  if (other.length) {
    sections.push({ label: __("Additional Fields"), fields: other });
  }
  return sections;
});

function getFieldInFormat(fieldTemplate, fieldMeta) {
  return {
    label: fieldMeta?.label || fieldTemplate.fieldname,
    value: ticket.value.doc[fieldTemplate.fieldname],
    fieldtype: fieldMeta?.fieldtype,
    doctype: fieldMeta?.options || "",
    options: fieldMeta?.options || "",
    placeholder:
      fieldTemplate.placeholder ||
      `Enter ${fieldMeta?.label || fieldTemplate.fieldname}`,
    readonly: Boolean(fieldMeta.read_only) || isTicketResolved.value,
    disabled: Boolean(fieldMeta.read_only) || isTicketResolved.value,
    url_method: fieldTemplate.url_method || "",
    fieldname: fieldTemplate.fieldname,
    required: fieldTemplate.required || fieldMeta?.required || false,
    visible: fieldMeta.display_via_depends_on && !fieldMeta.hidden,
  };
}

function handleFieldUpdate(
  fieldname: string,
  value: FieldValue,
  isCoreFieldUpdated = false
) {
  if (ticket.value.doc[fieldname] == value) return;
  if (isCoreFieldUpdated) {
    const label = getField(fieldname)?.label || fieldname;
    notifyTicketUpdate(label, value as string);
  }
  const values: Record<string, FieldValue> = { [fieldname]: value };
  if (fieldname === "custom_category") values.custom_sub_category = ""; // a sub category belongs to one category
  ticket.value.setValue.submit(
    values,
    {
      onSuccess: () => {
        // TODO: emit the event for notification to listeners
        if (fieldname === "agent_group") {
          assignees.value.reload();
        }
        // Reload activities after a short delay to ensure backend has created the activity log
        // The helpdesk:ticket-update event (emitted with after_commit=True) will also trigger a reload
        // This ensures real-time updates for both the user making the change and other viewers
        setTimeout(() => {
          activities.value.reload();
        }, 800);
      },
    }

    //show error toast
  );
}

const fieldRefs = ref<Record<string, any>>({});

const setFieldRef = (fieldname: string, el: any) => {
  if (el) {
    fieldRefs.value[fieldname] = el;
  }
};

useShortcut("t", () => {
  fieldRefs.value?.ticket_type?.$el?.querySelector("button")?.click();
});

useShortcut("p", () => {
  fieldRefs.value?.priority?.$el?.querySelector("button")?.click();
});

useShortcut({ key: "t", shift: true }, () => {
  fieldRefs.value?.agent_group?.$el?.querySelector("button")?.click();
});
</script>

<style scoped>
:deep(.form-control-core label),
.form-control-label {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  align-self: stretch;
  color: #727272;
}

:deep(.form-control-core button),
:deep(.form-control-core [role="combobox"]) {
  display: flex !important;
  align-items: center !important;
  gap: 8px !important;
  flex-shrink: 0 !important;
  align-self: stretch !important;
  width: 100% !important;
  height: 36px !important;
  min-height: 36px !important;
  padding: 8px 12px !important;
  border-radius: 4px !important;
  border: 1px solid var(--Color-Tokens-Border-Primary, #e4e4e4) !important;
  background: var(--Color-Tokens-Background-Secondary, #f9f9f9) !important;
  box-sizing: border-box !important;
}
:deep(.form-control-core button > div) {
  @apply truncate;
}

:deep(.form-control-link div) {
  width: 100%;
  display: flex;
}
</style>
