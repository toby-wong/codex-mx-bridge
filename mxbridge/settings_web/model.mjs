export const CLIENTS = { codex: "Codex", claude: "Claude", kiro: "Kiro", pi: "Pi" };
export const VIEWS = {
  paged: ["All chats, with pages", "Keep registration order. Use the console dial or next-page action to see more than nine chats."],
  recent: ["Nine most recently active", "Show the nine chats with the latest activity, including finished chats."],
  recent_open: ["Nine most recently active, still open", "Exclude closed, stopped and failed exits. Idle or stale chats can still appear."],
  newest: ["Nine newest chats", "Use recorded creation time. Resuming an older chat does not make it new."],
};
export const clone = value => structuredClone(value);
const final = new Set(["CLOSED", "EXIT ERROR", "STOPPED"]);
const compare = (a, b) => a < b ? -1 : a > b ? 1 : 0;

export function petNameFromSource(source) {
  let name = source.trim();
  if (name.includes("://")) {
    try {
      const url = new URL(name);
      if (url.protocol !== "https:") return "";
      const catalog = ["codex-pets.net", "www.codex-pets.net"].includes(url.hostname);
      const page = catalog && (url.hash.slice(1) || url.pathname).match(/^\/pets\/([a-zA-Z0-9_-]+)\/?$/);
      const download = catalog && url.pathname.match(/^\/api\/pets\/([a-zA-Z0-9_-]+)\/download$/);
      name = page?.[1] || download?.[1] || decodeURIComponent(url.pathname.split("/").at(-1));
    } catch { return ""; }
  }
  return name.replace(/(?:\.codex-pet)?\.(zip|png|webp)$/i, "")
    .replace(/[^a-zA-Z0-9_-]/g, "-").slice(0, 48);
}

export function selection(chat, config) {
  let pet = config.pet, rule = -1;
  for (const [index, item] of config.pet_rules.entries()) {
    if ((!item.client || item.client === chat.client) &&
        (!item.location || item.location === chat.location) &&
        (!item.host || (chat.location === "remote" && item.host === chat.host)) &&
        (!item.key || item.key === chat.key)) {
      pet = item.pet;
      rule = index;
    }
  }
  return { pet, rule };
}

export function resolvePet(reference, library) {
  const matches = library.filter(p => p.id === reference || p.name === reference);
  return matches.length === 1 && !matches[0].error ? matches[0] : null;
}

export function displayName(chat, config) {
  if (Object.hasOwn(config.name_overrides, chat.key)) return config.name_overrides[chat.key];
  if (!config.use_chat_names && chat.client === "pi" && chat.fallback_name) return chat.fallback_name;
  if (config.use_chat_names && chat.location === "local" && chat.client === "codex" &&
      chat.kind !== "subagent" && chat.saved_name) return chat.saved_name;
  return chat.name;
}

export function orderedChats(chats, view) {
  const rows = chats.filter(c => view !== "recent_open" || !final.has(c.raw_status ?? c.status));
  if (view === "paged") {
    return rows.sort((a, b) =>
      compare(a.location === "local" ? 0 : 1, b.location === "local" ? 0 : 1) ||
      compare(a.host, b.host) || a.order - b.order);
  }
  if (view === "newest") {
    return rows.sort((a, b) => compare(b.created_at ?? -Infinity, a.created_at ?? -Infinity) ||
      compare(a.host, b.host) || b.order - a.order || compare(a.key, b.key)).slice(0, 9);
  }
  return rows.sort((a, b) => b.updated_at - a.updated_at || compare(a.key, b.key)).slice(0, 9);
}

export function labels(chat, config) {
  const source = [];
  if (config.show_client) source.push(CLIENTS[chat.client] || "Codex");
  if (config.show_location) source.push(chat.location === "local" ? "local" : `remote: ${chat.host}`);
  return {
    source: source.join(" · "),
    name: config.show_name ? (chat.kind === "subagent" ? "> " : "") + displayName(chat, config) : "",
    status: config.show_status ? chat.status : "",
  };
}

export function animation(status, animate) {
  if (["WORKING", "TOOL", "COMPACT"].includes(status)) return { name: "running", still: !animate };
  if (["APPROVAL?", "WAITING"].includes(status)) return { name: "waiting", still: !animate };
  if (["TURN STOP", "STOPPED"].includes(status)) return { name: "review", still: !animate };
  if (["TURN ERROR", "EXIT ERROR"].includes(status)) return { name: "failed", still: !animate };
  return { name: "idle", still: !animate || status !== "READY" };
}

export function explicitChatPet(config, key) {
  return config.pet_rules.findLast(r => r.key === key &&
    !r.client && !r.location && !r.host)?.pet || "";
}

export function setChatPet(config, key, pet) {
  config.pet_rules = config.pet_rules.filter(r =>
    !(r.key === key && !r.client && !r.location && !r.host));
  if (pet) config.pet_rules.push({ key, pet });
}

export class Draft {
  constructor(document) { this.reset(document); }
  reset(document) {
    this.saved = clone(document.value);
    this.value = clone(document.value);
    this.revision = document.revision;
    this.path = document.path;
    this.error = document.error;
    this.conflict = false;
    this.latest = document;
  }
  get dirty() { return JSON.stringify(this.value) !== JSON.stringify(this.saved); }
  receive(document) {
    this.latest = document;
    if (document.revision === this.revision) return false;
    if (this.dirty) {
      this.conflict = true;
      return false;
    }
    this.reset(document);
    return true;
  }
  payload() { return { revision: this.revision, value: this.value }; }
}
