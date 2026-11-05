import { socket } from "@/socket";
import { createResource, getCachedResource } from "frappe-ui";
import { defineStore } from "pinia";
import { computed, ComputedRef } from "vue";

export const useConfigStore = defineStore("config", () => {
  const configResource = createResource({
    url: "helpdesk.api.config.get_config",
    auto: true,
  });

  const config = computed(() => configResource.data || {});
  const brandName = computed(() => config.value.brand_name);
  const brandLogo = computed(() => config.value.brand_logo);
  const favicon = computed(() => config.value.favicon);

  const teamRestrictionApplied = computed(
    () => !!parseInt(config.value.restrict_tickets_by_agent_group)
  );
  const assignWithinTeam = computed(
    () => !!parseInt(config.value.assign_within_team)
  );
  const skipEmailWorkflow: ComputedRef<boolean> = computed(
    () => !!parseInt(config.value.skip_email_workflow)
  );
  const preferKnowledgeBase = computed(
    () => !!parseInt(config.value.prefer_knowledge_base)
  );
  const isFeedbackMandatory = computed(
    () => !!parseInt(config.value.is_feedback_mandatory)
  );

  socket.on("helpdesk:settings-updated", () => configResource.reload());
  // An HD Ticket Type changed (e.g. Enabled toggled): refetch every cached ticket type list.
  // ["HD Ticket Type", "", hideMe] is the search cache key of components/frappe-ui/Link.vue.
  socket.on("helpdesk:ticket-types-updated", () => {
    for (const key of [
      "InternalSlaOptions",
      "TicketTypeForms",
      ["HD Ticket Type", "", false],
      ["HD Ticket Type", "", true],
    ])
      getCachedResource(key)?.reload();
  });

  return {
    configResource,
    brandName,
    brandLogo,
    favicon,
    config,
    preferKnowledgeBase,
    skipEmailWorkflow,
    isFeedbackMandatory,
    teamRestrictionApplied,
    assignWithinTeam,
  };
});
