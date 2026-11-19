import { call } from "frappe-ui";
import { askForTags, pickableTags, tagPrompt, tagsForType, type TagOption } from "./ticketTags";

// the real frappe-ui needs the app's vite plugins (icons); ticketTags.ts only uses `call`
vi.mock("frappe-ui", () => ({ call: vi.fn() }));

const options: TagOption[] = [
  { name: "Late", enabled: 1, ticket_types: ["Delivery Issues"] },
  { name: "Retired", enabled: 0, ticket_types: ["Delivery Issues"] },
  { name: "Taste", enabled: 1, ticket_types: ["Quality"] },
  { name: "Untyped", enabled: 1, ticket_types: [] },
];
const names = (tags: TagOption[]) => tags.map((tag) => tag.name);

describe("tagsForType", () => {
  it("offers only the type's enabled tags", () => {
    expect(names(tagsForType(options, "Delivery Issues"))).toEqual(["Late"]);
    expect(tagsForType(options, "Packing Issues")).toEqual([]);
    expect(tagsForType(options, undefined)).toEqual([]);
  });
});

describe("pickableTags", () => {
  it("keeps the ticket's own tags, disabled or of another type, so they can be removed", () => {
    expect(names(pickableTags(options, "Delivery Issues", ["Retired", "Taste"]))).toEqual([
      "Late",
      "Retired",
      "Taste",
    ]);
  });
});

describe("askForTags", () => {
  it("opens only for a ticket type that has tags", async () => {
    vi.mocked(call).mockResolvedValue({ tags: options });
    await askForTags(1, "Packing Issues", []);
    expect(tagPrompt.show).toBe(false);
    await askForTags(2, "Delivery Issues", ["Taste"]);
    expect(tagPrompt).toMatchObject({ show: true, ticket: "2", tags: ["Taste"] });
    expect(names(tagPrompt.choices)).toEqual(["Late", "Taste"]);
  });

  it("doesn't let a late list replace a later prompt, or a no-tags ask hide an earlier one", async () => {
    let release = (_: unknown) => {};
    vi.mocked(call)
      .mockReturnValueOnce(new Promise((resolve) => (release = resolve)))
      .mockResolvedValueOnce({ tags: options });
    const slow = askForTags(3, "Delivery Issues", []);
    await askForTags(4, "Delivery Issues", []);
    release({ tags: options });
    await slow;
    expect(tagPrompt.ticket).toBe("4");

    vi.mocked(call)
      .mockReturnValueOnce(new Promise((resolve) => (release = resolve)))
      .mockResolvedValueOnce({ tags: options });
    const configured = askForTags(5, "Delivery Issues", []);
    await askForTags(6, "Packing Issues", []);
    release({ tags: options });
    await configured;
    expect(tagPrompt.ticket).toBe("5");
  });
});
