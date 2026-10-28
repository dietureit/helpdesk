import LucideBarChart2 from "~icons/lucide/bar-chart-2";
import LucideBookOpen from "~icons/lucide/book-open";
import LucideClipboardList from "~icons/lucide/clipboard-list";
import LucideContact2 from "~icons/lucide/contact-2";
import LucideTicket from "~icons/lucide/ticket";
import LucideTimer from "~icons/lucide/timer";
import PhoneIcon from "../icons/PhoneIcon.vue";

export const agentPortalSidebarOptions = [
  {
    label: "Tickets",
    icon: LucideTicket,
    to: "TicketsAgent",
  },
  {
    label: "Monthly Report",
    icon: LucideBarChart2,
    to: "MonthlyReport",
  },
  {
    label: "Customer Complaints",
    icon: LucideClipboardList,
    to: "CustomerComplaintsReport",
  },
  {
    label: "SLA Breaches",
    icon: LucideTimer,
    to: "SlaBreachReport",
  },
  {
    label: "Contacts",
    icon: LucideContact2,
    to: "ContactList",
  },
  {
    label: "Call Logs",
    icon: PhoneIcon,
    to: "CallLogs",
  },
];

export const customerPortalSidebarOptions = [
  {
    label: "Tickets",
    icon: LucideTicket,
    to: "TicketsCustomer",
  },
  {
    label: "Knowledge Base",
    icon: LucideBookOpen,
    to: "CustomerKnowledgeBase",
  },
];
