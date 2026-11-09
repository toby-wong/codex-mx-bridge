import test from "node:test";
import assert from "node:assert/strict";
import { Draft, selection, resolvePet, displayName, orderedChats, labels, animation,
  setChatPet, explicitChatPet, petNameFromSource } from "../mxbridge/settings_web/model.mjs";

const config = () => ({ pet: "cat", mode: "pet", pet_rules: [
  { location: "remote", pet: "pingu" }, { client: "claude", pet: "dario" },
  { client: "pi", location: "remote", pet: "apupepe" },
  { client: "pi", location: "local", pet: "banana-cat" },
], show_name: true, show_location: true, show_client: true, show_status: true,
use_chat_names: true, name_overrides: {} });
const chat = values => ({ key: "chat", name: "Project", saved_name: "Saved title", fallback_name: "Agent",
  client: "pi", host: "local", location: "local", kind: "session", status: "READY", ...values });

test("suggests pet names from community links, signed file URLs and local files", () => {
  assert.equal(petNameFromSource("https://codex-pets.net/#/pets/banana-cat"), "banana-cat");
  assert.equal(petNameFromSource("https://codex-pets.net/pets/apupepe/"), "apupepe");
  assert.equal(petNameFromSource("https://codex-pets.net/api/pets/pingu/download?v=123"), "pingu");
  assert.equal(petNameFromSource("https://assets.example/My%20pet.codex-pet.zip?token=private"), "My-pet");
  assert.equal(petNameFromSource("Buddy.WEBP"), "Buddy");
  assert.equal(petNameFromSource("https://"), "");
  assert.equal(petNameFromSource("http://example.com/pet.png"), "");
});

test("matches all selectors and respects later rules for local and remote Pi children", () => {
  assert.equal(selection(chat({ kind: "subagent" }), config()).pet, "banana-cat");
  const row = chat({ host: "clouddesk", location: "remote", kind: "subagent" });
  assert.equal(selection(row, config()).pet, "apupepe");
  assert.equal(selection({ ...row, client: "claude" }, config()).pet, "dario");
  const value = config();
  value.pet_rules.push({ host: "different", client: "pi", pet: "wrong" });
  value.pet_rules.push({ host: "clouddesk", client: "pi", key: "chat", pet: "special" });
  assert.deepEqual(selection(row, value), { pet: "special", rule: 5 });
});
test("short pet names require one revision; missing and broken packs are not previewed", () => {
  const library = [{ id: "cat/123", name: "cat" }, { id: "cat/456", name: "cat" }];
  assert.equal(resolvePet("cat", library), null);
  assert.equal(resolvePet("cat/123", library).id, "cat/123");
  assert.equal(resolvePet("missing", library), null);
  assert.equal(resolvePet("cat", [{ name: "cat", id: "cat/123", error: "bad" }]), null);
});
test("chat views retain registration order or choose nine by the requested timestamp", () => {
  const rows = Array.from({ length: 12 }, (_, i) => chat({ key: `id${i}`, order: i,
    updated_at: 100 - i, created_at: i === 10 ? null : i, status: i === 0 ? "CLOSED" : "READY" }));
  assert.equal(orderedChats(rows, "paged").length, 12);
  assert.equal(orderedChats(rows, "paged")[0].key, "id0");
  assert.equal(orderedChats(rows, "recent").length, 9);
  assert.equal(orderedChats(rows, "recent")[0].key, "id0");
  assert.equal(orderedChats(rows, "recent_open")[0].key, "id1");
  assert.equal(orderedChats(rows, "newest")[0].key, "id11");
  assert(!orderedChats(rows, "newest").some(r => r.key === "id10"));
  rows[0].status = "OFFLINE"; rows[0].raw_status = "CLOSED";
  assert.equal(orderedChats(rows, "recent_open")[0].key, "id1");
  assert.equal(rows[0].key, "id0");
});
test("overrides win; local Codex names and Pi fallback follow the label switches", () => {
  const value = config(), row = chat({ client: "codex" });
  assert.equal(displayName(row, value), "Saved title");
  assert.equal(displayName({ ...row, location: "remote" }, value), "Project");
  assert.equal(displayName({ ...row, kind: "subagent" }, value), "Project");
  value.use_chat_names = false;
  assert.equal(displayName(row, value), "Project");
  assert.equal(displayName(chat(), value), "Agent");
  value.name_overrides.chat = "Mine";
  assert.equal(displayName(row, value), "Mine");
  Object.assign(value, { show_name: false, show_location: false, show_client: false, show_status: false });
  assert.deepEqual(labels(row, value), { source: "", name: "", status: "" });
});
test("chat pet changes follow stable keys and preserve unrelated assignment rules", () => {
  const value = config();
  value.pet_rules.push({ client: "pi", key: "chat", pet: "complex" });
  setChatPet(value, "chat", "special");
  assert.equal(explicitChatPet(value, "chat"), "special");
  assert.equal(selection(chat(), value).pet, "special");
  setChatPet(value, "chat", "");
  assert.equal(selection(chat(), value).pet, "complex");
  assert.equal(selection(chat({ key: "other" }), value).pet, "banana-cat");
});
test("external edits update a clean editor but preserve a dirty draft until explicit reload", () => {
  const original = { revision: "a", path: "/display.json", value: config(), error: "" };
  const draft = new Draft(original);
  const next = { ...original, revision: "b", value: { ...config(), pet: "new" } };
  assert.equal(draft.receive(next), true);
  assert.equal(draft.value.pet, "new");
  draft.value.pet = "unsaved";
  const third = { ...next, revision: "c", value: { ...config(), pet: "elsewhere" } };
  assert.equal(draft.receive(third), false);
  assert.equal(draft.value.pet, "unsaved");
  assert.equal(draft.revision, "b");
  assert.equal(draft.conflict, true);
  draft.reset(draft.latest);
  assert.equal(draft.value.pet, "elsewhere");
  assert.equal(draft.dirty, false);
});
test("motion off keeps the state pose and freezes its first frame", () => {
  assert.deepEqual(animation("TOOL", false), { name: "running", still: true });
  assert.deepEqual(animation("WAITING", true), { name: "waiting", still: false });
  assert.deepEqual(animation("CLOSED", true), { name: "idle", still: true });
});
