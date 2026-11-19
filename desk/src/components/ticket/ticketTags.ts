// Investigation tags record what a department's investigation found ("No issues", ...).
// Tickets keep them in the `investigation_tags` child table; the list is HD Ticket Tag (Settings > Ticket Tags).
// A tag is offered only on tickets of its ticket types (HD Ticket Tag > Ticket Types).
import { call } from "frappe-ui";
import { reactive } from "vue";

export type TagOption = { name: string; enabled: 0 | 1; ticket_types: string[] };

/** Tag names from a ticket doc's child rows ({tag}) or a list row's plain names. */
export function tagsOf(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value
    .map((row) => (typeof row === "string" ? row : row?.tag))
    .filter(Boolean);
}

/** Tags that can be added on a ticket of this type: enabled and linked to the type. With none, the ticket gets
 * no tag popup and no Details field. */
export function tagsForType(options: TagOption[], ticketType?: string): TagOption[] {
  // `?? []`: frappe-ui restores a cached list (IndexedDB) before refetching, and a bundle from before ticket types
  // cached tags without them
  return options.filter(
    (tag) => tag.enabled && !!ticketType && (tag.ticket_types ?? []).includes(ticketType)
  );
}

/** Tags a picker offers: the type's tags, plus the ticket's own (disabled or of another type) so they can be
 * removed. */
export function pickableTags(
  options: TagOption[],
  ticketType: string | undefined,
  current: string[]
): TagOption[] {
  const offered = tagsForType(options, ticketType);
  return options.filter((tag) => offered.includes(tag) || current.includes(tag.name));
}

export const tagPrompt = reactive({
  show: false,
  ticket: "",
  tags: [] as string[],
  choices: [] as TagOption[],
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

let asked = 0; // asks, numbered in the order they were made
let shown = 0; // the number of the ask the dialog shows, or showed last

/** Ask for tags right after a ticket's investigation was resolved (TicketTagsDialog, mounted in AgentRoot), only
 * when the ticket's type has tags. The list is fetched fresh: an admin may have changed tags since the page loaded. */
export async function askForTags(
  ticket: string | number,
  ticketType: string | undefined,
  current: string[],
  onSaved?: () => void
) {
  const ask = ++asked;
  let options: TagOption[];
  try {
    options = (await call("helpdesk.api.internal_sla.get_options"))?.tags || [];
  } catch {
    return; // no prompt; the Details tab can still tag the ticket
  }
  // an ask whose list arrived late doesn't replace a later one already on screen
  if (ask < shown || !tagsForType(options, ticketType).length) return;
  shown = ask;
  Object.assign(tagPrompt, {
    show: true,
    ticket: String(ticket),
    tags: [...current],
    choices: pickableTags(options, ticketType, current),
    seq: tagPrompt.seq + 1,
    onSaved,
  });
}
