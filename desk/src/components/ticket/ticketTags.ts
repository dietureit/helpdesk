// Investigation tags record what a department's investigation found ("No issues", ...).
// Tickets keep them in the `investigation_tags` child table; the list is HD Ticket Tag (Settings > Ticket Tags).
import { reactive } from "vue";

export type TagOption = { name: string; enabled: 0 | 1 };

/** Tag names from a ticket doc's child rows ({tag}) or a list row's plain names. */
export function tagsOf(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value
    .map((row) => (typeof row === "string" ? row : row?.tag))
    .filter(Boolean);
}

/** Tags a picker offers: enabled ones, plus disabled ones the ticket already has (so they can be removed). */
export function pickableTags(options: TagOption[], current: string[]): TagOption[] {
  return options.filter((tag) => tag.enabled || current.includes(tag.name));
}

export const tagPrompt = reactive({
  show: false,
  ticket: "",
  tags: [] as string[],
  // bumped by every askForTags, so the dialog resets even when a second ask arrives while it is open,
  // and a save that finishes late knows it no longer owns the dialog
  seq: 0,
  onSaved: undefined as undefined | (() => void),
});

let pendingSave: Promise<unknown> = Promise.resolve();

/** Save ticket fields after any save still in flight. The Details tag picker saves as it closes, usually on the
 * click into the next control (Investigation Status, the header's Inv menu), and two overlapping saves of one
 * ticket fail on the server ("Document has been modified after you have opened it"). */
export function queueTicketSave(
  doc: { setValue: { submit: (values: object, options?: object) => Promise<unknown> } },
  values: object,
  options: object = {}
) {
  // errors are already shown by the resource's onError; the queue only orders the requests
  pendingSave = pendingSave.then(() => doc.setValue.submit(values, options)).catch(() => {});
}

/** Ask for tags right after a ticket's investigation was resolved (TicketTagsDialog, mounted in AgentRoot). */
export function askForTags(ticket: string | number, current: string[], onSaved?: () => void) {
  Object.assign(tagPrompt, {
    show: true,
    ticket: String(ticket),
    tags: [...current],
    seq: tagPrompt.seq + 1,
    onSaved,
  });
}
