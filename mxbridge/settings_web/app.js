import { CLIENTS, VIEWS, Draft, clone, selection, resolvePet, displayName, orderedChats,
  labels, animation, explicitChatPet, setChatPet, petNameFromSource } from "/model.mjs";
import { PALETTES, DEFAULT_THEME, validColor, schemeFor, colorsFor, applyTheme } from "/theme.mjs";

const $ = selector => document.querySelector(selector);
const all = selector => [...document.querySelectorAll(selector)];
const titles = {
  display: ["Display", "Choose what appears on your agent buttons."],
  theme: ["Theme", "Choose the colours and brightness of this app."],
  pets: ["Pet library", "A little company for every kind of work."],
  rules: ["Assignments", "Give each agent, location, or chat its own pet."],
  chats: ["Chats & names", "Make each conversation easy to recognize."],
  bridge: ["Bridge & focus", "Check your sources and configure button switching."],
};
const initialToken = location.hash.slice(1);
if (/^[A-Za-z0-9_-]{43}$/.test(initialToken)) {
  sessionStorage.setItem("mx-settings-token", initialToken);
  history.replaceState(null, "", location.pathname);
}
const token = sessionStorage.getItem("mx-settings-token") || "";
let snapshot, display, bindings, theme, tab = "display", previewPage = 0, polling = false, saving = false, stopped = false;
let generation = 0, importing = false;
let sprites = [], nextFrame = 0;
const images = new Map();
const reducedMotion = matchMedia("(prefers-reduced-motion: reduce)");
const systemDark = matchMedia("(prefers-color-scheme: dark)");

function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}
function button(text, action, className = "secondary") {
  const node = element("button", text, className);
  node.type = "button";
  node.addEventListener("click", action);
  return node;
}
function option(value, label) {
  const node = element("option", label);
  node.value = value;
  return node;
}
function select(options, value, change) {
  const node = element("select");
  for (const [id, label] of options) node.append(option(id, label));
  if (![...node.options].some(o => o.value === value)) node.append(option(value, value || "Any"));
  node.value = value;
  node.addEventListener("change", () => change(node.value));
  return node;
}
function input(value, placeholder, change, maxLength = 700) {
  const node = element("input");
  node.type = "text";
  node.value = value;
  node.placeholder = placeholder;
  node.maxLength = maxLength;
  node.addEventListener("input", () => change(node.value));
  return node;
}
function field(label, control, wide = false) {
  const node = element("label", label);
  control.setAttribute("aria-label", label);
  if (wide) node.className = "wide";
  node.append(control);
  return node;
}
function notice(message, type = "") {
  const node = $("#notice");
  node.textContent = message;
  node.className = "notice" + (type ? ` ${type}` : "");
  node.hidden = !message;
}
async function api(path, body) {
  const headers = { Authorization: `Bearer ${token}` };
  const init = { headers, cache: "no-store" };
  if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    init.method = "POST";
    init.body = JSON.stringify(body);
  }
  const response = await fetch(path, init);
  const value = await response.json();
  if (!response.ok) {
    const error = new Error(value.error || "The local settings app could not complete this request.");
    error.status = response.status;
    throw error;
  }
  return value;
}
function draftFor(name) { return name === "bridge" ? bindings : name === "theme" ? theme : display; }
function activeDraft() { return draftFor(tab); }
function invalidThemeColor() {
  return theme?.value?.palette === "custom" && all("[data-theme-hex]").some(control => !control.validity.valid);
}
function changed() {
  updateSave();
  renderPreview();
}
function updateSave() {
  const draft = activeDraft();
  if (!draft) return;
  $("#save").textContent = tab === "bridge" ? "Save bindings" : tab === "theme" ? "Save theme" : "Save changes";
  $("#save").disabled = saving || !draft.value || !draft.dirty || draft.conflict || (tab === "theme" && invalidThemeColor());
  $("#discard").disabled = saving || !draft.dirty;
  $("#save-state").textContent = saving ? "Saving…" : draft.conflict ? "File changed elsewhere" :
    draft.dirty ? "Unsaved changes" : draft.error ? "File needs attention" : "Up to date";
  $("#conflict").hidden = !draft.conflict;
  for (const nav of all("[data-tab]")) {
    const dirty = draftFor(nav.dataset.tab)?.dirty;
    nav.title = dirty ? "Unsaved changes" : "";
  }
}
function previewTheme() {
  return applyTheme(theme?.value || DEFAULT_THEME, systemDark.matches);
}
function renderTheme() {
  const config = theme?.value || DEFAULT_THEME;
  const scheme = previewTheme();
  $("#theme-mode").value = config.mode;
  $("#theme-mode").disabled = !theme?.value;
  $("#theme-scheme").textContent = config.mode === "system" ?
    `Following your system: ${scheme}. Changes to system appearance apply automatically.` :
    `${scheme === "dark" ? "Dark" : "Light"} appearance stays on until you change it.`;
  $("#theme-warning").hidden = Boolean(theme?.value);
  $("#theme-warning").textContent = `Cannot read the theme: ${theme?.error || "invalid settings"}. Restore the default theme and save to recover; the original file will be backed up.`;
  $("#theme-palettes").replaceChildren();
  for (const [id, name] of [...Object.entries(PALETTES).map(([key, palette]) => [key, palette.name]), ["custom", "Custom"]]) {
    const choice = button(name, () => {
      theme.value.palette = id;
      renderTheme(); updateSave();
    }, "palette-choice");
    choice.dataset.palette = id;
    choice.setAttribute("aria-pressed", String(config.palette === id));
    choice.disabled = !theme?.value;
    const colors = colorsFor({ ...config, palette: id }, scheme);
    choice.style.setProperty("--swatch-background", colors.background);
    choice.style.setProperty("--swatch-accent", colors.accent);
    const swatch = element("span", "", "palette-swatch");
    swatch.setAttribute("aria-hidden", "true");
    choice.prepend(swatch);
    $("#theme-palettes").append(choice);
  }
  $("#custom-theme").hidden = config.palette !== "custom" || !theme?.value;
  $("#customize-theme").hidden = config.palette === "custom" || !theme?.value;
  $("#custom-theme-title").textContent = `Custom ${scheme} colours`;
  const colors = colorsFor(config, scheme);
  for (const name of ["accent", "background"]) {
    $(`#theme-${name}`).value = $(`#theme-${name}-hex`).value = colors[name];
  }
  $("#theme-color-error").hidden = true;
  $("#theme-path").textContent = theme?.path || "";
}
function petOptions(reference = "", inherit = null) {
  const choices = inherit === null ? [["", "Choose an imported pet"]] : [["", inherit]];
  const counts = new Map();
  for (const pet of snapshot.pets) counts.set(pet.name, (counts.get(pet.name) || 0) + 1);
  for (const pet of snapshot.pets) {
    choices.push([pet.id, `${pet.name}${counts.get(pet.name) > 1 ? ` · ${pet.id.split("/")[1].slice(0, 6)}` : ""}${pet.error ? " · unavailable" : ""}`]);
  }
  if (reference && !choices.some(([id]) => id === reference)) {
    choices.push([reference, resolvePet(reference, snapshot.pets) ? reference : `${reference} · not installed / ambiguous`]);
  }
  return choices;
}
function petSelect(value, change, inherit) { return select(petOptions(value, inherit), value, change); }
function updatePickers() {
  if (!display.value) return;
  const picker = $("#default-pet");
  picker.replaceChildren(...petOptions(display.value.pet).map(([id, name]) => option(id, name)));
  picker.value = display.value.pet;
}
function renderDisplay() {
  if (!display.value) return;
  updatePickers();
  for (const control of all("[data-setting]")) {
    const value = display.value[control.dataset.setting];
    if (control.type === "checkbox") control.checked = value;
    else control.value = value;
  }
  $("#fps-value").textContent = `${display.value.fps} fps`;
  $("#view-help").textContent = VIEWS[display.value.chat_view][1];
}

function sampleChats() {
  const examples = [
    ["pi", "local", "READY", "A fresh idea"], ["pi", "remote", "WORKING", "Remote build"],
    ["claude", "local", "APPROVAL?", "Review changes"], ["codex", "local", "TOOL", "Bridge settings"],
    ["codex", "remote", "TURN STOP", "API cleanup"], ["kiro", "local", "READY", "Weekend project"],
    ["claude", "remote", "WORKING", "Write the tests"], ["pi", "local", "TOOL", "Worker", "subagent"],
    ["kiro", "remote", "TURN ERROR", "Try again"],
  ];
  return examples.map(([client, location, status, name, kind = "session"], index) => ({
    key: `sample-${index}`, client, location, status, raw_status: status, name, kind,
    host: location === "local" ? "local" : snapshot.sources.find(s => s.location === "remote")?.host || "desktop",
    order: index, updated_at: 100 - index, created_at: 100 - index,
  }));
}
function tone(status) {
  if (["WORKING", "TOOL", "COMPACT"].includes(status)) return "work";
  if (["APPROVAL?", "WAITING"].includes(status)) return "wait";
  if (["TURN ERROR", "EXIT ERROR"].includes(status)) return "error";
  return "quiet";
}
function attachSprite(parent, pet, status = "READY", alt = "", library = false) {
  const image = element("img");
  image.alt = alt;
  parent.append(image);
  sprites.push({ image, pet, status, library, pending: "" });
}
function renderPreview() {
  if (!snapshot || !display?.value) return;
  sprites = sprites.filter(s => s.image.isConnected && s.library);
  const config = display.value;
  const sample = $("#preview-source").value === "sample" || snapshot.chats.length === 0;
  const rows = orderedChats(sample ? sampleChats() : snapshot.chats, config.chat_view);
  const count = Math.max(1, Math.ceil(rows.length / 9));
  previewPage = ((previewPage % count) + count) % count;
  const grid = $("#preview-grid");
  grid.replaceChildren();
  for (let i = 0; i < 9; i++) {
    const row = rows[previewPage * 9 + i];
    const key = element("div", undefined, "key");
    grid.append(key);
    if (!row) {
      key.classList.add("empty-key");
      key.textContent = "Empty";
      continue;
    }
    const text = labels(row, config);
    key.dataset.tone = tone(row.status);
    key.title = `${displayName(row, config)} · ${CLIENTS[row.client]} · ${row.host} · ${row.status}`;
    const pet = config.mode === "pet" ? resolvePet(selection(row, config).pet, snapshot.pets) : null;
    if (text.source) key.append(element("div", text.source, "source"));
    if (text.name) key.append(element("div", text.name, "chat-name"));
    if (pet) attachSprite(key, pet, row.status);
    else key.classList.add("text-mode");
    if (text.status) key.append(element("div", text.status, "status"));
    if (!pet && !text.name && !text.status && !text.source) key.textContent = config.mode === "pet" ? "Pet unavailable" : "";
  }
  $("#page-number").textContent = `${previewPage + 1} / ${count}`;
  $("#previous-page").disabled = $("#next-page").disabled = count === 1;
  $("#preview-caption").textContent = sample ? "Sample agents · preview only" :
    `${rows.length} ${config.chat_view === "paged" ? "chats across all pages" : "selected chats"} · changes are shown before saving`;
  drawFrames(performance.now(), true);
}
async function imageUrl(pet, filename) {
  const key = `${pet.id}/${filename}`;
  if (!images.has(key)) {
    images.set(key, fetch(`/api/frame?pet=${encodeURIComponent(pet.id)}&file=${encodeURIComponent(filename)}`,
      { headers: { Authorization: `Bearer ${token}` } }).then(async response => {
      if (!response.ok) throw new Error("Pet frame unavailable");
      return URL.createObjectURL(await response.blob());
    }).catch(error => {
      images.delete(key);
      throw error;
    }));
  }
  return images.get(key);
}
function drawFrames(now, force = false) {
  if (!snapshot || !display?.value || stopped || document.hidden) return;
  const fps = display.value.fps || 4;
  const frameNumber = Math.floor(now / 1000 * fps);
  if (!force && nextFrame === frameNumber) return;
  nextFrame = frameNumber;
  sprites = sprites.filter(s => s.image.isConnected);
  for (const sprite of sprites) {
    if (sprite.image.closest("[hidden]")) continue;
    if (sprite.retryAfter > now) continue;
    const pose = animation(sprite.status, display.value.animate && !reducedMotion.matches);
    const frames = sprite.pet.animations[pose.name] || sprite.pet.animations.idle;
    if (!frames?.length) continue;
    const filename = frames[pose.still ? 0 : Math.floor(now / 1000 * fps) % frames.length];
    if (sprite.pending === filename) continue;
    sprite.pending = filename;
    imageUrl(sprite.pet, filename).then(url => {
      if (sprite.pending === filename && sprite.image.isConnected) sprite.image.src = url;
    }).catch(() => {
      sprite.image.alt = "Frame unavailable";
      sprite.pending = "";
      sprite.retryAfter = performance.now() + 5000;
    });
  }
}
function tick(now) {
  drawFrames(now);
  if (!stopped) requestAnimationFrame(tick);
}
requestAnimationFrame(tick);

function renderLibrary() {
  const root = $("#pet-library");
  root.replaceChildren();
  sprites = sprites.filter(s => s.image.isConnected);
  $("#library-count").textContent = `${snapshot.pets.length} imported pet revisions`;
  if (!snapshot.pets.length) root.append(element("div", "Your pet library is empty. Import a package below to get started.", "empty"));
  for (const pet of snapshot.pets) {
    const selected = display.value && resolvePet(display.value.pet, snapshot.pets)?.id === pet.id;
    const card = element("article", undefined, `pet-card${selected ? " selected" : ""}`);
    const stage = element("div", undefined, "pet-stage");
    if (!pet.error) attachSprite(stage, pet, "READY", pet.name, true);
    else stage.textContent = "Pack unavailable";
    card.append(stage, element("h3", pet.name),
      element("p", pet.id.split("/")[1], "revision"));
    const use = button(selected ? "Default pet ✓" : "Use as default", () => {
      if (!display.value) return;
      display.value.pet = pet.id;
      display.value.mode = "pet";
      changed();
      renderLibrary();
      notice(`${pet.name} is selected in your draft. Save changes to apply it.`);
    });
    use.disabled = !!pet.error || !display.value;
    card.append(use);
    if (pet.error) card.append(element("p", pet.error, "help"));
    root.append(card);
  }
  $("#import-pet").disabled = importing || !snapshot.can_import;
  if (!snapshot.can_import) $("#import-status").textContent = "The importer needs Pillow. Run bash install.sh --with-pets once.";
  drawFrames(performance.now(), true);
}

function renderRules() {
  const root = $("#rules");
  root.replaceChildren();
  if (!display.value) return;
  if (!display.value.pet_rules.length) root.append(element("div", "Every chat uses the default pet. Add an assignment to make an exception.", "empty"));
  display.value.pet_rules.forEach((rule, index) => {
    const row = element("article", undefined, "rule");
    const heading = element("div", undefined, "rule-header");
    const title = element("h3");
    title.append(element("span", String(index + 1).padStart(2, "0"), "rule-index"), document.createTextNode("Assignment"));
    const actions = element("div", undefined, "rule-actions");
    for (const [delta, text, label] of [[-1, "↑", "Move assignment up"], [1, "↓", "Move assignment down"]]) {
      const move = button(text, () => {
        const rules = display.value.pet_rules;
        [rules[index], rules[index + delta]] = [rules[index + delta], rules[index]];
        changed(); renderRules();
      });
      move.setAttribute("aria-label", `${label} ${index + 1}`);
      move.disabled = index + delta < 0 || index + delta >= display.value.pet_rules.length;
      actions.append(move);
    }
    actions.append(button("Remove", () => { display.value.pet_rules.splice(index, 1); changed(); renderRules(); }, "text-button danger-button"));
    heading.append(title, actions);
    const fields = element("div", undefined, "rule-fields");
    const update = key => value => {
      if (value) rule[key] = value;
      else delete rule[key];
      changed();
    };
    const host = input(rule.host || "", "Any remote host", update("host"), 255);
    host.setAttribute("list", "remote-hosts");
    const chat = input(rule.key || "", "Any chat", update("key"));
    chat.setAttribute("list", "chat-keys");
    fields.append(
      field("Agent client", select([["", "Any client"], ...Object.entries(CLIENTS)], rule.client || "", update("client"))),
      field("Location", select([["", "Local + remote"], ["local", "Local"], ["remote", "Remote"]], rule.location || "", update("location"))),
      field("Pet", petSelect(rule.pet, update("pet"))),
      field("Remote host", host), field("Individual chat key", chat, true));
    row.append(heading, fields);
    root.append(row);
  });
  $("#add-rule").disabled = display.value.pet_rules.length >= 64 || !snapshot.pets.some(p => !p.error);
}

function setName(key, name) {
  const entries = Object.entries(display.value.name_overrides).filter(([id]) => id !== key);
  if (name.trim()) entries.push([key, name.trim()]);
  display.value.name_overrides = Object.fromEntries(entries);
  changed();
}
function renderChats() {
  if (!display.value) return;
  const root = $("#chat-rows");
  root.replaceChildren();
  const query = $("#chat-search").value.toLowerCase();
  const matches = snapshot.chats.filter(c => [displayName(c, display.value), c.name, c.client, c.host, c.key]
    .some(v => v.toLowerCase().includes(query)));
  const rows = [...matches].sort((a, b) => b.updated_at - a.updated_at).slice(0, 200);
  $("#chat-count").textContent = `${rows.length} of ${matches.length} chats${matches.length > 200 ? " · refine your search" : ""}`;
  if (!rows.length) {
    const cell = element("td", snapshot.chats.length ? "No matching chats." : "Chats will appear after an agent sends its first bridge event.");
    cell.colSpan = 3;
    const row = element("tr"); row.append(cell); root.append(row);
  }
  for (const chat of rows) {
    const row = element("tr"), info = element("td"), nameCell = element("td"), petCell = element("td");
    info.append(element("div", displayName(chat, display.value), "chat-title"),
      element("div", `${CLIENTS[chat.client] || chat.client} · ${chat.host} · ${chat.status}${chat.kind === "subagent" ? " · child agent" : ""}`, "chat-meta"),
      element("div", chat.key, "chat-key"));
    const name = input(display.value.name_overrides[chat.key] || "", "Use chat name", value => setName(chat.key, value), 80);
    name.setAttribute("aria-label", `Display name for ${chat.name}`);
    nameCell.append(name);
    const choice = petSelect(explicitChatPet(display.value, chat.key), value => {
      setChatPet(display.value, chat.key, value); changed(); renderChats();
    }, "Use assignment rules");
    choice.setAttribute("aria-label", `Pet for ${chat.name}`);
    const chosen = selection(chat, display.value);
    petCell.append(choice, element("div", `${chosen.pet || "No pet"} · ${chosen.rule < 0 ? "default" : `rule ${chosen.rule + 1}`}`, "chat-assignment"));
    row.append(info, nameCell, petCell); root.append(row);
  }
  renderOtherNames();
}
function renderOtherNames() {
  const root = $("#other-names");
  root.replaceChildren();
  if (!display.value) return;
  const keys = new Set(snapshot.chats.map(c => c.key));
  for (const [key, name] of Object.entries(display.value.name_overrides)) {
    if (keys.has(key)) continue;
    const row = element("div", undefined, "override-row");
    const keyInput = input(key, "Stable chat key", () => {});
    keyInput.readOnly = true;
    keyInput.setAttribute("aria-label", "Chat key");
    const title = input(name, "Display name", value => setName(key, value), 80);
    title.setAttribute("aria-label", `Display name for ${key}`);
    row.append(keyInput, title, button("Remove", () => { setName(key, ""); renderOtherNames(); }, "text-button danger-button"));
    root.append(row);
  }
}

function bindingEditor(item, index, remote) {
  const collection = remote ? "remote_bindings" : "bindings";
  const root = element("div", undefined, "binding");
  const heading = element("div", undefined, "rule-header");
  heading.append(element("strong", `${remote ? "Remote" : "Local"} binding ${index + 1}`),
    button("Remove", () => { bindings.value[collection].splice(index, 1); updateSave(); renderBindings(); }, "text-button danger-button"));
  const fields = element("div", undefined, "binding-fields");
  const specs = remote ? [
    ["source", "Collector source", "clouddesk", 64], ["ssh_target", "SSH alias / target", "desktop-ssh", 255],
    ["herdr_path", "Remote Herdr executable", "herdr", 512], ["remote_session", "Named Herdr session (optional)", "Default session", 64],
    ["iterm_id", "Outer Mac iTerm session UUID", "XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX", 256],
  ] : [
    ["socket_path", "Local Herdr socket", "/Users/you/.config/herdr/herdr.sock", 512],
    ["iterm_id", "Outer iTerm session UUID", "XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX", 256],
  ];
  for (const [key, label, hint, limit] of specs) {
    const control = input(item[key] || "", hint, value => {
      item[key] = key === "iterm_id" ? value.split(":").at(-1) : value;
      updateSave();
    }, limit);
    if (key === "source") control.setAttribute("list", "remote-hosts");
    fields.append(field(label, control, key === "iterm_id"));
  }
  root.append(heading, fields);
  return root;
}
function renderBindings() {
  $("#local-bindings").replaceChildren();
  $("#remote-bindings").replaceChildren();
  if (!bindings.value) {
    $("#local-bindings").append(element("p", `Cannot read bindings: ${bindings.error}. Repair the file before editing it.`, "help"));
    $("#add-local-binding").disabled = $("#add-remote-binding").disabled = true;
    return;
  }
  bindings.value.bindings.forEach((item, index) => $("#local-bindings").append(bindingEditor(item, index, false)));
  (bindings.value.remote_bindings || []).forEach((item, index) => $("#remote-bindings").append(bindingEditor(item, index, true)));
  $("#add-local-binding").disabled = bindings.value.bindings.length >= 16;
  $("#add-remote-binding").disabled = (bindings.value.remote_bindings || []).length >= 16;
}
function renderHealth() {
  const sources = $("#sources");
  sources.replaceChildren();
  for (const source of snapshot.sources) {
    const row = element("div", undefined, "source-row");
    const details = element("div");
    details.append(element("strong", source.host), element("p", `${source.count} recorded chats`, "help"));
    const status = element("span", source.location === "local" ? "Local hooks" :
      source.offline ? "Collector offline" : "Receiving updates", `source-status${source.offline ? " offline" : ""}`);
    status.prepend(element("i", "", `dot${source.offline ? " disconnected" : ""}`));
    row.append(details, status); sources.append(row);
  }
  $("#state-error").textContent = snapshot.state_error || (snapshot.dropped_rows ? `${snapshot.dropped_rows} old rows have been pruned by the bridge.` : "");
  $("#config-paths").replaceChildren(element("div", `Display: ${display.path}`),
    element("div", `Theme: ${theme.path}`), element("div", `Bindings: ${bindings.path}`));
  const diagnostics = $("#diagnostics");
  diagnostics.replaceChildren();
  if (!snapshot.diagnostics.length) diagnostics.append(element("p", "No diagnostic messages yet.", "help"));
  for (const item of snapshot.diagnostics) {
    const detail = element("details", undefined, "diagnostic");
    const summary = element("summary", item.name);
    const stamp = element("time", new Date(item.updated_at * 1000).toLocaleString());
    stamp.dateTime = new Date(item.updated_at * 1000).toISOString();
    summary.append(stamp);
    detail.append(summary, element("pre", item.text));
    diagnostics.append(detail);
  }
}
function renderActive() {
  previewTheme();
  if (tab === "display") renderDisplay();
  if (tab === "theme") renderTheme();
  if (tab === "pets") renderLibrary();
  if (tab === "rules") renderRules();
  if (tab === "chats") renderChats();
  if (tab === "bridge") { renderBindings(); renderHealth(); }
  renderPreview();
  updateSave();
}
function showTab(name) {
  tab = name;
  for (const view of all(".view")) view.hidden = view.id !== `view-${name}`;
  for (const item of all("[data-tab]")) {
    if (item.dataset.tab === name) item.setAttribute("aria-current", "page");
    else item.removeAttribute("aria-current");
  }
  [$("#page-title").textContent, $("#page-description").textContent] = titles[name];
  renderActive();
}
function datalists() {
  $("#remote-hosts").replaceChildren(...snapshot.sources.filter(s => s.location === "remote").map(s => option(s.host, s.host)));
  $("#chat-keys").replaceChildren(...snapshot.chats.map(c => option(c.key, `${c.name} · ${CLIENTS[c.client]} · ${c.host}`)));
}

async function refresh() {
  if (polling || stopped || saving) return;
  polling = true;
  const requestedGeneration = generation;
  try {
    const next = await api("/api/state");
    if (requestedGeneration !== generation) return;
    const first = !snapshot;
    const libraryChanged = first || JSON.stringify(next.pets) !== JSON.stringify(snapshot.pets);
    snapshot = next;
    let displayChanged = false, bindingsChanged = false, themeChanged = false;
    if (first) {
      display = new Draft(next.config); bindings = new Draft(next.bindings); theme = new Draft(next.theme);
    } else {
      displayChanged = display.receive(next.config);
      bindingsChanged = bindings.receive(next.bindings);
      themeChanged = theme.receive(next.theme);
    }
    if (first || themeChanged) previewTheme();
    $("#connection").textContent = "Local app connected";
    $("#connection-dot").classList.remove("disconnected");
    $("#version").textContent = `Bridge ${next.version}`;
    $("#loading").hidden = true; $("#app").hidden = false;
    if (first || (themeChanged && tab === "theme") || (displayChanged && tab !== "theme") ||
        (libraryChanged && tab === "pets") || (bindingsChanged && tab === "bridge")) renderActive();
    else {
      renderPreview();
      if (tab === "chats" && !document.activeElement.closest("#chat-rows, #other-names")) renderChats();
      if (tab === "bridge" && !document.activeElement.closest("#diagnostics")) renderHealth();
      updateSave();
    }
    if (first || snapshot.chats.length !== $("#chat-keys").options.length) datalists();
    if (!display.value) notice(`Cannot read display settings: ${display.error}. Import a valid display settings file under Bridge & focus to recover. The original file will be backed up.`, "error");
  } catch (error) {
    $("#connection").textContent = "Disconnected";
    $("#connection-dot").classList.add("disconnected");
    if (!snapshot) $("#loading").textContent = error.message;
    else notice(`Connection lost. Your unsaved changes are still in the editor. ${error.message}`, "error");
  } finally { polling = false; }
}

for (const item of all("[data-tab]")) item.addEventListener("click", () => snapshot && showTab(item.dataset.tab));
$("#theme-mode").addEventListener("change", event => {
  if (!theme?.value) return;
  theme.value.mode = event.target.value;
  renderTheme(); updateSave();
});
$("#customize-theme").addEventListener("click", () => {
  if (!theme?.value || !PALETTES[theme.value.palette]) return;
  for (const scheme of ["light", "dark"]) {
    Object.assign(theme.value.colors[scheme], PALETTES[theme.value.palette][scheme]);
  }
  theme.value.palette = "custom";
  renderTheme(); updateSave();
});
for (const control of all("[data-theme-color], [data-theme-hex]")) {
  control.addEventListener("input", () => {
    if (!theme?.value) return;
    const name = control.dataset.themeColor || control.dataset.themeHex;
    if (validColor(control.value)) {
      const scheme = schemeFor(theme.value, systemDark.matches);
      theme.value.colors[scheme][name] = control.value.toLowerCase();
      theme.value.palette = "custom";
      $(`#theme-${name}`).value = $(`#theme-${name}-hex`).value = control.value.toLowerCase();
      previewTheme();
      $('[data-palette="custom"]')?.style.setProperty(`--swatch-${name}`, control.value.toLowerCase());
    }
    $("#theme-color-error").hidden = !invalidThemeColor();
    updateSave();
  });
}
$("#reset-theme").addEventListener("click", () => {
  if (!theme) return;
  theme.value = { ...theme.value, ...clone(DEFAULT_THEME) };
  renderTheme(); updateSave();
});
systemDark.addEventListener("change", () => {
  if (theme?.value?.mode !== "system") return;
  previewTheme();
  if (tab === "theme") renderTheme();
});
for (const [id, [label]] of Object.entries(VIEWS)) $("#chat-view").append(option(id, label));
for (const control of all("[data-setting]")) {
  control.addEventListener(control.type === "range" ? "input" : "change", () => {
    if (!display?.value) return;
    const key = control.dataset.setting;
    display.value[key] = control.type === "checkbox" ? control.checked :
      key === "fps" ? Number(control.value) : control.value;
    if (key === "mode" && control.value === "pet" && !display.value.pet) {
      display.value.pet = snapshot.pets.find(p => !p.error)?.id || "";
      updatePickers();
    }
    $("#fps-value").textContent = `${display.value.fps} fps`;
    $("#view-help").textContent = VIEWS[display.value.chat_view][1];
    changed();
  });
}
$("#pet-only").addEventListener("click", () => {
  if (!display?.value) return;
  for (const key of ["show_name", "show_location", "show_client", "show_status"]) display.value[key] = false;
  renderDisplay(); changed();
});
$("#preview-source").addEventListener("change", () => { previewPage = 0; renderPreview(); });
$("#previous-page").addEventListener("click", () => { previewPage--; renderPreview(); });
$("#next-page").addEventListener("click", () => { previewPage++; renderPreview(); });
$("#chat-search").addEventListener("input", renderChats);
$("#add-rule").addEventListener("click", () => {
  if (!display?.value) return;
  display.value.pet_rules.push({ location: "remote", pet: snapshot.pets.find(p => !p.error)?.id || "" });
  changed(); renderRules();
  $("#rules").lastElementChild?.querySelector("select")?.focus();
});
$("#add-name").addEventListener("click", () => {
  const row = element("div", undefined, "override-row");
  const key = input("", "Stable chat key", () => {});
  key.setAttribute("aria-label", "New name override chat key");
  key.setAttribute("list", "chat-keys");
  const name = input("", "Display name", () => {}, 80);
  name.setAttribute("aria-label", "New display name");
  row.append(key, name, button("Add", () => {
    if (!key.value.trim() || !name.value.trim()) { notice("Enter a chat key and display name.", "warning"); return; }
    setName(key.value.trim(), name.value);
    renderChats();
  }));
  $("#other-names").append(row);
  key.focus();
});
for (const remote of [false, true]) {
  $(`#add-${remote ? "remote" : "local"}-binding`).addEventListener("click", () => {
    if (!bindings?.value) return;
    const key = remote ? "remote_bindings" : "bindings";
    bindings.value[key] ||= [];
    bindings.value[key].push(remote ? { source: "", ssh_target: "", herdr_path: "herdr", remote_session: "", iterm_id: "" } : { socket_path: "", iterm_id: "" });
    updateSave(); renderBindings();
  });
}
$("#save").addEventListener("click", async () => {
  const draft = activeDraft();
  if (!draft?.dirty || draft.conflict || (tab === "theme" && invalidThemeColor())) return;
  const kind = tab === "bridge" ? "bindings" : tab === "theme" ? "theme" : "display";
  const sent = clone(draft.payload());
  generation++;
  saving = true; updateSave();
  try {
    const result = await api(`/api/${kind}`, sent);
    const editedWhileSaving = JSON.stringify(draft.value) !== JSON.stringify(sent.value);
    const currentEdits = clone(draft.value);
    draft.reset(result.document);
    if (editedWhileSaving) draft.value = currentEdits;
    const label = { display: "display settings", bindings: "terminal bindings", theme: "app theme" }[kind];
    notice(`Saved ${label}. ${editedWhileSaving ? "Your newer edits are still unsaved." :
      kind === "theme" ? "Other settings windows reload automatically." : "The plugin will reload the file automatically."}`);
  } catch (error) {
    if (error.status === 409) draft.conflict = true;
    notice(error.message, "error");
  } finally { saving = false; updateSave(); await refresh(); }
});
$("#discard").addEventListener("click", () => {
  activeDraft().reset(activeDraft().latest); renderActive(); notice("");
});
$("#reload-file").addEventListener("click", async () => {
  const draft = activeDraft(), kind = tab === "bridge" ? "bindings" : tab === "theme" ? "theme" : "config";
  generation++;
  $("#reload-file").disabled = true;
  try {
    const latest = await api("/api/state");
    draft.reset(latest[kind]);
    renderActive();
    notice("Loaded the current file.");
  } catch (error) { notice(error.message, "error"); }
  finally { $("#reload-file").disabled = false; }
});
function importSource() {
  const remote = $("#pet-source").value === "url";
  $("#pet-url-field").hidden = !remote;
  $("#pet-url").disabled = !remote;
  $("#pet-url").required = remote;
  $("#pet-file-field").hidden = remote;
  $("#pet-file").disabled = remote;
  $("#pet-file").required = !remote;
  const source = remote ? $("#pet-url").value : $("#pet-file").files[0]?.name;
  if (source && !$("#pet-name").dataset.edited) $("#pet-name").value = petNameFromSource(source);
}
$("#pet-source").addEventListener("change", () => {
  importSource();
  if (snapshot.can_import) $("#import-status").textContent = "";
});
$("#pet-url").addEventListener("input", () => {
  if (!$("#pet-name").dataset.edited) $("#pet-name").value = petNameFromSource($("#pet-url").value);
  if (snapshot.can_import) $("#import-status").textContent = "";
});
$("#pet-name").addEventListener("input", () => {
  $("#pet-name").dataset.edited = $("#pet-name").value ? "true" : "";
});
$("#pet-file").addEventListener("change", () => {
  const file = $("#pet-file").files[0];
  if (file && !$("#pet-name").dataset.edited) $("#pet-name").value = petNameFromSource(file.name);
  if (snapshot.can_import) $("#import-status").textContent = "";
});
$("#pet-import").addEventListener("submit", async event => {
  event.preventDefault();
  if (importing) return;
  const remote = $("#pet-source").value === "url";
  const file = $("#pet-file").files[0], layoutFile = $("#pet-layout").files[0];
  const progress = $("#import-status");
  if (!remote && (!file || file.size > 20 * 1024 * 1024)) { progress.textContent = "Choose a file up to 20 MiB."; return; }
  importing = true;
  all("#pet-import input, #pet-import select").forEach(control => { control.disabled = true; });
  $("#import-pet").disabled = true;
  progress.textContent = remote ? "Downloading pet and importing frames…" : "Importing frames…";
  try {
    let layout = null;
    if (layoutFile) {
      if (layoutFile.size > 65536) throw new Error("Layout must be at most 64 KiB.");
      layout = JSON.parse(await layoutFile.text());
    }
    const payload = { name: $("#pet-name").value, layout };
    if (remote) payload.url = $("#pet-url").value.trim();
    else {
      const bytes = new Uint8Array(await file.arrayBuffer());
      const chunks = [];
      for (let i = 0; i < bytes.length; i += 32768) chunks.push(String.fromCharCode(...bytes.subarray(i, i + 32768)));
      Object.assign(payload, { filename: file.name, data: btoa(chunks.join("")) });
    }
    const result = await api(remote ? "/api/pets/import-url" : "/api/pets/import", payload);
    generation++;
    snapshot.pets = result.pets;
    renderLibrary(); datalists();
    progress.textContent = `Imported ${result.pet.split("/")[0]}. Choose it as the default or add an assignment.`;
    $("#pet-import").reset();
    delete $("#pet-name").dataset.edited;
    importSource();
  } catch (error) { progress.textContent = error.message; }
  finally {
    importing = false;
    all("#pet-import input, #pet-import select").forEach(control => { control.disabled = false; });
    importSource();
    $("#import-pet").disabled = !snapshot.can_import;
  }
});
$("#export-config").addEventListener("click", () => {
  if (!display?.value) return;
  const url = URL.createObjectURL(new Blob([JSON.stringify(display.value, null, 2) + "\n"], { type: "application/json" }));
  const anchor = element("a");
  anchor.href = url; anchor.download = "display.json"; anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  notice(display.dirty ? "Exported the current draft, including unsaved display edits." : "Exported display settings.");
});
$("#import-config").addEventListener("change", async event => {
  const file = event.target.files[0];
  if (!file) return;
  try {
    if (file.size > 65536) throw new Error("Settings file exceeds 64 KiB.");
    const value = JSON.parse(await file.text());
    if (!value || typeof value !== "object" || Array.isArray(value) || value.schema_version !== 1) throw new Error("Choose a bridge display settings file with schema_version 1.");
    const checked = await api("/api/display/validate", value);
    display.value = checked.value;
    showTab("display");
    notice("Loaded the settings file into your draft. Save changes to apply it.");
  } catch (error) { notice(error.message, "error"); }
  finally { event.target.value = ""; }
});
$("#quit").addEventListener("click", async () => {
  if ((display?.dirty || bindings?.dirty || theme?.dirty) && !confirm("Quit and discard unsaved settings changes?")) return;
  try {
    await api("/api/shutdown", {});
    stopped = true;
    $("#app").hidden = true;
    $("#loading").hidden = false;
    $("#loading").textContent = "Settings app closed. Open Codex MX Bridge to return. Agent collection and your console continue running.";
    $("#connection").textContent = "Closed";
    $("#save").disabled = $("#discard").disabled = true;
  } catch (error) { notice(error.message, "error"); }
});
window.addEventListener("beforeunload", event => {
  if (!stopped && (display?.dirty || bindings?.dirty || theme?.dirty)) { event.preventDefault(); event.returnValue = ""; }
});
await refresh();
setInterval(() => { if (!document.hidden) refresh(); }, 2000);
document.addEventListener("visibilitychange", () => { if (!document.hidden) refresh(); });
